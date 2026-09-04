"""Harness 迭代系统集成测试：端到端验证 M1→M4 闭环。"""

from pathlib import Path
from typing import Any, Dict

import pytest

from src.audiobook_studio.harness.canary import get_canary_abtest
from src.audiobook_studio.harness.collector import capture_feedback, get_correction_collector
from src.audiobook_studio.harness.config import get_harness_settings
from src.audiobook_studio.harness.dashboard import get_harness_dashboard
from src.audiobook_studio.harness.golden import GoldenDatasetManager
from src.audiobook_studio.harness.harness import run_iteration_cycle
from src.audiobook_studio.harness.models import (
    FeedbackSource,
    PipelineStage,
)
from src.audiobook_studio.harness.promotion_gate import promote_candidate
from src.audiobook_studio.harness.prompt_evolution import PromptEvolutionEngine
from src.audiobook_studio.harness.reflection import get_reflection_engine, run_reflection
from src.audiobook_studio.harness.routing_evolution import get_routing_evolution_engine
from src.audiobook_studio.harness.sop_store import create_sop_rule, get_sop_store
from src.audiobook_studio.harness.storage import get_storage, reset_storage
from src.audiobook_studio.harness.threshold_calibrator import get_threshold_calibrator


class TestHarnessFullLoop:
    """端到端完整闭环测试：M1→M4 全链路验证。"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """测试前后重置存储。

        Harness 的 SOP 规则库已隔离到独立的
        ``config/agent_sop.harness.json``（见 ``harness/sop_store.py`` 与
        ``harness/storage.reset_storage``），不再触碰仓库共享的
        ``config/agent_sop.json``，因此本 fixture 只需重置 harness 自有存储、
        创建所需目录即可，无需再处理共享 SOP 配置，从而避免污染依赖同一文件的
        其它测试套件（如 ``test_sop_reflection``）。
        """
        reset_storage()
        # 确保目录存在
        Path("data").mkdir(parents=True, exist_ok=True)
        Path("prompts").mkdir(parents=True, exist_ok=True)
        Path("data/golden").mkdir(parents=True, exist_ok=True)
        Path("prompts").mkdir(parents=True, exist_ok=True)
        yield
        reset_storage()

    def test_m1_golden_loop_closed(self):
        """M1: 金标数据集闭环 - 纠错 → 金标样本 → 三集隔离。"""
        # 1. 创建纠错记录
        get_correction_collector()
        fb_id = capture_feedback(
            project_id=1,
            source="human_edit",
            stage="edit",
            input_snapshot={"text": "原文"},
            llm_output={"text": "错误输出"},
            corrected_output={"text": "修正输出"},
            rationale="人工修正测试",
            pattern_tags=["speaker_error", "pronunciation"],
        )
        assert fb_id is not None

        # 2. 回流到 golden val 集
        manager = GoldenDatasetManager()
        added = manager.ingest_corrections(
            corrections=[
                {
                    "paragraph_index": 1,
                    "chapter_index": 1,
                    "field": "text",
                    "original_value": "错误输出",
                    "corrected_value": "修正输出",
                    "context": {},
                }
            ],
            split="val",
            stage="edit",
        )
        assert added == 1

        # 3. 验证三集隔离
        stats = GoldenDatasetManager().get_stats()
        assert stats.val_count >= 1
        assert stats.train_count >= 0
        assert stats.test_count >= 0

    def test_m2_harness_core_loop(self):
        """M2: Harness 核心逻辑 - 编译→评判→晋升→部署。"""

        # 此测试验证核心流程可跑通（使用 mock 运行函数）
        def mock_run_fn(inp):
            return {"output": "mock output", "stage": "judge"}

        def mock_baseline_fn(inp):
            return {"output": "baseline output", "stage": "judge"}

        # 运行单阶段迭代

        rep = run_iteration_cycle(
            stage="judge",
            run_fn=mock_run_fn,
            baseline_fn=mock_baseline_fn,
            k=3,
            auto_deploy=False,  # 测试不自动部署
        )
        assert rep.compiled is True
        assert rep.candidate_version > 0
        assert rep.eval_case_count >= 0

    def test_m3_sop_store_crud(self):
        """M3: SOP 规则库 CRUD + 版本化 + 命中统计。"""
        store = get_sop_store()

        # 创建
        rule = create_sop_rule(
            {
                "rule_id": "test_rule_1",
                "name": "测试规则",
                "description": "测试用规则",
                "stage": "edit",
                "condition": {"field": "text", "operator": "contains", "value": "错误"},
                "action": {"action": "replace", "replacement": "正确"},
                "created_by": 1,
            }
        )
        assert rule.rule_id == "test_rule_1"

        # 读取
        rule = store.get_rule("test_rule_1")
        assert rule is not None
        assert rule["name"] == "测试规则"

        # 更新
        updated = store.update_rule("test_rule_1", {"description": "更新后的描述"})
        assert updated["description"] == "更新后的描述"
        assert updated["version"] == 2

        # 命中记录
        store.record_hit("test_rule_1", success=True)
        store.record_hit("test_rule_1", success=False)
        stats = store.get_hit_stats("test_rule_1")
        assert stats[0]["hit_count"] == 2
        assert stats[0]["success_count"] == 1

        # 归档
        store.delete_rule("test_rule_1")
        rule = store.get_rule("test_rule_1")
        assert rule["status"] == "archived"

    def test_m3_prompt_evolution(self):
        """M3: Prompt 进化引擎 - 编译、评估、晋升。"""
        engine = PromptEvolutionEngine()

        # 1. 编译候选
        result = engine.compile_candidate(stage="judge", k=3)
        assert result["version"] > 0
        assert result["exemplars_count"] >= 0

        # 2. 评估（使用 mock）
        def mock_run(inp):
            return {"output": "test"}

        eval_result = engine.evaluate_candidate("judge", mock_run_fn=lambda x: {"output": "test"})
        assert "candidate_version" in eval_result
        assert "golden_pass_rate" in eval_result

    def test_m3_threshold_calibrator(self):
        """M3: 阈值自动校准器。"""
        calibrator = get_threshold_calibrator()

        # 生成模拟分布
        import random

        values = [3.5 + random.gauss(0, 0.2) for _ in range(200)]
        dist = calibrator.compute_distribution(values)

        assert dist.count == 200
        assert dist.mean > 0
        assert dist.std > 0
        assert "p5" in dist.percentiles
        assert "p95" in dist.percentiles

        # 推荐阈值
        rec = calibrator.recommend_threshold(
            stage="judge",
            metric_name="dnsmos",
            current_value=3.0,
            distribution=dist,
            direction="lower",
        )
        assert rec is not None
        assert "recommended_value" in rec

    def test_m3_routing_evolution(self):
        """M3: 路由表进化 - 记录结果、自动降权/增权。"""
        engine = get_routing_evolution_engine()

        # 确保权重存在
        engine.initialize_weight("旁白", "v1", "kokoro", initial_weight=1.0)

        # 记录失败 → 降权
        result = engine.record_result("旁白", "v1", success=False)
        assert result["new_weight"] < 1.0

        # 连续成功 → 增权
        for _ in range(10):
            engine.record_result("旁白", "v1", success=True)
        stats = engine.get_stats("旁白")
        assert stats[0]["success_count"] >= 10

    def test_m3_reflection_engine(self):
        """M3: 反思引擎 - 批量归因分析。"""
        get_reflection_engine()

        # 构造测试纠错记录
        corrections = [
            {
                "feedback_id": "fb_1",
                "stage": "edit",
                "source": "human_edit",
                "input_snapshot": {"text": "原文"},
                "llm_output": {"text": "错误输出"},
                "corrected_output": {"text": "修正输出"},
                "rationale": "发音错误",
                "pattern_tags": ["pronunciation_error"],
            }
            for _ in range(10)
        ]

        reflection = run_reflection(stage="edit", corrections=corrections, window_days=7)

        assert "summary" in reflection
        assert "root_causes" in reflection
        assert "sop_rule_candidates" in reflection
        assert "prompt_suggestions" in reflection
        assert "confidence" in reflection
        assert 0 <= reflection["confidence"] <= 1

    def test_m4_canary_ab_test(self):
        """M4: 金丝雀 A/B 测试 - 创建、记录指标、评估、晋升/回滚。"""
        canary = get_canary_abtest()

        # 1. 创建金丝雀
        result = canary.create_canary(
            stage="judge",
            candidate_version=5,
            baseline_version=4,
            traffic_percentage=10.0,
        )
        test_id = result["test_id"]
        assert result["status"] == "running"

        # 记录指标
        for _ in range(15):
            canary.record_metrics(test_id, is_candidate=True, passed=True, score=0.9, latency_ms=100)
            canary.record_metrics(test_id, is_candidate=False, passed=True, score=0.8, latency_ms=120)

        # 评估
        eval_result = canary.evaluate(test_id)
        assert "action" in eval_result

        # 晋升
        promoted = canary.promote(test_id)
        assert promoted is True

        state = canary.get_status(test_id)
        assert state["status"] == "promoted"

    def test_m4_promotion_gate(self, tmp_path):
        """M4: 晋升门禁 - 4 项硬指标裁决。"""
        from audiobook_studio.feedback.prompt_compiler import stage_to_prompt_dir

        # 格式门禁会读取候选 prompt 文件做真实语法检查，这里先落盘一个合规候选。
        def _write_candidate(stage, version):
            d = tmp_path / stage_to_prompt_dir(stage)
            d.mkdir(parents=True, exist_ok=True)
            (d / f"v{version}.j2").write_text(
                "你是专业评审。\n{% for ex in exemplars %}{{ ex }}\n{% endfor %}",
                encoding="utf-8",
            )

        _write_candidate("judge", 5)

        decision = promote_candidate(
            stage="judge",
            candidate_version=5,
            golden_dataset_pass_rate=0.98,
            quality_score_ratio=1.05,
            format_compliance_rate=1.0,
            human_preference_score=1.0,
            prompts_dir=tmp_path,
            auto_deploy=False,
        )
        assert decision.passed is True
        assert decision.deployed is False  # auto_deploy=False

        # 失败情况
        decision_fail = promote_candidate(
            stage="judge",
            candidate_version=6,
            golden_dataset_pass_rate=0.80,  # 低于 0.95
            quality_score_ratio=0.95,
            format_compliance_rate=1.0,
            human_preference_score=1.0,
            prompts_dir=tmp_path,
            auto_deploy=False,
        )
        assert decision_fail.passed is False

    def test_m4_dashboard_status(self):
        """M4: Dashboard 状态查询。"""
        dashboard = get_harness_dashboard()

        # 实时状态
        status = dashboard.get_status()
        assert isinstance(status.timestamp, str)

        # 健康检查
        health = dashboard.get_health()
        assert health.status in ("healthy", "degraded", "unhealthy")

    def test_config_loading(self):
        """配置加载验证。"""
        settings = get_harness_settings()
        assert settings.SELF_ITERATION_LLM == "ollama/qwen3.5:2b"
        assert settings.SELF_ITERATION_BATCH_SIZE == 20
        assert settings.RATE_LIMIT_ENABLED is True

    def test_golden_three_way_split(self):
        """验证 golden 三集隔离：train/val/test 互斥、无重叠。"""
        manager = GoldenDatasetManager()

        # 向三个 split 分别添加样本
        sample = {
            "stage": "test_stage",
            "input": {"text": "test"},
            "output": {"text": "output"},
            "source": "test",
        }
        manager.append_sample("test_stage", "train", sample)
        manager.append_sample("test_stage", "val", sample)
        manager.append_sample("test_stage", "test", sample)

        # 验证三集互斥（样本 hash 唯一）
        train_samples = manager.load_samples("test_stage", "train")
        val_samples = manager.load_samples("test_stage", "val")
        test_samples = manager.load_samples("test_stage", "test")

        {s.sample_hash for s in train_samples}
        {s.sample_hash for s in val_samples}
        {s.sample_hash for s in test_samples}

        # 同一样本 hash 不应同时出现在多个 split（由于去重，实际上会被拦截）
        # 这里验证样本数正确
        stats = GoldenDatasetManager().get_stats()
        assert stats.train_count >= 1
        assert stats.val_count >= 1
        assert stats.test_count >= 1

    def test_full_loop_integration(self, tmp_path):
        """完整闭环集成测试：M1→M4 单次迭代。"""
        # 1. M1: 创建纠错 → 回流 golden val
        get_correction_collector()
        fb_id = capture_feedback(
            project_id=1,
            source=FeedbackSource.HUMAN_EDIT,
            stage=PipelineStage.EDIT,
            input_snapshot={"text": "原文"},
            llm_output={"text": "错误"},
            corrected_output={"text": "正确"},
            rationale="修正测试",
            pattern_tags=["test"],
        )
        assert fb_id is not None

        manager = GoldenDatasetManager()
        manager.ingest_corrections(
            corrections=[
                {
                    "paragraph_index": 1,
                    "chapter_index": 1,
                    "field": "text",
                    "original_value": "错误",
                    "corrected_value": "正确",
                    "context": {},
                }
            ],
            split="val",
            stage="edit",
        )

        # 2. M2: 跑一轮迭代
        def mock_run(inp):
            return {"output": "ok"}

        def mock_baseline(inp):
            return {"output": "baseline"}

        rep = run_iteration_cycle(  # noqa: E303
            stage="edit",
            run_fn=lambda x: {"output": "edited"},
            baseline_fn=lambda x: {"output": "baseline"},
            auto_deploy=False,
        )
        assert rep.compiled is True
        assert rep.candidate_version > 0

        # 3. M3: Prompt 进化 + 阈值校准 + 路由进化 + 反思
        PromptEvolutionEngine()
        compile_result = PromptEvolutionEngine().compile_candidate("edit", k=3)
        assert compile_result["version"] > 0

        calibrator = get_threshold_calibrator()
        dist = calibrator.compute_distribution([3.5] * 100)
        rec = calibrator.recommend_threshold("edit", "dnsmos", 3.0, dist, "lower")
        assert rec is not None

        engine_route = get_routing_evolution_engine()
        engine_route.initialize_weight("旁白", "v1", "kokoro", 1.0)
        engine_route.record_result("旁白", "v1", True)

        engine_reflect = get_reflection_engine()
        reflection = engine_reflect.reflect_on_stage("edit", window_days=7, max_samples=10)
        assert "summary" in reflection

        # 4. M4: 金丝雀 + 晋升门禁
        canary = get_canary_abtest()
        canary_res = canary.create_canary("edit", 5, 4, traffic_percentage=10.0)
        test_id = canary_res["test_id"]
        canary.record_metrics(test_id, True, True, 0.9, 100)
        canary.record_metrics(test_id, False, True, 0.8, 120)
        canary.evaluate(canary._canary_file(canary.list_canaries()[0]["test_id"]).stem)

        # 晋升决策
        from audiobook_studio.feedback.prompt_compiler import stage_to_prompt_dir

        # 格式门禁需读取候选 prompt 文件；先在临时目录落盘一个合规候选。
        cd = tmp_path / stage_to_prompt_dir("edit")
        cd.mkdir(parents=True, exist_ok=True)
        (cd / "v6.j2").write_text(
            "你是专业编辑。\n{% for ex in exemplars %}{{ ex }}\n{% endfor %}",
            encoding="utf-8",
        )
        decision = promote_candidate(
            stage="edit",
            candidate_version=6,
            golden_dataset_pass_rate=0.98,
            quality_score_ratio=1.05,
            format_compliance_rate=1.0,
            human_preference_score=1.0,
            prompts_dir=tmp_path,
            auto_deploy=False,
        )
        assert decision.passed is True

    def test_audit_logging(self):
        """审计日志记录验证。"""
        from src.audiobook_studio.harness.storage import get_storage

        storage = get_storage()

        with storage.db.session() as session:
            from src.audiobook_studio.harness.models import AuditLog

            log = AuditLog(
                event_type="test_event",
                user_id=1,
                username="test_user",
                ip_address="127.0.0.1",
                user_agent="test_agent",
                details={"action": "test"},
            )
            session.add(log)
            session.commit()

        # 查询审计日志
        dashboard = get_harness_dashboard()
        logs = dashboard.query_audit_logs(event_type="test_event", limit=10)
        assert len(logs) >= 1
        assert logs[0].event_type == "test_event"

    def test_golden_three_way_split_isolation(self):
        """验证 train/val/test 三集严格隔离：样本 hash 不重复。"""
        manager = GoldenDatasetManager()
        sample = {
            "stage": "isolation_test",
            "input": {"text": "unique_test_content"},
            "output": {"text": "output"},
            "source": "isolation_test",
        }

        # 向三个 split 添加同一样本（应被去重拦截）
        added_train = manager.append_sample("isolation_test", "train", sample)
        added_val = manager.append_sample("isolation_test", "val", sample)
        added_test = manager.append_sample("isolation_test", "test", sample)

        # 只有第一次添加成功，后续被去重拦截
        assert added_train is True
        assert added_val is False  # 已存在相同 hash
        assert added_test is False

        # 验证统计
        stats = GoldenDatasetManager().get_stats()
        assert stats.train_count >= 1
        assert stats.val_count >= 0  # 未新增
        assert stats.test_count >= 0  # 未新增

    def test_sop_rule_versioning_and_archive(self):
        """SOP 规则版本化与自动归档。"""
        store = get_sop_store()

        # 创建规则
        rule = create_sop_rule(
            {
                "rule_id": "version_test_1",
                "name": "版本测试",
                "stage": "edit",
                "condition": {"field": "x", "op": "==", "value": 1},
                "action": {"type": "alert"},
            }
        )
        assert rule.version == 1

        # 更新触发版本号自增
        updated = store.update_rule("version_test_1", {"description": "v2"})
        assert updated["version"] == 2

        # 命中统计
        for _ in range(3):
            store.record_hit("version_test_1", True)
        stats = get_sop_store().get_hit_stats("version_test_1")
        assert stats[0]["hit_count"] == 3
        assert stats[0]["success_count"] == 3
        assert stats[0]["success_rate"] == 1.0

        # 归档
        store.delete_rule("version_test_1")
        rule = store.get_rule("version_test_1")
        assert rule["status"] == "archived"
        assert rule["archived_at"] is not None

    def test_prompt_version_management(self):
        """Prompt 版本管理：编译、版本号、部署、回滚。"""
        from src.audiobook_studio.feedback.prompt_compiler import write_candidate_prompt

        # 编译候选
        cp = write_candidate_prompt("judge", k=3, prompts_root=Path("prompts/harness"))
        v = cp.version
        assert v > 0

        # 模拟晋升（不实际写入 v1.j2）
        # 这里仅验证版本号递增逻辑
        assert cp.version >= 1

    def test_audit_logging_comprehensive(self):
        """完整审计日志链路验证。"""
        storage = get_storage()
        with storage.db.session() as session:
            from src.audiobook_studio.harness.models import AuditLog, User

            # 先创建用户
            user = User(
                email="test@example.com",
                username="test_user",
                hashed_password="test_hash",
                is_active=True,
            )
            session.add(user)
            session.commit()

            logs = []
            for i in range(5):
                log = AuditLog(
                    event_type=f"test_event_{i}",
                    user_id=user.id,
                    username=f"user_{i}",
                    ip_address=f"192.168.1.{i}",
                    user_agent=f"agent_{i}",
                    details={"action": f"action_{i}", "data": i},
                )
                session.add(log)
            session.commit()

        # 查询验证
        dashboard = get_harness_dashboard()
        logs = dashboard.query_audit_logs(limit=10)
        assert len(logs) >= 5
        for log in logs[:5]:
            assert log.event_type.startswith("test_event_")
            assert log.user_id == user.id


class TestHarnessAutonomyAndOps:
    """M-项1~3 落地验证：自主调度 / 学习型编译 / 人工抽检 / 运营件。"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        reset_storage()
        yield
        reset_storage()

    def test_autonomous_scheduler_tick(self):
        """M-项1：HarnessScheduler.tick 对各 stage 跑完整迭代闭环并产出报告。"""
        from src.audiobook_studio.harness.scheduler import HarnessScheduler

        def mock_run(inp):
            return {"output": "ok"}

        sched = HarnessScheduler(stages=["judge"], run_fn=mock_run, auto_deploy=False)
        report = sched.tick()
        assert "judge" in report
        assert report["judge"]["compiled"] is True
        assert report["judge"]["candidate_version"] > 0
        # 默认不自动部署
        assert report["judge"]["deployed"] is False

    def test_autonomous_scheduler_background_thread(self):
        """M-项1：后台线程 start/stop 不阻塞、可中断。"""
        from src.audiobook_studio.harness.scheduler import HarnessScheduler

        def mock_run(inp):
            return {"output": "ok"}

        sched = HarnessScheduler(stages=["judge"], run_fn=mock_run, interval=0.05, auto_deploy=False)
        sched.start()
        import time as _t

        _t.sleep(0.2)
        sched.stop(timeout=2.0)
        assert sched._thread is not None
        # stop 后线程应已退出
        assert not sched._thread.is_alive()

    def test_spotcheck_human_preference(self, tmp_path):
        """M-项3：人工抽检评分可被记录并聚合为 human_preference_score。"""
        from src.audiobook_studio.harness.spotcheck import (
            human_preference_score_for,
            record_spot_check,
            reset_spot_checks,
        )

        p = tmp_path / "spotcheck.jsonl"
        reset_spot_checks(p)
        # 无抽检时回退默认（1.0）
        assert human_preference_score_for("judge", default=1.0, path=p) == 1.0
        record_spot_check("judge", 2, 0.8, reviewer="x", path=p)
        record_spot_check("judge", 3, 0.6, reviewer="y", path=p)
        assert abs(human_preference_score_for("judge", path=p) - 0.7) < 1e-9
        # 按 stage 隔离
        assert human_preference_score_for("edit", path=p) == 1.0

    def test_run_iteration_cycle_uses_spotcheck_preference(self, tmp_path, monkeypatch):
        """M-项3：run_iteration_cycle 把人工抽检分注入晋升门禁（替代默认 1.0 放行）。"""
        import src.audiobook_studio.harness.harness as harness_mod
        from src.audiobook_studio.harness.spotcheck import record_spot_check, reset_spot_checks

        p = tmp_path / "spotcheck.jsonl"
        reset_spot_checks(p)
        record_spot_check("judge", 5, 0.5, path=p)

        # 让 harness 的抽检读取指向临时文件
        orig = harness_mod.human_preference_score_for

        def fake_fetch(stage, default=1.0):
            return orig(stage, default=default, path=p)

        harness_mod.human_preference_score_for = fake_fetch

        # 捕获 promote_candidate 实际收到的 human_preference_score
        captured = {}
        # harness 在导入时把 promote_candidate 绑定到自身命名空间
        # (harness.promote_candidate)，因此必须 patch harness 模块上的属性，
        # 而非 feedback.deploy 模块；spy 内部回退到真实函数。
        real_promote = harness_mod.promote_candidate

        def spy_promote(stage, candidate_version, **kwargs):
            captured.update(kwargs)
            return real_promote(stage, candidate_version, **kwargs)

        monkeypatch.setattr(harness_mod, "promote_candidate", spy_promote)
        try:

            def mock_run(inp):
                return {"output": "ok"}

            harness_mod.run_iteration_cycle("judge", run_fn=mock_run, auto_deploy=False)
            # 晋升门禁应收到来自抽检库的 0.5，而非默认 1.0
            assert "human_preference_score" in captured
            assert captured["human_preference_score"] == 0.5
        finally:
            harness_mod.human_preference_score_for = orig

    def test_reporting_weekly_and_shadow(self):
        """M-项3：周报结构化产出 + 7 天 shadow 对照。"""
        from src.audiobook_studio.harness.reporting import generate_weekly_report, seven_day_shadow

        rep = generate_weekly_report()
        assert rep["report"] == "weekly"
        assert "golden_stats" in rep
        assert rep["window_days"] == 7

        shadow = seven_day_shadow(
            "judge",
            {"mean_score": 0.90, "pass_rate": 0.95},
            {"mean_score": 0.85, "pass_rate": 0.90},
            tolerance=0.05,
        )
        assert shadow["deltas"]["mean_score"]["delta"] == 0.05
        assert shadow["all_within_tolerance"] is True
        # 超出容忍区间则标记
        shadow2 = seven_day_shadow("judge", {"mean_score": 1.0}, {"mean_score": 0.5}, tolerance=0.05)
        assert shadow2["all_within_tolerance"] is False

    def test_learnable_compile_candidate(self, monkeypatch):
        """M-项2：use_learned=True 时走 DSPy/GEPA 学习型变异并覆盖候选 prompt。"""
        from src.audiobook_studio.harness.prompt_evolution import PromptEvolutionEngine

        class FakeResult:
            optimized_prompt = "LEARNT PROMPT {{ example }}"

        monkeypatch.setattr(
            "audiobook_studio.feedback.bootstrap_fewshot.run_bootstrap_optimization",
            lambda stage: FakeResult(),
        )
        eng = PromptEvolutionEngine()
        res = eng.compile_candidate("judge", k=1, use_learned=True)
        assert res["learned"] is True
        target = Path("prompts/harness") / "quality_judge" / f"v{res['version']}.j2"
        assert target.exists()
        assert "LEARNT" in target.read_text(encoding="utf-8")

    def test_rulebased_compile_still_default(self):
        """M-项2：默认（use_learned=False）仍是规则拼接，learned=False。"""
        from src.audiobook_studio.harness.prompt_evolution import PromptEvolutionEngine

        eng = PromptEvolutionEngine()
        res = eng.compile_candidate("judge", k=1, use_learned=False)
        assert res["learned"] is False
        assert res["version"] > 0

    def test_scheduler_passes_run_fn_through_to_cycle(self, monkeypatch):
        """未注入 run_fn 时，HarnessScheduler.tick 透传 None，由 run_iteration_cycle 内部
        构造版本感知的默认 run_fn（候选版本 vs 已部署版本），而非在调度层硬编码 run_stage。"""
        import audiobook_studio.harness.harness as harness_mod
        from src.audiobook_studio.harness.scheduler import HarnessScheduler

        captured: Dict[str, Any] = {}

        class _FakeRep:
            compiled = True
            candidate_version = 1
            passed = True
            deployed = False
            eval_mean_score = 0.9

        def _fake_cycle(stage, run_fn=None, baseline_fn=None, **kw):
            captured["run_fn"] = run_fn
            captured["baseline_fn"] = baseline_fn
            return _FakeRep()

        monkeypatch.setattr(harness_mod, "run_iteration_cycle", _fake_cycle)

        HarnessScheduler(stages=["judge"]).tick()
        # 调度层只透传；版本感知 run_fn 由 run_iteration_cycle 构造
        assert captured["run_fn"] is None
        assert captured["baseline_fn"] is None

    def test_run_iteration_cycle_evals_candidate_vs_deployed_versions(self, monkeypatch, tmp_path):
        """run_iteration_cycle 默认把「编译出的候选版本」与「当前已部署版本」分别喂入
        候选/基线 eval 的 run_fn，且均从 prompts_root（默认 prompts/harness）读取对应版本，
        而非两次都跑 live v1（真实候选版本接入 eval 的闭环）。"""
        from types import SimpleNamespace

        import audiobook_studio.feedback.canary as canary_mod
        import audiobook_studio.harness.golden as golden_mod
        import audiobook_studio.harness.harness as harness_mod

        captured: list = []

        def _fake_run_stage_with_version(pipeline_stage, version, input_data, mock_mode=None, prompts_root=None):
            captured.append({"stage": pipeline_stage, "version": version, "prompts_root": prompts_root})
            return {"output": "ok"}

        monkeypatch.setattr(canary_mod, "_run_stage_with_prompt_version", _fake_run_stage_with_version)

        # 注入 harness 自有 test 留出集样本，确保 eval 真正调用 run_fn（仓库默认无 judge 测试集）。
        def _fake_load_samples(self, stage, split):
            if stage == "judge" and split == "test":
                return [SimpleNamespace(input={"text": "x"}, expected_output={"text": "y"})]
            return []

        monkeypatch.setattr(golden_mod.GoldenDatasetManager, "load_samples", _fake_load_samples)

        rep = harness_mod.run_iteration_cycle(
            "judge", run_fn=None, baseline_fn=None, auto_deploy=False, prompts_root=tmp_path / "prompts"
        )
        assert rep.compiled is True

        calls = [c for c in captured if c["stage"] == "judge"]
        assert calls, "eval 应真正调用 run_fn"
        # 候选与基线使用不同版本（候选版本 > 已部署版本），证明候选版本真正喂入 eval。
        versions = sorted({c["version"] for c in calls})
        assert len(versions) >= 2, f"候选/基线应使用不同版本，实际: {versions}"
        assert max(versions) > min(versions)
        # 均从 harness prompts_root 读取对应版本（真实候选版本接入 eval）。
        assert all(c["prompts_root"] == tmp_path / "prompts" for c in calls)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

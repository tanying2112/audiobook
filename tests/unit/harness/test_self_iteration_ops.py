"""M-项1/项2/项3 收尾测试：调度开关、晋升门禁、看板真实计数。"""

from typing import Any, Dict

from audiobook_studio.feedback.prompt_compiler import stage_to_prompt_dir
from audiobook_studio.harness.dashboard import get_harness_dashboard
from audiobook_studio.harness.golden import GoldenDatasetManager
from audiobook_studio.harness.promotion_gate import PromotionGate, promote_candidate
from audiobook_studio.harness.scheduler import HarnessScheduler
from src.audiobook_studio.pipeline.sop_reflection import SOPBackgroundThread

# ── 项1+项2：调度层把 use_learned 透传给 run_iteration_cycle ───────────────────


def test_scheduler_forwards_use_learned_to_iteration(monkeypatch):
    """HarnessScheduler 的 use_learned 开关（含实例级与参数级覆盖）必须透传。"""
    import audiobook_studio.harness.harness as harness_mod

    captured = {}

    class _FakeRep:
        compiled = True
        candidate_version = 1
        passed = True
        deployed = False
        eval_mean_score = 0.9

    def _fake_cycle(
        stage,
        run_fn=None,
        baseline_fn=None,
        *,
        k=3,
        golden_root=None,
        prompts_root=None,
        judge=None,
        auto_deploy=True,
        format_compliance_rate=1.0,
        human_preference_score=1.0,
        candidate_id=None,
        use_learned=False,
    ):
        captured.setdefault("calls", []).append((stage, use_learned))
        return _FakeRep()

    monkeypatch.setattr(harness_mod, "run_iteration_cycle", _fake_cycle)

    # 实例级开关开
    HarnessScheduler(stages=["judge"], use_learned=True).tick()
    assert captured["calls"] == [("judge", True)]

    # 实例级开关关
    captured["calls"].clear()
    HarnessScheduler(stages=["judge"], use_learned=False).tick()
    assert captured["calls"] == [("judge", False)]

    # 参数级覆盖优先于实例级
    captured["calls"].clear()
    HarnessScheduler(stages=["judge"], use_learned=True).tick(use_learned=False)
    assert captured["calls"] == [("judge", False)]

    captured["calls"].clear()
    HarnessScheduler(stages=["judge"], use_learned=False).tick(use_learned=True)
    assert captured["calls"] == [("judge", True)]


# ── 项3/晋升门禁：4 项硬指标真实裁决 ────────────────────────────────────────


def _write_candidate(tmp_path, stage, version, content="合法 prompt\n{% for e in ex %}{{ e }}{% endfor %}"):
    d = tmp_path / stage_to_prompt_dir(stage)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"v{version}.j2").write_text(content, encoding="utf-8")


def test_promotion_gate_human_preference_gates(tmp_path):
    """人工抽检分（human_preference_score）真实参与门禁：1.0 通过，0.5 拦截。"""
    gate = PromotionGate(
        golden_pass_rate_min=0.95,
        quality_ratio_min=1.0,
        human_preference_min=1.0,
        format_compliance_min=1.0,
    )
    _write_candidate(tmp_path, "judge", 1)

    ok = gate.evaluate("judge", 1, 0.98, 1.05, 1.0, tmp_path)
    assert ok.passed is True

    low = gate.evaluate("judge", 1, 0.98, 1.05, 0.5, tmp_path)
    assert low.passed is False
    # 人工抽检分门禁（check_human_sample）在 human_preference_min=1.0 下拦截 0.5
    assert "人工抽样通过率" in low.failed_criteria


def test_promotion_gate_format_missing_file_fails(tmp_path):
    """候选 prompt 文件缺失时，格式门禁应判失败（而非默认通过）。"""
    gate = PromotionGate()
    dec = gate.evaluate("judge", 99, 0.98, 1.05, 1.0, tmp_path)
    assert dec.passed is False
    names = [g.name for g in dec.gates]
    assert "格式合规率" in names
    assert dec.gates[names.index("格式合规率")].passed is False


def test_promotion_gate_deploy_forwards_human_preference(tmp_path, monkeypatch):
    """promote_candidate 把 human_preference_score 如实透传给真引擎（feedback/deploy）。"""
    import audiobook_studio.feedback.deploy as deploy_mod

    _write_candidate(tmp_path, "judge", 1)

    captured = {}

    def _fake_deploy(stage, version, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(deploy_mod, "promote_candidate", _fake_deploy)

    promote_candidate("judge", 1, 0.98, 1.05, 1.0, 0.5, tmp_path, auto_deploy=True)
    # 0.5 低于 human_preference_min(1.0) 故门禁不通过、不应触发部署
    assert "human_preference_score" not in captured

    # 1.0 通过门禁 -> 触发部署并透传
    promote_candidate("judge", 1, 0.98, 1.05, 1.0, 1.0, tmp_path, auto_deploy=True)
    assert captured.get("human_preference_score") == 1.0
    assert captured.get("golden_dataset_pass_rate") == 0.98


# ── 看板：get_status / get_health 返回真实计数（修复此前恒为 0 的 bug） ──────


def test_dashboard_status_reflects_golden_counts():
    mgr = GoldenDatasetManager()
    mgr.append_sample(
        "dash_stage",
        "test",
        {
            "stage": "dash_stage",
            "input": {"text": "x"},
            "output": {"text": "y"},
            "source": "test",
        },
    )

    dash = get_harness_dashboard()
    status = dash.get_status()
    assert isinstance(status.golden_stats, dict)
    assert status.golden_stats.get("test", 0) >= 1

    health = dash.get_health()
    assert health.golden_stats.get("test", 0) >= 1


# ── 项2：学习型候选生成的调度开关（AUDIOBOOK_HARNESS_USE_LEARNED） ──────────────


def test_sop_use_learned_env_switch(monkeypatch):
    """SOP 后台线程应读 AUDIOBOOK_HARNESS_USE_LEARNED 决定是否走 learned 候选。"""
    monkeypatch.setenv("AUDIOBOOK_HARNESS_USE_LEARNED", "1")
    assert SOPBackgroundThread._harness_use_learned_enabled() is True
    monkeypatch.setenv("AUDIOBOOK_HARNESS_USE_LEARNED", "0")
    assert SOPBackgroundThread._harness_use_learned_enabled() is False


# ── 实验证据：离线 DSPy/GEPA 可复现落地 ──────────────────────────────────────


def test_learned_experiment_records_evidence(tmp_path, monkeypatch):
    """run_learned_experiment 离线（MockLM）跑通 GEPA 并落盘可回读的证据。"""
    monkeypatch.setenv("MOCK_LLM", "true")
    from audiobook_studio.harness.learned_experiment import load_experiment_records, run_learned_experiment

    out = tmp_path / "exp.jsonl"
    records = run_learned_experiment(
        stages=["annotate_paragraph"],
        out_path=str(out),
        prompts_root=tmp_path / "prompts",
    )
    assert len(records) == 1
    r = records[0]
    # GEPA 多目标优化端到端执行（预算 500、Pareto 前沿产出）
    assert r["optimized_prompt_len"] > 0
    assert r["iterations_completed"] == 500
    assert r["pareto_frontier_size"] >= 1
    # rule-based 与 learned 候选均产出且版本不同（learned 走额外反思变异）
    assert r["rulebased_candidate_version"] is not None
    assert r["learned_candidate_version"] is not None
    assert r["learned_learned_flag"] is True
    # 证据可回读
    loaded = load_experiment_records(str(out))
    assert len(loaded) == 1
    assert loaded[0]["stage"] == "annotate_paragraph"


# ── 项1：SOPBackgroundThread 真正拉起 harness 自主迭代 worker ─────────────────


def test_sop_background_thread_starts_harness_worker(monkeypatch, tmp_path):
    """AUDIOBOOK_HARNESS_AUTONOMOUS=1 时，SOPBackgroundThread.start() 真正拉起
    harness 自主迭代 worker（独立后台线程），并按自身 interval 驱动 run_iteration_cycle。"""
    import audiobook_studio.harness.harness as harness_mod
    from audiobook_studio.harness.scheduler import HarnessScheduler
    from src.audiobook_studio.pipeline.sop_reflection import (
        CorrectionCollector,
        ReflectionEngine,
        SOPBackgroundThread,
        SOPConfig,
    )

    captured: Dict[str, Any] = {}

    class _FakeRep:
        compiled = True
        candidate_version = 1
        passed = True
        deployed = False
        eval_mean_score = 0.9

    def _fake_cycle(
        stage,
        run_fn=None,
        baseline_fn=None,
        *,
        k=3,
        golden_root=None,
        prompts_root=None,
        judge=None,
        auto_deploy=True,
        format_compliance_rate=1.0,
        human_preference_score=1.0,
        candidate_id=None,
        use_learned=False,
    ):
        captured.setdefault("calls", []).append(stage)
        return _FakeRep()

    monkeypatch.setattr(harness_mod, "run_iteration_cycle", _fake_cycle)
    monkeypatch.setenv("AUDIOBOOK_HARNESS_AUTONOMOUS", "1")
    monkeypatch.setenv("AUDIOBOOK_HARNESS_INTERVAL", "0.05")

    sop = SOPConfig(tmp_path / "agent_sop.json")
    collector = CorrectionCollector()
    engine = ReflectionEngine(sop)
    # 注入一个快速 scheduler（stages 收敛到 judge，interval 极小），避免跑全量 stage。
    sched = HarnessScheduler(stages=["judge"], interval=0.05, auto_deploy=False)
    thread = SOPBackgroundThread(sop, collector, engine, check_interval=30.0, harness_scheduler=sched)

    try:
        thread.start()
        # 自主迭代 worker 应作为独立后台线程被拉起
        assert sched._thread is not None and sched._thread.is_alive()
        import time as _t

        _t.sleep(0.3)
        # 周期线程已按自身 interval 驱动 run_iteration_cycle
        assert "judge" in captured.get("calls", [])
    finally:
        thread.stop(timeout=2.0)
    # 退出时 worker 与反思主线程都应已终止
    assert not sched._thread.is_alive()
    assert not thread._thread.is_alive()


def test_sop_background_thread_no_harness_worker_when_disabled(monkeypatch, tmp_path):
    """AUDIOBOOK_HARNESS_AUTONOMOUS 未开启时，start() 不应拉起 harness worker。"""
    import audiobook_studio.harness.harness as harness_mod
    from src.audiobook_studio.pipeline.sop_reflection import (
        CorrectionCollector,
        ReflectionEngine,
        SOPBackgroundThread,
        SOPConfig,
    )

    monkeypatch.delenv("AUDIOBOOK_HARNESS_AUTONOMOUS", raising=False)
    # 即便 run_iteration_cycle 被调用也应失败，确保 worker 真的没启动
    monkeypatch.setattr(harness_mod, "run_iteration_cycle", lambda *a, **k: None)

    sop = SOPConfig(tmp_path / "agent_sop.json")
    collector = CorrectionCollector()
    engine = ReflectionEngine(sop)
    thread = SOPBackgroundThread(sop, collector, engine, check_interval=30.0)

    try:
        thread.start()
        # 自主迭代默认关闭：不应构建/启动 harness worker
        assert thread._harness_scheduler is None
    finally:
        thread.stop(timeout=2.0)
    assert not thread._thread.is_alive()

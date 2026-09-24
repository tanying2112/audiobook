"""dry-run 冒烟验收：``harness.smoke_test`` + ``HarnessScheduler`` 每日冒烟接线。"""

from __future__ import annotations

from pathlib import Path

from audiobook_studio.harness.scheduler import HarnessScheduler
from audiobook_studio.harness.smoke_test import run_smoke_test

REPO_CONFIG_PATH = Path(__file__).resolve().parents[3] / "config" / "agent_sop.json"


class TestSmokeTestModule:
    def test_run_smoke_test_passes(self):
        """端到端 dry-run 双对照：好候选放行、坏候选被拒（fail-closed）。"""
        report = run_smoke_test(stage="analyze", cases=3)
        assert report["all_passed"] is True
        assert report["failure_count"] == 0
        assert len(report["controls"]) == 2
        by_label = {c["control"]: c for c in report["controls"]}
        assert by_label["positive"]["report"]["passed"] is True
        neg = by_label["negative"]["report"]
        assert neg["passed"] is False
        assert neg["failed_criteria"], "坏候选应给出 failed_criteria（非恒通过）"
        # 候选确实以不同版本喂入 eval（候选 vs 基线）。
        for c in report["controls"]:
            assert len(c["recorded_eval_versions"]) >= 2

    def test_run_smoke_test_captures_exception(self, monkeypatch):
        """任一对照异常时返回 all_passed=False 且带 error，不向上抛。"""
        import audiobook_studio.harness.smoke_test as smoke_mod

        # run_iteration_cycle 是 run_smoke_test 内部直接调用、且不会被其自带的
        # load_samples 桩覆盖的真实入口；让它抛错以验证异常被捕获进报告。
        def _boom(stage, run_fn, baseline_fn=None, **kw):
            raise RuntimeError("injected")

        monkeypatch.setattr(smoke_mod, "run_iteration_cycle", _boom)
        report = run_smoke_test(stage="analyze", cases=1)
        assert report["all_passed"] is False
        assert "error" in report


class TestSchedulerSmokeWiring:
    def test_should_run_smoke_test_gate(self):
        # 开启且从未跑过 → True
        s = HarnessScheduler(smoke_test_enabled=True)
        assert s.should_run_smoke_test() is True
        # 关闭 → False
        assert HarnessScheduler(smoke_test_enabled=False).should_run_smoke_test() is False
        # 当天已跑过 → False
        s2 = HarnessScheduler(smoke_test_enabled=True)
        s2.last_smoke_test = __import__("time").time()
        assert s2.should_run_smoke_test() is False

    def test_run_smoke_test_records_report(self):
        """调度层直接调用 run_smoke_test 会跑端到端验证并记录 last_smoke_report。"""
        s = HarnessScheduler(smoke_test_enabled=True, smoke_test_stage="analyze")
        report = s.run_smoke_test()
        assert report["all_passed"] is True
        assert s.last_smoke_test > 0
        assert s.last_smoke_report.get("all_passed") is True

    def test_run_smoke_test_runs_even_when_disabled(self):
        """run_smoke_test 是手动触发入口，不受 smoke_test_enabled 门禁限制。"""
        s = HarnessScheduler(smoke_test_enabled=False)
        report = s.run_smoke_test()
        assert report["all_passed"] is True


class TestSOPBackgroundThreadSmokeWiring:
    def test_env_wires_smoke_test_into_scheduler(self, monkeypatch):
        """SOPBackgroundThread 按 AUDIOBOOK_HARNESS_SMOKE* 环境变量把冒烟接进 worker。"""
        from src.audiobook_studio.pipeline.sop_reflection import (
            CorrectionCollector,
            ReflectionEngine,
            SOPBackgroundThread,
            SOPConfig,
        )

        monkeypatch.setenv("AUDIOBOOK_HARNESS_AUTONOMOUS", "0")  # 不真正拉起调度线程
        monkeypatch.setenv("AUDIOBOOK_HARNESS_SMOKE", "1")
        monkeypatch.setenv("AUDIOBOOK_HARNESS_SMOKE_STAGE", "edit")
        monkeypatch.setenv("AUDIOBOOK_HARNESS_SMOKE_INTERVAL_DAYS", "2")

        config = SOPConfig(REPO_CONFIG_PATH)
        collector = CorrectionCollector()
        engine = ReflectionEngine(config)
        thread = SOPBackgroundThread(config, collector, engine, check_interval=1.0)
        sched = thread._ensure_harness_scheduler()
        assert sched.smoke_test_enabled is True
        assert sched.smoke_test_stage == "edit"
        assert sched.smoke_test_interval_days == 2.0

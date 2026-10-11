"""HARNESS 评估层非 Mock 端到端测试。

覆盖此前为占位桩的 ``run_harness_cycle`` 与 ``get_harness_status``：
- ``run_harness_cycle`` 现在对每个 stage 跑一轮真实迭代（编译→评判→晋升），
  返回真实 ``IterationReport`` 字典，而非 ``status: pending`` 占位。
- ``get_harness_status`` 的金标三集统计从真实存储（SQLite GoldenSample）聚合，
  而非硬编码零值。

两者均只注入「LLM stage 执行器」这一离线不可用的接缝（确定性 run_fn），
马具机制本身（候选编译 / 留出集评判 / 晋升门禁 / 金标统计）全程真实驱动，
不引入 MagicMock/AsyncMock 替换被测系统。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

import src.audiobook_studio.harness.harness as harness_mod
from src.audiobook_studio.harness.golden import GoldenDatasetManager
from src.audiobook_studio.harness.storage import reset_storage


class TestRunHarnessCycleReal:
    """run_harness_cycle 真实迭代（非占位桩）。"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        reset_storage()
        Path("data").mkdir(parents=True, exist_ok=True)
        Path("prompts").mkdir(parents=True, exist_ok=True)
        yield
        reset_storage()

    def test_run_harness_cycle_produces_real_reports(self, monkeypatch):
        """run_harness_cycle 对每个 stage 返回真实 IterationReport 字典，而非占位。"""
        # 在留出集 (test) 播种一条真实金标样本，使评判真实读盘。
        manager = GoldenDatasetManager()
        added = manager.append_sample(
            stage="edit",
            split="test",
            sample={
                "input": {"text": "原文段落"},
                "output": {"text": "修正后的段落"},
                "source": "test_seed",
            },
        )
        assert added is True

        # 仅注入 LLM stage 执行器接缝：确定性输出（离线可复现，不触网）。
        monkeypatch.setattr(
            harness_mod,
            "run_stage",
            lambda stage, inp: {"text": "修正后的段落"},
        )

        reports = asyncio.run(harness_mod.run_harness_cycle(stages=["edit"], auto_deploy=False))

        assert len(reports) == 1
        report = reports[0]
        # 真实报告结构，而非 {"status": "pending", "message": "待集成..."} 占位。
        assert "status" not in report
        assert "待集成" not in report.get("notes", "")
        assert report["stage"] == "edit"
        assert report["compiled"] is True
        assert report["eval_case_count"] >= 1
        assert isinstance(report["passed"], bool)
        assert isinstance(report["deployed"], bool)
        assert report["candidate_version"] >= 1

    def test_get_harness_status_reflects_real_golden_stats(self):
        """get_harness_status 的金标三集统计来自真实存储，而非硬编码零值。"""
        manager = GoldenDatasetManager()
        for split in ("train", "val", "test"):
            ok = manager.append_sample(
                stage="edit",
                split=split,
                sample={
                    "input": {"text": f"{split} 输入"},
                    "output": {"text": f"{split} 输出"},
                    "source": "test_seed",
                },
            )
            assert ok is True

        status = harness_mod.get_harness_status()

        assert status["golden_stats"]["train"] == 1
        assert status["golden_stats"]["val"] == 1
        assert status["golden_stats"]["test"] == 1
        # 真实聚合（golden_stats 不再是硬编码 {0,0,0}）。
        assert isinstance(status["active_canaries"], int)
        assert isinstance(status["pending_promotions"], int)

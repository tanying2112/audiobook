"""晋升门禁非 Mock 测试：直接驱动真实 PromotionGate.evaluate。

用真实数值输入（金标通过率 / 质量比 / 人工偏好分）与真实候选 prompt 文件，
验证 4 项硬指标门禁的真实裁决，不注入 MagicMock / MockRouter。
"""

from __future__ import annotations

from pathlib import Path

from src.audiobook_studio.harness.promotion_gate import PromotionGate


def _write_candidate(prompts_dir: Path, stage: str, version: int) -> None:
    """写入一份真实（格式合规）的候选 prompt 文件。"""
    path = prompts_dir / stage / f"v{version}.j2"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "{{ text }} 优化为口语化表达，保持 {{ speaker }} 的语气。",
        encoding="utf-8",
    )


def test_promotion_gate_all_pass(tmp_path):
    """四项指标全部达标 → 全部门禁通过。"""
    _write_candidate(tmp_path, "edit", 1)
    gate = PromotionGate(
        golden_pass_rate_min=0.95,
        quality_ratio_min=1.0,
        format_compliance_min=1.0,
        human_preference_min=0.85,
    )

    decision = gate.evaluate(
        stage="edit",
        candidate_version=1,
        golden_dataset_pass_rate=0.98,
        quality_score_ratio=1.05,
        human_preference_score=1.0,
        prompts_dir=tmp_path,
    )

    assert decision.passed is True
    assert decision.failed_criteria == []
    assert len(decision.gates) == 4


def test_promotion_gate_golden_pass_rate_fails(tmp_path):
    """金标通过率低于 0.95 → 门禁失败，失败项含「金标数据集通过率」。"""
    _write_candidate(tmp_path, "edit", 1)
    gate = PromotionGate(
        golden_pass_rate_min=0.95,
        quality_ratio_min=1.0,
        format_compliance_min=1.0,
        human_preference_min=0.85,
    )

    decision = gate.evaluate(
        stage="edit",
        candidate_version=1,
        golden_dataset_pass_rate=0.80,
        quality_score_ratio=1.05,
        human_preference_score=1.0,
        prompts_dir=tmp_path,
    )

    assert decision.passed is False
    assert "金标数据集通过率" in decision.failed_criteria


def test_promotion_gate_missing_candidate_fails(tmp_path):
    """候选 prompt 文件缺失 → 格式门禁失败（真实读盘，非伪造）。"""
    gate = PromotionGate(
        golden_pass_rate_min=0.95,
        quality_ratio_min=1.0,
        format_compliance_min=1.0,
        human_preference_min=0.85,
    )

    decision = gate.evaluate(
        stage="edit",
        candidate_version=1,
        golden_dataset_pass_rate=0.98,
        quality_score_ratio=1.05,
        human_preference_score=1.0,
        prompts_dir=tmp_path,  # 无 v1.j2
    )

    assert decision.passed is False
    assert "格式合规率" in decision.failed_criteria

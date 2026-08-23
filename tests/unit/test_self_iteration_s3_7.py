"""Tests for S3.7 — full self-iteration loop validation.

验收(免费资源可达成部分):
- ≥3 次 corrections 被 SOPBackgroundThread 检测到并自动更新 agent_sop.json
- <3 次不触发更新(门限)
- 重新处理(measure_quality)显示 >10% 收益
- 结果要求人工复核(requires_human_review=True)
"""

from pathlib import Path

import pytest

from src.audiobook_studio.pipeline.self_iteration import (
    UserCorrection,
    synthesize_role_aware_rules,
    validate_self_iteration,
)
from src.audiobook_studio.pipeline.sop_reflection import CorrectionCollector


def _correction(field, corrected, speaker, genre="仙侠"):
    return UserCorrection(
        timestamp="2026-01-01T00:00:00Z",
        project_id=1,
        chapter_index=0,
        paragraph_index=0,
        field=field,
        original_value="x",
        corrected_value=corrected,
        genre=genre,
        context={"speaker": speaker},
    )


def _xianxia_corrections():
    return [
        _correction("voice", "kokoro_zh_narrator", "旁白"),
        _correction("voice", "kokoro_zh_protagonist", "林轩"),
        _correction("voice", "kokoro_zh_antagonist", "魔尊"),
        _correction("emotion", "solemn", "旁白"),
        _correction("emotion", "resolute", "林轩"),
    ]


def _held_out():
    return [
        {"speaker": "旁白", "emotion": "solemn"},
        {"speaker": "林轩", "emotion": "resolute"},
        {"speaker": "魔尊", "emotion": "cold"},
    ]


def test_synthesize_role_aware_rules():
    rules = synthesize_role_aware_rules(_xianxia_corrections())
    # 旁白 & 林轩 均未命中具体角色关键词 -> narrator;魔尊 含"魔" -> demon_lord
    assert rules["voice_bindings"]["demon_lord"] == "kokoro_zh_antagonist"
    assert "narrator" in rules["voice_bindings"]
    assert rules["emotion_defaults"]["narrator"] == "resolute"  # 林轩 覆盖 旁白


def test_loop_updates_sop_after_3_corrections(tmp_path: Path):
    config = tmp_path / "agent_sop.json"
    report = validate_self_iteration(
        config_path=config,
        genre="仙侠",
        corrections=_xianxia_corrections(),
        held_out=_held_out(),
    )
    assert report["corrections_fed"] >= 3
    assert report["sop_updated"] is True
    assert report["requires_human_review"] is True
    # Measurable >10% gain on the held-out sample.
    assert report["gain_pct"] > 10.0


def test_loop_does_not_update_below_threshold(tmp_path: Path):
    config = tmp_path / "agent_sop.json"
    # Only 2 corrections -> below the min-corrections gate (3).
    few = _xianxia_corrections()[:2]
    report = validate_self_iteration(
        config_path=config,
        genre="仙侠",
        corrections=few,
        held_out=_held_out(),
    )
    assert report["sop_updated"] is False
    assert report["gain_pct"] == 0.0


def test_collector_counts_corrections():
    c = CorrectionCollector()
    for corr in _xianxia_corrections():
        c.add_correction(corr)
    assert c.queue_size() == 5

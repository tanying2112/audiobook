"""A2 — quality_check 质检结果(pass/fail + 原因) 回流为 judge 金标样本。"""

from __future__ import annotations

from pathlib import Path

from audiobook_studio.feedback.loop import (
    _load_samples,
    quality_judgment_to_sample,
    quality_judgments_to_golden,
)
from audiobook_studio.schemas.quality import QualityJudgment


def _judgment(segment_id: str, needs_regen: bool, issues: list) -> QualityJudgment:
    return QualityJudgment(
        segment_id=segment_id,
        speaker_clarity=0.8,
        emotion_match=0.7,
        prosody_naturalness=0.75,
        text_audio_alignment=0.8,
        overall_score=0.7 if needs_regen else 0.9,
        issues=issues,
        fix_suggestions=[],
        needs_regeneration=needs_regen,
    )


def test_quality_judgment_to_sample_captures_pass_fail_and_reasons():
    j_pass = _judgment("seg_1", needs_regen=False, issues=[])
    s_pass = quality_judgment_to_sample(j_pass, annotation={"speaker": "narrator"}, reference_text="你好世界")
    assert s_pass.stage == "judge"
    assert s_pass.source == "quality_check"
    assert "PASS" in s_pass.rubric
    assert s_pass.input["segment_id"] == "seg_1"
    assert s_pass.input["reference_text"] == "你好世界"
    assert s_pass.output["needs_regeneration"] is False
    assert s_pass.output["overall_score"] == 0.9

    j_fail = _judgment("seg_2", needs_regen=True, issues=["wrong_speaker", "silent_segment"])
    s_fail = quality_judgment_to_sample(j_fail, annotation={"speaker": "A"}, reference_text="x")
    assert "FAIL" in s_fail.rubric
    # 原因（issues）进入 rubric
    assert "wrong_speaker" in s_fail.rubric
    assert s_fail.output["needs_regeneration"] is True


def test_quality_judgments_to_golden_writes_and_dedups(tmp_path: Path):
    root = tmp_path / "data" / "golden"
    js = [
        _judgment("seg_1", False, []),
        _judgment("seg_2", True, ["wrong_speaker"]),
    ]
    anns = [{"speaker": "narrator"}, {"speaker": "A"}]
    refs = ["你好", "世界"]
    added = quality_judgments_to_golden(
        js, annotations=anns, reference_texts=refs, split="val", stage="judge", golden_root=root
    )
    assert added == 2
    # 重复回流 -> 去重为 0
    again = quality_judgments_to_golden(
        js, annotations=anns, reference_texts=refs, split="val", stage="judge", golden_root=root
    )
    assert again == 0

    lines = (root / "val" / "judge" / "judge.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    loaded = _load_samples(root / "val" / "judge" / "judge.jsonl")
    assert all(s.stage == "judge" for s in loaded)
    # 回流样本可被 judge 阶段金丝雀加载器识别（schema 一致）
    assert loaded[0].input["reference_text"] in ("你好", "世界")

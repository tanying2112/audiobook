"""Tests for H2 fix: LLM-judge exceptions must not be mislabeled as sensitive_content.

A transient judge failure (network/timeout) used to be reported as
``issues=["sensitive_content"]`` with ``needs_regeneration=True``, which both
fabricated a content-moderation conclusion and could force a regeneration loop.
Now it is reported honestly as ``judge_error`` with ``needs_regeneration=False``.
"""

from src.audiobook_studio.llm.judge import LLMJudge
from src.audiobook_studio.schemas import AudioPostProcessParams, ParagraphAnnotation


def _make_annotation() -> ParagraphAnnotation:
    return ParagraphAnnotation(
        paragraph_index=0,
        speaker_canonical_name="narrator",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        speech_rate=1.0,
        pitch_shift_semitones=0,
        pause_before_ms=300,
        pause_after_ms=500,
        confidence=0.9,
    )


class _BoomRouter:
    """Router whose ``call`` always raises, simulating a transient judge failure."""

    def call(self, *args, **kwargs):  # noqa: D401 - test double
        raise RuntimeError("upstream timeout")


def test_judge_quality_error_is_judge_error_not_sensitive():
    judge = LLMJudge(router=_BoomRouter())
    out = judge.judge_quality(
        "seg-1",
        _make_annotation(),
        "audio description",
        "reference text",
        AudioPostProcessParams(),
    )
    assert out.issues == ["judge_error"]
    assert out.needs_regeneration is False
    assert "Judge error" in out.fix_suggestions[0].rationale


def test_judge_error_is_valid_schema_literal():
    # Importing the schema and constructing with judge_error must succeed
    # (i.e. judge_error is part of the issues Literal).
    from src.audiobook_studio.schemas import QualityJudgment

    j = QualityJudgment(
        segment_id="x",
        speaker_clarity=0.0,
        emotion_match=0.0,
        prosody_naturalness=0.0,
        text_audio_alignment=0.0,
        overall_score=0.0,
        issues=["judge_error"],
        needs_regeneration=False,
    )
    assert j.issues == ["judge_error"]

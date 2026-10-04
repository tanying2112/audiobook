"""Sprint 1 S1-4 coverage: pipeline edit_for_tts stage in mock_mode.

Uses ``mock_mode=True`` so no LLM provider call is made. This isolates the
external LLM dependency while still exercising the pipeline's branching logic
(difficulty gating, forbid_edit, mock fallback).
"""

from __future__ import annotations

from src.audiobook_studio.pipeline.edit_for_tts import EditForTtsPipeline
from src.audiobook_studio.schemas import ParagraphAnnotation, TtsEditInput


def _annotation(difficulty: str = "B") -> ParagraphAnnotation:
    return ParagraphAnnotation(
        paragraph_index=1,
        text="原文保持不变。",
        speaker_canonical_name="_narrator_",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        confidence=0.9,
        difficulty=difficulty,
    )


def _input(difficulty: str = "B", forbid_edit: bool = False) -> TtsEditInput:
    return TtsEditInput(
        paragraph_text="原文保持不变。",
        paragraph_annotation=_annotation(difficulty),
        difficulty=difficulty,
        forbid_edit=forbid_edit,
    )


def test_mock_mode_preserves_original_for_difficulty_a() -> None:
    """Hard rule: difficulty A always preserves the original text."""
    pipeline = EditForTtsPipeline(mock_mode=True)
    out = pipeline.run(_input(difficulty="A"))
    assert out.edited_text == "原文保持不变。"
    assert "difficulty_A_or_forbid_edit_preserved_original" in out.changes_made


def test_mock_mode_returns_original_with_no_changes() -> None:
    """In mock mode the pipeline applies no real edits."""
    pipeline = EditForTtsPipeline(mock_mode=True)
    out = pipeline.run(_input(difficulty="B"))
    assert out.edited_text == "原文保持不变。"
    assert out.changes_made == ["mock_mode_no_changes"]
    assert out.confidence == 0.9


def test_forbid_edit_preserves_original() -> None:
    """forbid_edit=True forces the original text regardless of difficulty."""
    pipeline = EditForTtsPipeline(mock_mode=True)
    out = pipeline.run(_input(difficulty="C", forbid_edit=True))
    assert out.edited_text == "原文保持不变。"
    assert "difficulty_A_or_forbid_edit_preserved_original" in out.changes_made

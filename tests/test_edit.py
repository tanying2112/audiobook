"""Tests for EditForTtsPipeline (Stage 4).

Covers initialization, mock_mode, hard rules (difficulty A, forbid_edit),
convenience function, and error handling.
Target coverage: >= 60%.
"""

import sys

import pytest

sys.path.insert(0, "src")

from audiobook_studio.pipeline import edit_for_tts
from audiobook_studio.pipeline.edit_for_tts import EditForTtsPipeline
from audiobook_studio.schemas import ParagraphAnnotation, TtsEditInput, TtsEditOutput


class TestEditForTtsPipeline:
    """Test EditForTtsPipeline class."""

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        pipeline = EditForTtsPipeline()
        assert pipeline is not None
        assert pipeline.mock_mode is False
        assert pipeline.router is not None

    def test_init_mock_mode(self):
        """Test pipeline initialization in mock mode."""
        pipeline = EditForTtsPipeline(mock_mode=True)
        assert pipeline.mock_mode is True

    def test_init_custom_router(self, mock_router):
        """Test pipeline with custom router."""
        pipeline = EditForTtsPipeline(router=mock_router)
        assert pipeline.router == mock_router

    def test_run_mock_mode(self, sample_input):
        """Test run in mock mode returns expected result."""
        pipeline = EditForTtsPipeline(mock_mode=True)
        result = pipeline.run(sample_input)
        assert isinstance(result, TtsEditOutput)
        assert "mock_mode_no_changes" in result.changes_made
        assert result.confidence == 0.9
        assert result.edited_text == "测试段落文本。"

    def test_run_mock_mode_different_text(self):
        """Test mock mode with different input text."""
        pipeline = EditForTtsPipeline(mock_mode=True)
        input_data = _make_input(paragraph_text="不同文本内容。")
        result = pipeline.run(input_data)
        assert result.edited_text == "不同文本内容。"

    def test_difficulty_a_returns_original(self, sample_input):
        """Test difficulty A preserves original text regardless of mock_mode."""
        # Even with mock_mode=False, difficulty A should skip editing
        pipeline = EditForTtsPipeline(mock_mode=False)
        input_data = _make_input(difficulty="A")
        result = pipeline.run(input_data)
        assert result.edited_text == "测试段落文本。"
        assert "difficulty_A_or_forbid_edit_preserved_original" in result.changes_made
        assert result.confidence == 1.0

    def test_forbid_edit_returns_original(self, sample_input):
        """Test forbid_edit=True preserves original text."""
        pipeline = EditForTtsPipeline(mock_mode=True)
        input_data = _make_input(forbid_edit=True)
        result = pipeline.run(input_data)
        assert result.edited_text == "测试段落文本。"
        assert "difficulty_A_or_forbid_edit_preserved_original" in result.changes_made

    def test_difficulty_a_precedes_mock_mode(self, sample_input):
        """Test difficulty A rule is checked before mock_mode."""
        pipeline = EditForTtsPipeline(mock_mode=False)
        input_data = _make_input(difficulty="A")
        result = pipeline.run(input_data)
        # Should NOT go into mock_mode path; should return from hard rule
        assert "difficulty_A_or_forbid_edit_preserved_original" in result.changes_made

    def test_convenience_function_mock(self):
        """Test edit_for_tts convenience function."""
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=300,
            pause_after_ms=500,
            confidence=0.9,
            needs_sfx=False,
            sfx_tags=[],
        )
        result = edit_for_tts(
            paragraph_text="测试文本。",
            paragraph_annotation=annotation,
            difficulty="B",
            mock_mode=True,
        )
        assert isinstance(result, TtsEditOutput)
        assert "mock_mode_no_changes" in result.changes_made

    def test_convenience_function_difficulty_a(self):
        """Test edit_for_tts with difficulty A returns original."""
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=300,
            pause_after_ms=500,
            confidence=0.9,
            needs_sfx=False,
            sfx_tags=[],
        )
        result = edit_for_tts(
            paragraph_text="原文本。",
            paragraph_annotation=annotation,
            difficulty="A",
            mock_mode=False,
        )
        assert result.edited_text == "原文本。"

    def test_convenience_function_forbid_edit(self):
        """Test edit_for_tts with forbid_edit=True."""
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=300,
            pause_after_ms=500,
            confidence=0.9,
            needs_sfx=False,
            sfx_tags=[],
        )
        result = edit_for_tts(
            paragraph_text="原文本。",
            paragraph_annotation=annotation,
            difficulty="C",
            forbid_edit=True,
            mock_mode=False,
        )
        assert result.edited_text == "原文本。"

    def test_load_few_shot_exists(self):
        """Test _load_few_shot loads from golden dataset."""
        pipeline = EditForTtsPipeline(mock_mode=True)
        result = pipeline._load_few_shot("edit_for_tts")
        assert "示例" in result
        assert "输入" in result

    def test_load_few_shot_missing(self):
        """Test _load_few_shot returns fallback for missing stage."""
        pipeline = EditForTtsPipeline(mock_mode=True)
        result = pipeline._load_few_shot("nonexistent_stage")
        assert result == "(暂无示例)"

    def test_build_prompt(self, sample_input):
        """Test _build_prompt returns valid Jinja2-rendered prompt."""
        pipeline = EditForTtsPipeline(mock_mode=True)
        prompt = pipeline._build_prompt(sample_input)
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_init_no_mock_mode_fallback(self):
        """Test pipeline creates default router when none provided."""
        pipeline = EditForTtsPipeline()
        assert pipeline.router is not None

    def test_difficulty_b_mock_mode(self):
        """Test difficulty B in mock mode uses mock path."""
        pipeline = EditForTtsPipeline(mock_mode=True)
        input_data = _make_input(difficulty="B")
        result = pipeline.run(input_data)
        assert "mock_mode_no_changes" in result.changes_made


# --- Fixtures ---


@pytest.fixture
def mock_router():
    """Create a mock router for testing."""
    from unittest.mock import MagicMock

    router = MagicMock()
    router.call.return_value.output = TtsEditOutput(
        edited_text="编辑后文本。",
        changes_made=["mock_edit"],
        forbidden_content_removed=[],
        confidence=0.95,
        rationale="Mock edit",
    )
    return router


@pytest.fixture
def sample_input():
    """Create a sample TtsEditInput for testing."""
    return _make_input()


def _make_input(
    paragraph_text="测试段落文本。",
    difficulty="B",
    forbid_edit=False,
):
    """Helper to create TtsEditInput."""
    annotation = ParagraphAnnotation(
        paragraph_index=0,
        speaker_canonical_name="旁白",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        speech_rate=1.0,
        pitch_shift_semitones=0,
        pause_before_ms=300,
        pause_after_ms=500,
        confidence=0.9,
    )
    return TtsEditInput(
        paragraph_text=paragraph_text,
        paragraph_annotation=annotation,
        difficulty=difficulty,
        forbid_edit=forbid_edit,
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

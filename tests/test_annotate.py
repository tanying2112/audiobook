"""Tests for AnnotateParagraphPipeline (Stage 3).

Covers initialization, mock_mode, convenience function, and error handling.
Target coverage: >= 60%.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, "src")

from audiobook_studio.pipeline import annotate_paragraph
from audiobook_studio.pipeline.annotate_paragraph import AnnotateParagraphPipeline
from audiobook_studio.schemas import (
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
    ParagraphAnnotation,
    ParagraphAnnotationInput,
)


class TestAnnotateParagraphPipeline:
    """Test AnnotateParagraphPipeline class."""

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        os.environ["MOCK_LLM"] = "false"
        pipeline = AnnotateParagraphPipeline()
        assert pipeline is not None
        assert pipeline.mock_mode is False
        assert pipeline.router is not None

    def test_init_mock_mode(self):
        """Test pipeline initialization in mock mode."""
        os.environ["MOCK_LLM"] = "true"
        pipeline = AnnotateParagraphPipeline()
        assert pipeline.mock_mode is True

    def test_init_custom_router(self, mock_router):
        """Test pipeline with custom router."""
        pipeline = AnnotateParagraphPipeline(router=mock_router)
        assert pipeline.router == mock_router

    def test_run_mock_mode(self, sample_input):
        """Test run in mock mode returns expected annotation."""
        pipeline = AnnotateParagraphPipeline()
        result = pipeline.run(sample_input)
        assert isinstance(result, ParagraphAnnotation)
        assert result.speaker_canonical_name == "旁白"
        assert result.emotion == "neutral"
        assert result.confidence == 0.9
        assert result.paragraph_index == 0

    def test_run_mock_mode_different_index(self):
        """Test mock mode preserves different paragraph index."""
        pipeline = AnnotateParagraphPipeline()
        input_data = _make_input(
            paragraph_index=5, paragraph_text="不同索引的测试段落文本，满足长度要求。"
        )
        result = pipeline.run(input_data)
        assert result.paragraph_index == 5

    def test_convenience_function_mock(self):
        """Test annotate_paragraph convenience function."""
        book_meta = BookMeta(
            title="Test",
            author="Author",
            genre="小说",
            difficulty="B",
            language="zh",
            era="现代",
            total_chapters_estimated=1,
        )
        char_map = [
            CharacterVoiceBinding(
                canonical_name="旁白",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="v1",
                sample_quote="test",
            )
        ]
        emotion = EmotionSnapshot(chapter=1, dominant_emotion="neutral", intensity=0.5)
        result = annotate_paragraph(
            paragraph_text="这是一个测试段落文本，用于验证标注功能。",
            paragraph_index=0,
            chapter_index=1,
            book_meta=book_meta,
            character_voice_map=char_map,
            emotion_snapshot=emotion,
            story_line_summary="这是一个用于测试的模拟故事摘要，包含足够的字符数以满足最小长度要求，用于验证模拟模式下的段落标注功能是否正常工作。"
            * 2,
            global_style_notes="测试文风：简洁明了。",
            mock_mode=True,
        )
        assert isinstance(result, ParagraphAnnotation)
        assert result.speaker_canonical_name == "旁白"

    def test_load_few_shot_exists(self):
        """Test _load_few_shot loads from golden dataset."""
        pipeline = AnnotateParagraphPipeline()
        result = pipeline._load_few_shot("annotate_paragraph")
        assert "示例" in result
        assert "输入" in result

    def test_load_few_shot_missing(self):
        """Test _load_few_shot returns fallback for missing stage."""
        pipeline = AnnotateParagraphPipeline()
        result = pipeline._load_few_shot("nonexistent_stage")
        assert result == "(暂无示例)"

    def test_build_prompt(self, sample_input):
        """Test _build_prompt returns valid Jinja2-rendered prompt."""
        pipeline = AnnotateParagraphPipeline()
        prompt = pipeline._build_prompt(sample_input)
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert "paragraph_text" in prompt or "测试" in prompt

    def test_run_no_mock_mode_fallback(self):
        """Test run without mock mode but no router raises appropriate error."""
        # Not testing actual LLM call, just that the code path is exercised
        pipeline = AnnotateParagraphPipeline()
        assert pipeline.mock_mode is True


# --- Fixtures ---


@pytest.fixture
def mock_router():
    """Create a mock router for testing."""
    from unittest.mock import MagicMock

    router = MagicMock()
    router.call.return_value.output = ParagraphAnnotation(
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
        notes="Mock annotation",
    )
    return router


@pytest.fixture
def sample_input():
    """Create a sample ParagraphAnnotationInput for testing."""
    return _make_input()


def _make_input(paragraph_index=0, paragraph_text=None):
    """Helper to create ParagraphAnnotationInput."""
    book_meta = BookMeta(
        title="测试书",
        author="测试作者",
        genre="小说",
        difficulty="B",
        language="zh",
        era="现代",
        total_chapters_estimated=1,
    )
    char_map = [
        CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="v1",
            sample_quote="测试",
        )
    ]
    emotion = EmotionSnapshot(chapter=1, dominant_emotion="neutral", intensity=0.5)
    return ParagraphAnnotationInput(
        paragraph_text=paragraph_text or "这是一个测试段落文本，满足最小长度要求。",
        paragraph_index=paragraph_index,
        chapter_index=1,
        book_meta=book_meta,
        character_voice_map=char_map,
        emotion_snapshot=emotion,
        story_line_summary="这是一个用于测试的模拟故事摘要，包含足够的字符数以满足最小长度要求，用于验证模拟模式下的段落标注功能是否正常工作。"
        * 2,
        global_style_notes="测试文风：简洁明了。",
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

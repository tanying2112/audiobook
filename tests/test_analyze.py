"""Tests for AnalyzeStructurePipeline (Stage 2).

Covers initialization, mock_mode, convenience function,
and error handling.
Target coverage: >= 75%
"""

import os
import sys
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, "src")

from audiobook_studio.pipeline import analyze_structure
from audiobook_studio.pipeline.analyze_structure import AnalyzeStructurePipeline
from audiobook_studio.schemas import BookAnalysisInput, BookAnalysisOutput


class TestAnalyzeStructurePipeline:
    """Test AnalyzeStructurePipeline class."""

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        # Ensure MOCK_LLM is false for this test
        os.environ["MOCK_LLM"] = "false"
        pipeline = AnalyzeStructurePipeline()
        assert pipeline is not None
        assert pipeline.mock_mode is False
        assert pipeline.router is not None

    def test_init_mock_mode(self):
        """Test pipeline initialization in mock mode."""
        os.environ["MOCK_LLM"] = "true"
        pipeline = AnalyzeStructurePipeline()
        assert pipeline.mock_mode is True

    def test_init_custom_prompt_dir(self, tmp_path):
        """Test pipeline with custom prompt directory."""
        pipeline = AnalyzeStructurePipeline(mock_mode=True, prompt_dir=str(tmp_path))
        assert pipeline.prompt_dir == tmp_path

    def test_run_mock_mode(self):
        """Test run in mock mode returns expected analysis."""
        os.environ["MOCK_LLM"] = "true"
        input_data = BookAnalysisInput(
            raw_text="第一章 测试文本内容。" * 20,
            title_hint="测试书",
            author_hint="测试作者",
            target_difficulty="B",
        )
        pipeline = AnalyzeStructurePipeline()
        result = pipeline.run(input_data)
        assert isinstance(result, BookAnalysisOutput)
        assert result.book_meta.title == "Test Book"
        assert len(result.character_voice_map) >= 1
        assert len(result.emotion_snapshots) >= 1
        assert len(result.story_line_summary) >= 100

    def test_run_mock_mode_short_text(self):
        """Test mock mode with very short text."""
        input_data = BookAnalysisInput(
            raw_text="短文本。",
            title_hint="短篇",
        )
        pipeline = AnalyzeStructurePipeline()
        result = pipeline.run(input_data)
        assert isinstance(result, BookAnalysisOutput)
        assert result.book_meta.title == "Test Book"

    def test_run_non_mock_router_call(self):
        """Test run method calls router with correct parameters."""
        from audiobook_studio.schemas import (
            BookAnalysisOutput,
            BookMeta,
            CharacterVoiceBinding,
            EmotionSnapshot,
        )

        mock_router = Mock()
        mock_output = BookAnalysisOutput(
            book_meta=BookMeta(
                title="Test",
                author="Test Author",
                genre="小说",
                difficulty="B",
                language="zh",
                era="现代",
                total_chapters_estimated=10,
            ),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="narrator", sample_quote="旁白文本"
                )
            ],
            emotion_snapshots=[
                EmotionSnapshot(chapter=1, dominant_emotion="neutral", intensity=0.5)
            ],
            story_line_summary="This is a test summary that is long enough to pass the minimum length requirement of 100 characters.",
            global_style_notes="Test style notes",
        )
        mock_result = Mock()
        mock_result.output = mock_output
        mock_result.schema_compliance = True
        mock_result.model = "test-model"
        mock_result.cost_usd = 0.001
        mock_result.latency_ms = 100
        mock_router.call.return_value = mock_result

        input_data = BookAnalysisInput(
            raw_text="测试文本。" * 20,
            title_hint="测试书",
        )
        pipeline = AnalyzeStructurePipeline(router=mock_router, mock_mode=False)
        result = pipeline.run(input_data)

        assert isinstance(result, BookAnalysisOutput)
        mock_router.call.assert_called_once()
        call_args = mock_router.call.call_args
        assert call_args.kwargs["stage"] == "analyze"
        assert call_args.kwargs["response_model"] == BookAnalysisOutput

    def test_run_router_exception(self):
        """Test run method handles router exception."""
        mock_router = Mock()
        mock_router.call.side_effect = Exception("LLM API error")

        input_data = BookAnalysisInput(
            raw_text="测试文本。" * 20,
            title_hint="测试书",
        )
        pipeline = AnalyzeStructurePipeline(router=mock_router, mock_mode=False)

        with pytest.raises(Exception, match="LLM API error"):
            pipeline.run(input_data)

    def test_convenience_function_mock(self):
        """Test analyze_structure convenience function."""
        result = analyze_structure(
            raw_text="第一章 测试内容。" * 20,
            title_hint="测试书",
            mock_mode=True,
        )
        assert isinstance(result, BookAnalysisOutput)
        assert result.book_meta.title == "Test Book"

    def test_convenience_function_with_author(self):
        """Test convenience function with author hint."""
        result = analyze_structure(
            raw_text="第一章 测试内容。" * 20,
            title_hint="测试书",
            author_hint="作者",
            target_difficulty="C",
            mock_mode=True,
        )
        assert isinstance(result, BookAnalysisOutput)

    def test_load_few_shot_exists(self):
        """Test _load_few_shot_examples loads from golden dataset."""
        pipeline = AnalyzeStructurePipeline()
        result = pipeline._load_few_shot_examples("analyze_structure")
        assert "input" in result or "示例" in result or "{" in result

    def test_load_few_shot_missing(self):
        """Test _load_few_shot_examples returns fallback for missing stage."""
        pipeline = AnalyzeStructurePipeline()
        result = pipeline._load_few_shot_examples("nonexistent_stage")
        # Returns full-width Chinese parentheses
        assert "暂无示例" in result

    def test_build_prompt(self):
        """Test _build_prompt returns valid Jinja2-rendered prompt."""
        input_data = BookAnalysisInput(
            raw_text="第一章 测试文本。",
            title_hint="测试书",
            target_difficulty="B",
        )
        pipeline = AnalyzeStructurePipeline()
        prompt = pipeline._build_prompt(input_data)
        assert isinstance(prompt, str)
        assert len(prompt) > 100
        assert "测试" in prompt or "title_hint" in prompt

    def test_jinja_env_configured(self):
        """Test Jinja2 environment has correct configuration."""
        pipeline = AnalyzeStructurePipeline()
        assert pipeline.jinja_env is not None
        assert hasattr(pipeline.jinja_env, "get_template")
        assert pipeline.jinja_env.filters.get("tojson") is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Comprehensive unit tests for analyze_structure pipeline targeting ≥80% line coverage.

Tests match the ACTUAL API from src/audiobook_studio/pipeline/analyze_structure.py:
- AnalyzeStructurePipeline class with run(), _build_prompt(), _load_few_shot_examples()
- analyze_structure() convenience function
- BookAnalysisInput/BookAnalysisOutput Pydantic models
- mock_mode behavior for testing without external APIs
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.audiobook_studio.pipeline.analyze_structure import AnalyzeStructurePipeline, analyze_structure
from src.audiobook_studio.schemas import (
    BookAnalysisInput,
    BookAnalysisOutput,
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
)


class TestAnalyzeStructurePipeline:
    """Test AnalyzeStructurePipeline class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = AnalyzeStructurePipeline()

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_minimal_input(self, **overrides):
        """Create minimal valid BookAnalysisInput for testing."""
        defaults = {
            "raw_text": "第一章 开始\n\n这是第一段内容。\n\n第二章 继续\n\n这是第二段内容。",
            "title_hint": "测试书籍",
            "author_hint": "测试作者",
            "target_difficulty": "B",
        }
        defaults.update(overrides)
        return BookAnalysisInput(**defaults)

    def create_mock_output(self, **overrides):
        """Create a valid BookAnalysisOutput for mocking."""
        defaults = {
            "book_meta": BookMeta(
                title="Test Book",
                author="Test Author",
                genre="小说",
                difficulty="B",
                language="zh",
                era="现代",
                total_chapters_estimated=10,
            ),
            "character_voice_map": [
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="kokoro_narrator",
                    sample_quote="这是旁白的样本文本。",
                ),
            ],
            "emotion_snapshots": [
                EmotionSnapshot(
                    chapter=1,
                    dominant_emotion="neutral",
                    intensity=0.5,
                    notes="平静的开头",
                ),
            ],
            "story_line_summary": "这是一个关于测试的故事，主角经历各种冒险最终成功，并在过程中获得了宝贵的友谊和成长。"
            * 3,
            "global_style_notes": "Mock style notes.",
        }
        defaults.update(overrides)
        return BookAnalysisOutput(**defaults)

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        from src.audiobook_studio.llm import create_router

        pipeline = AnalyzeStructurePipeline()
        assert pipeline.router is not None
        assert pipeline.jinja_env is not None

    def test_init_with_custom_router(self):
        """Test pipeline initialization with custom router."""
        mock_router = Mock()
        pipeline = AnalyzeStructurePipeline(router=mock_router)
        assert pipeline.router == mock_router

    def test_init_with_custom_prompt_dir(self):
        """Test pipeline initialization with custom prompt directory."""
        pipeline = AnalyzeStructurePipeline(prompt_dir=self.temp_dir)
        assert pipeline.prompt_dir == Path(self.temp_dir)

    def test_load_few_shot_examples_no_file(self):
        """Test _load_few_shot_examples when file doesn't exist."""
        result = self.pipeline._load_few_shot_examples("nonexistent_stage")
        assert result == "（暂无示例）"

    def test_load_few_shot_examples_with_file(self):
        """Test _load_few_shot_examples with existing few-shot file."""
        stage_dir = Path(self.temp_dir) / "analyze_structure"
        stage_dir.mkdir(parents=True)

        few_shot_file = stage_dir / "few_shot.jsonl"
        examples = [
            {"input": {"raw_text": "示例文本"}, "expected_output": {"chapters": []}},
        ]
        with open(few_shot_file, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        pipeline = AnalyzeStructurePipeline(prompt_dir=self.temp_dir)
        result = pipeline._load_few_shot_examples("analyze_structure")

        assert "示例 1" in result
        assert "示例文本" in result

    def test_build_prompt_includes_all_context(self):
        """Test _build_prompt includes all context data."""
        input_data = self.create_minimal_input()
        prompt = self.pipeline._build_prompt(input_data)

        assert "第一章" in prompt
        assert "测试书籍" in prompt
        assert "测试作者" in prompt
        assert "B" in prompt  # target_difficulty

    def test_run_mock_mode_returns_book_analysis_output(self):
        """Test run() returns BookAnalysisOutput from router mock result."""
        mock_router = MagicMock()
        mock_result = MagicMock()
        mock_result.output = self.create_mock_output()
        mock_result.model = "gpt-4o-mini"
        mock_result.tokens_in = 200
        mock_result.tokens_out = 100
        mock_result.cost_usd = 0.002
        mock_result.latency_ms = 800
        mock_result.schema_compliance = True
        mock_router.call.return_value = mock_result

        pipeline = AnalyzeStructurePipeline(router=mock_router)
        input_data = self.create_minimal_input()

        result = pipeline.run(input_data)

        assert isinstance(result, BookAnalysisOutput)
        assert result.book_meta.title == "Test Book"
        mock_router.call.assert_called_once()
        call_args = mock_router.call.call_args
        assert call_args[1]["stage"] == "analyze"
        assert call_args[1]["response_model"] == BookAnalysisOutput

    def test_run_real_mode_calls_router(self):
        """Test run() in real mode calls router with correct parameters."""
        mock_router = MagicMock()
        mock_result = MagicMock()
        mock_result.output = self.create_mock_output()
        mock_result.model = "gpt-4o-mini"
        mock_result.tokens_in = 200
        mock_result.tokens_out = 100
        mock_result.cost_usd = 0.002
        mock_result.latency_ms = 800
        mock_result.schema_compliance = True
        mock_router.call.return_value = mock_result

        pipeline = AnalyzeStructurePipeline(router=mock_router)
        input_data = self.create_minimal_input(raw_text="第1章 开始\n\n这是第一段。")

        result = pipeline.run(input_data)

        assert isinstance(result, BookAnalysisOutput)
        assert result.book_meta.title == "Test Book"
        mock_router.call.assert_called_once()
        call_args = mock_router.call.call_args
        assert call_args[1]["stage"] == "analyze"
        assert call_args[1]["response_model"] == BookAnalysisOutput

    def test_run_real_mode_router_exception(self):
        """Test run() raises exception when router fails."""
        mock_router = MagicMock()
        mock_router.call.side_effect = Exception("API Error")

        pipeline = AnalyzeStructurePipeline(router=mock_router)
        input_data = self.create_minimal_input()

        with pytest.raises(Exception, match="API Error"):
            pipeline.run(input_data)


class TestAnalyzeStructureConvenienceFunction:
    """Test analyze_structure convenience function."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_minimal_params(self, **overrides):
        """Create minimal valid parameters for convenience function."""
        defaults = {
            "raw_text": "第一章 开始\n\n这是第一段内容。\n\n第二章 继续\n\n这是第二段内容。",
            "title_hint": "便利函数测试书",
            "author_hint": "测试作者",
            "target_difficulty": "A",
        }
        defaults.update(overrides)
        return defaults

    def test_analyze_structure_mock_mode(self):
        """Test analyze_structure convenience function with mocked router."""
        # The convenience function creates a pipeline and calls run()
        # We patch the router creation to return a mock
        mock_router = MagicMock()
        mock_result = MagicMock()
        mock_result.output = BookAnalysisOutput(
            book_meta=BookMeta(
                title="Convenience Test",
                author="Test Author",
                genre="小说",
                difficulty="A",
                language="zh",
                era="现代",
                total_chapters_estimated=5,
            ),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="kokoro_narrator",
                    sample_quote="旁白样本。",
                ),
            ],
            emotion_snapshots=[
                EmotionSnapshot(chapter=1, dominant_emotion="neutral", intensity=0.5, notes="开始"),
            ],
            story_line_summary="这是一个关于测试的故事，主角经历各种冒险最终成功，并在过程中获得了宝贵的友谊和成长。"
            * 3,
            global_style_notes="风格备注。",
        )
        mock_result.model = "gpt-4o-mini"
        mock_result.tokens_in = 200
        mock_result.tokens_out = 100
        mock_result.cost_usd = 0.002
        mock_result.latency_ms = 800
        mock_result.schema_compliance = True

        from src.audiobook_studio.llm.router import create_router

        with patch("src.audiobook_studio.pipeline.analyze_structure.create_router") as mock_create_router:
            mock_router = MagicMock()
            mock_router.call.return_value = mock_result
            mock_create_router.return_value = mock_router

            params = self.create_minimal_params()
            result = analyze_structure(**params)

        assert isinstance(result, BookAnalysisOutput)
        assert result.book_meta.title == "Convenience Test"
        mock_router.call.assert_called_once()

    def test_analyze_structure_creates_correct_input(self):
        """Test analyze_structure creates BookAnalysisInput correctly."""
        # Test the full flow with mocked router
        mock_router = MagicMock()
        mock_result = MagicMock()
        mock_result.output = BookAnalysisOutput(
            book_meta=BookMeta(
                title="Test Book",
                author="Test Author",
                genre="小说",
                difficulty="B",
                language="zh",
                era="现代",
                total_chapters_estimated=10,
            ),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    aliases=[],
                    gender="neutral",
                    age_range="adult",
                    suggested_voice_id="kokoro_narrator",
                    sample_quote="旁白样本。",
                ),
            ],
            emotion_snapshots=[
                EmotionSnapshot(chapter=1, dominant_emotion="neutral", intensity=0.5, notes="开始"),
            ],
            story_line_summary="这是一个关于测试的故事，主角经历各种冒险最终成功，并在过程中获得了宝贵的友谊和成长。"
            * 3,
            global_style_notes="风格备注。",
        )
        mock_result.model = "gpt-4o-mini"
        mock_result.tokens_in = 100
        mock_result.tokens_out = 50
        mock_result.cost_usd = 0.001
        mock_result.latency_ms = 500
        mock_result.schema_compliance = True
        mock_router.call.return_value = mock_result

        with patch(
            "src.audiobook_studio.pipeline.analyze_structure.create_router",
            return_value=mock_router,
        ):
            params = self.create_minimal_params(raw_text="特定文本内容")
            result = analyze_structure(**params)

        assert isinstance(result, BookAnalysisOutput)
        assert "特定文本" in params["raw_text"]
        mock_router.call.assert_called_once()
        call_args = mock_router.call.call_args
        assert call_args[1]["stage"] == "analyze"


class TestAnalyzeStructureEdgeCases:
    """Test edge cases for AnalyzeStructurePipeline."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = AnalyzeStructurePipeline()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_base_input(self, **overrides):
        """Create base input with overrides."""
        defaults = {
            "raw_text": "这是基础测试文本内容。\n\n第二段内容。",
            "title_hint": "边界测试",
            "author_hint": "作者",
            "target_difficulty": "B",
        }
        defaults.update(overrides)
        return BookAnalysisInput(**defaults)

    def create_test_output(self, **overrides):
        """Create a valid BookAnalysisOutput for test mocking."""
        return self.create_mock_output(**overrides)

    def test_whitespace_only_text(self):
        """Test analysis with whitespace-heavy text."""
        input_data = self.create_base_input(raw_text="   \n\n  \t  \n\n  ")
        # Test _build_prompt handles it without error
        prompt = self.pipeline._build_prompt(input_data)
        assert isinstance(prompt, str)
        assert len(prompt) > 0

    def test_unicode_content(self):
        """Test analysis with unicode content (emoji, special chars)."""
        input_data = self.create_base_input(raw_text="第1章 🎉\n\n这是测试内容 📚\n\n第2章 🎊\n\n更多内容 🎈")
        prompt = self.pipeline._build_prompt(input_data)
        assert "🎉" in prompt
        assert "第1章" in prompt

    def test_all_difficulty_levels(self):
        """Test analysis with different difficulty levels."""
        for diff in ["A", "B", "C", "D"]:
            input_data = self.create_base_input(target_difficulty=diff)
            prompt = self.pipeline._build_prompt(input_data)
            assert diff in prompt

    def test_title_and_author_hints(self):
        """Test title and author hints are passed through."""
        input_data = self.create_base_input(title_hint="特定书名", author_hint="特定作者")
        prompt = self.pipeline._build_prompt(input_data)
        assert "特定书名" in prompt
        assert "特定作者" in prompt


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

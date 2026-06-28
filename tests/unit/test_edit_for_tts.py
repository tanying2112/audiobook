"""Comprehensive unit tests for edit_for_tts pipeline targeting ≥80% line coverage.
import os
os.environ["MOCK_LLM"] = "true"

Tests match the ACTUAL API from src/audiobook_studio/pipeline/edit_for_tts.py:
- EditForTtsPipeline class with run(), _build_prompt(), _load_few_shot()
- edit_for_tts() convenience function
- TtsEditInput/TtsEditOutput Pydantic models
- mock_mode behavior for testing without external APIs
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.audiobook_studio.pipeline.edit_for_tts import EditForTtsPipeline, edit_for_tts
from src.audiobook_studio.schemas import (
    BookMeta,
    CharacterVoiceBinding,
    EmotionSnapshot,
    ParagraphAnnotation,
    TtsEditInput,
    TtsEditOutput,
)


class TestEditForTtsPipeline:
    """Test EditForTtsPipeline class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = EditForTtsPipeline()

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_mock_annotation(self, **overrides):
        """Create a minimal ParagraphAnnotation for testing."""
        defaults = {
            "paragraph_index": 0,
            "speaker_canonical_name": "旁白",
            "is_dialogue": False,
            "emotion": "neutral",
            "emotion_intensity": 0.5,
            "speech_rate": 1.0,
            "pitch_shift_semitones": 0,
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.9,
            "difficulty": "B",
            "needs_sfx": False,
            "sfx_tags": [],
        }
        defaults.update(overrides)
        return ParagraphAnnotation(**defaults)

    def create_minimal_input(self, **overrides):
        """Create minimal valid TtsEditInput for testing."""
        defaults = {
            "paragraph_text": "这是一个足够长的测试段落文本内容，用于编辑。",
            "paragraph_annotation": self.create_mock_annotation(),
            "difficulty": "B",
            "forbid_edit": False,
        }
        defaults.update(overrides)
        return TtsEditInput(**defaults)

    def create_mock_output(self, **overrides):
        """Create a valid TtsEditOutput for mocking."""
        defaults = {
            "edited_text": "这是一个足够长的测试段落文本内容，用于编辑。",
            "changes_made": ["heuristic_fallback_no_llm_available"],
            "forbidden_content_removed": [],
            "confidence": 0.8,
            "rationale": "LLM unavailable, using heuristic fallback",
        }
        defaults.update(overrides)
        return TtsEditOutput(**defaults)

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        from src.audiobook_studio.llm import create_router

        pipeline = EditForTtsPipeline()
        assert pipeline.router is not None
        assert pipeline.jinja_env is not None

    def test_init_with_custom_router(self):
        """Test pipeline initialization with custom router."""
        mock_router = Mock()
        pipeline = EditForTtsPipeline(router=mock_router)
        assert pipeline.router == mock_router

    def test_init_with_custom_prompt_dir(self):
        """Test pipeline initialization with custom prompt directory."""
        pipeline = EditForTtsPipeline(prompt_dir=self.temp_dir)
        assert pipeline.prompt_dir == Path(self.temp_dir)

    def test_load_few_shot_no_file(self):
        """Test _load_few_shot when file doesn't exist."""
        result = self.pipeline._load_few_shot("nonexistent_stage")
        assert result == "(暂无示例)"

    def test_load_few_shot_with_file(self):
        """Test _load_few_shot with existing few-shot file."""
        stage_dir = Path(self.temp_dir) / "edit_for_tts"
        stage_dir.mkdir(parents=True)

        few_shot_file = stage_dir / "few_shot.jsonl"
        examples = [
            {"input": {"text": "示例1"}, "expected_output": {"edited_text": "编辑后1"}},
            {"input": {"text": "示例2"}, "expected_output": {"edited_text": "编辑后2"}},
        ]
        with open(few_shot_file, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex, ensure_ascii=False) + "\n")

        pipeline = EditForTtsPipeline(prompt_dir=self.temp_dir)
        result = pipeline._load_few_shot("edit_for_tts")

        assert "示例 1" in result
        assert "示例 2" in result
        assert "编辑后1" in result
        assert "编辑后2" in result

    def test_build_prompt_includes_all_context(self):
        """Test _build_prompt includes all context data."""
        input_data = self.create_minimal_input()
        prompt = self.pipeline._build_prompt(input_data)

        assert "测试段落文本" in prompt
        assert "旁白" in prompt
        assert "B" in prompt  # difficulty
        assert "False" in prompt  # forbid_edit

    def test_run_mock_mode_returns_tts_edit_output(self):
        """Test run() in mock mode returns TtsEditOutput with original text.

        Note: In mock mode, edit_for_tts returns original text without LLM call.
        """
        input_data = self.create_minimal_input()
        result = self.pipeline.run(input_data)

        assert isinstance(result, TtsEditOutput)
        # In mock mode, original text is returned without changes
        assert result.edited_text == input_data.paragraph_text
        assert "mock_mode_no_changes" in result.changes_made
        assert result.confidence == 0.9

    def test_run_mock_mode_difficulty_a_preserves_original(self):
        """Test run() in mock mode with difficulty A preserves original."""
        input_data = self.create_minimal_input(
            difficulty="A", paragraph_text="第1章 标题\n\n这是正文内容。"
        )
        result = self.pipeline.run(input_data)

        assert isinstance(result, TtsEditOutput)
        assert result.edited_text == input_data.paragraph_text
        assert "difficulty_A_or_forbid_edit_preserved_original" in result.changes_made
        assert result.confidence == 1.0
        assert "Difficulty A" in result.rationale

    def test_run_mock_mode_forbid_edit_preserves_original(self):
        """Test run() in mock mode with forbid_edit=True preserves original."""
        input_data = self.create_minimal_input(
            forbid_edit=True, paragraph_text="张三在2023年去了北京。"
        )
        result = self.pipeline.run(input_data)

        assert isinstance(result, TtsEditOutput)
        assert result.edited_text == input_data.paragraph_text
        assert "difficulty_A_or_forbid_edit_preserved_original" in result.changes_made
        assert result.confidence == 1.0

    def test_run_real_mode_calls_router(self):
        """Test run() in real mode calls router with correct parameters."""
        mock_router = MagicMock()
        mock_result = MagicMock()
        mock_result.output = self.create_mock_output()
        mock_result.model = "gpt-4o-mini"
        mock_result.tokens_in = 150
        mock_result.tokens_out = 75
        mock_result.cost_usd = 0.0015
        mock_result.latency_ms = 600
        mock_result.schema_compliance = True
        mock_router.call.return_value = mock_result

        # Explicitly set mock_mode=False for real mode test
        pipeline = EditForTtsPipeline(router=mock_router, mock_mode=False)
        input_data = self.create_minimal_input()

        result = pipeline.run(input_data)

        assert isinstance(result, TtsEditOutput)
        assert result.edited_text == "这是一个足够长的测试段落文本内容，用于编辑。"
        mock_router.call.assert_called_once()
        call_args = mock_router.call.call_args
        assert call_args[1]["stage"] == "edit"
        assert call_args[1]["response_model"] == TtsEditOutput

    def test_run_real_mode_records_performance_on_success(self):
        """Test run() records performance metrics on success."""
        mock_router = MagicMock()
        mock_result = MagicMock()
        mock_result.output = self.create_mock_output()
        mock_result.model = "gpt-4o-mini"
        mock_result.tokens_in = 150
        mock_result.tokens_out = 75
        mock_result.cost_usd = 0.0015
        mock_result.latency_ms = 600
        mock_result.schema_compliance = True
        mock_router.call.return_value = mock_result

        with patch(
            "src.audiobook_studio.monitoring.record_stage_performance"
        ) as mock_record:
            # Explicitly set mock_mode=False for real mode test
            pipeline = EditForTtsPipeline(router=mock_router, mock_mode=False)
            input_data = self.create_minimal_input()
            pipeline.run(input_data)

            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args[1]
            assert call_kwargs["stage"] == "edit_for_tts"
            assert call_kwargs["success"] is True
            assert call_kwargs["difficulty"] == "B"

    def test_run_real_mode_records_performance_on_failure(self):
        """Test run() records performance metrics on failure."""
        mock_router = MagicMock()
        mock_router.call.side_effect = Exception("API Error")

        with patch(
            "src.audiobook_studio.monitoring.record_stage_performance"
        ) as mock_record:
            # Explicitly set mock_mode=False for real mode test
            pipeline = EditForTtsPipeline(router=mock_router, mock_mode=False)
            input_data = self.create_minimal_input()

            with pytest.raises(Exception, match="API Error"):
                pipeline.run(input_data)

            mock_record.assert_called_once()
            call_kwargs = mock_record.call_args[1]
            assert call_kwargs["success"] is False
            assert call_kwargs["error"] == "API Error"
            assert call_kwargs["difficulty"] == "B"


class TestEditForTtsConvenienceFunction:
    """Test edit_for_tts convenience function."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_mock_annotation(self, **overrides):
        """Create a minimal ParagraphAnnotation for testing."""
        defaults = {
            "paragraph_index": 0,
            "speaker_canonical_name": "旁白",
            "is_dialogue": False,
            "emotion": "neutral",
            "emotion_intensity": 0.5,
            "speech_rate": 1.0,
            "pitch_shift_semitones": 0,
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.9,
            "difficulty": "B",
            "needs_sfx": False,
            "sfx_tags": [],
        }
        defaults.update(overrides)
        return ParagraphAnnotation(**defaults)

    def create_minimal_params(self, **overrides):
        """Create minimal valid parameters for convenience function."""
        defaults = {
            "paragraph_text": "这是一个足够长的测试段落文本内容，用于编辑。",
            "paragraph_annotation": self.create_mock_annotation(),
            "difficulty": "B",
            "forbid_edit": False,
        }
        defaults.update(overrides)
        return defaults

    def test_edit_for_tts_mock_mode(self):
        """Test edit_for_tts convenience function in mock mode.

        Note: In mock mode, original text is returned without LLM call.
        """
        params = self.create_minimal_params()
        result = edit_for_tts(**params)

        assert isinstance(result, TtsEditOutput)
        # In mock mode, original text is returned
        assert result.edited_text == params["paragraph_text"]
        assert "mock_mode_no_changes" in result.changes_made

    def test_edit_for_tts_creates_correct_input(self):
        """Test edit_for_tts creates TtsEditInput correctly."""
        params = self.create_minimal_params(paragraph_text="特定文本内容测试用例")
        result = edit_for_tts(**params)

        assert isinstance(result, TtsEditOutput)


class TestEditForTtsEdgeCases:
    """Test edge cases for EditForTtsPipeline."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = EditForTtsPipeline()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_base_input(self, **overrides):
        """Create base input with overrides."""
        defaults = {
            "paragraph_text": "这是基础测试文本内容。",
            "paragraph_annotation": ParagraphAnnotation(
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
                difficulty="B",
                needs_sfx=False,
                sfx_tags=[],
            ),
            "difficulty": "B",
            "forbid_edit": False,
        }
        defaults.update(overrides)
        return TtsEditInput(**defaults)

    def test_whitespace_only_text(self):
        """Test edit with whitespace-heavy text."""
        input_data = self.create_base_input(
            paragraph_text="   这是一个包含大量空白字符的测试文本内容。   \n\t  "
        )
        result = self.pipeline.run(input_data)
        assert isinstance(result, TtsEditOutput)

    def test_very_long_text(self):
        """Test edit with very long text (within field limits)."""
        long_text = "这是一个非常长的段落。" * 50  # ~1000 chars
        input_data = self.create_base_input(paragraph_text=long_text)
        result = self.pipeline.run(input_data)
        assert isinstance(result, TtsEditOutput)
        assert len(result.edited_text) > 0

    def test_unicode_content(self):
        """Test edit with unicode content (emoji, special chars)."""
        input_data = self.create_base_input(
            paragraph_text="Hello 世界! 🌍 你好 👋 特殊字符：①②③㈠㈡"
        )
        result = self.pipeline.run(input_data)
        assert isinstance(result, TtsEditOutput)

    def test_all_difficulty_levels(self):
        """Test edit with different difficulty levels."""
        for diff in ["A", "B", "C", "D"]:
            input_data = self.create_base_input(difficulty=diff)
            result = self.pipeline.run(input_data)
            assert isinstance(result, TtsEditOutput)

    def test_forbid_edit_flag(self):
        """Test forbid_edit flag preserves original text."""
        input_data = self.create_base_input(
            forbid_edit=True, paragraph_text="张三在2023年去了北京。"
        )
        result = self.pipeline.run(input_data)
        assert result.edited_text == "张三在2023年去了北京。"
        assert "difficulty_A_or_forbid_edit_preserved_original" in result.changes_made

    def test_dialogue_preservation(self):
        """Test dialogue text is preserved in mock mode."""
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="张三",
            is_dialogue=True,
            emotion="happy",
            emotion_intensity=0.8,
            speech_rate=1.1,
            pitch_shift_semitones=1,
            pause_before_ms=200,
            pause_after_ms=400,
            confidence=0.95,
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
        )
        input_data = self.create_base_input(
            paragraph_text="张三说：大哥，我们走吧！",
            paragraph_annotation=annotation,
        )
        result = self.pipeline.run(input_data)
        assert isinstance(result, TtsEditOutput)
        # In mock mode, original text is preserved
        assert result.edited_text == "张三说：大哥，我们走吧！"

    def test_chapter_marker_preservation(self):
        """Test chapter markers are preserved in mock mode."""
        input_data = self.create_base_input(
            paragraph_text="第 1 章 开始\n\n内容\n\n第 2 章 继续\n\n更多内容"
        )
        result = self.pipeline.run(input_data)
        assert isinstance(result, TtsEditOutput)
        # In mock mode, original text is preserved
        assert result.edited_text == "第 1 章 开始\n\n内容\n\n第 2 章 继续\n\n更多内容"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

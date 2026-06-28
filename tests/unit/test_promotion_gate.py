"""Tests for feedback/promotion_gate module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.feedback.promotion_gate import (
    GateResult,
    PromotionVerdict,
    _aggregate_quality_score,
    _char_ngram_similarity,
    _compute_audio_quality_metrics,
    _compute_output_similarity,
    _compute_structure_quality_metrics,
    _compute_text_quality_metrics,
    _convert_input_to_model,
    _get_required_input_fields,
    _golden_to_pipeline_stage,
    _load_golden_examples,
    _load_prompt_version,
    _pipeline_stage_to_prompt_dir,
    check_format_compliance,
    check_golden_dataset,
    check_human_sample,
    check_quality_improvement,
    evaluate_promotion,
)


class TestGateResult:
    """Tests for GateResult dataclass."""

    def test_pass_rate_calculation(self):
        gates = [
            GateResult("Gate1", True, 0.9, 0.8),
            GateResult("Gate2", False, 0.7, 0.8),
            GateResult("Gate3", True, 0.95, 0.8),
        ]
        verdict = PromotionVerdict(
            passed=False,
            gates=gates,
            summary="Test",
            version_from=1,
            version_to=2,
            stage="test",
            evaluated_at="2024-01-01T00:00:00",
        )
        assert verdict.pass_rate == 2 / 3

    def test_pass_rate_empty(self):
        verdict = PromotionVerdict(
            passed=False,
            gates=[],
            summary="Test",
            version_from=1,
            version_to=2,
            stage="test",
            evaluated_at="2024-01-01T00:00:00",
        )
        assert verdict.pass_rate == 0.0


class TestCheckFormatCompliance:
    """Tests for check_format_compliance function."""

    def test_valid_prompt(self):
        prompt = "This is a valid prompt with {{ variable }} and {% if condition %}block{% endif %}"
        result = check_format_compliance(prompt)

        assert result.name == "格式合规率"
        assert result.passed is True
        assert result.score == 1.0
        assert "全部格式检查通过" in result.details

    def test_unclosed_variable(self):
        prompt = "Prompt with {{ unclosed variable"
        result = check_format_compliance(prompt)

        assert result.passed is False
        assert "未闭合的变量" in result.details

    def test_unclosed_block(self):
        prompt = "Prompt with {% unclosed block"
        result = check_format_compliance(prompt)

        assert result.passed is False
        assert "未闭合的块" in result.details

    def test_excessive_empty_lines(self):
        prompt = "Line 1\n\n\n\nLine 2"
        result = check_format_compliance(prompt)

        assert result.passed is False
        assert "连续超过 3 个空行" in result.details

    def test_trailing_empty_lines(self):
        prompt = "Content\n\n"
        result = check_format_compliance(prompt)

        assert result.passed is False
        assert "文件末尾多余空行" in result.details

    def test_custom_threshold(self):
        prompt = "Prompt with {{ unclosed"
        result = check_format_compliance(prompt, threshold=0.5)
        # With threshold 0.5, 1 failed out of 3 checks = score 0.67, should pass
        assert result.passed is True


class TestCheckGoldenDataset:
    """Tests for check_golden_dataset function."""

    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_examples")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_no_golden_dataset(self, mock_load_prompt, mock_load_golden):
        mock_load_golden.return_value = []
        mock_load_prompt.return_value = "prompt content"

        result = check_golden_dataset("edit_for_tts", 2)

        assert result.name == "黄金数据集通过率"
        assert result.passed is False
        assert result.score == 0.0
        assert "黄金数据集未找到" in result.details

    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_examples")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_no_prompt_version(self, mock_load_prompt, mock_load_golden):
        mock_load_golden.return_value = [{"input": "test", "expected_output": "test"}]
        mock_load_prompt.return_value = None

        result = check_golden_dataset("edit_for_tts", 2)

        assert result.passed is False
        assert "Prompt v2 not found" in result.details

    @patch(
        "src.audiobook_studio.feedback.promotion_gate._run_stage_with_prompt_version"
    )
    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_examples")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_golden_dataset_pass(
        self, mock_load_prompt, mock_load_golden, mock_run_stage
    ):
        mock_load_golden.return_value = [
            {
                "input": {
                    "paragraph_text": "test content",
                    "paragraph_annotation": {
                        "paragraph_index": 0,
                        "speaker_canonical_name": "_narrator_",
                        "is_dialogue": False,
                        "emotion": "neutral",
                        "emotion_intensity": 0.5,
                        "confidence": 0.9,
                        "difficulty": "B",
                    },
                    "difficulty": "B",
                    "forbid_edit": False,
                },
                "expected_output": {
                    "edited_text": "test content",
                    "confidence": 0.9,
                    "rationale": "mock",
                    "changes_made": [],
                    "forbidden_content_removed": [],
                    "forbid_edit": False,
                    "difficulty": "B",
                },
            },
        ]
        mock_load_prompt.return_value = "prompt content"
        # Mock stage output to match expected
        from src.audiobook_studio.schemas.tts_edit import TtsEditOutput

        mock_run_stage.return_value = TtsEditOutput(
            edited_text="test content", confidence=0.9, rationale="mock"
        )

        result = check_golden_dataset("edit_for_tts", 2, threshold=0.0)

        assert result.passed is True  # threshold 0.0 so anything passes
        assert "1/1 用例通过" in result.details

    @patch(
        "src.audiobook_studio.feedback.promotion_gate._run_stage_with_prompt_version"
    )
    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_examples")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_golden_dataset_partial(
        self, mock_load_prompt, mock_load_golden, mock_run_stage
    ):
        mock_load_golden.return_value = [
            {
                "input": {
                    "paragraph_text": "test content",
                    "paragraph_annotation": {
                        "paragraph_index": 0,
                        "speaker_canonical_name": "_narrator_",
                        "is_dialogue": False,
                        "emotion": "neutral",
                        "emotion_intensity": 0.5,
                        "confidence": 0.9,
                        "difficulty": "B",
                    },
                    "difficulty": "B",
                    "forbid_edit": False,
                },
                "expected_output": {
                    "edited_text": "test content",
                    "confidence": 0.9,
                    "rationale": "mock",
                    "changes_made": [],
                    "forbidden_content_removed": [],
                    "forbid_edit": False,
                    "difficulty": "B",
                },
            },
            {"missing": "fields"},
        ]
        mock_load_prompt.return_value = "prompt content"
        from src.audiobook_studio.schemas.tts_edit import TtsEditOutput

        mock_run_stage.return_value = TtsEditOutput(
            edited_text="test content", confidence=0.9, rationale="mock"
        )

        result = check_golden_dataset("edit_for_tts", 2, threshold=0.0)

        # 1 valid example out of 2 total, but one is malformed
        assert result.passed is True
        assert "1/1 用例通过" in result.details


class TestCheckQualityImprovement:
    """Tests for check_quality_improvement function."""

    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_no_old_prompt(self, mock_load_prompt):
        mock_load_prompt.side_effect = [None, "new prompt"]

        result = check_quality_improvement("edit_for_tts", 1, 2)

        assert result.name == "质量 ≥ 旧版 102%"
        assert result.passed is False
        assert "无法加载 prompt" in result.details

    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_no_new_prompt(self, mock_load_prompt):
        mock_load_prompt.side_effect = ["old prompt", None]

        result = check_quality_improvement("edit_for_tts", 1, 2)

        assert result.passed is False
        assert "无法加载 prompt" in result.details

    @patch(
        "src.audiobook_studio.feedback.promotion_gate._run_stage_with_prompt_version"
    )
    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_examples")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_quality_improvement_pass(
        self, mock_load_prompt, mock_load_golden, mock_run_stage
    ):
        # Old prompt with some patterns, new prompt with more patterns and longer
        old_prompt = "Basic prompt with dialogue_attribution"
        new_prompt = (
            "Enhanced prompt with dialogue_attribution emotion_too_mild emotion_wrong speaker_wrong "
            + "x" * 2000
        )
        mock_load_prompt.side_effect = [old_prompt, new_prompt]
        mock_load_golden.return_value = [
            {
                "input": {
                    "paragraph_text": "test content",
                    "paragraph_annotation": {
                        "paragraph_index": 0,
                        "speaker_canonical_name": "_narrator_",
                        "is_dialogue": False,
                        "emotion": "neutral",
                        "emotion_intensity": 0.5,
                        "confidence": 0.9,
                        "difficulty": "B",
                    },
                    "difficulty": "B",
                    "forbid_edit": False,
                },
                "expected_output": {
                    "edited_text": "test content",
                    "confidence": 0.9,
                    "rationale": "mock",
                    "changes_made": [],
                    "forbidden_content_removed": [],
                    "forbid_edit": False,
                    "difficulty": "B",
                },
            },
        ]
        from src.audiobook_studio.schemas.tts_edit import TtsEditOutput

        # Return identical outputs for both old and new (score ratio = 1.0)
        mock_run_stage.return_value = TtsEditOutput(
            edited_text="test content", confidence=0.9, rationale="mock"
        )

        result = check_quality_improvement("edit_for_tts", 1, 2, threshold=1.0)

        # Both versions produce same output in mock mode, score = 1.0 >= 1.0 threshold
        assert result.score == 1.0  # Both outputs identical

    @patch(
        "src.audiobook_studio.feedback.promotion_gate._run_stage_with_prompt_version"
    )
    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_examples")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_quality_no_improvement(
        self, mock_load_prompt, mock_load_golden, mock_run_stage
    ):
        old_prompt = (
            "Enhanced prompt with dialogue_attribution emotion_too_mild " + "x" * 5000
        )
        new_prompt = "Basic prompt"
        mock_load_prompt.side_effect = [old_prompt, new_prompt]
        mock_load_golden.return_value = [
            {
                "input": {
                    "paragraph_text": "test content",
                    "paragraph_annotation": {
                        "paragraph_index": 0,
                        "speaker_canonical_name": "_narrator_",
                        "is_dialogue": False,
                        "emotion": "neutral",
                        "emotion_intensity": 0.5,
                        "confidence": 0.9,
                        "difficulty": "B",
                    },
                    "difficulty": "B",
                    "forbid_edit": False,
                },
                "expected_output": {
                    "edited_text": "test content",
                    "confidence": 0.9,
                    "rationale": "mock",
                    "changes_made": [],
                    "forbidden_content_removed": [],
                    "forbid_edit": False,
                    "difficulty": "B",
                },
            },
        ]
        from src.audiobook_studio.schemas.tts_edit import TtsEditOutput

        mock_run_stage.return_value = TtsEditOutput(
            edited_text="test content", confidence=0.9, rationale="mock"
        )

        result = check_quality_improvement("edit_for_tts", 1, 2, threshold=1.0)

        # Both versions produce same output, so score = 1.0
        assert result.score == 1.0


class TestCheckHumanSample:
    """Tests for check_human_sample function."""

    def test_no_samples(self):
        result = check_human_sample(None)

        assert result.name == "人工抽样通过率"
        assert result.passed is False
        assert result.score == 0.0
        assert "尚无人工抽样结果" in result.details

    def test_all_pass(self):
        result = check_human_sample([True, True, True, True, True])

        assert result.passed is True
        assert result.score == 1.0
        assert "5/5 抽样通过" in result.details

    def test_mixed_results(self):
        result = check_human_sample([True, False, True, True, False])

        # 3/5 = 60% < 80% threshold, should fail
        assert result.passed is False
        assert result.score == 0.6

    def test_meets_threshold(self):
        result = check_human_sample([True, True, True, True, False])  # 4/5 = 80%

        assert result.passed is True
        assert result.score == 0.8

    def test_custom_threshold(self):
        result = check_human_sample([True, False], threshold=0.5)

        assert result.passed is True
        assert result.score == 0.5


class TestEvaluatePromotion:
    """Tests for evaluate_promotion main function."""

    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_prompt_not_found(self, mock_load_prompt):
        mock_load_prompt.return_value = None

        verdict = evaluate_promotion("edit_for_tts", 1, 2)

        assert verdict.passed is False
        assert len(verdict.gates) == 0
        assert "not found" in verdict.summary

    @patch("src.audiobook_studio.feedback.promotion_gate.check_format_compliance")
    @patch("src.audiobook_studio.feedback.promotion_gate.check_golden_dataset")
    @patch("src.audiobook_studio.feedback.promotion_gate.check_quality_improvement")
    @patch("src.audiobook_studio.feedback.promotion_gate.check_human_sample")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_all_gates_pass(
        self, mock_load_prompt, mock_human, mock_quality, mock_golden, mock_format
    ):
        mock_load_prompt.return_value = "new prompt"
        mock_format.return_value = GateResult("格式合规率", True, 1.0, 0.99)
        mock_golden.return_value = GateResult("黄金数据集通过率", True, 0.95, 0.95)
        mock_quality.return_value = GateResult("质量 ≥ 旧版 102%", True, 1.05, 1.02)
        mock_human.return_value = GateResult("人工抽样通过率", True, 0.8, 0.8)

        verdict = evaluate_promotion("edit_for_tts", 1, 2, human_samples=[True] * 5)

        assert verdict.passed is True
        assert len(verdict.gates) == 4
        assert "✅ 全部门禁通过" in verdict.summary
        assert verdict.version_from == 1
        assert verdict.version_to == 2
        assert verdict.stage == "edit_for_tts"

    @patch("src.audiobook_studio.feedback.promotion_gate.check_format_compliance")
    @patch("src.audiobook_studio.feedback.promotion_gate.check_golden_dataset")
    @patch("src.audiobook_studio.feedback.promotion_gate.check_quality_improvement")
    @patch("src.audiobook_studio.feedback.promotion_gate.check_human_sample")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_some_gates_fail(
        self, mock_load_prompt, mock_human, mock_quality, mock_golden, mock_format
    ):
        mock_load_prompt.return_value = "new prompt"
        mock_format.return_value = GateResult("格式合规率", True, 1.0, 0.99)
        mock_golden.return_value = GateResult("黄金数据集通过率", False, 0.8, 0.95)
        mock_quality.return_value = GateResult("质量 ≥ 旧版 102%", True, 1.05, 1.02)
        mock_human.return_value = GateResult("人工抽样通过率", True, 0.8, 0.8)

        verdict = evaluate_promotion("edit_for_tts", 1, 2)

        assert verdict.passed is False
        assert "1/4 门禁未通过" in verdict.summary
        assert verdict.gates[1].passed is False


class TestLoadFunctions:
    """Tests for internal load functions."""

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.glob")
    def test_load_golden_examples_no_dir(self, mock_glob, mock_exists):
        mock_exists.return_value = False

        result = _load_golden_examples("nonexistent_stage")
        assert result == []

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.glob")
    def test_load_prompt_version_not_found(self, mock_glob, mock_exists):
        mock_exists.return_value = False

        result = _load_prompt_version("stage", 1)
        assert result is None

    def test_golden_to_pipeline_stage(self):
        """Test mapping of golden dataset names to pipeline stages."""
        assert _golden_to_pipeline_stage("edit_for_tts") == "edit"
        assert _golden_to_pipeline_stage("annotate_paragraph") == "annotate"
        assert _golden_to_pipeline_stage("unknown_stage") == "unknown_stage"

    def test_pipeline_stage_to_prompt_dir(self):
        """Test mapping of pipeline stages to prompt directory names."""
        assert _pipeline_stage_to_prompt_dir("edit") == "edit_for_tts"
        assert _pipeline_stage_to_prompt_dir("annotate") == "annotate_paragraph"
        assert _pipeline_stage_to_prompt_dir("unknown") == "unknown"

    def test_convert_input_to_model_unknown_stage(self):
        """Test _convert_input_to_model returns input as-is for unknown stages."""
        result = _convert_input_to_model("unknown_stage", {"text": "test"})
        assert result == {"text": "test"}

    def test_get_required_input_fields(self):
        """Test _get_required_input_fields returns correct field lists."""
        assert _get_required_input_fields("edit") == [
            "paragraph_text",
            "paragraph_annotation",
            "difficulty",
            "forbid_edit",
        ]
        assert _get_required_input_fields("annotate") == [
            "paragraph_text",
            "paragraph_index",
        ]
        assert _get_required_input_fields("analyze") == ["book_text", "book_meta"]
        assert _get_required_input_fields("extract") == ["text"]
        assert _get_required_input_fields("quality") == ["audio_path", "expected_text"]
        assert _get_required_input_fields("synthesize") == ["text", "voice_id"]
        assert _get_required_input_fields("unknown") == []

    def test_char_ngram_similarity(self):
        """Test character n-gram similarity computation."""
        # Identical strings should have similarity 1.0
        assert _char_ngram_similarity("hello", "hello") == 1.0
        # Completely different strings have lower similarity
        assert _char_ngram_similarity("abc", "xyz") < 1.0
        # Empty strings
        assert _char_ngram_similarity("", "hello") == 0.0
        assert _char_ngram_similarity("hello", "") == 0.0

    def test_compute_output_similarity(self):
        """Test output similarity computation."""
        # Identical outputs
        assert _compute_output_similarity({"text": "hello"}, {"text": "hello"}) == 1.0
        # Missing keys
        assert _compute_output_similarity({}, {"text": "hello"}) == 0.0
        # One empty
        assert _compute_output_similarity({"text": ""}, {"text": "hello"}) == 0.0

    def test_compute_text_quality_metrics(self):
        """Test text quality metrics computation."""
        actual = {"edited_text": "hello world", "confidence": 0.9}
        expected = {"edited_text": "hello world", "confidence": 0.9}
        input_data = {}
        metrics = _compute_text_quality_metrics(actual, expected, input_data)
        assert "output_similarity" in metrics
        assert "text_similarity" in metrics
        assert "confidence" in metrics

    def test_compute_audio_quality_metrics(self):
        """Test audio quality metrics computation."""
        actual = {"overall_score": 0.9, "speaker_clarity": 0.85}
        expected = {"overall_score": 0.9, "speaker_clarity": 0.85}
        input_data = {}
        metrics = _compute_audio_quality_metrics(actual, expected, input_data)
        assert "output_similarity" in metrics
        assert "overall_score_match" in metrics

    def test_compute_structure_quality_metrics(self):
        """Test structure quality metrics computation."""
        actual = {"book_meta": {"title": "Test"}}
        expected = {"book_meta": {"title": "Test"}}
        input_data = {}
        metrics = _compute_structure_quality_metrics(actual, expected, input_data)
        assert "output_similarity" in metrics

    def test_aggregate_quality_score(self):
        """Test quality score aggregation."""
        metrics = {"output_similarity": 0.9, "confidence": 0.8}
        # Text edit stage
        score = _aggregate_quality_score(metrics, "text_edit")
        assert 0.0 <= score <= 1.0
        # Unknown stage (should use output_similarity only)
        score = _aggregate_quality_score({}, "unknown")
        assert score == 0.0
        score = _aggregate_quality_score({"output_similarity": 0.5}, "unknown")
        assert score == 0.5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Tests for feedback/promotion_gate module."""

import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from src.audiobook_studio.feedback.promotion_gate import (
    GateResult,
    PromotionVerdict,
    check_format_compliance,
    check_golden_dataset,
    check_quality_improvement,
    check_human_sample,
    evaluate_promotion,
    _load_golden_dataset,
    _load_golden_jsonl,
    _load_prompt_version,
    _EXTRACTED_PATTERNS,
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
        assert verdict.pass_rate == 2/3

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

    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_jsonl")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_dataset")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_no_golden_dataset(self, mock_load_prompt, mock_load_golden, mock_load_jsonl):
        mock_load_golden.return_value = []
        mock_load_jsonl.return_value = []
        mock_load_prompt.return_value = "prompt content"

        result = check_golden_dataset("edit_for_tts", 2)

        assert result.name == "黄金数据集通过率"
        assert result.passed is False
        assert result.score == 0.0
        assert "黄金数据集未找到" in result.details

    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_dataset")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_no_prompt_version(self, mock_load_prompt, mock_load_golden):
        mock_load_golden.return_value = [{"input": "test", "output": "test"}]
        mock_load_prompt.return_value = None

        result = check_golden_dataset("edit_for_tts", 2)

        assert result.passed is False
        assert "Prompt v2 not found" in result.details

    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_dataset")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_golden_dataset_pass(self, mock_load_prompt, mock_load_golden):
        mock_load_golden.return_value = [
            {"input": "test1", "output": "out1"},
            {"input": "test2", "output": "out2"},
        ]
        mock_load_prompt.return_value = "prompt content"

        result = check_golden_dataset("edit_for_tts", 2, threshold=0.5)

        assert result.passed is True
        assert result.score == 1.0
        assert "2/2 用例通过" in result.details

    @patch("src.audiobook_studio.feedback.promotion_gate._load_golden_dataset")
    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_golden_dataset_partial(self, mock_load_prompt, mock_load_golden):
        mock_load_golden.return_value = [
            {"input": "test1", "output": "out1"},
            {"missing": "fields"},
        ]
        mock_load_prompt.return_value = "prompt content"

        result = check_golden_dataset("edit_for_tts", 2, threshold=0.5)

        assert result.passed is True
        assert result.score == 0.5
        assert "1/2 用例通过" in result.details


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

    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_quality_improvement_pass(self, mock_load_prompt):
        # Old prompt with some patterns, new prompt with more patterns and longer
        old_prompt = "Basic prompt with dialogue_attribution"
        new_prompt = "Enhanced prompt with dialogue_attribution emotion_too_mild emotion_wrong speaker_wrong " + "x" * 2000
        mock_load_prompt.side_effect = [old_prompt, new_prompt]

        result = check_quality_improvement("edit_for_tts", 1, 2, threshold=1.02)

        # Should have improvement
        assert result.score > 1.0

    @patch("src.audiobook_studio.feedback.promotion_gate._load_prompt_version")
    def test_quality_no_improvement(self, mock_load_prompt):
        old_prompt = "Enhanced prompt with dialogue_attribution emotion_too_mild " + "x" * 5000
        new_prompt = "Basic prompt"
        mock_load_prompt.side_effect = [old_prompt, new_prompt]

        result = check_quality_improvement("edit_for_tts", 1, 2, threshold=1.02)

        assert result.passed is False
        assert result.score < 1.02


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
    def test_all_gates_pass(self, mock_load_prompt, mock_human, mock_quality, mock_golden, mock_format):
        mock_load_prompt.return_value = "new prompt"
        mock_format.return_value = GateResult("格式合规率", True, 1.0, 0.99)
        mock_golden.return_value = GateResult("黄金数据集通过率", True, 0.95, 0.95)
        mock_quality.return_value = GateResult("质量 ≥ 旧版 102%", True, 1.05, 1.02)
        mock_human.return_value = GateResult("人工抽样通过率", True, 0.8, 0.8)

        verdict = evaluate_promotion("edit_for_tts", 1, 2, human_samples=[True]*5)

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
    def test_some_gates_fail(self, mock_load_prompt, mock_human, mock_quality, mock_golden, mock_format):
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
    def test_load_golden_dataset_no_dir(self, mock_glob, mock_exists):
        mock_exists.return_value = False

        result = _load_golden_dataset("nonexistent_stage")
        assert result == []

    @patch("pathlib.Path.exists")
    @patch("pathlib.Path.glob")
    def test_load_prompt_version_not_found(self, mock_glob, mock_exists):
        mock_exists.return_value = False

        result = _load_prompt_version("stage", 1)
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
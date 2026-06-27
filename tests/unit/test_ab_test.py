"""Tests for feedback/ab_test module."""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from src.audiobook_studio.feedback.ab_test import (
    ABTestSample,
    ABTestResult,
    ABTestReport,
    _score_output,
    run_ab_test,
    build_ab_samples,
    blind_evaluate,
)


class TestABTestSample:
    """Tests for ABTestSample dataclass."""

    def test_sample_creation(self):
        sample = ABTestSample(
            sample_id="test-123",
            stage="edit_for_tts",
            input_data={"text": "input"},
            output_a={"edited_text": "output a"},
            output_b={"edited_text": "output b"},
            version_a=1,
            version_b=2,
        )

        assert sample.sample_id == "test-123"
        assert sample.stage == "edit_for_tts"
        assert sample.version_a == 1
        assert sample.version_b == 2


class TestABTestResult:
    """Tests for ABTestResult dataclass."""

    def test_result_creation(self):
        result = ABTestResult(
            sample_id="test-123",
            winner="B",
            score_a=0.7,
            score_b=0.85,
            rationale="B has better emotion handling",
        )

        assert result.sample_id == "test-123"
        assert result.winner == "B"
        assert result.score_a == 0.7
        assert result.score_b == 0.85
        assert "emotion handling" in result.rationale


class TestScoreOutput:
    """Tests for _score_output heuristic function."""

    def test_edit_for_tts_basic(self):
        output = {"edited_text": "hello world"}
        score = _score_output(output, "edit_for_tts")
        assert 0.5 <= score <= 1.0

    def test_edit_for_tts_with_forbidden(self):
        output = {
            "edited_text": "hello world",
            "forbidden_content_removed": True,
            "confidence": 0.9,
        }
        score = _score_output(output, "edit_for_tts")
        assert score > 0.6

    def test_edit_for_tts_empty_text(self):
        output = {"edited_text": ""}
        score = _score_output(output, "edit_for_tts")
        assert score == 0.5  # baseline only

    def test_quality_judge_basic(self):
        output = {"overall_score": 0.8}
        score = _score_output(output, "quality_judge")
        assert score > 0.5

    def test_quality_judge_with_issues_and_fixes(self):
        output = {
            "overall_score": 0.9,
            "issues": ["silence"],
            "fix_suggestions": [{"action": "regenerate"}],
        }
        score = _score_output(output, "quality_judge")
        assert score > 0.7

    def test_annotate_paragraph_basic(self):
        output = {
            "emotion": "happy",
            "speaker_canonical_name": "旁白",
            "is_dialogue": False,
            "emotion_intensity": 0.7,
        }
        score = _score_output(output, "annotate_paragraph")
        assert score > 0.8

    def test_annotate_partial_fields(self):
        output = {
            "emotion": "happy",
        }
        score = _score_output(output, "annotate_paragraph")
        assert 0.5 <= score <= 1.0

    def test_unknown_stage(self):
        output = {"some": "data"}
        score = _score_output(output, "unknown_stage")
        assert score == 0.5  # baseline only


class TestRunABTest:
    """Tests for run_ab_test function."""

    def test_empty_samples(self):
        report = run_ab_test("edit_for_tts", [])

        assert report.stage == "edit_for_tts"
        assert report.num_samples == 0
        assert report.results == []
        assert "无样本数据" in report.recommendation
        assert report.a_wins == 0
        assert report.b_wins == 0
        assert report.ties == 0

    def test_b_wins_clear(self):
        samples = [
            ABTestSample(
                sample_id="s1",
                stage="edit_for_tts",
                input_data={},
                output_a={"edited_text": "short"},
                output_b={"edited_text": "much longer and better output text with more content"},
                version_a=1,
                version_b=2,
            ),
            ABTestSample(
                sample_id="s2",
                stage="edit_for_tts",
                input_data={},
                output_a={"edited_text": "short"},
                output_b={"edited_text": "much longer and better output text with more content"},
                version_a=1,
                version_b=2,
            ),
            ABTestSample(
                sample_id="s3",
                stage="edit_for_tts",
                input_data={},
                output_a={"edited_text": "short"},
                output_b={"edited_text": "much longer and better output text with more content"},
                version_a=1,
                version_b=2,
            ),
        ]

        report = run_ab_test("edit_for_tts", samples)

        assert report.num_samples == 3
        assert report.b_wins == 3
        assert report.a_wins == 0
        assert report.ties == 0
        assert report.avg_score_b > report.avg_score_a
        assert "推荐升级" in report.recommendation
        assert report.version_a == 1
        assert report.version_b == 2

    def test_a_wins(self):
        samples = [
            ABTestSample(
                sample_id="s1",
                stage="edit_for_tts",
                input_data={},
                output_a={"edited_text": "much longer and better output text with more content", "confidence": 0.9},
                output_b={"edited_text": "short"},
                version_a=2,
                version_b=3,
            ),
        ]

        report = run_ab_test("edit_for_tts", samples)

        assert report.a_wins == 1
        assert report.b_wins == 0
        assert "不建议升级" in report.recommendation

    def test_tie(self):
        samples = [
            ABTestSample(
                sample_id="s1",
                stage="edit_for_tts",
                input_data={},
                output_a={"edited_text": "same length text"},
                output_b={"edited_text": "same length text"},
                version_a=1,
                version_b=2,
            ),
        ]

        report = run_ab_test("edit_for_tts", samples)

        assert report.ties == 1
        assert report.a_wins == 0
        assert report.b_wins == 0
        assert "不明确" in report.recommendation

    def test_custom_judge_fn(self):
        samples = [
            ABTestSample(
                sample_id="s1",
                stage="edit_for_tts",
                input_data={},
                output_a={"edited_text": "a"},
                output_b={"edited_text": "b"},
                version_a=1,
                version_b=2,
            ),
        ]

        # Custom judge that always prefers A
        def custom_judge(output):
            return 1.0 if output.get("edited_text") == "a" else 0.0

        report = run_ab_test("edit_for_tts", samples, judge_fn=custom_judge)

        assert report.a_wins == 1
        assert report.b_wins == 0
        assert report.avg_score_a == 1.0
        assert report.avg_score_b == 0.0

    def test_improvement_pct_calculation(self):
        samples = [
            ABTestSample(
                sample_id=f"s{i}",
                stage="edit_for_tts",
                input_data={},
                output_a={"edited_text": "a" * 10},  # score ~0.55
                output_b={"edited_text": "b" * 100},  # score ~0.65
                version_a=1,
                version_b=2,
            )
            for i in range(10)
        ]

        report = run_ab_test("edit_for_tts", samples)

        # Score difference should be ~18% (0.1/0.55)
        assert abs(report.improvement_pct - 18) < 10  # approximate


class TestBuildABSamples:
    """Tests for build_ab_samples function."""

    def test_build_from_golden(self):
        golden = [
            {
                "input": {"text": "test 1"},
                "output_old": {"edited_text": "old output 1"},
                "output_new": {"edited_text": "new improved output 1"},
            },
            {
                "input": {"text": "test 2"},
                "output_old": {"edited_text": "old output 2"},
                "output_new": {"edited_text": "new improved output 2"},
            },
        ]

        samples = build_ab_samples("edit_for_tts", golden, 1, 2)

        assert len(samples) == 2
        assert samples[0].version_a == 1
        assert samples[0].version_b == 2
        assert samples[0].input_data == {"text": "test 1"}
        assert samples[0].output_a == {"edited_text": "old output 1"}
        assert samples[0].output_b == {"edited_text": "new improved output 1"}

    def test_build_fallback_to_output(self):
        # If output_old/output_new not present, fall back to output
        golden = [
            {"input": {"text": "test"}, "output": {"edited_text": "default"}},
        ]

        samples = build_ab_samples("edit_for_tts", golden, 1, 2)

        assert len(samples) == 1
        assert samples[0].output_a == {"edited_text": "default"}
        assert samples[0].output_b == {"edited_text": "default"}


class TestBlindEvaluate:
    """Tests for blind_evaluate function."""

    def test_no_human_ratings(self):
        report = ABTestReport(
            stage="edit_for_tts",
            version_a=1,
            version_b=2,
            num_samples=2,
            results=[
                ABTestResult("s1", "A", 0.7, 0.6),
                ABTestResult("s2", "B", 0.5, 0.8),
            ],
            a_wins=1,
            b_wins=1,
            ties=0,
            avg_score_a=0.6,
            avg_score_b=0.7,
            improvement_pct=16.67,
        )

        result = blind_evaluate(report, None)

        assert result is report  # Should return same object
        assert result.a_wins == 1
        assert result.b_wins == 1

    def test_with_human_ratings(self):
        report = ABTestReport(
            stage="edit_for_tts",
            version_a=1,
            version_b=2,
            num_samples=3,
            results=[
                ABTestResult("s1", "A", 0.7, 0.6),
                ABTestResult("s2", "B", 0.5, 0.8),
                ABTestResult("s3", "tie", 0.6, 0.6),
            ],
            a_wins=1,
            b_wins=1,
            ties=1,
            avg_score_a=0.6,
            avg_score_b=0.67,
            improvement_pct=11.67,
        )

        human_ratings = [
            {"sample_id": "s1", "score_a": 0.5, "score_b": 0.9, "rationale": "B much better"},
            {"sample_id": "s3", "score_a": 0.4, "score_b": 0.7, "rationale": "B better"},
        ]

        result = blind_evaluate(report, human_ratings)

        assert result.results[0].winner == "B"  # Updated by human rating
        assert result.results[0].score_a == 0.5
        assert result.results[0].score_b == 0.9
        assert result.results[0].rationale == "B much better"
        assert result.results[2].winner == "B"  # Updated by human rating
        assert result.b_wins == 3  # s1, s2, s3 now B wins
        assert result.a_wins == 0
        assert result.ties == 0

    def test_human_rating_partial(self):
        report = ABTestReport(
            stage="edit_for_tts",
            version_a=1,
            version_b=2,
            num_samples=2,
            results=[
                ABTestResult("s1", "A", 0.7, 0.6),
                ABTestResult("s2", "B", 0.5, 0.8),
            ],
            a_wins=1,
            b_wins=1,
            ties=0,
            avg_score_a=0.6,
            avg_score_b=0.7,
        )

        # Only rate s1
        human_ratings = [
            {"sample_id": "s1", "score_a": 0.8, "score_b": 0.9},
        ]

        result = blind_evaluate(report, human_ratings)

        assert result.results[0].winner == "B"  # Human rated B higher
        assert result.results[1].winner == "B"  # Unchanged (was B)


class TestIntegration:
    """Integration tests for A/B testing workflow."""

    def test_full_ab_workflow(self):
        """Simulate a complete A/B test workflow."""
        # 1. Build samples from golden dataset
        golden = [
            {"input": {"text": f"paragraph {i}"}, "output_old": {"edited_text": f"v1 text {i}"}, "output_new": {"edited_text": f"v2 improved text {i}"}}
            for i in range(5)
        ]

        samples = build_ab_samples("edit_for_tts", golden, 1, 2)
        assert len(samples) == 5

        # 2. Run A/B test
        report = run_ab_test("edit_for_tts", samples)
        assert report.num_samples == 5

        # 3. Apply human blind evaluation on subset
        human_ratings = [
            {"sample_id": r.sample_id, "score_a": r.score_a, "score_b": r.score_b + 0.1}
            for r in report.results[:2]
        ]

        final_report = blind_evaluate(report, human_ratings)
        assert final_report.b_wins >= report.b_wins  # Should improve or stay same

    def test_quality_judge_stage(self):
        """Test A/B test on quality_judge stage."""
        samples = [
            ABTestSample(
                sample_id=f"q{i}",
                stage="quality_judge",
                input_data={},
                output_a={"overall_score": 0.7, "issues": []},
                output_b={"overall_score": 0.85, "issues": ["minor"], "fix_suggestions": [{"action": "check"}]},
                version_a=1,
                version_b=2,
            )
            for i in range(3)
        ]

        report = run_ab_test("quality_judge", samples)

        assert report.b_wins == 3
        assert report.avg_score_b > report.avg_score_a

    def test_annotate_stage(self):
        """Test A/B test on annotate_paragraph stage."""
        samples = [
            ABTestSample(
                sample_id=f"a{i}",
                stage="annotate_paragraph",
                input_data={},
                output_a={"emotion": "neutral", "speaker_canonical_name": "narrator", "is_dialogue": False},
                output_b={"emotion": "happy", "speaker_canonical_name": "旁白", "is_dialogue": True, "emotion_intensity": 0.8},
                version_a=1,
                version_b=2,
            )
            for i in range(3)
        ]

        report = run_ab_test("annotate_paragraph", samples)

        assert report.b_wins == 3
        assert report.avg_score_b > report.avg_score_a


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
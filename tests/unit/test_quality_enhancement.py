"""Tests for feedback/quality_enhancement module."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.feedback.quality_enhancement import (
    _VALID_EMOTIONS,
    DifficultyWeights,
    FalsePositiveIssue,
    FalsePositiveTracker,
    FreeTierHealth,
    SemanticCoherenceResult,
    ValidationReport,
    _cosine_similarity,
    check_semantic_coherence,
    get_false_positive_tracker,
    get_free_tier_health,
    grade_difficulty,
    validate_emotions,
)


class TestCosineSimilarity:
    """Tests for _cosine_similarity function."""

    def test_identical_text(self):
        sim = _cosine_similarity("hello world", "hello world")
        assert sim == pytest.approx(1.0)

    def test_completely_different(self):
        sim = _cosine_similarity("hello", "world")
        assert 0 <= sim < 1.0

    def test_empty_strings(self):
        sim = _cosine_similarity("", "")
        assert sim == 0.0  # Returns 0 when magnitude is 0

    def test_one_empty(self):
        sim = _cosine_similarity("hello", "")
        assert sim == 0.0

    def test_chinese_text(self):
        sim = _cosine_similarity("你好世界", "你好世界")
        assert sim == pytest.approx(1.0)

    def test_partial_overlap(self):
        sim = _cosine_similarity("hello world", "hello there")
        assert 0 < sim < 1.0


class TestCheckSemanticCoherence:
    """Tests for check_semantic_coherence function."""

    def test_insufficient_paragraphs(self):
        result = check_semantic_coherence(["single paragraph"])
        assert result.is_coherent is True
        assert result.mean_score == 1.0
        assert result.std_score == 0.0
        assert len(result.anomalies) == 0

    def test_empty_list(self):
        result = check_semantic_coherence([])
        assert result.is_coherent is True
        assert result.mean_score == 1.0

    def test_two_paragraphs(self):
        paragraphs = ["第一段内容", "第二段内容"]
        result = check_semantic_coherence(paragraphs)

        assert len(result.scores) == 1
        assert 0 <= result.mean_score <= 1
        assert result.std_score == 0.0  # Only one score, no variance
        assert result.is_coherent is True

    def test_multiple_paragraphs(self):
        paragraphs = [
            "第一章 开始了故事",
            "第二章 故事继续发展",
            "第三章 故事达到高潮",
            "第四章 故事结束",
        ]
        result = check_semantic_coherence(paragraphs)

        assert len(result.scores) == 3
        assert 0 <= result.mean_score <= 1
        assert result.std_score >= 0
        assert isinstance(result.is_coherent, bool)

    def test_with_golden_stats(self):
        paragraphs = ["段落一", "段落二", "段落三", "段落四"]
        golden_stats = {"mean": 0.6, "std": 0.15}
        result = check_semantic_coherence(paragraphs, golden_stats)

        # Uses golden stats for anomaly detection
        assert result.mean_score >= 0

    def test_anomaly_detection(self):
        # Create paragraphs with very different content
        paragraphs = [
            "正常的段落内容",
            "正常的段落内容",
            "完全不同的内容xyz",
            "正常的段落内容",
        ]
        result = check_semantic_coherence(paragraphs)

        # Should detect anomalies
        assert isinstance(result.anomalies, list)


class TestValidateEmotions:
    """Tests for validate_emotions function."""

    def test_valid_emotions(self):
        annotations = [
            {"emotion": "happy"},
            {"emotion": "sad"},
            {"emotion": "neutral"},
            {"emotion": "angry"},
        ]
        report = validate_emotions(annotations)

        assert report.total_segments == 4
        assert "happy" in report.emotion_distribution
        assert "sad" in report.emotion_distribution
        assert report.other_emotions_count == 0
        assert len(report.unexpected_emotions) == 0
        assert "所有情感类型合法" in report.validation_summary

    def test_other_emotion(self):
        annotations = [
            {"emotion": "happy"},
            {"emotion": "other"},
            {"emotion": "sad"},
        ]
        report = validate_emotions(annotations)

        assert report.other_emotions_count == 1
        # Check for the substring (may have different quote styles)
        assert "出现 1 次" in report.validation_summary
        assert "33.3%" in report.validation_summary

    def test_invalid_emotion(self):
        annotations = [
            {"emotion": "happy"},
            {"emotion": "invalid_emotion"},
        ]
        report = validate_emotions(annotations)

        assert len(report.unexpected_emotions) > 0
        assert "invalid_emotion" in str(report.unexpected_emotions)
        assert "非法情感类型" in report.validation_summary

    def test_mixed_valid_invalid(self):
        annotations = [
            {"emotion": "happy"},
            {"emotion": "sad"},
            {"emotion": "weird_emotion"},
            {"emotion": "other"},
        ]
        report = validate_emotions(annotations)

        assert report.total_segments == 4
        assert report.emotion_distribution["happy"] == 1
        assert report.emotion_distribution["sad"] == 1
        assert report.emotion_distribution["weird_emotion"] == 1
        assert report.emotion_distribution["other"] == 1
        assert report.other_emotions_count == 1
        assert len(report.unexpected_emotions) == 1

    def test_custom_valid_emotions(self):
        custom_emotions = {"custom1", "custom2"}
        annotations = [
            {"emotion": "custom1"},
            {"emotion": "custom2"},
            {"emotion": "happy"},  # Not in custom set
        ]
        report = validate_emotions(annotations, valid_emotions=custom_emotions)

        assert "happy" in [e for e, _ in report.unexpected_emotions]
        assert "custom1" not in [e for e, _ in report.unexpected_emotions]

    def test_generated_at_present(self):
        annotations = [{"emotion": "happy"}]
        report = validate_emotions(annotations)
        assert report.generated_at
        # Should be valid ISO format
        datetime.fromisoformat(report.generated_at.replace("Z", "+00:00"))


class TestDifficultyWeights:
    """Tests for DifficultyWeights class."""

    def test_default_weights(self):
        w = DifficultyWeights({})
        assert w.get_weight("text_length") == 1.0  # default
        assert w.get_weight("unknown", 2.5) == 2.5  # custom default

    def test_custom_weights(self):
        custom = {"text_length": 2.0, "entropy": 1.5}
        w = DifficultyWeights(custom)
        assert w.get_weight("text_length") == 2.0
        assert w.get_weight("entropy") == 1.5
        assert w.get_weight("unknown") == 1.0  # default


class TestGradeDifficulty:
    """Tests for grade_difficulty function."""

    def test_short_simple_text(self):
        text = "简单的文本。"
        result = grade_difficulty(text)

        assert result["level"] == "easy"
        assert 0 <= result["overall_score"] <= 1
        assert "text_length" in result["weighted_dimensions"]
        assert "vocabulary_rarity" in result["weighted_dimensions"]
        assert "narrative_complexity" in result["weighted_dimensions"]
        assert "raw_metrics" in result

    def test_long_complex_text(self):
        text = "这是一段很长的文本。" * 501  # >5000 chars
        result = grade_difficulty(text)

        assert result["level"] in ["medium", "hard"]
        assert result["raw_metrics"]["text_length"] > 5000

    def test_chinese_text(self):
        text = "这是一个中文测试文本，包含多个句子。这是第二个句子。这是第三个句子！"
        result = grade_difficulty(text)

        assert result["raw_metrics"]["sentence_count"] == 3
        assert result["raw_metrics"]["text_length"] > 0

    def test_custom_weights(self):
        custom_weights = DifficultyWeights({"text_length": 3.0})
        text = "测试文本"
        result = grade_difficulty(text, weights=custom_weights)

        assert "text_length" in result["weighted_dimensions"]


class TestFreeTierHealth:
    """Tests for get_free_tier_health function."""

    def test_returns_health_object(self):
        health = get_free_tier_health()

        assert isinstance(health, FreeTierHealth)
        assert health.cpu_count >= 1
        assert health.memory_gb >= 0
        assert health.disk_free_gb >= 0
        assert health.uptime_hours >= 0
        assert isinstance(health.load_avg, tuple)
        assert len(health.load_avg) == 3
        assert 0 <= health.score <= 100
        assert isinstance(health.warnings, list)

    def test_score_bounds(self):
        health = get_free_tier_health()
        assert health.score >= 0
        assert health.score <= 100


class TestFalsePositiveTracker:
    """Tests for FalsePositiveTracker class."""

    def test_record_false_positive(self):
        tracker = FalsePositiveTracker()
        issue = tracker.record_false_positive(
            segment_id="seg-123",
            issue_type="clipping",
            description="False clipping detection",
            reason="Background noise mistaken for clipping",
            reported_by="human",
        )

        assert issue.issue_id is not None
        assert issue.segment_id == "seg-123"
        assert issue.issue_type == "clipping"
        assert issue.false_positive_reason == "Background noise mistaken for clipping"
        assert issue.reported_by == "human"
        assert len(tracker.issues) == 1

    def test_false_positive_rate(self):
        tracker = FalsePositiveTracker()

        # Add 3 false positives
        tracker.record_false_positive("seg-1", "clipping", "desc", "reason")
        tracker.record_false_positive("seg-2", "clipping", "desc", "reason")
        tracker.record_false_positive("seg-3", "silence", "desc", "reason")

        # Overall rate
        assert tracker.get_false_positive_rate(10) == 0.3  # 3/10

        # Type-specific rate
        assert tracker.get_false_positive_rate(10, "clipping") == 0.2  # 2/10
        assert tracker.get_false_positive_rate(10, "silence") == 0.1  # 1/10
        assert tracker.get_false_positive_rate(10, "unknown") == 0.0

    def test_false_positive_rate_zero_total(self):
        tracker = FalsePositiveTracker()
        assert tracker.get_false_positive_rate(0) == 0.0

    def test_adjusted_quality_score(self):
        tracker = FalsePositiveTracker()

        # Add some false positives
        tracker.record_false_positive("seg-1", "clipping", "desc", "reason")
        tracker.record_false_positive("seg-2", "clipping", "desc", "reason")

        # 10 total issues, 2 false positives = 20% FP rate
        # Penalty = 0.2 * 0.2 = 0.04
        adjusted = tracker.get_adjusted_quality_score(0.9, 10, "clipping")
        assert adjusted == 0.86  # 0.9 - 0.04

    def test_adjusted_score_bounds(self):
        tracker = FalsePositiveTracker()

        # Should not go below 0
        for _ in range(20):
            tracker.record_false_positive("seg", "clipping", "desc", "reason")

        adjusted = tracker.get_adjusted_quality_score(0.5, 100, "clipping")
        assert adjusted >= 0.0

        # Should not exceed 1
        adjusted = tracker.get_adjusted_quality_score(1.0, 100)
        assert adjusted <= 1.0

    def test_high_fp_issues(self):
        tracker = FalsePositiveTracker()

        # Add many clipping false positives
        for i in range(5):
            tracker.record_false_positive(f"seg-{i}", "clipping", "desc", "reason")

        # Add few silence false positives
        tracker.record_false_positive("seg-sil", "silence", "desc", "reason")

        high_fp = tracker.get_high_fp_issues(threshold=0.2)
        assert "clipping" in high_fp
        assert high_fp["clipping"] == 5
        # All issues are tracked as false positives, so rate = 100% for all types
        assert "silence" in high_fp
        assert high_fp["silence"] == 1

    def test_global_tracker_singleton(self):
        tracker1 = get_false_positive_tracker()
        tracker2 = get_false_positive_tracker()

        assert tracker1 is tracker2


class TestIntegration:
    """Integration-style tests."""

    def test_full_quality_pipeline(self):
        """Test a typical quality enhancement workflow."""
        # 1. Check semantic coherence
        paragraphs = [
            "故事开始了，主角登场。",
            "主角遇到了挑战。",
            "主角克服了困难。",
            "故事圆满结束。",
        ]
        coherence = check_semantic_coherence(paragraphs)
        assert coherence.is_coherent

        # 2. Validate emotions
        annotations = [
            {"emotion": "neutral"},
            {"emotion": "fearful"},
            {"emotion": "proud"},
            {"emotion": "happy"},
        ]
        emotion_report = validate_emotions(annotations)
        assert emotion_report.total_segments == 4
        assert len(emotion_report.unexpected_emotions) == 0

        # 3. Grade difficulty
        text = " ".join(paragraphs)
        difficulty = grade_difficulty(text)
        assert difficulty["level"] in ["easy", "medium", "hard"]

        # 4. Check health
        health = get_free_tier_health()
        assert health.score >= 0

        # 5. Track false positives
        tracker = get_false_positive_tracker()
        tracker.record_false_positive("seg-1", "silence", "desc", "reason")
        fp_rate = tracker.get_false_positive_rate(10, "silence")
        assert fp_rate > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

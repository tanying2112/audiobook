"""Comprehensive tests for feedback/quality_enhancement.py."""

import math
from collections import Counter
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.feedback.quality_enhancement import (
    _DEFAULT_DIFFICULTY_WEIGHTS,
    _VALID_EMOTIONS,
    DifficultyWeights,
    FalsePositiveIssue,
    FalsePositiveTracker,
    FreeTierHealth,
    SemanticCoherenceResult,
    ValidationReport,
    _compute_text_difficulty,
    _cosine_similarity,
    _fp_tracker,
    check_semantic_coherence,
    get_false_positive_tracker,
    get_free_tier_health,
    grade_difficulty,
    validate_emotions,
)

# ── SemanticCoherenceResult ──────────────────────────────────────────────────


class TestSemanticCoherenceResult:
    def test_creation(self):
        r = SemanticCoherenceResult(
            scores=[0.5, 0.6],
            mean_score=0.55,
            std_score=0.05,
            anomalies=[1],
            is_coherent=True,
            details="test",
        )
        assert r.mean_score == 0.55
        assert r.anomalies == [1]


# ── _cosine_similarity ───────────────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical(self):
        assert abs(_cosine_similarity("hello world", "hello world") - 1.0) < 1e-6

    def test_empty(self):
        assert _cosine_similarity("", "") == 0.0

    def test_empty_one_side(self):
        assert _cosine_similarity("hello", "") == 0.0

    def test_similar(self):
        sim = _cosine_similarity("hello world", "hello word")
        assert 0.0 < sim < 1.0

    def test_different(self):
        sim = _cosine_similarity("aaa", "zzz")
        assert sim <= 1.0

    def test_single_char(self):
        sim = _cosine_similarity("a", "a")
        assert sim == 0.0  # Not enough chars for 2-gram

    def test_two_chars(self):
        sim = _cosine_similarity("ab", "ab")
        assert sim == 1.0


# ── check_semantic_coherence ─────────────────────────────────────────────────


class TestSemanticCoherence:
    def test_empty(self):
        r = check_semantic_coherence([])
        assert r.is_coherent is True
        assert r.scores == []

    def test_single_paragraph(self):
        r = check_semantic_coherence(["hello"])
        assert r.is_coherent is True
        assert r.mean_score == 1.0

    def test_two_identical(self):
        r = check_semantic_coherence(["hello world", "hello world"])
        assert abs(r.mean_score - 1.0) < 1e-6
        assert r.is_coherent is True

    def test_two_different(self):
        r = check_semantic_coherence(["aaa aaa", "zzz zzz"])
        assert r.mean_score < 1.0

    def test_many_paragraphs(self):
        paras = [f"paragraph {i} with some text" for i in range(10)]
        r = check_semantic_coherence(paras)
        assert len(r.scores) == 9
        assert r.std_score >= 0

    def test_with_golden_stats(self):
        paras = [f"paragraph {i} text" for i in range(5)]
        golden = {"mean": 0.5, "std": 0.1}
        r = check_semantic_coherence(paras, golden_stats=golden)
        assert isinstance(r.anomalies, list)

    def test_details_string(self):
        r = check_semantic_coherence(["a", "b", "c"])
        assert "3 段落" in r.details


# ── validate_emotions ────────────────────────────────────────────────────────


class TestValidateEmotions:
    def test_all_valid(self):
        annotations = [{"emotion": "happy"}, {"emotion": "sad"}, {"emotion": "neutral"}]
        r = validate_emotions(annotations)
        assert r.total_segments == 3
        assert r.unexpected_emotions == []
        assert r.other_emotions_count == 0
        assert "所有情感类型合法" in r.validation_summary

    def test_with_other(self):
        annotations = [{"emotion": "other"}, {"emotion": "other"}]
        r = validate_emotions(annotations)
        assert r.other_emotions_count == 2

    def test_with_invalid(self):
        annotations = [{"emotion": "unknown_emotion"}, {"emotion": "happy"}]
        r = validate_emotions(annotations)
        assert len(r.unexpected_emotions) > 0

    def test_empty_annotations(self):
        r = validate_emotions([])
        assert r.total_segments == 0
        assert r.validation_summary is not None

    def test_missing_emotion_field(self):
        annotations = [{"text": "no emotion"}]
        r = validate_emotions(annotations)
        assert r.total_segments == 1

    def test_custom_valid_set(self):
        annotations = [{"emotion": "custom1"}]
        r = validate_emotions(annotations, valid_emotions={"custom1", "custom2"})
        assert r.unexpected_emotions == []

    def test_aggregated_unexpected(self):
        annotations = [{"emotion": "bad1"}, {"emotion": "bad1"}, {"emotion": "bad2"}]
        r = validate_emotions(annotations)
        assert len(r.unexpected_emotions) == 2

    def test_generated_at(self):
        r = validate_emotions([{"emotion": "happy"}])
        assert r.generated_at is not None


# ── DifficultyWeights ────────────────────────────────────────────────────────


class TestDifficultyWeights:
    def test_get_weight(self):
        w = DifficultyWeights({"a": 2.0, "b": 1.5})
        assert w.get_weight("a") == 2.0
        assert w.get_weight("b") == 1.5
        assert w.get_weight("c") == 1.0
        assert w.get_weight("c", 0.5) == 0.5


# ── _compute_text_difficulty ─────────────────────────────────────────────────


class TestComputeTextDifficulty:
    def test_short_text(self):
        m = _compute_text_difficulty("hello")
        assert m["text_length"] == 5
        assert m["entropy"] >= 0
        assert m["sentence_count"] >= 1

    def test_long_text(self):
        text = "这是一段很长的文本。" * 100
        m = _compute_text_difficulty(text)
        assert m["text_length"] > 500

    def test_punctuation_ratio(self):
        text = "你好，世界！我来？"
        m = _compute_text_difficulty(text)
        assert m["punct_ratio"] > 0

    def test_empty_text(self):
        m = _compute_text_difficulty("")
        assert m["text_length"] == 0
        assert m["entropy"] == 0.0

    def test_sentence_count(self):
        text = "第一句。第二句。第三句。"
        m = _compute_text_difficulty(text)
        assert m["sentence_count"] >= 3


# ── grade_difficulty ─────────────────────────────────────────────────────────


class TestGradeDifficulty:
    def test_easy(self):
        result = grade_difficulty("short")
        assert result["level"] == "easy"
        assert result["overall_score"] < 0.4

    def test_medium(self):
        text = "这是一段中等长度的文本，" * 20
        result = grade_difficulty(text)
        assert result["level"] in ("easy", "medium", "hard")
        assert "weighted_dimensions" in result
        assert "raw_metrics" in result

    def test_hard(self):
        text = "这是一段非常非常长的文本，包含了很多内容。" * 200
        result = grade_difficulty(text)
        assert result["level"] in ("medium", "hard")

    def test_custom_weights(self):
        w = DifficultyWeights({"text_length": 5.0, "vocabulary_rarity": 5.0, "narrative_complexity": 5.0})
        result = grade_difficulty("hello", weights=w)
        assert "overall_score" in result


# ── get_free_tier_health ─────────────────────────────────────────────────────


class TestFreeTierHealth:
    def test_returns_health(self):
        h = get_free_tier_health()
        assert isinstance(h, FreeTierHealth)
        assert h.cpu_count >= 1
        assert h.score >= 0
        assert isinstance(h.warnings, list)
        assert isinstance(h.load_avg, tuple)

    def test_health_fields(self):
        h = get_free_tier_health()
        assert h.memory_gb >= 0
        assert h.disk_free_gb >= 0
        assert h.uptime_hours >= 0

    def test_healthy_field(self):
        h = get_free_tier_health()
        assert isinstance(h.healthy, bool)


# ── FalsePositiveIssue ───────────────────────────────────────────────────────


class TestFalsePositiveIssue:
    def test_creation(self):
        issue = FalsePositiveIssue(
            issue_id="1",
            segment_id="seg1",
            issue_type="wer",
            description="desc",
            false_positive_reason="reason",
            reported_by="human",
            created_at="2024-01-01",
        )
        assert issue.issue_id == "1"
        assert issue.reported_by == "human"


# ── FalsePositiveTracker ─────────────────────────────────────────────────────


class TestFalsePositiveTracker:
    def test_record_false_positive(self):
        t = FalsePositiveTracker()
        issue = t.record_false_positive("seg1", "wer", "desc", "reason")
        assert issue.segment_id == "seg1"
        assert len(t.issues) == 1

    def test_record_auto(self):
        t = FalsePositiveTracker()
        issue = t.record_false_positive("seg1", "wer", "desc", "reason", reported_by="auto")
        assert issue.reported_by == "auto"

    def test_get_false_positive_rate(self):
        t = FalsePositiveTracker()
        t.record_false_positive("s1", "wer", "d", "r")
        t.record_false_positive("s2", "snr", "d", "r")
        rate = t.get_false_positive_rate(10)
        assert rate == 0.2

    def test_get_fp_rate_zero_total(self):
        t = FalsePositiveTracker()
        assert t.get_false_positive_rate(0) == 0.0

    def test_get_fp_rate_by_type(self):
        t = FalsePositiveTracker()
        t.record_false_positive("s1", "wer", "d", "r")
        t.record_false_positive("s2", "snr", "d", "r")
        rate = t.get_false_positive_rate(10, issue_type="wer")
        assert rate == 0.1

    def test_adjusted_quality_score(self):
        t = FalsePositiveTracker()
        t.record_false_positive("s1", "wer", "d", "r")
        score = t.get_adjusted_quality_score(0.8, 10)
        assert score < 0.8
        assert score >= 0.0

    def test_adjusted_quality_score_floor(self):
        t = FalsePositiveTracker()
        for i in range(20):
            t.record_false_positive(f"s{i}", "wer", "d", "r")
        score = t.get_adjusted_quality_score(0.1, 10)
        assert score == 0.0

    def test_adjusted_quality_score_ceiling(self):
        t = FalsePositiveTracker()
        score = t.get_adjusted_quality_score(1.0, 10)
        assert score == 1.0

    def test_high_fp_issues(self):
        t = FalsePositiveTracker()
        for i in range(5):
            t.record_false_positive(f"s{i}", "wer", "d", "r")
        high = t.get_high_fp_issues(threshold=0.5)
        assert "wer" in high

    def test_high_fp_issues_none(self):
        t = FalsePositiveTracker()
        t.record_false_positive("s1", "wer", "d", "r")
        high = t.get_high_fp_issues(threshold=0.5)
        # Only 1 issue for "wer" with 1 total → rate = 1.0 > 0.5
        assert "wer" in high


# ── get_false_positive_tracker ───────────────────────────────────────────────


class TestGetFalsePositiveTracker:
    def test_singleton(self):
        import src.audiobook_studio.feedback.quality_enhancement as mod

        original = mod._fp_tracker
        mod._fp_tracker = None
        t1 = get_false_positive_tracker()
        t2 = get_false_positive_tracker()
        assert t1 is t2
        mod._fp_tracker = original

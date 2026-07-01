"""Tests for quality/semantic_coherence.py — SemanticCoherenceChecker (146 miss lines)."""

from unittest.mock import patch, MagicMock

import pytest
import numpy as np


class TestSemanticCoherenceCheckerInit:
    def test_init_with_default_config(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent/path.yaml")
        assert checker.config is not None
        assert checker.config.get("audio") is not None

    def test_init_with_real_config(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker()
        assert checker.config is not None


class TestCheckCoherence:
    def test_empty_paragraphs(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        result = checker.check_coherence([])
        assert result["passed"] is True
        assert result["score"] == 1.0

    def test_single_paragraph(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        result = checker.check_coherence(["Hello world"])
        assert result["passed"] is True

    def test_two_paragraphs(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        result = checker.check_coherence(["今天天气真好。", "我决定去公园散步。"])
        assert "passed" in result
        assert "semantic_score" in result
        assert "emotional_score" in result
        assert "issues" in result

    def test_without_emotional_curve(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        result = checker.check_coherence(
            ["段落A内容", "段落B内容"],
            check_emotional_curve=False,
        )
        assert result["emotional_score"] is None

    def test_with_reference_paragraphs(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        result = checker.check_coherence(
            ["这是翻译后的文本", "第二段翻译"],
            reference_paragraphs=["这是原文", "第二段原文"],
        )
        assert result["translation_quality"] is not None

    def test_with_mismatched_reference_length(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        result = checker.check_coherence(
            ["段落1", "段落2"],
            reference_paragraphs=["只有原文一段"],
        )
        assert result["translation_quality"] is None

    def test_with_empty_paragraphs_in_list(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        result = checker.check_coherence(["段落一", "", "段落三"])
        assert "issues" in result


class TestSimilarity:
    def test_fallback_similarity_empty_both(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score = checker._fallback_similarity("", "")
        assert score == 1.0

    def test_fallback_similarity_empty_one(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score = checker._fallback_similarity("hello", "")
        assert score == 0.0

    def test_fallback_similarity_identical(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score = checker._fallback_similarity("hello", "hello")
        assert score == 1.0

    def test_fallback_similarity_similar(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score = checker._fallback_similarity("hello world", "hello world!")
        assert score > 0.5

    def test_fallback_similarity_different(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score = checker._fallback_similarity("你好", "hello")
        assert score < 0.5

    def test_calculate_semantic_similarity_no_model(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        # semantic_model should be None since sentence-transformers likely not installed
        if checker.semantic_model is None:
            score = checker._calculate_semantic_similarity("text a", "text b")
            assert 0.0 <= score <= 1.0


class TestEmotionIntensity:
    def test_estimate_empty(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        assert checker._estimate_emotion_intensity("") == 0.0

    def test_estimate_neutral(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score = checker._estimate_emotion_intensity("这是一个普通的句子。")
        assert score >= 0.0

    def test_estimate_positive_words(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score = checker._estimate_emotion_intensity("我非常高兴！")
        assert score > 0.0

    def test_estimate_negative_words(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score = checker._estimate_emotion_intensity("他非常愤怒！！")
        assert score > 0.0

    def test_estimate_exclamation_marks(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score_high = checker._estimate_emotion_intensity("好！！！")
        score_low = checker._estimate_emotion_intensity("好。")
        assert score_high >= score_low

    def test_estimate_repeated_chars(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        score = checker._estimate_emotion_intensity("啊啊啊啊啊")
        assert score > 0.0


class TestEmotionalCurve:
    def test_curve_continuity(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        scores = checker._check_emotional_curve_continuity([
            "今天天气真好！",
            "我心情愉快。",
            "突然下起雨来。",
        ])
        assert len(scores) == 2
        assert all(0.0 <= s <= 1.0 for s in scores)

    def test_curve_identical_emotion(self):
        from src.audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker
        checker = SemanticCoherenceChecker(config_path="/nonexistent.yaml")
        scores = checker._check_emotional_curve_continuity(["普通句子。", "另一个普通句子。"])
        assert len(scores) == 1
        assert scores[0] >= 0.9  # Similar emotion intensity

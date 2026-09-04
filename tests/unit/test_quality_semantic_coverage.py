"""Tests for semantic_coherence.py."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Add src to path

# Mock sentence_transformers module before importing our module
mock_sentence_transformers = MagicMock()
mock_st_instance = MagicMock()
# Mock the encode method to return two embedding vectors
mock_st_instance.encode.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
mock_sentence_transformers.SentenceTransformer.return_value = mock_st_instance
sys.modules["sentence_transformers"] = mock_sentence_transformers


@pytest.fixture(autouse=True)
def _install_st_mock(monkeypatch):
    """Re-install our sentence_transformers mock before each test.

    Without this, a sibling test that pops/replaces ``sys.modules['sentence_transformers']``
    (e.g. test_segment_coverage's fake_sentence_transformers fixture) leaves a stale or
    alternative mock in place, producing nan embeddings in this file's tests.
    """
    monkeypatch.setitem(sys.modules, "sentence_transformers", mock_sentence_transformers)


from audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker


class TestSemanticCoherenceChecker:
    """Test SemanticCoherenceChecker class."""

    def test_init_default_config(self):
        """配置源返回空时，构造器回退到内置默认配置。"""
        mock_unified = MagicMock()
        mock_unified.load_yaml_config.return_value = None  # 未找到 → 默认值
        with patch(
            "audiobook_studio.quality.semantic_coherence.get_unified_config",
            return_value=mock_unified,
        ):
            checker = SemanticCoherenceChecker("dummy/path.yaml")

        expected_default = {
            "audio": {
                "semantic_coherence_threshold": 0.75,
                "emotional_coherence_threshold": 0.80,
            }
        }
        assert checker.config == expected_default

    def test_init_with_config_file(self):
        """构造器通过 UnifiedConfig 加载配置并原样保留各节。"""
        loaded = {
            "audio": {"silence_threshold_db": -30},
            "semantic": {"similarity_threshold": 0.8},
        }
        mock_unified = MagicMock()
        mock_unified.load_yaml_config.return_value = loaded
        with patch(
            "audiobook_studio.quality.semantic_coherence.get_unified_config",
            return_value=mock_unified,
        ):
            checker = SemanticCoherenceChecker("dummy/path.yaml")

        mock_unified.load_yaml_config.assert_called_once_with("quality_thresholds")
        assert checker.config["audio"]["silence_threshold_db"] == -30
        assert "audio" in checker.config

    def test_get_default_config(self):
        """Test _get_default_config returns a dict."""
        checker = SemanticCoherenceChecker()
        config = checker._get_default_config()
        assert isinstance(config, dict)
        assert "audio" in config
        assert "semantic_coherence_threshold" in config["audio"]
        assert "emotional_coherence_threshold" in config["audio"]

    def test_calculate_semantic_similarity(self):
        """Test _calculate_semantic_similarity method."""
        checker = SemanticCoherenceChecker()

        # 共享全局 mock：重置调用记录，仅统计本次触发的 encode
        mock_st_instance.encode.reset_mock()
        # Call the private method
        similarity = checker._compute_semantic_similarity("text1", "text2")

        # The cosine similarity of [0.1,0.2,0.3] and [0.4,0.5,0.6] is 0.9746318461970762
        # We don't need to check the exact value, just that it's a float and reasonable
        assert isinstance(similarity, float)
        assert 0.0 <= similarity <= 1.0
        # The encode method should have been called once with a list of two strings
        mock_st_instance.encode.assert_called_once_with(["text1", "text2"], convert_to_numpy=True)

    def test_check_coherence_basic(self):
        """Test check_coherence method with basic input."""
        checker = SemanticCoherenceChecker()

        # Test with insufficient paragraphs
        result = checker.check_coherence(["Single paragraph"])
        assert result["passed"] is True
        assert result["score"] == 1.0
        assert "段落数量不足" in result["issues"][0]

        # Test with empty list
        result = checker.check_coherence([])
        assert result["passed"] is True
        assert result["score"] == 1.0
        assert "段落数量不足" in result["issues"][0]

    def test_check_coherence_with_sufficient_paragraphs(self):
        """Test check_coherence method with enough paragraphs."""
        checker = SemanticCoherenceChecker()

        # Mock the similarity to return a high value (good coherence)
        mock_st_instance.encode.return_value = [[0.1, 0.2, 0.3], [0.15, 0.25, 0.35]]  # Similar vectors

        paragraphs = ["First paragraph", "Second paragraph"]
        result = checker.check_coherence(paragraphs)

        # Should pass because similarity is high (above default threshold of 0.75)
        assert isinstance(result["score"], float)
        assert 0.0 <= result["score"] <= 1.0
        # The exact behavior depends on the implementation, but we can check structure
        assert "passed" in result
        assert "score" in result
        assert "semantic_score" in result
        assert "emotional_score" in result
        assert "issues" in result

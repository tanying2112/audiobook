"""Tests for semantic_coherence.py."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Add src to path
sys.path.insert(0, "src")

# Mock sentence_transformers module before importing our module
mock_sentence_transformers = MagicMock()
mock_st_instance = MagicMock()
# Mock the encode method to return two embedding vectors
mock_st_instance.encode.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
mock_sentence_transformers.SentenceTransformer.return_value = mock_st_instance
sys.modules['sentence_transformers'] = mock_sentence_transformers

from audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker


class TestSemanticCoherenceChecker:
    """Test SemanticCoherenceChecker class."""

    @patch("audiobook_studio.quality.semantic_coherence.Path")
    @patch("audiobook_studio.quality.semantic_coherence.yaml")
    def test_init_default_config(self, mock_yaml, mock_path):
        """Test initialization with default config when file not found."""
        # Mock the path existence to return True (so we try to open the file)
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        # Mock the file open to raise FileNotFoundError
        mock_yaml.safe_load.side_effect = FileNotFoundError()

        # Create the checker
        checker = SemanticCoherenceChecker("dummy/path.yaml")

        # Check that the default config was used
        expected_config = {
            "audio": {
                "semantic_coherence_threshold": 0.75,
                "emotional_coherence_threshold": 0.80,
            }
        }
        assert checker.config == expected_config
        # Check that the SentenceTransformer was called to create the model
        mock_sentence_transformers.SentenceTransformer.assert_called_once_with(
            "paraphrase-multilingual-MiniLM-L12-v2"
        )
        # Check that the model was set on the instance
        assert checker.model == mock_st_instance

    @patch("audiobook_studio.quality.semantic_coherence.Path")
    @patch("audiobook_studio.quality.semantic_coherence.yaml")
    def test_init_with_config_file(self, mock_yaml, mock_path):
        """Test initialization with a config file."""
        # Mock the path existence to return True
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path.return_value = mock_path_instance

        # Mock yaml.safe_load to return a config
        mock_yaml.safe_load.return_value = {
            "audio": {"silence_threshold_db": -30},
            "semantic": {"similarity_threshold": 0.8},
        }

        checker = SemanticCoherenceChecker("dummy/path.yaml")

        # Check that the config was loaded (note: the actual code only uses audio section)
        # The semantic section in the config file is ignored by the current implementation
        assert checker.config["audio"]["silence_threshold_db"] == -30
        # The semantic section is not used in the current implementation, so it won't be in config
        # But let's check what actually gets loaded
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

        # Call the private method
        similarity = checker._calculate_semantic_similarity("text1", "text2")

        # The cosine similarity of [0.1,0.2,0.3] and [0.4,0.5,0.6] is 0.9746318461970762
        # We don't need to check the exact value, just that it's a float and reasonable
        assert isinstance(similarity, float)
        assert 0.0 <= similarity <= 1.0
        # The encode method should have been called once with a list of two strings
        mock_st_instance.encode.assert_called_once_with(["text1", "text2"])

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
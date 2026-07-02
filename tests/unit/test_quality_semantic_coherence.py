"""Tests for semantic_coherence.py."""

import sys
from unittest.mock import MagicMock, patch

import pytest

# Add src to path
sys.path.insert(0, "src")

from audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker


class TestSemanticCoherenceChecker:
    """Test SemanticCoherenceChecker class."""

    @patch("audiobook_studio.quality.semantic_coverage.Path")
    @patch("audiobook_studio.quality.semantic_coverage.yaml")
    @patch("audiobook_studio.quality.semantic_coverage.SentenceTransformer")
    def test_init_default_config(self, mock_st, mock_yaml, mock_path):
        """Test initialization with default config when file not found."""
        # Mock the path existence to return False (file not found)
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = False
        mock_path.return_value = mock_path_instance

        # Mock yaml.safe_load to return None (so we go to except)
        mock_yaml.safe_load.return_value = None

        # Mock the SentenceTransformer to avoid loading the model
        mock_st_instance = MagicMock()
        mock_st.return_value = mock_st_instance

        # Create the checker
        checker = SemanticCoherenceChecker("dummy/path.yaml")

        # Check that the default config was used
        assert checker.config == checker._get_default_config()
        # Check that the model was initialized (even if mocked)
        assert checker.model == mock_st_instance

    @patch("audiobook_studio.quality.semantic_coverage.Path")
    @patch("audiobook_studio.quality.semantic_coverage.yaml")
    @patch("audiobook_studio.quality.semantic_coverage.SentenceTransformer")
    def test_init_with_config_file(self, mock_st, mock_yaml, mock_path):
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

        # Mock the SentenceTransformer
        mock_st_instance = MagicMock()
        mock_st.return_value = mock_st_instance

        checker = SemanticCoherenceChecker("dummy/path.yaml")

        # Check that the config was loaded
        assert checker.config["audio"]["silence_threshold_db"] == -30
        assert checker.config["semantic"]["similarity_threshold"] == 0.8

    def test_get_default_config(self):
        """Test _get_default_config returns a dict."""
        checker = SemanticCoherenceChecker()
        config = checker._get_default_config()
        assert isinstance(config, dict)
        assert "audio" in config
        assert "semantic" in config

    @patch("audiobook_studio.quality.semantic_coverage.SentenceTransformer")
    def test_compute_similarity(self, mock_st):
        """Test compute_similarity method."""
        # Mock the SentenceTransformer instance and its encode method
        mock_st_instance = MagicMock()
        mock_st_instance.encode.return_value = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        mock_st.return_value = mock_st_instance

        checker = SemanticCoherenceChecker()
        # Replace the model with our mock
        checker.model = mock_st_instance

        # Call the method
        similarity = checker.compute_similarity("text1", "text2")

        # We don't know the exact value, but we can check that it's a float
        assert isinstance(similarity, float)
        # The encode method should have been called twice
        assert mock_st_instance.encode.call_count == 2

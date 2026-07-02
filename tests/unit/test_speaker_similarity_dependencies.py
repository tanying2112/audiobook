"""
Test to verify SpeakerSimilarityMetric correctly detects dependencies and sets mock_mode appropriately.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

import numpy as np

# Add the src directory to the path so we can import the module as a package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

from src.audiobook_studio.quality.metrics import ECAPATDNNBackend, SpeakerSimilarityMetric, WavLMBackend


class TestSpeakerSimilarityDependencies(unittest.TestCase):

    @patch("src.audiobook_studio.quality.metrics._speechbrain_available", True)
    @patch("src.audiobook_studio.quality.metrics._torch_available", True)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", True)
    def test_ecapa_tdnn_backend_mock_mode_false_when_speechbrain_available(self):
        """ECAPA-TDNN backend should have mock_mode=False when speechbrain is available."""
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn")
        self.assertIsInstance(metric._backend, ECAPATDNNBackend)
        self.assertFalse(metric._backend.mock_mode)

    @patch("src.audiobook_studio.quality.metrics._speechbrain_available", False)
    def test_ecapa_tdnn_backend_mock_mode_true_when_speechbrain_unavailable(self):
        """ECAPA-TDNN backend should have mock_mode=True when speechbrain is unavailable."""
        metric = SpeakerSimilarityMetric(backend="ecapa_tdnn")
        self.assertIsInstance(metric._backend, ECAPATDNNBackend)
        self.assertTrue(metric._backend.mock_mode)

    @patch("src.audiobook_studio.quality.metrics._torch_available", True)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", True)
    @patch("src.audiobook_studio.quality.metrics._transformers_available", True)
    def test_wavlm_backend_mock_mode_false_when_torch_and_torchaudio_available(self):
        """WavLM backend should have mock_mode=False when both torch and torchaudio are available."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        self.assertIsInstance(metric._backend, WavLMBackend)
        self.assertFalse(metric._backend.mock_mode)

    @patch("src.audiobook_studio.quality.metrics._torch_available", False)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", True)
    @patch("src.audiobook_studio.quality.metrics._transformers_available", True)
    def test_wavlm_backend_mock_mode_true_when_torch_unavailable(self):
        """WavLM backend should have mock_mode=True when torch is unavailable."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        self.assertIsInstance(metric._backend, WavLMBackend)
        self.assertTrue(metric._backend.mock_mode)

    @patch("src.audiobook_studio.quality.metrics._torch_available", True)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", False)
    @patch("src.audiobook_studio.quality.metrics._transformers_available", True)
    def test_wavlm_backend_mock_mode_true_when_torchaudio_unavailable(self):
        """WavLM backend should have mock_mode=True when torchaudio is unavailable."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        self.assertIsInstance(metric._backend, WavLMBackend)
        self.assertTrue(metric._backend.mock_mode)

    @patch("src.audiobook_studio.quality.metrics._torch_available", False)
    @patch("src.audiobook_studio.quality.metrics._torchaudio_available", False)
    @patch("src.audiobook_studio.quality.metrics._transformers_available", False)
    def test_wavlm_backend_mock_mode_true_when_both_unavailable(self):
        """WavLM backend should have mock_mode=True when both torch and torchaudio are unavailable."""
        metric = SpeakerSimilarityMetric(backend="wavlm_large")
        self.assertIsInstance(metric._backend, WavLMBackend)
        self.assertTrue(metric._backend.mock_mode)


if __name__ == "__main__":
    unittest.main()

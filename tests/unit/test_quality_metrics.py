"""Tests for metrics.py."""

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from audiobook_studio.quality.metrics import (
    ASRResult,
    DNSMOSResult,
    QualityCheckResult,
    SpeakerEmbedding,
    SpeakerSimilarityResult,
    WERResult,
)

# Add src to path



class TestDataClasses:
    """Test the data classes in metrics.py."""

    def test_dns_mos_result(self):
        """Test DNSMOSResult creation and to_dict."""
        result = DNSMOSResult(
            mos_overall=4.0,
            mos_sig=4.2,
            mos_bak=3.8,
            mos_ovr=4.1,
            success=True,
            error=None,
        )
        assert result.mos_overall == 4.0
        assert result.mos_sig == 4.2
        assert result.mos_bak == 3.8
        assert result.mos_ovr == 4.1
        assert result.success is True
        assert result.error is None

        # Test to_dict
        d = result.to_dict()
        assert d["mos_overall"] == 4.0
        assert d["mos_sig"] == 4.2
        assert d["mos_bak"] == 3.8
        assert d["mos_ovr"] == 4.1
        assert d["success"] is True
        assert d["error"] is None

    def test_asr_result(self):
        """Test ASRResult creation and to_dict."""
        words = [{"word": "hello", "start": 0.0, "end": 0.5}]
        result = ASRResult(
            text="hello",
            words=words,
            language="en",
            confidence=0.9,
            duration_ms=500.0,
            success=True,
            error=None,
        )
        assert result.text == "hello"
        assert result.words == words
        assert result.language == "en"
        assert result.confidence == 0.9
        assert result.duration_ms == 500.0
        assert result.success is True
        assert result.error is None

        d = result.to_dict()
        assert d["text"] == "hello"
        assert d["words"] == words
        assert d["language"] == "en"
        assert d["confidence"] == 0.9
        assert d["duration_ms"] == 500.0
        assert d["success"] is True
        assert d["error"] is None

    def test_wer_result(self):
        """Test WERResult creation and to_dict."""
        result = WERResult(
            wer=0.1,
            cer=0.05,
            insertions=2,
            deletions=1,
            substitutions=3,
            reference_words=10,
            hypothesis_words=9,
            success=True,
            error=None,
        )
        assert result.wer == 0.1
        assert result.cer == 0.05
        assert result.insertions == 2
        assert result.deletions == 1
        assert result.substitutions == 3
        assert result.reference_words == 10
        assert result.hypothesis_words == 9
        assert result.success is True
        assert result.error is None

        d = result.to_dict()
        assert d["wer"] == 0.1
        assert d["cer"] == 0.05
        assert d["insertions"] == 2
        assert d["deletions"] == 1
        assert d["substitutions"] == 3
        assert d["reference_words"] == 10
        assert d["hypothesis_words"] == 9
        assert d["success"] is True
        assert d["error"] is None

    def test_speaker_embedding(self):
        """Test SpeakerEmbedding creation."""
        embedding = SpeakerEmbedding(
            embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32),
            model_name="test_model",
            sample_rate=16000,
        )
        np.testing.assert_array_equal(embedding.embedding, np.array([0.1, 0.2, 0.3], dtype=np.float32))
        assert embedding.model_name == "test_model"
        assert embedding.sample_rate == 16000

        d = embedding.to_dict()
        assert d["embedding"] == [0.1, 0.2, 0.3]
        assert d["model_name"] == "test_model"
        assert d["sample_rate"] == 16000
        assert d["dim"] == 3

    def test_speaker_similarity_result(self):
        """Test SpeakerSimilarityResult creation and to_dict."""
        result = SpeakerSimilarityResult(
            similarity=0.85,
            threshold=0.8,
            is_same_speaker=True,
            reference_id="ref1",
            target_id="tgt1",
            success=True,
            error=None,
        )
        assert result.similarity == 0.85
        assert result.threshold == 0.8
        assert result.is_same_speaker is True
        assert result.reference_id == "ref1"
        assert result.target_id == "tgt1"
        assert result.success is True
        assert result.error is None

        d = result.to_dict()
        assert d["similarity"] == 0.85
        assert d["threshold"] == 0.8
        assert d["is_same_speaker"] is True
        assert d["reference_id"] == "ref1"
        assert d["target_id"] == "tgt1"
        assert d["success"] is True
        assert d["error"] is None

    def test_quality_check_result(self):
        """Test QualityCheckResult creation and to_dict."""
        dnsmos = DNSMOSResult(4.0, 4.2, 3.8, 4.1, True)
        asr = ASRResult("hello", [], "en", 0.9, 500.0, True)
        wer = WERResult(0.1, 0.05, 0, 0, 0, 10, 10, True)
        speaker_sim = SpeakerSimilarityResult(0.85, 0.8, True, "ref1", "tgt1", True, None)
        result = QualityCheckResult(
            passed=True,
            dnsmos=dnsmos,
            wer=wer,
            speaker_sim=speaker_sim,
            overall_message="All good",
        )
        assert result.passed is True
        assert result.dnsmos == dnsmos
        assert result.wer == wer
        assert result.speaker_sim == speaker_sim
        assert result.overall_message == "All good"

        d = result.to_dict()
        assert d["passed"] is True
        assert d["dnsmos"] is not None
        assert d["wer"] is not None
        assert d["speaker_sim"] is not None
        assert d["overall_message"] == "All good"

"""Targeted tests for src/audiobook_studio/quality/metrics.py dataclasses and
metric result objects — covers to_dict and similar serialization methods
that are typically skipped in the main parametric test suite.
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import numpy as np
import pytest

os.environ["MOCK_LLM"] = "true"

from src.audiobook_studio.quality.metrics import (
    ASRResult,
    DNSMOSResult,
    QualityCheckResult,
    SpeakerEmbedding,
    SpeakerSimilarityResult,
    WERResult,
)


class TestDNSMOSResult:
    def test_to_dict(self):
        r = DNSMOSResult(
            mos_overall=4.5,
            mos_sig=4.2,
            mos_bak=4.7,
            mos_ovr=4.5,
            success=True,
        )
        d = r.to_dict()
        assert d["mos_overall"] == 4.5
        assert d["mos_sig"] == 4.2
        assert d["mos_bak"] == 4.7
        assert d["mos_ovr"] == 4.5
        assert d["success"] is True
        assert d["error"] is None

    def test_to_dict_with_error(self):
        r = DNSMOSResult(
            mos_overall=0.0,
            mos_sig=0.0,
            mos_bak=0.0,
            mos_ovr=0.0,
            success=False,
            error="model failed",
        )
        d = r.to_dict()
        assert d["success"] is False
        assert d["error"] == "model failed"


class TestASRResult:
    def test_to_dict(self):
        r = ASRResult(
            text="hello world",
            words=[{"w": "hello", "t": 0.0}],
            language="en",
            confidence=0.95,
            duration_ms=1500,
            success=True,
        )
        d = r.to_dict()
        assert d["text"] == "hello world"
        assert d["language"] == "en"
        assert d["confidence"] == 0.95
        assert d["duration_ms"] == 1500
        assert d["words"] == [{"w": "hello", "t": 0.0}]
        assert d["success"] is True
        assert d["error"] is None


class TestWERResult:
    def test_to_dict(self):
        r = WERResult(
            wer=0.5,
            cer=0.5,
            insertions=2,
            deletions=1,
            substitutions=3,
            reference_words=10,
            hypothesis_words=11,
            success=True,
        )
        d = r.to_dict()
        assert d["wer"] == 0.5
        assert d["cer"] == 0.5
        assert d["insertions"] == 2
        assert d["deletions"] == 1
        assert d["substitutions"] == 3
        assert d["reference_words"] == 10
        assert d["hypothesis_words"] == 11
        assert d["success"] is True


class TestSpeakerEmbeddingDataclass:
    def test_to_dict(self):
        emb = SpeakerEmbedding(
            embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32),
            model_name="ecapa_tdnn",
            sample_rate=16000,
        )
        d = emb.to_dict()
        # Float32→Python float conversion via tolist is approximate
        assert len(d["embedding"]) == 3
        np.testing.assert_allclose(d["embedding"], [0.1, 0.2, 0.3], atol=1e-6)
        assert d["model_name"] == "ecapa_tdnn"
        assert d["sample_rate"] == 16000
        assert d["dim"] == 3

    def test_from_dict_round_trip(self):
        original = SpeakerEmbedding(
            embedding=np.array([0.5, -0.5, 1.0], dtype=np.float32),
            model_name="wavlm_large",
            sample_rate=16000,
        )
        d = original.to_dict()
        recovered = SpeakerEmbedding.from_dict(d)
        assert recovered.model_name == "wavlm_large"
        np.testing.assert_array_equal(recovered.embedding, original.embedding)
        assert recovered.sample_rate == 16000


class TestSpeakerSimilarityResult:
    def test_to_dict(self):
        r = SpeakerSimilarityResult(
            similarity=0.92,
            threshold=0.85,
            is_same_speaker=True,
            reference_id="ref1",
            target_id="tgt1",
            success=True,
        )
        d = r.to_dict()
        assert d["similarity"] == 0.92
        assert d["threshold"] == 0.85
        assert d["is_same_speaker"] is True
        assert d["reference_id"] == "ref1"
        assert d["target_id"] == "tgt1"
        assert d["success"] is True
        assert d["error"] is None

    def test_to_dict_with_error(self):
        r = SpeakerSimilarityResult(
            similarity=0.0,
            threshold=0.85,
            is_same_speaker=False,
            reference_id="",
            target_id="",
            success=False,
            error="audio empty",
        )
        d = r.to_dict()
        assert d["error"] == "audio empty"


class TestQualityCheckResult:
    def test_to_dict(self):
        # Test the dataclass's to_dict method
        from src.audiobook_studio.quality.metrics import QualityCheckResult

        dnsmos = DNSMOSResult(mos_overall=4.0, mos_sig=4.0, mos_bak=4.0, mos_ovr=4.0, success=True)
        wer = WERResult(
            wer=0.05,
            cer=0.05,
            insertions=0,
            deletions=0,
            substitutions=1,
            reference_words=20,
            hypothesis_words=21,
            success=True,
        )
        spk_sim = SpeakerSimilarityResult(
            similarity=0.93,
            threshold=0.85,
            is_same_speaker=True,
            reference_id="ref1",
            target_id="tgt1",
            success=True,
        )
        r = QualityCheckResult(
            passed=True,
            dnsmos=dnsmos,
            wer=wer,
            speaker_sim=spk_sim,
            overall_message="Audio quality acceptable",
        )
        d = r.to_dict()
        assert d["passed"] is True
        assert d["dnsmos"]["mos_overall"] == 4.0
        assert d["wer"]["wer"] == 0.05
        assert d["speaker_sim"]["similarity"] == 0.93
        assert d["overall_message"] == "Audio quality acceptable"


def test_quality_metric_abstract_class():
    """Verify QualityMetric ABC behavior."""
    from src.audiobook_studio.quality.metrics import QualityMetric

    # Cannot instantiate abstract class directly
    with pytest.raises(TypeError):
        QualityMetric()


def test_asr_backend_abstract():
    """Verify ASRBackend ABC behavior."""
    from src.audiobook_studio.quality.metrics import ASRBackend

    with pytest.raises(TypeError):
        ASRBackend()


def test_speaker_embedding_backend_abstract():
    """Verify SpeakerEmbeddingBackend ABC behavior."""
    from src.audiobook_studio.quality.metrics import SpeakerEmbeddingBackend

    with pytest.raises(TypeError):
        SpeakerEmbeddingBackend()

"""Tests for quality/metrics.py data models."""

import numpy as np
import pytest


class TestDNSMOSResult:
    def test_to_dict_success(self):
        from src.audiobook_studio.quality.metrics import DNSMOSResult

        r = DNSMOSResult(mos_overall=3.5, mos_sig=3.8, mos_bak=3.2, mos_ovr=3.5, success=True)
        d = r.to_dict()
        assert d["success"] is True


class TestASRResult:
    def test_to_dict(self):
        from src.audiobook_studio.quality.metrics import ASRResult

        r = ASRResult(text="hello", words=[], language="en", confidence=0.9, duration_ms=1000, success=True)
        assert r.to_dict()["success"] is True


class TestWERResult:
    def test_to_dict(self):
        from src.audiobook_studio.quality.metrics import WERResult

        r = WERResult(
            wer=0.1,
            cer=0.05,
            insertions=1,
            deletions=0,
            substitutions=1,
            reference_words=10,
            hypothesis_words=11,
            success=True,
        )
        assert r.to_dict()["wer"] == 0.1


class TestSpeakerEmbedding:
    def test_to_dict(self):
        from src.audiobook_studio.quality.metrics import SpeakerEmbedding

        emb = SpeakerEmbedding(
            embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32), model_name="ecapa", sample_rate=16000
        )
        assert emb.to_dict()["dim"] == 3


class TestSpeakerSimilarityResult:
    def test_to_dict(self):
        from src.audiobook_studio.quality.metrics import SpeakerSimilarityResult

        r = SpeakerSimilarityResult(
            similarity=0.85, threshold=0.7, is_same_speaker=True, reference_id="r", target_id="t", success=True
        )
        assert r.to_dict()["similarity"] == 0.85


class TestWERComputation:
    def test_identical(self):
        from src.audiobook_studio.quality.metrics import ASRWerMetric

        m = ASRWerMetric.__new__(ASRWerMetric)
        wer, _, _, _, _, _, _ = m._compute_wer_cer("hello", "hello")
        assert wer == 0.0

    def test_substitution(self):
        from src.audiobook_studio.quality.metrics import ASRWerMetric

        m = ASRWerMetric.__new__(ASRWerMetric)
        wer, _, ins, _, sub, _, _ = m._compute_wer_cer("hello", "hallo")
        assert sub == 1


class TestMetricNames:
    def test_dnsmos(self):
        from src.audiobook_studio.quality.metrics import DNSMOSMetric

        assert DNSMOSMetric.__new__(DNSMOSMetric).get_name() == "dnsmos"

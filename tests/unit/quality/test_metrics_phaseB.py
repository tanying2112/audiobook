"""Phase B tests for quality/metrics.py.

Covers the testable logic of the three quality metrics (DNSMOS, ASR WER,
Speaker Similarity) and the QualityCheckSuite orchestrator using mock_mode
backends (no real models / network required), plus direct unit tests for the
pure helpers (_tensor_to_float32_l2norm, _cosine_similarity, _compute_wer_cer),
model-URL resolution, and the backend factory error paths.
"""

from __future__ import annotations

import numpy as np
import pytest

from src.audiobook_studio.quality import metrics as M

# ── Pure helpers ─────────────────────────────────────────────────────────────


class _FakeTensor:
    """Duck-typed stand-in for a torch tensor (torch is globally mocked in tests)."""

    def squeeze(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return np.array([3.0, 4.0, 0.0], dtype=np.float32)


def test_tensor_to_float32_l2norm_torch():
    emb = M._tensor_to_float32_l2norm(_FakeTensor())
    assert emb.dtype == np.float32
    assert abs(float(np.linalg.norm(emb)) - 1.0) < 1e-5


def test_cosine_similarity_basic():
    a = [1.0, 0.0, 0.0]
    b = [1.0, 0.0, 0.0]
    assert M.SpeakerSimilarityMetric(mock_mode=True)._cosine_similarity(a, b) == 1.0


def test_cosine_similarity_empty_and_zero_magnitude():
    sm = M.SpeakerSimilarityMetric(mock_mode=True)
    assert sm._cosine_similarity([], [1.0]) == 0.0
    assert sm._cosine_similarity([0.0, 0.0], [1.0, 1.0]) == 0.0


# ── DNSMOS ──────────────────────────────────────────────────────────────────


def test_dnsmos_get_model_url(monkeypatch):
    monkeypatch.setenv("DNSMOS_MODEL_URL", "https://example.com/m.onnx")
    m = M.DNSMOSMetric()
    assert m._get_model_url() == "https://example.com/m.onnx"


def test_dnsmos_compute_mock(monkeypatch):
    m = M.DNSMOSMetric(mock_mode=True)
    monkeypatch.setattr(m, "_preprocess_audio", lambda p: np.zeros(m.INPUT_LENGTH_SAMPLES, dtype=np.float32))
    score = m.compute("dummy.wav")
    assert score == m._mock_scores["mos_overall"]


def test_dnsmos_compute_detailed_mock(monkeypatch):
    m = M.DNSMOSMetric(mock_mode=True)
    monkeypatch.setattr(m, "_preprocess_audio", lambda p: np.zeros(m.INPUT_LENGTH_SAMPLES, dtype=np.float32))
    res = m.compute_detailed("dummy.wav")
    assert res.success is True
    assert res.mos_ovr == m._mock_scores["mos_ovr"]


def test_dnsmos_compute_failure_returns_zero(monkeypatch):
    m = M.DNSMOSMetric(mock_mode=True)
    monkeypatch.setattr(m, "_preprocess_audio", lambda p: (_ for _ in ()).throw(RuntimeError("boom")))
    assert m.compute("dummy.wav") == 0.0


def test_dnsmos_ensure_model_existing(tmp_path):
    m = M.DNSMOSMetric(model_path=tmp_path / "dnsmos.onnx")
    (tmp_path / "dnsmos.onnx").write_bytes(b"x" * 2000000)
    assert m._ensure_model() is True


def test_dnsmos_ensure_model_download_failure(monkeypatch, tmp_path):
    import urllib.error
    import urllib.request

    m = M.DNSMOSMetric(model_path=tmp_path / "dnsmos.onnx")

    def _raise(*a, **k):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    assert m._ensure_model() is False


# ── ASR WER ─────────────────────────────────────────────────────────────────


def test_asr_wer_compute_mock():
    metric = M.ASRWerMetric(backend="whisper", mock_mode=True)
    res = metric.compute("dummy.wav", reference_text="This is a mock English transcription result")
    assert res.success is True
    assert res.wer == 0.0


def test_asr_wer_compute_mismatch():
    metric = M.ASRWerMetric(backend="whisper", mock_mode=True)
    res = metric.compute("dummy.wav", reference_text="完全不相关的参考文本xyz")
    assert res.success is True
    assert res.wer > 0.0


def test_asr_wer_no_reference():
    metric = M.ASRWerMetric(backend="whisper", mock_mode=True)
    res = metric.compute("dummy.wav")
    assert res.success is False
    assert res.error == "No reference text provided"


def test_asr_wer_compute_wer_shortcut():
    metric = M.ASRWerMetric(backend="whisper", mock_mode=True)
    score = metric.compute_wer("dummy.wav", reference_text="This is a mock English transcription result")
    assert score == 0.0


def test_asr_backend_factory_unknown():
    metric = M.ASRWerMetric(backend="whisper", mock_mode=True)
    with pytest.raises(ValueError):
        metric._create_backend("bogus", "m", "cpu", "int8", True)


def test_asr_wer_cer_direct():
    metric = M.ASRWerMetric(backend="whisper", mock_mode=True)
    wer, cer, ins, dels, subs, ref, hyp = metric._compute_wer_cer("a b c", "a b d")
    assert wer == 1 / 3
    assert ins == 0 and dels == 0 and subs == 1


# ── Speaker Similarity ──────────────────────────────────────────────────────


def test_speaker_sim_compute_mock():
    metric = M.SpeakerSimilarityMetric(backend="ecapa_tdnn", mock_mode=True)
    res = metric.compute("target.wav", reference_audio="ref.wav")
    assert res.success is True
    assert isinstance(res.similarity, float)


def test_speaker_sim_no_reference():
    metric = M.SpeakerSimilarityMetric(backend="ecapa_tdnn", mock_mode=True)
    res = metric.compute("target.wav")
    assert res.success is False
    assert res.error == "No reference provided"


def test_speaker_sim_reference_extract_failure():
    metric = M.SpeakerSimilarityMetric(backend="ecapa_tdnn", mock_mode=True)
    metric._backend.extract_embedding = lambda p: (_ for _ in ()).throw(RuntimeError("bad"))
    res = metric.compute("target.wav", reference_audio="ref.wav")
    assert res.success is False


def test_speaker_sim_register_reference():
    metric = M.SpeakerSimilarityMetric(backend="ecapa_tdnn", mock_mode=True)
    assert metric.register_reference("spk1", "ref.wav") is True


def test_speaker_sim_backend_factory_unknown():
    with pytest.raises(ValueError):
        M.SpeakerSimilarityMetric(backend="bogus", mock_mode=True)


# ── QualityCheckSuite (orchestrator) ────────────────────────────────────────


def _suite_config(thresholds=None, qc=None):
    return {
        "thresholds": thresholds or {"dnsmos_min": 3.5, "asr_wer_max": 0.05, "speaker_sim_min": 0.85},
        "quality_check": qc
        or {
            "mock_mode": True,
            "dnsmos_enabled": True,
            "asr_enabled": True,
            "asr_backend": "whisper",
            "speaker_similarity_enabled": True,
        },
    }


def test_suite_check_all_pass(monkeypatch):
    monkeypatch.setattr(
        M.DNSMOSMetric,
        "_preprocess_audio",
        lambda self, p: np.zeros(M.DNSMOSMetric.INPUT_LENGTH_SAMPLES, dtype=np.float32),
    )
    # Lenient speaker threshold: mock cosine of two hash-derived embeddings
    # can be near zero/negative, so require it to be >= -1 to count as "pass".
    thresholds = {"dnsmos_min": 3.5, "asr_wer_max": 0.05, "speaker_sim_min": -1.0}
    suite = M.QualityCheckSuite(config=_suite_config(thresholds=thresholds))
    result = suite.check_all(
        "target.wav",
        reference_text="This is a mock English transcription result",
        reference_speaker_audio="ref.wav",
    )
    assert result.passed is True
    assert result.dnsmos is not None
    assert result.wer is not None
    assert result.speaker_sim is not None


def test_suite_check_all_with_issues(monkeypatch):
    monkeypatch.setattr(
        M.DNSMOSMetric,
        "_preprocess_audio",
        lambda self, p: np.zeros(M.DNSMOSMetric.INPUT_LENGTH_SAMPLES, dtype=np.float32),
    )
    thresholds = {"dnsmos_min": 5.0, "asr_wer_max": 0.0, "speaker_sim_min": 0.99}
    suite = M.QualityCheckSuite(config=_suite_config(thresholds=thresholds))
    result = suite.check_all(
        "target.wav",
        reference_text="完全不相关的参考文本xyz",
        reference_speaker_audio="ref.wav",
    )
    assert result.passed is False
    assert "DNSMOS" in result.overall_message
    assert "WER" in result.overall_message
    assert "Speaker" in result.overall_message


def test_suite_register_speaker_success():
    suite = M.QualityCheckSuite(config=_suite_config())
    suite._initialize()
    assert suite.register_speaker("spk1", "ref.wav") is True


def test_suite_register_speaker_no_backend():
    config = _suite_config(qc={"mock_mode": True, "speaker_similarity_enabled": False})
    suite = M.QualityCheckSuite(config=config)
    suite._initialize()
    assert suite.register_speaker("spk1", "ref.wav") is False


def test_suite_initialize_disabled_components():
    config = _suite_config(
        qc={"mock_mode": True, "dnsmos_enabled": False, "asr_enabled": False, "speaker_similarity_enabled": False}
    )
    suite = M.QualityCheckSuite(config=config)
    suite._initialize()
    assert suite._dnsmos is None
    assert suite._wer is None
    assert suite._speaker_sim is None

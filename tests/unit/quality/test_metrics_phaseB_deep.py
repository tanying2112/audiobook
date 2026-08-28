"""Deep-mock Phase B tests for quality/metrics.py.

The mock_mode paths are covered elsewhere; this file exercises the *real*
backend code paths (Whisper, FunASR, DNSMOS, audio preprocessing) by injecting
fake model classes / modules so no real models or network access are required.
(The ECAPA/WavLM real paths cannot be covered here: torchaudio is not
installed in this environment.)
"""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from src.audiobook_studio.quality import metrics as M

# ── Whisper (faster-whisper) real transcribe path ───────────────────────────


class _FakeWhisperSeg:
    def __init__(self, text):
        self.text = text
        self.words = []
        self.start = 0.0
        self.end = 1.0
        self.probability = 0.9


class _FakeWhisperInfo:
    language = "en"
    duration = 1.0


class _FakeWhisperModel:
    def __init__(self, *a, **k):
        pass

    def transcribe(self, audio_path, **k):
        return (iter([_FakeWhisperSeg("hello world")]), _FakeWhisperInfo())


def test_whisper_real_transcribe(monkeypatch):
    monkeypatch.setattr("faster_whisper.WhisperModel", _FakeWhisperModel)
    backend = M.WhisperBackend(model_size="tiny", use_faster=True)
    res = backend.transcribe("dummy.wav")
    assert res.success is True
    assert res.text == "hello world"


def test_whisper_real_get_name():
    backend = M.WhisperBackend(model_size="base")
    assert backend.get_name() == "whisper_base"


# ── FunASR real transcribe path (inject fake funasr module) ─────────────────


def test_funasr_real_transcribe(monkeypatch):
    fake_funasr = types.ModuleType("funasr")

    class _AutoModel:
        def __init__(self, **kw):
            pass

        def generate(self, **kw):
            return [
                {
                    "text": "识别结果",
                    "words": [{"word": "识别", "start": 0.0, "end": 1.0, "confidence": 0.9}],
                    "language": "zh",
                    "confidence": 0.9,
                    "duration": 3.7,
                }
            ]

    fake_funasr.AutoModel = _AutoModel
    monkeypatch.setitem(sys.modules, "funasr", fake_funasr)

    backend = M.FunASRBackend(model_name="paraformer-zh")
    res = backend.transcribe("dummy.wav")
    assert res.success is True
    assert res.text == "识别结果"


def test_funasr_backend_get_name():
    backend = M.FunASRBackend(model_name="sensevoice_small")
    assert "sensevoice" in backend.get_name()


# ── DNSMOS real inference path (fake ONNX session) ──────────────────────────


class _FakeONNXInput:
    def __init__(self):
        self.name = "input"
        self.shape = [None, 144160]


class _FakeONNXSession:
    def __init__(self, path, sess_options=None, providers=None):
        pass

    def get_inputs(self):
        return [_FakeONNXInput()]

    def get_outputs(self):
        return [_FakeONNXInput()]

    def run(self, out, feed):
        # SIG, BAK, OVR
        return [np.array([[4.0, 4.1, 4.2]], dtype=np.float32)]


def test_dnsmos_real_inference(monkeypatch, tmp_path):
    monkeypatch.setattr("onnxruntime.InferenceSession", _FakeONNXSession)
    monkeypatch.setattr(
        M.DNSMOSMetric,
        "_preprocess_audio",
        lambda self, p: np.zeros(self.INPUT_LENGTH_SAMPLES, dtype=np.float32),
    )
    model_file = tmp_path / "dnsmos.onnx"
    model_file.write_bytes(b"x" * 2_000_000)
    m = M.DNSMOSMetric(model_path=model_file)
    res = m.compute_detailed("dummy.wav")
    assert res.success is True
    assert res.mos_ovr == pytest.approx(4.2)
    assert res.mos_sig == pytest.approx(4.0)


def test_dnsmos_real_initialize_failure(monkeypatch, tmp_path):
    class _BoomSession:
        def __init__(self, *a, **k):
            raise RuntimeError("bad onnx")

    monkeypatch.setattr("onnxruntime.InferenceSession", _BoomSession)
    monkeypatch.setattr(
        M.DNSMOSMetric,
        "_preprocess_audio",
        lambda self, p: np.zeros(self.INPUT_LENGTH_SAMPLES, dtype=np.float32),
    )
    model_file = tmp_path / "dnsmos.onnx"
    model_file.write_bytes(b"x" * 2_000_000)
    m = M.DNSMOSMetric(model_path=model_file)
    res = m.compute_detailed("dummy.wav")
    assert res.success is False


# ── Frame preparation (real numpy ops; _preprocess_audio needs soundfile) ──


def test_prepare_input_frames_real():
    m = M.DNSMOSMetric()
    short = np.zeros(1000, dtype=np.float32)
    framed = m._prepare_input_frames(short)
    assert framed.shape[-1] == m.INPUT_LENGTH_SAMPLES


def test_prepare_input_frames_long():
    m = M.DNSMOSMetric()
    long = np.zeros(m.INPUT_LENGTH_SAMPLES * 2, dtype=np.float32)
    framed = m._prepare_input_frames(long)
    assert framed.shape[-1] == m.INPUT_LENGTH_SAMPLES


# ── ECAPA / WavLM real _initialize raises honestly when model unavailable ──


def test_ecapa_initialize_honest_failure(monkeypatch):
    def _boom(self):
        raise RuntimeError("model unavailable")

    metric = M.SpeakerSimilarityMetric(backend="ecapa_tdnn")
    monkeypatch.setattr(metric._backend, "_initialize", _boom)
    res = metric.compute("target.wav", reference_audio="ref.wav")
    assert res.success is False


def test_wavlm_initialize_honest_failure(monkeypatch):
    def _boom(self):
        raise RuntimeError("model unavailable")

    metric = M.SpeakerSimilarityMetric(backend="wavlm_large")
    monkeypatch.setattr(metric._backend, "_initialize", _boom)
    res = metric.compute("target.wav", reference_audio="ref.wav")
    assert res.success is False


# ── QualityCheckSuite graceful degradation when a metric dep is missing ──


def test_suite_degrades_when_metric_init_fails(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("dependency unavailable")

    monkeypatch.setattr(M, "DNSMOSMetric", _boom)
    monkeypatch.setattr(M, "ASRWerMetric", _boom)
    monkeypatch.setattr(M, "SpeakerSimilarityMetric", _boom)

    suite = M.QualityCheckSuite({"quality_check": {}})
    suite._initialize()

    assert suite._dnsmos is None
    assert suite._wer is None
    assert suite._speaker_sim is None
    assert suite._initialized is True


def test_register_speaker_handles_runtime_error(monkeypatch):
    suite = M.QualityCheckSuite({"quality_check": {"mock_mode": True}})
    suite._initialize()
    assert suite._speaker_sim is not None

    def _raise(*a, **k):
        raise RuntimeError("register failed")

    monkeypatch.setattr(type(suite._speaker_sim), "register_reference", _raise)
    assert suite.register_speaker("spk1", "ref.wav") is False

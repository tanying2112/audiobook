"""Mock-mode coverage tests for quality/metrics.py.

These exercise the torch/ML metric classes through their model-free
``mock_mode`` paths (fixed scores, no ONNX/speechbrain load) plus the
torch-free helpers, to push production coverage up without downloading
heavy model weights.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import numpy as np

from src.audiobook_studio.quality.metrics import (
    ASRWerMetric,
    DNSMOSMetric,
    FunASRBackend,
    SpeakerEmbedding,
    SpeakerSimilarityMetric,
    _tensor_to_float32_l2norm,
)


def _fake_tensor(values: list[float]):
    """Minimal torch-tensor stand-in for _tensor_to_float32_l2norm."""

    class FakeTensor:
        def squeeze(self) -> "FakeTensor":
            return self

        def cpu(self) -> "FakeTensor":
            return self

        def numpy(self) -> np.ndarray:
            return np.array(values, dtype=np.float32)

    return FakeTensor()


def test_tensor_to_float32_l2norm() -> None:
    emb = _tensor_to_float32_l2norm(_fake_tensor([3.0, 4.0]))
    assert np.allclose(emb, [0.6, 0.8])
    # empty tensor -> zero norm guard
    empty = _tensor_to_float32_l2norm(_fake_tensor([]))
    assert empty.size == 0


def _dummy_audio(*_args: Any, **_kwargs: Any) -> np.ndarray:
    return np.zeros(16000, dtype=np.float32)


def test_dnsmos_mock_compute(tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF....WAVE")  # placeholder; preprocess is patched
    m = DNSMOSMetric(mock_mode=True)
    with patch.object(m, "_preprocess_audio", _dummy_audio):
        score = m.compute(wav)
        assert score == 4.2
        detailed = m.compute_detailed(wav)
    assert detailed.success is True
    assert detailed.mos_overall == 4.2


def test_funasr_mock_transcribe(tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF....WAVE")
    backend = FunASRBackend(model_name="sensevoice_small", mock_mode=True)
    res = backend.transcribe(wav)
    assert res.success is True
    assert isinstance(res.text, str)


def test_asr_wer_mock_compute(tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF....WAVE")
    m = ASRWerMetric(mock_mode=True)
    res = m.compute(wav, reference_text="这是一段参考文本")
    assert res.success is True
    assert isinstance(res.wer, float)


def test_speaker_similarity_mock_compute(tmp_path: Path) -> None:
    wav = tmp_path / "clip.wav"
    wav.write_bytes(b"RIFF....WAVE")
    m = SpeakerSimilarityMetric(backend="ecapa_tdnn", mock_mode=True)
    res = m.compute(wav, reference_audio=wav)
    assert res.success is True
    assert isinstance(res.similarity, float)


def test_speaker_embedding_roundtrip() -> None:
    emb = SpeakerEmbedding(
        embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32),
        model_name="ecapa_tdnn",
        sample_rate=16000,
    )
    d = emb.to_dict()
    assert d["model_name"] == "ecapa_tdnn"
    restored = SpeakerEmbedding.from_dict(d)
    assert np.allclose(restored.embedding, [0.1, 0.2, 0.3])

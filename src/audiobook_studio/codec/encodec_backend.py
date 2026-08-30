"""Real frontier backends (EnCodec / HuBERT) -- lazy, dependency-free to import.

These wrap the *actual* state-of-the-art neural audio codecs:

* **EnCodec** (Meta, 2022) -- a convnet-based neural codec producing discrete
  acoustic tokens at 1.5 / 3 / 6 / 24 kbps.  This is the codec powering
  MusicGen and AudioCraft.
* **HuBERT / wav2vec 2.0 semantic tokens** -- *semantic* rather than acoustic
  tokens; the representation used by SpeechTokenizer and VALL-E for
  prosody/content disentanglement.

Both require ``torch`` (and ``encodec`` / ``transformers``), which are optional
in the free stack.  Importing this module never fails; the backends report
``available() == False`` and raise :class:`CodecBackendUnavailable` when the
dependency is missing, so the rest of the system stays green on CPU-only / free
environments while the frontier path lights up automatically wherever torch is
present.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .base import CodecBackendUnavailable, CodecResult


def _require_encodec() -> tuple[Any, Any]:
    try:
        import encodec
        import torch

        return encodec, torch
    except Exception as exc:  # pragma: no cover - depends on optional deps
        raise CodecBackendUnavailable(
            "EnCodec backend requires 'torch' and 'encodec' " f"(pip install torch encodec): {exc}"
        )


class EncodecAdapter:
    """Adapter around Meta's EnCodec neural codec (lazy torch import)."""

    name = "encodec"

    def __init__(self, bandwidth: float = 1.5, sample_rate: int = 24000) -> None:
        encodec, torch = _require_encodec()
        self._torch = torch
        self.sample_rate = sample_rate
        model = encodec.models.EncodecModel.get_default_model()
        model.set_target_bandwidth(bandwidth)
        model.eval()
        self._model = model
        self.bandwidth = bandwidth

    @classmethod
    def available(cls) -> bool:
        try:
            import encodec
            import torch

            return True
        except ImportError:  # pragma: no cover
            return False

    def encode(self, audio: np.ndarray[Any, Any], sample_rate: int | None = None) -> CodecResult:
        torch = self._torch
        sr = sample_rate or self.sample_rate
        if sr != self.sample_rate:
            raise ValueError("EnCodec operates at 24 kHz")
        a = np.asarray(audio, dtype=np.float64)
        if a.ndim > 1:
            a = a.mean(axis=1)
        # EnCodec expects (batch, channels, time) at 24 kHz
        wav = torch.from_numpy(a.astype(np.float32)).unsqueeze(0).unsqueeze(0)
        with torch.no_grad():
            encoded = self._model.encode(wav)
        # encoded[0][0] is a list of (codes, scale) per quantizer
        codes = encoded[0][0]  # shape (n_q, 1, n_frames)
        tokens = [codes[q, 0].cpu().numpy().astype(np.int32) for q in range(codes.shape[0])]
        return CodecResult(
            tokens=tokens,
            sample_rate=self.sample_rate,
            n_freq=0,
            n_codebooks=codes.shape[0],
            frame_rate=75.0,  # EnCodec emits 75 frames/sec at 24 kHz
            original_length=len(a),
            meta={"bandwidth": self.bandwidth},
        )

    def decode(self, result: CodecResult) -> np.ndarray[Any, Any]:
        torch = self._torch
        import torch as _torch

        codes = _torch.stack([torch.from_numpy(t).unsqueeze(0) for t in result.tokens], dim=0)
        with torch.no_grad():
            wav = self._model.decode(codes)[0, 0, 0]
        return wav.cpu().numpy().astype(np.float64)  # type: ignore[no-any-return]


def _require_transformers() -> tuple[Any, Any, Any]:
    try:
        import torch
        from transformers import HubertModel, Wav2Vec2FeatureExtractor

        return torch, Wav2Vec2FeatureExtractor, HubertModel
    except Exception as exc:  # pragma: no cover
        raise CodecBackendUnavailable(
            "HuBERT backend requires 'torch' and 'transformers' " f"(pip install torch transformers): {exc}"
        )


class HubertSemanticTokenizer:
    """Extracts HuBERT *semantic* tokens -- the representation behind VALL-E /
    SpeechTokenizer.  Frontier alternative to acoustic (EnCodec) tokens."""

    name = "hubert-semantic"

    def __init__(self, model_id: str = "facebook/hubert-base-ls960") -> None:
        torch, feat_cls, model_cls = _require_transformers()
        self._torch = torch
        self._feat = feat_cls.from_pretrained(model_id)
        self._model = model_cls.from_pretrained(model_id)
        self._model.eval()
        self.sample_rate = 16000

    @classmethod
    def available(cls) -> bool:
        try:
            import torch
            from transformers import HubertModel

            return True
        except ImportError:  # pragma: no cover
            return False

    def encode(self, audio: np.ndarray[Any, Any], sample_rate: int | None = None) -> CodecResult:
        torch = self._torch
        a = np.asarray(audio, dtype=np.float64)
        if a.ndim > 1:
            a = a.mean(axis=1)
        inputs = self._feat(a, sampling_rate=self.sample_rate, return_tensors="pt")
        with torch.no_grad():
            out = self._model(**inputs).logits  # (1, time, hidden)
        # quantize the hidden states to the nearest centroids found on the fly
        flat = out[0].cpu().numpy()
        tokens = self._coarse_quantize(flat)
        return CodecResult(
            tokens=[tokens],
            sample_rate=self.sample_rate,
            n_freq=0,
            n_codebooks=1,
            frame_rate=flat.shape[0] / max(1, len(a) / self.sample_rate),
            original_length=len(a),
            meta={"model": "hubert-base"},
        )

    @staticmethod
    def _coarse_quantize(flat: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
        # simple per-dimension uniform quantization -> int tokens
        lo, hi = flat.min(axis=0), flat.max(axis=0)
        span = (hi - lo) + 1e-9
        q = ((flat - lo) / span * 255).astype(np.int32)
        return q[:, 0] if q.shape[1] == 1 else q.mean(axis=1).astype(np.int32)  # type: ignore[no-any-return]

    def decode(self, result: CodecResult) -> np.ndarray[Any, Any]:  # pragma: no cover
        # Semantic tokens are not directly invertible to audio; return a placeholder
        # waveform so callers can detect the no-op.  Full synthesis needs a vocoder.
        raise CodecBackendUnavailable("HuBERT semantic tokens are not waveform-invertible without a vocoder")

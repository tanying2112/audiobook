"""High-level entry points: compress / decompress / benchmark audio.

These are the functions the rest of the application (export pipeline, API, CLI)
would call to apply a neural audio codec to generated audiobook audio.  They are
opt-in (see :func:`is_codec_enabled`) and degrade gracefully when optional
backends (torch/ffmpeg) are unavailable.
"""

from __future__ import annotations

import os

from .base import CodecBackendUnavailable
from .numpy_codec import NumpyNeuralCodec
from .opus import OpusCompressor

ENV_ENABLED = "NEURAL_CODEC_ENABLED"


def is_codec_enabled() -> bool:
    """Opt-in flag for the neural audio codec feature (default: off)."""
    return os.environ.get(ENV_ENABLED, "false").lower() in ("1", "true", "yes", "on")


def get_numpy_codec(**kwargs: object) -> NumpyNeuralCodec:
    """Return a ready-to-use reference neural audio codec."""
    return NumpyNeuralCodec(**kwargs)  # type: ignore[arg-type]


def compress_audio_file(
    input_path: str,
    output_path: str,
    method: str = "neural",
    **kwargs: object,
) -> dict:
    """Compress ``input_path`` (WAV) to ``output_path``.

    ``method`` is one of:

    * ``"neural"`` -- the numpy RVQ/STFT neural codec (token container).
    * ``"opus"``   -- Opus via ffmpeg (self-contained bitstream).
    """
    if method == "neural":
        codec = get_numpy_codec(**kwargs)  # type: ignore[arg-type]
        return codec.compress_file(input_path, output_path)
    if method == "opus":
        if not OpusCompressor.available():
            raise CodecBackendUnavailable("ffmpeg not found on PATH")
        comp = OpusCompressor(**kwargs)  # type: ignore[arg-type]
        return comp.compress_file(input_path, output_path)
    raise ValueError(f"unknown codec method: {method!r}")


def decompress_audio_file(output_path: str, wav_path: str, method: str = "neural", **kwargs: object) -> None:
    """Inverse of :func:`compress_audio_file`."""
    if method == "neural":
        codec = get_numpy_codec(**kwargs)  # type: ignore[arg-type]
        codec.decompress_file(output_path, wav_path)
        return
    if method == "opus":
        if not OpusCompressor.available():
            raise CodecBackendUnavailable("ffmpeg not found on PATH")
        OpusCompressor(**kwargs).decompress_file(output_path, wav_path)  # type: ignore[arg-type]
        return
    raise ValueError(f"unknown codec method: {method!r}")


def benchmark(input_wav: str, opus_bitrate: str = "16k") -> dict:
    """Report size-reduction for every available codec method.

    Returns a dict with ``neural`` and (if ffmpeg present) ``opus`` stats.  This
    is the quantitative evidence behind the "≥50% smaller audio" claim.
    """
    report: dict[str, object] = {}
    codec = get_numpy_codec()
    report["neural"] = codec.compress_file(input_wav, input_wav + ".nac")
    os.remove(input_wav + ".nac")
    if OpusCompressor.available():
        comp = OpusCompressor(bitrate=opus_bitrate)
        out = input_wav + ".opus"
        report["opus"] = comp.compress_file(input_wav, out)
        os.remove(out)
    return report

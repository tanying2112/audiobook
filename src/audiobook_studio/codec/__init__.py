"""Neural audio codecs and other frontier audio-compression techniques.

This package introduces a **neural audio codec** (EnCodec / SoundStream / DAC
style: encoder -> Residual Vector Quantization -> decoder) plus frontier
comparison codecs, all runnable for free:

* :class:`NumpyNeuralCodec` -- a fully-numpy reference codec (STFT front-end +
  RVQ).  The token stream it emits is dramatically smaller than raw PCM, which is
  the quantitative basis for the "audio file size reduced by 50%" goal.
* :class:`~encodec_backend.EncodecAdapter` -- Meta's EnCodec via torch (lazy;
  activates automatically where torch + encodec are installed).
* :class:`~encodec_backend.HubertSemanticTokenizer` -- HuBERT *semantic* tokens
  (VALL-E / SpeechTokenizer style), another frontier representation.
* :class:`~opus.OpusCompressor` -- Opus via ffmpeg, a self-contained >90%
  compression for environments without the neural backends.

Typical usage::

    from audiobook_studio.codec import get_numpy_codec, CodecContainer
    codec = get_numpy_codec()
    result = codec.encode(audio, 16000)
    data = CodecContainer(result).to_bytes()      # tiny token file
    audio2 = codec.decode(CodecContainer.from_bytes(data).result)
"""

from __future__ import annotations

from .base import (
    CodecBackendUnavailable,
    CodecContainer,
    CodecResult,
    NeuralAudioCodec,
)
from .engine import (
    benchmark,
    compress_audio_file,
    decompress_audio_file,
    get_numpy_codec,
    is_codec_enabled,
)
from .numpy_codec import NumpyNeuralCodec
from .rvq import ResidualVectorQuantizer, RvqConfig

__all__ = [
    "CodecBackendUnavailable",
    "CodecContainer",
    "CodecResult",
    "NeuralAudioCodec",
    "NumpyNeuralCodec",
    "ResidualVectorQuantizer",
    "RvqConfig",
    "benchmark",
    "compress_audio_file",
    "decompress_audio_file",
    "get_numpy_codec",
    "is_codec_enabled",
]

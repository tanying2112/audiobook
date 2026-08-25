"""Abstract interface and container format for neural audio codecs.

A *neural audio codec* maps a waveform to a set of **discrete tokens**
(plus a small header) and back.  Storing only the tokens -- not the raw samples
-- is what makes these codecs so compact: at 24 kHz a typical codec emits ~75
tokens/second, i.e. well under 1 kbps, versus 384 kbps for 16-bit PCM.

The "model" (the RVQ codebooks / EnCodec weights) is shared between encoder and
decoder and is *not* stored in the per-file container -- exactly like real
codecs, where you ship tokens and the receiver already has the model.  This is
why the container file is dramatically smaller than the source WAV.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

MAGIC = b"NAC1"
# magic, sr, n_freq, n_codebooks, n_frames, codebook_size, original_length,
# frame_rate_x100, gain_x10000
HEADER_FMT = "<4s8i"
HEADER_SIZE = struct.calcsize(HEADER_FMT)


class CodecBackendUnavailable(Exception):
    """Raised when a codec backend (e.g. EnCodec/torch) cannot be loaded."""


@dataclass
class CodecResult:
    """The discrete representation produced by a neural audio codec."""

    tokens: list[np.ndarray]  # one int array (n_frames,) per codebook
    sample_rate: int
    n_freq: int
    n_codebooks: int
    frame_rate: float
    original_length: int
    gain: float = 1.0  # RMS of the original signal, used to restore level
    meta: dict[str, object] = field(default_factory=dict)

    @property
    def n_frames(self) -> int:
        return int(self.tokens[0].shape[0])


@dataclass
class CodecContainer:
    """A compact, self-describing binary container for codec tokens.

    Layout: ``MAGIC | 8 int32 header fields | packed token bytes``.
    Each token is stored as a single byte (codebook sizes are <= 256).  The
    shared model/codebooks are intentionally excluded -- they live in the codec
    instance, mirroring how real neural codecs transmit tokens only.  ``gain``
    stores the original signal RMS so the decoder can restore the exact level
    (the quantiser attenuates energy, so a plain stored-peak multiply is not
    enough).
    """

    result: CodecResult

    def to_bytes(self) -> bytes:
        r = self.result
        n_frames = r.n_frames
        header = struct.pack(
            HEADER_FMT,
            MAGIC,
            int(r.sample_rate),
            int(r.n_freq),
            int(r.n_codebooks),
            int(n_frames),
            int(r.tokens[0].max()) + 1 if n_frames else 256,
            int(r.original_length),
            int(round(r.frame_rate * 100)),
            int(round(r.gain * 10000)),
        )
        body = b"".join(t.astype(np.uint8).tobytes() for t in r.tokens)
        return header + body

    @classmethod
    def from_bytes(cls, data: bytes) -> "CodecContainer":
        (
            magic,
            sr,
            n_freq,
            n_cb,
            n_frames,
            codebook_size,
            orig_len,
            fr_x100,
            gain_x10000,
        ) = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
        if magic != MAGIC:
            raise ValueError("not a neural-audio-codec container")
        body = data[HEADER_SIZE:]
        tokens: list[np.ndarray] = []
        for q in range(n_cb):
            seg = body[q * n_frames : (q + 1) * n_frames]
            tokens.append(np.frombuffer(seg, dtype=np.uint8).astype(np.int32))
        return cls(
            CodecResult(
                tokens=tokens,
                sample_rate=sr,
                n_freq=n_freq,
                n_codebooks=n_cb,
                frame_rate=fr_x100 / 100.0,
                original_length=orig_len,
                gain=gain_x10000 / 10000.0,
                meta={},
            )
        )


class NeuralAudioCodec(Protocol):
    """Interface every neural audio codec backend implements."""

    name: str

    @classmethod
    def available(cls) -> bool:
        """Whether this backend can run in the current environment."""
        ...

    def encode(self, audio: np.ndarray, sample_rate: int | None = None) -> CodecResult:
        """Encode mono audio (float, [-1, 1]) into discrete tokens."""
        ...

    def decode(self, result: CodecResult) -> np.ndarray:
        """Decode tokens back into a mono float waveform."""
        ...

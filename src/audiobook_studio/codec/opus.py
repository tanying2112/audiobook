"""Opus / Lyra-class waveform codec via ffmpeg (free, self-contained).

While the neural codec stores *tokens* (requiring the shared model/codebooks to
decode), classic transform-codecs like **Opus** produce a fully self-contained
bitstream.  Opus reaches ~6-12 kbps at transparent quality, so a 16 kHz / 16-bit
mono WAV (256 kbps) shrinks by **>90%** -- comfortably clearing the 50% target
with no shared-model caveat.  We expose it as one of the "frontier" comparison
codecs and as a robust, dependency-light fallback.

Uses the system ``ffmpeg`` binary (already a hard dependency of the project).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from .base import CodecBackendUnavailable


class OpusCompressor:
    """Compress / decompress audio with Opus through ffmpeg."""

    name = "opus"

    def __init__(self, bitrate: str = "16k") -> None:
        exe = shutil.which("ffmpeg")
        if exe is None:
            raise CodecBackendUnavailable("ffmpeg not found on PATH")
        self.ffmpeg = exe
        self.bitrate = bitrate

    @classmethod
    def available(cls) -> bool:
        return shutil.which("ffmpeg") is not None

    def compress_file(self, wav_path: str, opus_path: str) -> dict:
        cmd = [
            self.ffmpeg,
            "-y",
            "-i",
            wav_path,
            "-c:a",
            "libopus",
            "-b:a",
            self.bitrate,
            opus_path,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise CodecBackendUnavailable(f"ffmpeg failed: {proc.stderr[-500:]}")
        orig = os.path.getsize(wav_path)
        comp = os.path.getsize(opus_path)
        return {
            "original_bytes": orig,
            "compressed_bytes": comp,
            "ratio": comp / orig if orig else 0.0,
            "bitrate": self.bitrate,
        }

    def decompress_file(self, opus_path: str, wav_path: str) -> None:
        cmd = [self.ffmpeg, "-y", "-i", opus_path, wav_path]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise CodecBackendUnavailable(f"ffmpeg failed: {proc.stderr[-500:]}")


def benchmark_opus(wav_path: str, bitrate: str = "16k") -> dict:
    """Convenience: compress a WAV with Opus and report the size ratio."""
    if not OpusCompressor.available():
        raise CodecBackendUnavailable("ffmpeg not found on PATH")
    comp = OpusCompressor(bitrate=bitrate)
    out = wav_path + ".opus"
    try:
        stats = comp.compress_file(wav_path, out)
    finally:
        if os.path.exists(out):
            os.remove(out)
    return stats

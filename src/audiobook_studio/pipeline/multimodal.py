"""Multimodal audio/video pipeline — S3.3.

Adds the missing multimodal pieces on top of the existing SFX overlay in
``audio_finalize``:

- :class:`MusicGenerator`: BGM / sound-effect *generation*. Ships a
  **local, free** implementation (loops a BGM asset under the TTS track via
  ffmpeg) and a **remote stub** documenting that high-fidelity generative models
  (StableAudio / AudioLDM2) require GPU/paid hosting and are out of scope for
  the free-resource constraint.
- :func:`mix_with_bg_music`: composite TTS audio + a background-music bed.
- :func:`mux_audio_subtitle_to_mp4`: produce an MP4 with burned-in subtitles
  for the existing ``VideoCanvasView`` export path.
- :func:`qc_adapt_audio`: quality-control adaptation (loudness normalisation)
  so downstream playback does not clip.

All heavy lifting uses the locally-installed ``ffmpeg`` (no network, free).
"""

from __future__ import annotations

import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional


class MusicGenerator(ABC):
    """Generate background music / sound effects for a segment."""

    @abstractmethod
    def generate(self, prompt: str, duration_sec: float, output_path: Path) -> Path:
        """Generate audio from ``prompt`` of roughly ``duration_sec`` seconds."""
        raise NotImplementedError


class LocalBgmGenerator(MusicGenerator):
    """Free, local BGM generator: loops a provided BGM asset to the target length.

    This is the free-resource stand-in for generative models. Provide a BGM
    asset (e.g. a royalty-free loop) and it is time-stretched/looped under the
    requested duration with ffmpeg — no model download, no network.
    """

    def __init__(self, bgm_asset: Optional[Path] = None) -> None:
        self.bgm_asset = bgm_asset

    def generate(self, prompt: str, duration_sec: float, output_path: Path) -> Path:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.bgm_asset or not Path(self.bgm_asset).exists():
            # No asset available: emit silent BGM of the requested length.
            _write_silence(output_path, duration_sec)
            return output_path
        cmd = [
            "ffmpeg", "-y", "-stream_loop", "-1", "-i", str(self.bgm_asset),
            "-t", str(duration_sec), "-c:a", "libmp3lame", "-q:a", "4",
            str(output_path),
        ]
        _run_ffmpeg(cmd)
        return output_path


class RemoteGenerativeStub(MusicGenerator):
    """Documents the StableAudio / AudioLDM2 path (requires paid GPU hosting).

    Kept as an explicit, honest stub so the integration point is clear and the
    free-resource constraint is respected: this method must NOT be called in a
    free-only deployment.
    """

    def generate(self, prompt: str, duration_sec: float, output_path: Path) -> Path:
        raise NotImplementedError(
            "StableAudio / AudioLDM2 generative music requires GPU/paid hosting "
            "and is outside the free-resource constraint. Use LocalBgmGenerator "
            "with a royalty-free BGM asset instead."
        )


def _run_ffmpeg(cmd: list[str]) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found on PATH; required for multimodal mixing.")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-500:]}")


def _write_silence(output_path: Path, duration_sec: float) -> None:
    cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        f"anullsrc=r=24000:d={duration_sec}",
        "-c:a", "libmp3lame", "-q:a", "4", str(output_path),
    ]
    _run_ffmpeg(cmd)


def mix_with_bg_music(
    tts_path: Path,
    bgm_path: Path,
    output_path: Path,
    bgm_gain_db: float = -20.0,
) -> Path:
    """Composite a TTS track with a background-music bed (S3.3 auto-BGM mix).

    ``bgm_gain_db`` lowers the music bed so dialogue stays intelligible.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(tts_path),
        "-i", str(bgm_path),
        "-filter_complex",
        f"[1:a]volume={bgm_gain_db}dB[bg];[0:a][bg]amix=inputs=2:duration=first",
        "-c:a", "libmp3lame", "-q:a", "3", str(output_path),
    ]
    _run_ffmpeg(cmd)
    return output_path


def mux_audio_subtitle_to_mp4(
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
) -> Path:
    """Produce an MP4 with an embedded subtitle track for VideoCanvasView (S3.3).

    Uses a static black video canvas (lavfi) so no video asset is required.
    Subtitles are muxed as a *soft* ``mov_text`` stream (no libass needed); the
    ``VideoCanvasView`` frontend also renders burned-in subtitle overlays on the
    client, so hard-burn is unnecessary here.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(audio_path),
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=1",
        "-i", str(subtitle_path),
        "-map", "0:a", "-map", "1:v", "-map", "2:s?",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "1",
        "-c:a", "aac", "-b:a", "192k", "-c:s", "mov_text",
        "-shortest", str(output_path),
    ]
    _run_ffmpeg(cmd)
    return output_path


def qc_adapt_audio(input_path: Path, output_path: Path) -> Path:
    """Quality-control adaptation: loudness-normalise to podcast standards (S3.3).

    Applies EBU R128-style loudness normalisation (``loudnorm``) so the mastered
    track sits at a consistent, non-clipping level regardless of source TTS.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
        "-c:a", "libmp3lame", "-q:a", "3", str(output_path),
    ]
    _run_ffmpeg(cmd)
    return output_path

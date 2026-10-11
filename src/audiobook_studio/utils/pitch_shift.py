"""Pitch shift utility using ffmpeg band-shift (asetrate+atempo+aresample).

Validated in v6 ablation: ffmpeg band-shift achieves ~4.46 UTMOS (transparent);
librosa phase-vocoder collapses to ~1.33 UTMOS.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

_pitch_warned: bool = False


def _pitch_warn_once(msg: str) -> None:
    """Log pitch-shift warning once per process."""
    global _pitch_warned
    if not _pitch_warned:
        logger.warning(msg)
        _pitch_warned = True


def shift_semitones_path(
    in_path: str | Path,
    out_path: str | Path,
    semitones: float,
    sr: int,
) -> bool:
    """Shift pitch of an audio file by semitones using ffmpeg band-shift.

    Args:
        in_path: Input audio file path
        out_path: Output audio file path
        semitones: Pitch shift in semitones (-12 to +12). |st| < 0.001 → copy.
        sr: Sample rate (must match input file's sample rate).

    Returns:
        True on success, False on failure (caller should fall back to original).
    """
    in_path = Path(in_path)
    out_path = Path(out_path)

    if abs(semitones) < 0.001:
        # Near-zero: copy file
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(in_path.read_bytes())
        return True

    rate_f = 2.0 ** (semitones / 12.0)      # asetrate factor
    tempo_f = 2.0 ** (-semitones / 12.0)    # atempo compensation (duration restore)

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-i",
                str(in_path),
                "-af",
                f"asetrate={sr}*{rate_f:.6f},atempo={tempo_f:.6f},aresample={sr}",
                "-c:a",
                "pcm_f32le",
                "-ar",
                str(sr),
                str(out_path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            _pitch_warn_once(f"ffmpeg pitch shift failed ({result.stderr.strip()[:200]}); keeping original")
            return False
        return True
    except Exception as e:
        _pitch_warn_once(f"pitch shift error ({e}); keeping original")
        return False


def shift_semitones_array(
    audio: np.ndarray,
    sr: int,
    semitones: float,
) -> np.ndarray:
    """Shift pitch of a numpy audio array by semitones.

    Writes to temp float WAV → calls shift_semitones_path → reads back.

    Args:
        audio: Float32 audio array (mono or stereo, shape [N] or [N, C])
        sr: Sample rate
        semitones: Pitch shift in semitones

    Returns:
        Shifted audio array (same shape/dtype as input). On failure, returns original.
    """
    if abs(semitones) < 0.001:
        return audio

    # Preserve shape info
    is_stereo = audio.ndim == 2
    if is_stereo:
        n_ch = audio.shape[1]
    else:
        n_ch = 1

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf_in:
        in_f = tf_in.name
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf_out:
        out_f = tf_out.name

    try:
        # Write input as float WAV
        import soundfile as sf

        sf.write(in_f, audio, sr, subtype="FLOAT")

        ok = shift_semitones_path(in_f, out_f, semitones, sr)
        if not ok:
            return audio

        shifted, _ = sf.read(out_f, dtype="float32")
        return shifted
    except Exception as e:
        _pitch_warn_once(f"pitch shift array error ({e}); keeping original")
        return audio
    finally:
        for f in (in_f, out_f):
            try:
                os.unlink(f)
            except OSError:
                pass


__all__ = ["shift_semitones_path", "shift_semitones_array"]

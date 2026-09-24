"""Time-frequency front-end for the neural audio codec.

A *neural audio codec* (EnCodec / SoundStream / DAC) is an
``encoder -> Residual Vector Quantization (RVQ) -> decoder`` pipeline.  This
module provides the **analysis / synthesis front-end** used by the numpy
reference codec:

* a real STFT with a **sine window** (which satisfies the complementary-power
  COLA condition ``w[n]^2 + w[n + N/2]^2 = 1`` at 50% overlap), and
* **reflection padding** at the signal boundaries so the whole signal is
  perfectly reconstructed.

The STFT/iSTFT pair here is provably perfectly reconstructing (verified to
~1e-12), so *all* codec distortion comes purely from the RVQ quantization
step -- exactly as in a real neural codec.  Implemented in pure numpy (no
torch / scipy dependency) so it runs anywhere for free.
"""

from __future__ import annotations

from typing import Any

import numpy as np


def sine_window(n: int) -> np.ndarray[Any, Any]:
    """Sine window ``sin(pi*(n+0.5)/N)`` -- complementary at 50% overlap."""
    return np.asarray(np.sin(np.pi * (np.arange(n) + 0.5) / n), dtype=np.float64)


def reflect_pad(x: np.ndarray[Any, Any], win: int, hop: int) -> np.ndarray[Any, Any]:
    """Mirror ``win//2`` samples at each end so the OLA edges are filled in."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim > 1:
        x = x.mean(axis=1)
    left = x[win // 2 : 0 : -1]
    right = x[-1 : -win // 2 - 1 : -1]
    return np.concatenate([left, x, right])


def stft(x: np.ndarray[Any, Any], win: int, hop: int) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], int]:
    """Real STFT with a sine window.

    Returns ``(X, window, n_frames)`` where ``X`` is complex ``(n_frames, n_freq)``
    and ``n_freq = win // 2 + 1``.
    """
    w = sine_window(win)
    n_frames = 1 + (len(x) - win) // hop
    if n_frames < 1:
        raise ValueError("signal too short for the chosen STFT frame size")
    idx = np.arange(win)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = x[idx] * w
    x_spec = np.fft.rfft(frames, axis=1)
    return x_spec, w, n_frames


def istft(
    x_spec: np.ndarray[Any, Any],
    win: int,
    hop: int,
    w: np.ndarray[Any, Any],
    length: int | None = None,
) -> np.ndarray[Any, Any]:
    """Inverse STFT with overlap-add (perfect reconstruction for sine window)."""
    n_frames, n_freq = x_spec.shape
    buf = np.zeros(n_frames * hop + win, dtype=np.float64)
    win_power = np.zeros(n_frames * hop + win, dtype=np.float64)
    for i in range(n_frames):
        frame = np.fft.irfft(x_spec[i], n=win) * w
        buf[i * hop : i * hop + win] += frame
        win_power[i * hop : i * hop + win] += w * w
    out = buf / (win_power + 1e-12)
    if length is not None:
        out = out[:length]
    return out


def audio_to_spectrogram(
    audio: np.ndarray[Any, Any], win: int, hop: int
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any], int]:
    """Mono audio -> ``(magnitude, phase, window, n_frames)``."""
    padded = reflect_pad(audio, win, hop)
    x_spec, w, n_frames = stft(padded, win, hop)
    mag = np.abs(x_spec)
    phase = np.angle(x_spec)
    return mag, phase, w, n_frames


def spectrogram_to_audio(
    mag: np.ndarray[Any, Any],
    phase: np.ndarray[Any, Any],
    win: int,
    hop: int,
    w: np.ndarray[Any, Any],
    length: int,
) -> np.ndarray[Any, Any]:
    """``(magnitude, phase)`` -> mono audio of exactly ``length`` samples."""
    x_spec = mag * np.exp(1j * phase)
    padded_len = len(reflect_pad(np.zeros(length), win, hop)) if length else None
    rec = istft(x_spec, win, hop, w, length=padded_len)
    # undo the reflection padding
    start = win // 2
    return rec[start : start + length]

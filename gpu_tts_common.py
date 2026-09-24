#!/usr/bin/env python3
"""Shared helpers for the self-hosted GPU TTS servers (VoxCPM2 / CosyVoice2).

These servers are what makes "专业显卡模式" (Pro Studio) real: they are the only
components that can actually perform zero-shot voice cloning. This module holds the
parts of that job which must be correct and therefore testable **without** a GPU:
resolving how to hand the reference sample to whatever model build is installed, and
normalising whatever the model returns into a plain waveform.

Honesty contract (project red line)
-----------------------------------
A synthesis request carrying a reference sample is a *clone* request. If the loaded
model build exposes no zero-shot cloning entry point, the server MUST fail that task
with an explicit error instead of quietly synthesising its default voice: returning a
non-cloned voice while the API reports ``mode='clone'`` is precisely the
"placeholder pretending to be real" failure mode this project refuses.

That is why :func:`accepted_kwargs` deliberately ignores ``**kwargs`` sinks. FunASR's
``AutoModel.generate(input, **cfg)`` happily swallows an unknown ``prompt_wav_path``
and synthesises the default voice — a silent fake clone. Only *declared* parameters
are trusted; operators with a build we do not recognise can opt in explicitly via
``CLONE_PROMPT_KWARG`` (see :func:`resolve_clone_invocation`).
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# Reference-sample parameter names, in descending order of preference. The first
# group takes a decoded waveform (CosyVoice-style), the second a file path
# (VoxCPM-style).
TENSOR_PROMPT_KWARGS: Tuple[str, ...] = (
    "prompt_speech_16k",
    "prompt_speech",
    "prompt_audio_16k",
    "prompt_wav_16k",
)
PATH_PROMPT_KWARGS: Tuple[str, ...] = (
    "prompt_wav_path",
    "prompt_audio_path",
    "prompt_wav",
    "ref_audio_path",
    "reference_wav",
    "reference_audio_path",
)
# Candidate entry points, in descending order of preference.
CLONE_METHODS: Tuple[str, ...] = ("inference_zero_shot", "generate", "inference", "__call__")
TEXT_KWARGS: Tuple[str, ...] = ("tts_text", "text", "input")
PROMPT_TEXT_KWARGS: Tuple[str, ...] = ("prompt_text", "reference_text", "prompt_transcript")

PROMPT_SAMPLE_RATE = 16000


class CloneNotSupportedError(RuntimeError):
    """Raised when a clone was requested but the loaded model cannot clone.

    The caller must surface this as a task failure. Falling back to a preset/default
    voice is forbidden: the client would report a real clone that never happened.
    """


@dataclass(frozen=True)
class CloneInvocation:
    """A concrete, ready-to-call zero-shot cloning invocation."""

    method_name: str
    kwargs: Dict[str, Any] = field(default_factory=dict)
    prompt_kwarg: str = ""
    prompt_is_tensor: bool = False
    explicit_override: bool = False

    def call(self, model: Any) -> Any:
        """Invoke the resolved method on ``model``."""
        method = model if self.method_name == "__call__" else getattr(model, self.method_name)
        return method(**self.kwargs)


def accepted_kwargs(fn: Any) -> set:
    """Return the keyword parameter names ``fn`` *declares*.

    ``**kwargs`` sinks are intentionally excluded — see the module docstring: a sink
    silently discards an unknown reference-sample argument and yields a fake clone.
    """
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):  # builtins / C extensions without signatures
        return set()
    kinds = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
    return {p.name for p in sig.parameters.values() if p.kind in kinds}


def _first_present(names: Sequence[str], available: set) -> Optional[str]:
    for name in names:
        if name in available:
            return name
    return None


def resolve_clone_invocation(
    model: Any,
    *,
    text: str,
    reference_audio_path: str,
    reference_text: Optional[str] = None,
    speed: float = 1.0,
    load_prompt: Optional[Callable[[str], Any]] = None,
    override_kwarg: Optional[str] = None,
    override_method: Optional[str] = None,
) -> CloneInvocation:
    """Work out how to pass the reference sample to ``model`` for zero-shot cloning.

    Args:
        model: The loaded TTS model object (CosyVoice2, VoxCPM, FunASR AutoModel, ...).
        text: Text to synthesise.
        reference_audio_path: Path of the 15s reference sample, *as visible to this
            server* (the compose stack shares ``./output`` with the API container).
        reference_text: Transcript of the reference sample. Zero-shot quality depends
            on it for CosyVoice-style models, so it is forwarded whenever accepted.
        speed: Speech-rate multiplier, forwarded when the entry point accepts it.
        load_prompt: Callable turning the sample path into the waveform object the
            model expects (e.g. a 16 kHz tensor). Required for tensor-style APIs.
        override_kwarg: Operator escape hatch (``CLONE_PROMPT_KWARG``) naming the
            reference parameter for an unrecognised build. Trusted as given.
        override_method: Optional method name to use with ``override_kwarg``.

    Raises:
        FileNotFoundError: The reference sample is missing (dangling anchor).
        CloneNotSupportedError: No cloning entry point could be resolved.
    """
    sample = Path(reference_audio_path)
    if not sample.is_file():
        raise FileNotFoundError(
            f"Reference sample not found on the TTS server: {reference_audio_path}. "
            "Pro Studio requires the API and GPU services to share the ./output volume."
        )

    if override_kwarg:
        method_name = override_method or _first_existing_method(model) or "generate"
        prompt_is_tensor = override_kwarg in TENSOR_PROMPT_KWARGS
        kwargs: Dict[str, Any] = {"text": text} if method_name != "inference_zero_shot" else {"tts_text": text}
        declared = accepted_kwargs(model if method_name == "__call__" else getattr(model, method_name, None))
        text_kwarg = _first_present(TEXT_KWARGS, declared)
        if text_kwarg:
            kwargs = {text_kwarg: text}
        kwargs[override_kwarg] = _prompt_value(sample, prompt_is_tensor, load_prompt)
        if reference_text:
            prompt_text_kwarg = _first_present(PROMPT_TEXT_KWARGS, declared) or "prompt_text"
            kwargs[prompt_text_kwarg] = reference_text
        logger.warning(
            "Using operator-provided CLONE_PROMPT_KWARG=%s on %s(); this bypasses signature "
            "verification, so verify the output really is cloned.",
            override_kwarg,
            method_name,
        )
        return CloneInvocation(
            method_name=method_name,
            kwargs=kwargs,
            prompt_kwarg=override_kwarg,
            prompt_is_tensor=prompt_is_tensor,
            explicit_override=True,
        )

    for method_name in CLONE_METHODS:
        method = model if method_name == "__call__" else getattr(model, method_name, None)
        if method is None:
            continue
        declared = accepted_kwargs(method)
        if not declared:
            continue
        prompt_kwarg = _first_present(TENSOR_PROMPT_KWARGS, declared)
        prompt_is_tensor = prompt_kwarg is not None
        if prompt_kwarg is None:
            prompt_kwarg = _first_present(PATH_PROMPT_KWARGS, declared)
        if prompt_kwarg is None:
            continue
        text_kwarg = _first_present(TEXT_KWARGS, declared)
        if text_kwarg is None:
            continue

        kwargs = {
            text_kwarg: text,
            prompt_kwarg: _prompt_value(sample, prompt_is_tensor, load_prompt),
        }
        prompt_text_kwarg = _first_present(PROMPT_TEXT_KWARGS, declared)
        if prompt_text_kwarg is not None:
            # CosyVoice2 requires prompt_text positionally-or-by-keyword; an empty
            # string is valid but degrades similarity, so forward what we have.
            kwargs[prompt_text_kwarg] = reference_text or ""
        if "speed" in declared and speed and speed != 1.0:
            kwargs["speed"] = speed
        return CloneInvocation(
            method_name=method_name,
            kwargs=kwargs,
            prompt_kwarg=prompt_kwarg,
            prompt_is_tensor=prompt_is_tensor,
        )

    raise CloneNotSupportedError(
        "The loaded model build exposes no zero-shot cloning entry point "
        f"(checked {list(CLONE_METHODS)} for one of {list(TENSOR_PROMPT_KWARGS + PATH_PROMPT_KWARGS)}). "
        "Refusing to synthesise a non-cloned voice for a clone request. "
        "Set CLONE_PROMPT_KWARG=<param> if this build accepts a reference sample under "
        "a parameter name we do not know."
    )


def _first_existing_method(model: Any) -> Optional[str]:
    for name in CLONE_METHODS:
        if name == "__call__":
            if callable(model):
                return name
        elif getattr(model, name, None) is not None:
            return name
    return None


def _prompt_value(sample: Path, prompt_is_tensor: bool, load_prompt: Optional[Callable[[str], Any]]) -> Any:
    if not prompt_is_tensor:
        return str(sample)
    if load_prompt is None:
        raise CloneNotSupportedError(
            "Model expects a decoded reference waveform but no loader was provided "
            "(server bug: pass load_prompt=...)."
        )
    return load_prompt(str(sample))


def read_audio_mono(path: str, target_sr: Optional[int] = PROMPT_SAMPLE_RATE) -> Tuple[np.ndarray, int]:
    """Read ``path`` as mono float32, optionally resampled to ``target_sr``."""
    import soundfile as sf

    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    mono = np.asarray(data, dtype=np.float32).mean(axis=1)
    if target_sr and sr != target_sr:
        mono = resample_mono(mono, sr, target_sr)
        sr = target_sr
    return mono, sr


def resample_mono(data: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """Resample a mono signal, preferring scipy's polyphase filter."""
    if orig_sr == target_sr:
        return np.asarray(data, dtype=np.float32)
    try:
        from math import gcd

        from scipy.signal import resample_poly

        divisor = gcd(int(orig_sr), int(target_sr))
        return np.asarray(
            resample_poly(data, int(target_sr) // divisor, int(orig_sr) // divisor),
            dtype=np.float32,
        )
    except Exception:  # pragma: no cover - scipy always present in the GPU images
        # Linear-interpolation fallback: lower quality but never silently wrong SR.
        duration = len(data) / float(orig_sr)
        target_len = max(1, int(round(duration * target_sr)))
        src_idx = np.linspace(0.0, len(data) - 1, num=target_len, dtype=np.float64)
        return np.interp(src_idx, np.arange(len(data)), np.asarray(data, dtype=np.float64)).astype(np.float32)


def normalize_audio_result(result: Any) -> np.ndarray:
    """Normalise a model output into a float32 array shaped ``[channels, samples]``.

    Handles the shapes real TTS builds return: tensors, numpy arrays, dicts keyed by
    ``tts_speech``/``audio``/``waveform``/``audio_path``, generators of such dicts
    (CosyVoice2 streams chunk dicts), and plain file paths.
    """
    array = _to_array(result)
    if array is None:
        raise RuntimeError(f"Model returned no audio (type={type(result).__name__})")
    if array.ndim == 1:
        array = array[np.newaxis, :]
    elif array.ndim == 2 and array.shape[0] > array.shape[1]:
        # [samples, channels] -> [channels, samples]
        array = array.T
    elif array.ndim > 2:
        array = array.reshape(array.shape[0], -1)
    return np.ascontiguousarray(array, dtype=np.float32)


def _to_array(result: Any) -> Optional[np.ndarray]:
    if result is None:
        return None
    # torch.Tensor (duck-typed to avoid importing torch here)
    detach = getattr(result, "detach", None)
    if callable(detach) and hasattr(result, "cpu"):
        return np.asarray(result.detach().cpu().numpy(), dtype=np.float32)
    if isinstance(result, np.ndarray):
        return np.asarray(result, dtype=np.float32)
    if isinstance(result, (str, Path)):
        data, _ = read_audio_mono(str(result), target_sr=None)
        return data
    if isinstance(result, dict):
        for key in ("tts_speech", "audio", "waveform", "speech", "wav"):
            if result.get(key) is not None:
                return _to_array(result[key])
        if result.get("audio_path"):
            return _to_array(result["audio_path"])
        return None
    if isinstance(result, (list, tuple)):
        chunks = [c for c in (_to_array(item) for item in result) if c is not None]
        return _concat_chunks(chunks)
    if hasattr(result, "__iter__"):  # generator / iterator of chunks
        chunks = [c for c in (_to_array(item) for item in result) if c is not None]
        return _concat_chunks(chunks)
    return None


def _concat_chunks(chunks: Sequence[np.ndarray]) -> Optional[np.ndarray]:
    if not chunks:
        return None
    flat = [c.reshape(-1) if c.ndim > 1 else c for c in chunks]
    return np.concatenate(flat).astype(np.float32)


def write_wav(path: str, audio: np.ndarray, sample_rate: int) -> None:
    """Write ``[channels, samples]`` float32 audio to ``path`` as a WAV file."""
    import soundfile as sf

    data = audio.T if audio.ndim == 2 else audio
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, sample_rate)

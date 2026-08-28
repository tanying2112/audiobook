"""Piper TTS model registry & downloader (S2-4).

Reuses the P0-2 model-downloader primitives (``download_file`` /
``verify_model_files`` from :mod:`audiobook_studio.tts.model_downloader`) to fetch
Piper voice models — including the Chinese ``zh_CN-huayan-medium`` family — and
exposes a small registry used by :class:`PiperBackend` and the TTS readiness probe.

Piper ships one ONNX model per voice. Models follow the well-known
``rhasspy/piper-voices`` layout on Hugging Face::

    {lang}/{lang}_{speaker}/{quality}/{lang}_{speaker}-{quality}.onnx
    {lang}/{lang}_{speaker}/{quality}/{lang}_{speaker}-{quality}.onnx.json

e.g. ``zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx``.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .engine import VoiceInfo
from .model_downloader import download_file, verify_model_files

logger = logging.getLogger(__name__)

# Default location mirrors kokoro's convention: <repo-root>/models/piper
PIPER_DEFAULT_MODEL_DIR = Path(__file__).parent.parent.parent / "models" / "piper"

# Base URL for the official Piper voice collection (Hugging Face mirror).
PIPER_VOICES_REPO = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

#: Default voice used when none is specified.
DEFAULT_PIPER_VOICE = "zh_CN-huayan-medium"

# Voice catalogue. ``model`` is the onnx stem (== voice id by convention).
# ``size_mb`` is a soft sanity bound only (tolerance is applied in verify()).
PIPER_VOICE_MODELS: Dict[str, Dict[str, str]] = {
    "zh_CN-huayan-medium": {
        "name": "华婉 (中等)",
        "language": "zh-CN",
        "gender": "female",
        "description": "中文女声 · 自然中等质量 (默认旁白)",
        "speaker": "huayan",
        "quality": "medium",
        "size_mb": 60,
    },
    "zh_CN-huayan-x_low": {
        "name": "华婉 (极轻量)",
        "language": "zh-CN",
        "gender": "female",
        "description": "中文女声 · 极轻量 (CPU 低延迟)",
        "speaker": "huayan",
        "quality": "x_low",
        "size_mb": 12,
    },
    "zh_CN-shaoer-medium": {
        "name": "少儿 (中等)",
        "language": "zh-CN",
        "gender": "neutral",
        "description": "中文少儿/活泼声线",
        "speaker": "shaoer",
        "quality": "medium",
        "size_mb": 60,
    },
    "en_US-lessac-medium": {
        "name": "Lessac (中等, 英)",
        "language": "en-US",
        "gender": "female",
        "description": "English female narrator (fallback)",
        "speaker": "lessac",
        "quality": "medium",
        "size_mb": 60,
    },
    "en_US-libritts-r-medium": {
        "name": "LibriTTS-R (中等, 英)",
        "language": "en-US",
        "gender": "male",
        "description": "English male narrator (fallback)",
        "speaker": "libritts-r",
        "quality": "medium",
        "size_mb": 60,
    },
}


def _voice_url(voice_id: str) -> str:
    """Build the Hugging Face resolve URL for a Piper voice model + its config JSON."""
    info = PIPER_VOICE_MODELS.get(voice_id)
    if info is None:
        # Unknown voice id: treat it as a bare model stem under zh/zh_CN.
        lang = "zh"
        speaker = "zh_CN"
        quality = "medium"
    else:
        # Model path layout: {lang}/{lang}_{speaker}/{quality}/{stem}
        lang = info["language"].split("-")[0].lower()
        speaker = info["speaker"]
        quality = info["quality"]
    return f"{PIPER_VOICES_REPO}/{lang}/{lang}_{speaker}/{quality}/{voice_id}.onnx"


def get_piper_model_path(
    voice_id: str,
    model_dir: Optional[Path] = None,
) -> Tuple[Path, Path]:
    """Resolve the ``.onnx`` and ``.onnx.json`` paths for a Piper voice.

    Returns:
        (model_path, json_path)
    """
    base = Path(model_dir) if model_dir else PIPER_DEFAULT_MODEL_DIR
    model_path = base / f"{voice_id}.onnx"
    json_path = base / f"{voice_id}.onnx.json"
    return model_path, json_path


def build_piper_files_spec(
    voices: Optional[List[str]] = None,
) -> Dict[str, Dict[str, object]]:
    """Build a ``model_downloader``-compatible files spec for the requested voices.

    Each voice contributes the ``.onnx`` model and its ``.onnx.json`` config.
    """
    voices = voices or [DEFAULT_PIPER_VOICE]
    spec: Dict[str, Dict[str, object]] = {}
    for voice_id in voices:
        info = PIPER_VOICE_MODELS.get(voice_id, {})
        # size_mb intentionally left as None: Piper model sizes vary by quality and
        # we only enforce *existence* in verify_model_files (no false size rejections).
        url = _voice_url(voice_id)
        spec[f"{voice_id}.onnx"] = {"url": url, "size_mb": None, "sha256": None}
        spec[f"{voice_id}.onnx.json"] = {
            "url": url + ".json",
            "size_mb": None,  # config JSON is tiny; only existence matters
            "sha256": None,
        }
    return spec


def ensure_piper_models(
    model_dir: Optional[Path] = None,
    voices: Optional[List[str]] = None,
    force: bool = False,
) -> bool:
    """Ensure the requested Piper voice models are downloaded (reuses P0-2 logic).

    Args:
        model_dir: Where to store models (default: ./models/piper under repo root).
        voices: Voice ids to fetch; defaults to the default Chinese voice.
        force: Re-download even if files already exist.

    Returns:
        True if all required files are present and verified.
    """
    target_dir = Path(model_dir) if model_dir else PIPER_DEFAULT_MODEL_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    files_spec = build_piper_files_spec(voices)

    # Skip download if already valid (unless forced).
    valid, issues = verify_model_files(target_dir, files_spec)
    if valid and not force:
        logger.info("All requested Piper models already present and valid.")
        return True
    if issues:
        logger.info(f"Piper model verification issues: {issues}")

    success = True
    for filename, spec in files_spec.items():
        filepath = target_dir / filename
        if filepath.exists() and not force:
            continue
        ok, err = download_file(
            str(spec["url"]),
            filepath,
            spec.get("size_mb"),
        )
        if not ok:
            logger.error(f"Failed to download Piper model file {filename}: {err}")
            success = False

    valid, issues = verify_model_files(target_dir, files_spec)
    if valid:
        logger.info("All requested Piper models downloaded and verified.")
        return True
    logger.error(f"Piper model verification failed after download: {issues}")
    return False


def list_piper_voices(model_dir: Optional[Path] = None) -> List[VoiceInfo]:
    """Return the catalogue of Piper voices as :class:`VoiceInfo`."""
    voices: List[VoiceInfo] = []
    for voice_id, info in PIPER_VOICE_MODELS.items():
        model_path, json_path = get_piper_model_path(voice_id, model_dir)
        # Mark available only if model file exists on disk.
        available = model_path.exists()
        voices.append(
            VoiceInfo(
                voice_id=voice_id,
                name=info["name"],
                language=info["language"],
                gender=info["gender"],
                description=info["description"] + ("" if available else " (模型未下载)"),
                sample_rate=22050,
                supports_prosody=True,
                supports_reference_audio=False,
                engine="piper",
            )
        )
    return voices


def detect_piper_availability(
    binary: Optional[str] = None,
    model_dir: Optional[Path] = None,
) -> Tuple[bool, Dict[str, object]]:
    """Detect whether a real Piper engine is usable on this host.

    Piper is considered *available* only when BOTH a runnable ``piper`` binary
    and at least one ``.onnx`` model file are present. This never falsely
    reports availability (honest degradation — the same rule the S1-6 probe uses
    for Kokoro).

    Returns:
        (available, detail) where ``detail`` explains the verdict.
    """
    import glob

    # Respect the global local-TTS switch (consistent with kokoro in the probe).
    enable_local = os.environ.get("ENABLE_LOCAL_TTS", "true").lower() not in ("false", "0")
    if not enable_local:
        return False, {"reason": "local_tts_disabled", "available": False}

    # 1) Binary detection.
    candidates = []
    if binary:
        candidates.append(binary)
    env_bin = os.environ.get("PIPER_BIN")
    if env_bin:
        candidates.append(env_bin)
    candidates.extend(["piper", "piper-tts"])

    found_bin = None
    for cand in candidates:
        if cand and (Path(cand).exists() or shutil.which(cand)):
            found_bin = cand if Path(cand).exists() else shutil.which(cand)
            break

    if not found_bin:
        return False, {
            "available": False,
            "reason": "binary_not_found",
            "checked": candidates,
        }

    # 2) Model detection.
    env_model = os.environ.get("PIPER_MODEL_PATH")
    mdir = Path(env_model) if env_model else (Path(model_dir) if model_dir else PIPER_DEFAULT_MODEL_DIR)
    models: List[str] = []
    if mdir.exists():
        models = sorted(glob.glob(str(mdir / "*.onnx")))

    if not models:
        return False, {
            "available": False,
            "reason": "model_not_found",
            "binary": found_bin,
            "model_dir": str(mdir),
        }

    return True, {
        "available": True,
        "binary": found_bin,
        "model": models[0],
        "model_count": len(models),
    }

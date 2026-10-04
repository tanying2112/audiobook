"""Storage layer for Audiobook Studio.

Manages the file system layout under ``storage/books/<id>/``.

Directory structure::

    storage/
        books/
            <project_id>/
                raw/            ← original input files (PDF, EPUB, TXT, …)
                extracted/      ← extracted plain text per chapter
                annotated/      ← paragraph-level annotations (JSON)
                audio/          ← generated TTS audio files (per paragraph)
                reports/        ← quality reports (JSON)

Idempotent helpers ensure directories exist on first access.
All paths use ``pathlib.Path`` for cross-platform safety.
"""

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

# Root storage directory (relative to the project root)
_STORAGE_ROOT = Path(__file__).resolve().parent.parent.parent / "storage"

# Subdirectory names (kept as constants for consistency)
_RAW = "raw"
_EXTRACTED = "extracted"
_ANNOTATED = "annotated"
_AUDIO = "audio"
_REPORTS = "reports"

_SUBDIRS = [_RAW, _EXTRACTED, _ANNOTATED, _AUDIO, _REPORTS]


# ── Path helpers ──────────────────────────────────────────────────────────────


def _ensure_dir(path: Path) -> Path:
    """Create directory (and parents) if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_dir(project_id: int, *, ensure: bool = False) -> Path:
    """Return the top-level storage directory for a project.

    Parameters
    ----------
    project_id:
        Numeric project ID.
    ensure:
        If True, create the directory (and all subdirectories) on demand.

    Returns
    -------
    Path to ``storage/books/<project_id>/``.
    """
    path = _STORAGE_ROOT / "books" / str(project_id)
    if ensure:
        _ensure_dir(path)
        for sub in _SUBDIRS:
            _ensure_dir(path / sub)
    return path


def raw_dir(project_id: int, *, ensure: bool = False) -> Path:
    """Storage for original input files per chapter."""
    return _ensure_dir(project_dir(project_id, ensure=ensure) / _RAW)


def extracted_dir(project_id: int, *, ensure: bool = False) -> Path:
    """Storage for extracted plain text per chapter."""
    return _ensure_dir(project_dir(project_id, ensure=ensure) / _EXTRACTED)


def annotated_dir(project_id: int, *, ensure: bool = False) -> Path:
    """Storage for paragraph-level annotation JSON files per chapter."""
    return _ensure_dir(project_dir(project_id, ensure=ensure) / _ANNOTATED)


def audio_dir(project_id: int, *, ensure: bool = False) -> Path:
    """Storage for generated TTS audio files (per paragraph)."""
    return _ensure_dir(project_dir(project_id, ensure=ensure) / _AUDIO)


def reports_dir(project_id: int, *, ensure: bool = False) -> Path:
    """Storage for quality reports / logs."""
    return _ensure_dir(project_dir(project_id, ensure=ensure) / _REPORTS)


# ── File name helpers ─────────────────────────────────────────────────────────


def _chapter_filename(chapter_index: int, suffix: str) -> str:
    """Generate a zero-padded chapter filename, e.g. ``ch_001.txt``."""
    return f"ch_{chapter_index:03d}{suffix}"


def _paragraph_basename(chapter_index: int, paragraph_index: int) -> str:
    """Generate a zero-padded paragraph basename, e.g. ``ch_001_p_042``."""
    return f"ch_{chapter_index:03d}_p_{paragraph_index:03d}"


# ── Raw / Input files ─────────────────────────────────────────────────────────


def save_raw_file(
    project_id: int,
    chapter_index: int,
    content: bytes,
    suffix: str = ".txt",
    *,
    ensure: bool = True,
) -> Path:
    """Write raw input content for a chapter.

    Parameters
    ----------
    project_id:
        Numeric project ID.
    chapter_index:
        1-based chapter index.
    content:
        Binary content to write.
    suffix:
        File extension (e.g. ``.txt``, ``.pdf``, ``.epub``).
    ensure:
        Auto-create directories if they don't exist.

    Returns
    -------
    The written file path.
    """
    dst = raw_dir(project_id, ensure=ensure) / _chapter_filename(chapter_index, suffix)
    dst.write_bytes(content)
    return dst


def raw_file_path(
    project_id: int,
    chapter_index: int,
    suffix: str = ".txt",
) -> Path:
    """Return the expected raw file path (no I/O)."""
    return raw_dir(project_id) / _chapter_filename(chapter_index, suffix)


# ── Extracted text files ──────────────────────────────────────────────────────


def save_extracted_text(
    project_id: int,
    chapter_index: int,
    text: str,
    *,
    ensure: bool = True,
) -> Path:
    """Write extracted plain text for a chapter."""
    dst = extracted_dir(project_id, ensure=ensure) / _chapter_filename(chapter_index, ".txt")
    dst.write_text(text, encoding="utf-8")
    return dst


def load_extracted_text(
    project_id: int,
    chapter_index: int,
) -> Optional[str]:
    """Read previously extracted text, or None if missing."""
    path = extracted_dir(project_id) / _chapter_filename(chapter_index, ".txt")
    return path.read_text(encoding="utf-8") if path.exists() else None


# ── Annotation JSON files ─────────────────────────────────────────────────────


def save_chapter_annotations(
    project_id: int,
    chapter_index: int,
    annotations: List[Dict[str, Any]],
    *,
    ensure: bool = True,
) -> Path:
    """Write paragraph annotations for a chapter as JSON."""
    dst = annotated_dir(project_id, ensure=ensure) / _chapter_filename(chapter_index, ".json")
    dst.write_text(json.dumps(annotations, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def load_chapter_annotations(
    project_id: int,
    chapter_index: int,
) -> Optional[List[Dict[str, Any]]]:
    """Read previously saved annotations, or None if missing."""
    path = annotated_dir(project_id) / _chapter_filename(chapter_index, ".json")
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data if isinstance(data, list) else None


# ── Audio files ───────────────────────────────────────────────────────────────


def audio_file_path(
    project_id: int,
    chapter_index: int,
    paragraph_index: int,
    fmt: str = "mp3",
) -> Path:
    """Return the expected audio file path."""
    return audio_dir(project_id) / f"{_paragraph_basename(chapter_index, paragraph_index)}.{fmt}"


def save_audio(
    project_id: int,
    chapter_index: int,
    paragraph_index: int,
    content: bytes,
    fmt: str = "mp3",
    *,
    ensure: bool = True,
) -> Path:
    """Write a TTS audio segment to disk."""
    dst = audio_file_path(project_id, chapter_index, paragraph_index)
    if ensure:
        dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(content)
    return dst


# ── Report files ──────────────────────────────────────────────────────────────


def save_report(
    project_id: int,
    name: str,
    data: Dict[str, Any],
    *,
    ensure: bool = True,
) -> Path:
    """Write a quality / progress report as JSON.

    Parameters
    ----------
    project_id:
        Numeric project ID.
    name:
        Report name (e.g. ``"quality_summary"``, ``"checkpoint"``).
    data:
        Serializable dictionary.
    ensure:
        Auto-create directories.

    Returns
    -------
    The written file path.
    """
    dst = reports_dir(project_id, ensure=ensure) / f"{name}.json"
    dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return dst


def load_report(
    project_id: int,
    name: str,
) -> Optional[Dict[str, Any]]:
    """Read a previously saved report, or None if missing."""
    path = reports_dir(project_id) / f"{name}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        return data if isinstance(data, dict) else None


# ── Cleanup ───────────────────────────────────────────────────────────────────


def remove_project_storage(project_id: int) -> None:
    """Recursively delete the entire storage directory for a project."""
    path = project_dir(project_id)
    if path.exists():
        shutil.rmtree(path)

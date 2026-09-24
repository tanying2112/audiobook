"""Checkpoint manager — progress snapshots and resume capability.

Saves per-project, per-chapter, per-paragraph checkpoints as JSON files in
``storage/books/<project_id>/reports/checkpoints.json``.

The checkpoint tracks which pipeline stages have been completed for each
chapter and each paragraph, enabling resume from the last successful stage
without reprocessing the entire pipeline.

Stage granularity (ADR-005):
  - Chapter-level stages (``extract``/``analyze``/``review``) are tracked with
    the ``(stage, chapter_index)`` tuple.
  - Paragraph-level stages (``annotate``/``edit``/``audio_postprocess``/
    ``synthesize``/``quality``) are tracked with the
    ``(stage, chapter_index, paragraph_index)`` tuple. Without this per-
    paragraph granularity, completing a paragraph-level stage for paragraph 1
    would mark it done for the whole chapter and cause paragraphs 2..N to be
    silently skipped (see ``storage/books/4/logs/pipe_fix8.log``).

Usage::

    from src.audiobook_studio.pipeline.checkpoint import CheckpointManager

    cp = CheckpointManager(project_id=123)
    # chapter-level stage:
    cp.mark_stage_done("extract", chapter_index=1)
    if cp.is_stage_done("extract", chapter_index=1):
        logger.info("Already extracted, skipping")
    # paragraph-level stage:
    cp.mark_stage_done("annotate", chapter_index=1, paragraph_index=3)
    if cp.is_stage_done("annotate", chapter_index=1, paragraph_index=3):
        logger.info("Paragraph 3 already annotated, skipping)
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, cast

from ..storage import reports_dir

logger = logging.getLogger(__name__)

# Current checkpoint schema version.
CHECKPOINT_VERSION = 3

# Pipeline stages in order (used for resume logic).
STAGE_ORDER = [
    "extract",
    "analyze",
    "annotate",
    "edit",
    "synthesize",
    "quality",
]

# Stages that operate per-paragraph and therefore require paragraph_index in
# checkpoint tracking (ADR-005).
PACKAGE_STAGES = frozenset({"annotate", "edit", "synthesize", "quality"})

# Chapter-level stages tracked with (stage, chapter_index) only.
CHAPTER_STAGES = frozenset({"extract", "analyze", "review"})


class CheckpointManager:
    """Checkpoint manager with file-based persistence."""

    def __init__(self, project_id: int):
        self.project_id = project_id
        self._dirty = False
        self._data: Dict[str, Any] = self._load()

    # ── Internal persistence ───────────────────────────────────────────────

    def _checkpoint_path(self) -> Path:
        return reports_dir(self.project_id, ensure=True) / "checkpoints.json"

    def _load(self) -> Dict[str, Any]:
        path = self._checkpoint_path()
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data: Dict[str, Any] = json.load(f)
                    return self._migrate_to_v3(data)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load checkpoint, starting fresh: %s", e)
        return {
            "project_id": self.project_id,
            "chapters": {},
            "version": CHECKPOINT_VERSION,
        }

    def _migrate_to_v3(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate v2 (and earlier) checkpoint data to the v3 schema.

        v2 ``chapters[c].stages_done`` may erroneously contain paragraph-level
        stage names (``annotate``/``edit``/``audio_postprocess``/
        ``synthesize``/``quality``) because the v2 code tracked per-paragraph
        stages at chapter granularity. Those entries are unreliable --
        completing the stage for paragraph 1 was recorded as if all paragraphs
        were done -- so we drop them during the migration and signal that the
        affected paragraph-level stages need to re-run.

        The new v3 structure lives under ``chapters[c].paragraphs[str(p)].
        stages_done`` for paragraph-level stages and ``chapters[c].stages_done``
        for chapter-level stages (extract/analyze/review).
        """
        version = data.get("version", 2)
        if version >= 3:
            return data

        # v2 → v3 migration: drop paragraph-level stages from chapter-level list,
        # carry forward only chapter-level stages (extract/analyze/review).
        chapters = data.get("chapters", {})
        for _ch_key, ch_data in chapters.items():
            old_stage_list = ch_data.get("stages_done", [])
            # Keep only genuine chapter-level stages; drop the buggy
            # per-paragraph stage entries that v2 mistakenly stored here.
            kept = [s for s in old_stage_list if s in CHAPTER_STAGES]
            ch_data["stages_done"] = kept
            # Introduce the new paragraphs sub-dict (shares paragraph_index keys
            # as strings, matching the JSON convention).
            ch_data.setdefault("paragraphs", {})
            # ``paragraphs_done`` (legacy 1-bit-per-paragraph field) is kept
            # for backward compatibility with the old ``mark_paragraph_done`` /
            # ``are_paragraphs_done`` / ``get_pending_paragraphs`` APIs which
            # some downstream callers still use; per-stage paragraph tracking
            # lives under the new ``paragraphs`` sub-dict.
            # Note: ``paragraphs_done`` was never written by orchestrator in
            # the v2 era (only ``stages_done`` was), so it is usually empty.
        data["version"] = CHECKPOINT_VERSION
        return data

    def _save(self) -> None:
        path = self._checkpoint_path()
        path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self._dirty = False

    def _flush(self) -> None:
        if self._dirty:
            self._save()

    # ── Per-chapter checkpoint data ────────────────────────────────────────

    def _chapter(self, chapter_index: int) -> dict[str, Any]:
        key = str(chapter_index)
        if key not in self._data["chapters"]:
            self._data["chapters"][key] = {
                "stages_done": [],
                "paragraphs_done": [],
                "paragraphs": {},
                "current_stage": None,
            }
            self._dirty = True
        return cast(dict[str, Any], self._data["chapters"][key])

    def _paragraph(self, chapter_index: int, paragraph_index: int) -> dict[str, Any]:
        """Get (or create) the per-paragraph checkpoint sub-dict (ADR-005)."""
        ch = self._chapter(chapter_index)
        p_key = str(paragraph_index)
        paras = cast(dict[str, Any], ch.setdefault("paragraphs", {}))
        if p_key not in paras:
            paras[p_key] = {"stages_done": []}
            self._dirty = True
        return cast(dict[str, Any], paras[p_key])

    # ── Stage tracking ─────────────────────────────────────────────────────

    def is_stage_done(
        self,
        stage: str,
        chapter_index: int,
        paragraph_index: Optional[int] = None,
    ) -> bool:
        """Check if a stage has been completed.

        Granularity is chosen by STAGE TYPE, not by whether ``paragraph_index``
        was supplied (ADR-005): chapter-level stages (``extract``/``analyze``/
        ``review``) are always tracked at chapter granularity, while
        paragraph-level stages (``annotate``/``edit``/``audio_postprocess``/
        ``synthesize``/``quality``) always use the per-paragraph sub-dict. This
        means callers passing ``paragraph_index`` to a chapter-level stage is a
        no-op (the call falls back to the chapter-level lookup).
        """
        if stage in CHAPTER_STAGES or paragraph_index is None:
            return stage in self._chapter(chapter_index).get("stages_done", [])
        p_stages = self._paragraph(chapter_index, paragraph_index).get("stages_done", [])
        return stage in p_stages

    def has_checkpoint(self, stage: str, chapter_index: int = 1) -> bool:
        """Alias for is_stage_done for backward compatibility."""
        return self.is_stage_done(stage, chapter_index)

    def mark_stage_done(
        self,
        stage: str,
        chapter_index: int,
        paragraph_index: Optional[int] = None,
    ) -> None:
        """Mark a pipeline stage as completed.

        Stage type determines storage location (ADR-005): chapter-level stages
        are recorded under ``chapters[c].stages_done`` regardless of whether
        ``paragraph_index`` is given; paragraph-level stages use the
        per-paragraph sub-dict.
        """
        if stage not in CHAPTER_STAGES and paragraph_index is not None:
            p = self._paragraph(chapter_index, paragraph_index)
            p_stages = p.setdefault("stages_done", [])
            if stage not in p_stages:
                p_stages.append(stage)
                self._dirty = True
                self._flush()
                logger.info(
                    "Checkpoint: ch%d p%d stage '%s' completed",
                    chapter_index,
                    paragraph_index,
                    stage,
                )
            return
        ch = self._chapter(chapter_index)
        if stage not in ch["stages_done"]:
            ch["stages_done"].append(stage)
            ch["current_stage"] = None  # clear current when done
            self._dirty = True
            self._flush()
            logger.info("Checkpoint: ch%d stage '%s' completed", chapter_index, stage)

    def mark_stage_started(
        self,
        stage: str,
        chapter_index: int,
        paragraph_index: Optional[int] = None,
    ) -> None:
        """Mark a pipeline stage as in-progress.

        For paragraph-level stages (``paragraph_index`` provided) there is no
        distinct in-progress field per paragraph -- we record progress at the
        chapter-level ``current_stage`` for observability, while the precise
        per-paragraph-per-stage completion is tracked via ``mark_stage_done``.
        """
        ch = self._chapter(chapter_index)
        ch["current_stage"] = stage
        self._dirty = True
        self._flush()

    def get_current_stage(self, chapter_index: int) -> Optional[str]:
        """Get the current in-progress stage for a chapter."""
        return self._chapter(chapter_index).get("current_stage")

    def last_completed_stage(self, chapter_index: int) -> Optional[str]:
        """Return the last completed stage, or None."""
        stages = self._chapter(chapter_index).get("stages_done", [])
        return stages[-1] if stages else None

    # ── Paragraph-level tracking ───────────────────────────────────────────

    def are_paragraphs_done(self, chapter_index: int, paragraph_indices: Set[int]) -> bool:
        """Check if all given paragraphs have been processed."""
        done = set(self._chapter(chapter_index).get("paragraphs_done", []))
        return paragraph_indices.issubset(done)

    def mark_paragraph_done(self, chapter_index: int, paragraph_index: int) -> None:
        """Mark a single paragraph as processed."""
        ch = self._chapter(chapter_index)
        pd_list: List[int] = ch.setdefault("paragraphs_done", [])
        if paragraph_index not in pd_list:
            pd_list.append(paragraph_index)
            self._dirty = True
            self._flush()

    def mark_paragraphs_done(self, chapter_index: int, paragraph_indices: List[int]) -> None:
        """Mark multiple paragraphs as processed (batch)."""
        ch = self._chapter(chapter_index)
        pd_set: Set[int] = set(ch.get("paragraphs_done", []))
        pd_set.update(paragraph_indices)
        ch["paragraphs_done"] = sorted(pd_set)
        self._dirty = True
        self._flush()

    def get_pending_paragraphs(self, chapter_index: int, total: int) -> List[int]:
        """Return 0-based paragraph indices that haven't been processed yet."""
        done = set(self._chapter(chapter_index).get("paragraphs_done", []))
        return [i for i in range(total) if i not in done]

    # ── Resume helpers ─────────────────────────────────────────────────────

    def next_stage(self, chapter_index: int) -> Optional[str]:
        """Return the next stage to run for a chapter, or None if all done."""
        done = set(self._chapter(chapter_index).get("stages_done", []))
        for stage in STAGE_ORDER:
            if stage not in done:
                return stage
        return None

    def stages_to_run(self, chapter_index: int) -> List[str]:
        """Return ordered list of stages still pending for a chapter."""
        done = set(self._chapter(chapter_index).get("stages_done", []))
        return [s for s in STAGE_ORDER if s not in done]

    def resume_from(self, chapter_index: int) -> Optional[str]:
        """Return the stage to resume from (the first incomplete stage)."""
        stage = self.next_stage(chapter_index)
        if stage:
            logger.info(
                "Resume ch%d: next stage is '%s' (done: %s)",
                chapter_index,
                stage,
                self._chapter(chapter_index).get("stages_done", []),
            )
        return stage

    # ── Batch metadata ─────────────────────────────────────────────────────

    def set_metadata(self, key: str, value: Any) -> None:
        """Store arbitrary metadata (e.g. config snapshot)."""
        if "metadata" not in self._data:
            self._data["metadata"] = {}
        self._data["metadata"][key] = value
        self._dirty = True
        self._flush()

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self._data.get("metadata", {}).get(key, default)

    # ── Reset ──────────────────────────────────────────────────────────────

    def reset_chapter(self, chapter_index: int) -> None:
        """Clear all checkpoint data for a chapter."""
        key = str(chapter_index)
        if key in self._data.get("chapters", {}):
            del self._data["chapters"][key]
            self._dirty = True
            self._flush()

    def reset_all(self) -> None:
        """Clear all checkpoints for the project."""
        self._data["chapters"] = {}
        self._dirty = True
        self._flush()

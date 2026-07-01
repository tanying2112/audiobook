"""Checkpoint manager — progress snapshots and resume capability.

Saves per-project, per-chapter checkpoints as JSON files in
``storage/books/<project_id>/reports/checkpoints.json``.

The checkpoint tracks which pipeline stages have been completed and which
paragraph indices have been processed, enabling resume from the last
successful stage without reprocessing the entire pipeline.

Usage::

    from src.audiobook_studio.pipeline.checkpoint import CheckpointManager

    cp = CheckpointManager(project_id=1)
    cp.mark_stage_done("extract", chapter_index=1)
    if cp.is_stage_done("extract", chapter_index=1):
        logger.info("Already extracted, skipping")
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from ..storage import reports_dir

logger = logging.getLogger(__name__)

# Pipeline stages in order (used for resume logic)
STAGE_ORDER = [
    "extract",
    "analyze",
    "annotate",
    "edit",
    "synthesize",
    "quality",
]


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
                    return json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load checkpoint, starting fresh: %s", e)
        return {
            "project_id": self.project_id,
            "chapters": {},
            "version": 2,
        }

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

    def _chapter(self, chapter_index: int) -> Dict[str, Any]:
        key = str(chapter_index)
        if key not in self._data["chapters"]:
            self._data["chapters"][key] = {
                "stages_done": [],
                "paragraphs_done": [],
                "current_stage": None,
            }
            self._dirty = True
        return self._data["chapters"][key]

    # ── Stage tracking ─────────────────────────────────────────────────────

    def is_stage_done(self, stage: str, chapter_index: int) -> bool:
        """Check if a stage has been completed for a chapter."""
        return stage in self._chapter(chapter_index).get("stages_done", [])

    def has_checkpoint(self, stage: str, chapter_index: int = 1) -> bool:
        """Alias for is_stage_done for backward compatibility."""
        return self.is_stage_done(stage, chapter_index)

    def mark_stage_done(self, stage: str, chapter_index: int) -> None:
        """Mark a pipeline stage as completed for a chapter."""
        ch = self._chapter(chapter_index)
        if stage not in ch["stages_done"]:
            ch["stages_done"].append(stage)
            ch["current_stage"] = None  # clear current when done
            self._dirty = True
            self._flush()
            logger.info("Checkpoint: ch%d stage '%s' completed", chapter_index, stage)

    def mark_stage_started(self, stage: str, chapter_index: int) -> None:
        """Mark a pipeline stage as in-progress for a chapter."""
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

    def are_paragraphs_done(
        self, chapter_index: int, paragraph_indices: Set[int]
    ) -> bool:
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

    def mark_paragraphs_done(
        self, chapter_index: int, paragraph_indices: List[int]
    ) -> None:
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

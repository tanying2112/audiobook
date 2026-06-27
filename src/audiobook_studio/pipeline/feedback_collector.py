"""Feedback Collector — captures LLM inputs/outputs at each pipeline stage for self-iteration.

This module provides hooks that wrap each pipeline stage to capture:
- Input snapshot (what was sent to the LLM)
- LLM output (what the LLM returned)
- Corrected output (human/expected correction)
- Rationale (why the correction was made)
- Stage identifier (which pipeline stage)
- Source (human_edit, quality_judge, user_rating)

The collected feedback is saved to storage/books/<project_id>/feedback/raw/
and can be processed by FeedbackProcessor for prompt improvement.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from ..storage import project_dir

logger = logging.getLogger(__name__)


class FeedbackCollector:
    """Collects and persists feedback records for each pipeline stage.

    Usage:
        collector = FeedbackCollector(project_id=1)

        # In each pipeline stage, wrap the LLM call:
        with collector.capture_stage("annotate", chapter_index=1, paragraph_index=5) as capture:
            result = llm_call(input_data)
            capture.set_llm_output(result.model_dump())
            # Later, when human corrects:
            capture.set_corrected_output(corrected_result)
            capture.set_rationale("Fixed emotion detection for dialogue")
    """

    def __init__(self, project_id: int, enable: bool = True):
        self.project_id = project_id
        self.enable = enable
        self._active_captures: Dict[str, "StageCapture"] = {}
        self._feedback_dir = project_dir(project_id, ensure=True) / "feedback" / "raw"
        self._feedback_dir.mkdir(parents=True, exist_ok=True)

    def _generate_feedback_id(self) -> str:
        """Generate unique feedback ID."""
        return f"fb_{uuid.uuid4().hex[:12]}"

    def capture_stage(
        self,
        stage: str,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
        chapter_id: Optional[int] = None,
        paragraph_id: Optional[int] = None,
        input_snapshot: Optional[Dict[str, Any]] = None,
    ) -> "StageCapture":
        """Create a context manager for capturing feedback at a pipeline stage.

        Args:
            stage: Pipeline stage name (extract, analyze, annotate, edit, synthesize, quality)
            chapter_index: 1-based chapter number
            paragraph_index: 1-based paragraph index
            chapter_id: DB chapter ID (optional)
            paragraph_id: DB paragraph ID (optional)
            input_snapshot: Optional input data snapshot (will be captured if not provided)

        Returns:
            StageCapture context manager
        """
        if not self.enable:
            return StageCapture._disabled()

        capture = StageCapture(
            collector=self,
            feedback_id=self._generate_feedback_id(),
            stage=stage,
            project_id=self.project_id,
            chapter_index=chapter_index,
            paragraph_index=paragraph_index,
            chapter_id=chapter_id,
            paragraph_id=paragraph_id,
            input_snapshot=input_snapshot,
        )

        key = f"{stage}_{chapter_index}_{paragraph_index}"
        self._active_captures[key] = capture
        return capture

    def save_feedback(self, capture: "StageCapture") -> Path:
        """Save a completed feedback capture to disk.

        Args:
            capture: StageCapture with llm_output, corrected_output, and rationale set

        Returns:
            Path to saved feedback file
        """
        if not self.enable or capture._disabled:
            return Path("/dev/null")

        # Build the feedback record matching FeedbackRecord schema
        record = {
            "id": capture.feedback_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": capture.source or "human_edit",
            "stage": capture.stage,
            "project_id": self.project_id,
            "chapter_index": capture.chapter_index,
            "paragraph_index": capture.paragraph_index,
            "chapter_id": capture.chapter_id,
            "paragraph_id": capture.paragraph_id,
            "input_snapshot": capture.input_snapshot or {},
            "llm_output": capture.llm_output or {},
            "corrected_output": capture.corrected_output or {},
            "rationale": capture.rationale or "",
            "diff_summary": capture.diff_summary or "",
            "pattern_tags": capture.pattern_tags or [],
            "contract_version": 1,
        }

        # Validate required fields
        if not record["llm_output"]:
            logger.warning("Feedback %s: llm_output is empty", capture.feedback_id)
        if not record["corrected_output"]:
            logger.warning("Feedback %s: corrected_output is empty", capture.feedback_id)
        if not record["rationale"] or len(record["rationale"]) < 10:
            logger.warning("Feedback %s: rationale too short or missing", capture.feedback_id)

        # Save to file
        filename = f"{capture.stage}_{capture.feedback_id}.json"
        filepath = self._feedback_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)

        logger.info("Saved feedback: %s", filepath)
        return filepath

    def load_feedback(self, feedback_id: str) -> Optional[Dict[str, Any]]:
        """Load a feedback record by ID."""
        for filepath in self._feedback_dir.glob(f"*_{feedback_id}.json"):
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def list_feedback(
        self,
        stage: Optional[str] = None,
        chapter_index: Optional[int] = None,
    ) -> list[Dict[str, Any]]:
        """List all feedback records, optionally filtered."""
        results = []
        for filepath in self._feedback_dir.glob("*.json"):
            with open(filepath, "r", encoding="utf-8") as f:
                record = json.load(f)
                if stage and record.get("stage") != stage:
                    continue
                if chapter_index and record.get("chapter_index") != chapter_index:
                    continue
                results.append(record)
        return results


class StageCapture:
    """Context manager for capturing feedback at a single pipeline stage."""

    def __init__(
        self,
        collector: FeedbackCollector,
        feedback_id: str,
        stage: str,
        project_id: int,
        chapter_index: Optional[int] = None,
        paragraph_index: Optional[int] = None,
        chapter_id: Optional[int] = None,
        paragraph_id: Optional[int] = None,
        input_snapshot: Optional[Dict[str, Any]] = None,
    ):
        self.collector = collector
        self.feedback_id = feedback_id
        self.stage = stage
        self.project_id = project_id
        self.chapter_index = chapter_index
        self.paragraph_index = paragraph_index
        self.chapter_id = chapter_id
        self.paragraph_id = paragraph_id
        self.input_snapshot = input_snapshot or {}

        # To be filled by the pipeline stage
        self.llm_output: Optional[Dict[str, Any]] = None
        self.corrected_output: Optional[Dict[str, Any]] = None
        self.rationale: Optional[str] = None
        self.diff_summary: Optional[str] = None
        self.pattern_tags: Optional[list[str]] = None
        self.source: str = "human_edit"
        self._disabled = False

    @classmethod
    def _disabled(cls) -> "StageCapture":
        """Create a no-op disabled capture."""
        capture = cls.__new__(cls)
        capture._disabled = True
        capture.feedback_id = "disabled"
        capture.stage = "disabled"
        capture.project_id = 0
        capture.chapter_index = None
        capture.paragraph_index = None
        capture.chapter_id = None
        capture.paragraph_id = None
        capture.input_snapshot = {}
        capture.llm_output = None
        capture.corrected_output = None
        capture.rationale = None
        capture.diff_summary = None
        capture.pattern_tags = None
        capture.source = "disabled"
        capture.collector = None
        return capture

    def __enter__(self) -> "StageCapture":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        # Auto-save if we have the minimum required data
        if not self._disabled and self.llm_output and self.corrected_output and self.rationale:
            self.collector.save_feedback(self)

    def set_llm_output(self, output: Dict[str, Any]) -> None:
        """Set the LLM's output (required)."""
        self.llm_output = output

    def set_corrected_output(self, output: Dict[str, Any]) -> None:
        """Set the human-corrected/expected output (required)."""
        self.corrected_output = output

    def set_rationale(self, rationale: str) -> None:
        """Set the correction rationale (required, min 10 chars)."""
        self.rationale = rationale

    def set_diff_summary(self, summary: str) -> None:
        """Set optional diff summary (auto-generated by diff agent)."""
        self.diff_summary = summary

    def set_pattern_tags(self, tags: list[str]) -> None:
        """Set optional pattern tags (auto-generated by feedback processor)."""
        self.pattern_tags = tags

    def set_source(self, source: str) -> None:
        """Set feedback source (human_edit, quality_judge, user_rating)."""
        if source in ("human_edit", "quality_judge", "user_rating"):
            self.source = source
        else:
            logger.warning("Unknown feedback source: %s, defaulting to human_edit", source)
            self.source = "human_edit"

    def set_input_snapshot(self, snapshot: Dict[str, Any]) -> None:
        """Update input snapshot (can be called after initial creation)."""
        self.input_snapshot = snapshot


def create_feedback_collector(project_id: int, enable: bool = True) -> FeedbackCollector:
    """Factory function to create a FeedbackCollector."""
    return FeedbackCollector(project_id=project_id, enable=enable)
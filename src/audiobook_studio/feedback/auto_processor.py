"""
Auto-trigger module for FeedbackProcessor.

This module provides automatic triggering of feedback analysis when:
1. Feedback threshold is reached (configurable count)
2. Scheduled periodic analysis (cron job)
3. Manual trigger via CLI/API

It integrates with the FeedbackCollector's file-based storage and
the existing processor.py for batch analysis.
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import FeedbackRecord as FeedbackRecordModel
from ..storage import project_dir
from .collector import list_unprocessed_feedback, mark_feedback_processed
from .processor import AggregateAnalysis, analyze_batch

logger = logging.getLogger(__name__)


class FeedbackAutoProcessor:
    """Automatically triggers feedback analysis based on configurable rules."""

    def __init__(
        self,
        db_session_factory,
        project_id: int,
        min_feedback_count: int = 10,
        check_interval_seconds: int = 300,  # 5 minutes
        enable_auto_trigger: bool = True,
    ):
        """
        Initialize the auto processor.

        Args:
            db_session_factory: Callable that returns a new SQLAlchemy Session
            project_id: Project ID to monitor
            min_feedback_count: Minimum feedback records to trigger analysis
            check_interval_seconds: How often to check for new feedback
            enable_auto_trigger: Whether to enable automatic triggering
        """
        self.db_session_factory = db_session_factory
        self.project_id = project_id
        self.min_feedback_count = min_feedback_count
        self.check_interval_seconds = check_interval_seconds
        self.enable_auto_trigger = enable_auto_trigger

        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._last_analysis_count = 0
        self._feedback_dir = project_dir(project_id, ensure=True) / "feedback" / "raw"

    def start(self) -> None:
        """Start the background monitoring thread."""
        if not self.enable_auto_trigger:
            logger.info("Auto-trigger disabled, not starting worker")
            return

        if self._worker_thread and self._worker_thread.is_alive():
            logger.warning("Worker already running")
            return

        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._worker_thread.start()
        logger.info(
            f"FeedbackAutoProcessor started for project {self.project_id}: "
            f"check_interval={self.check_interval_seconds}s, threshold={self.min_feedback_count}"
        )

    def stop(self) -> None:
        """Stop the background monitoring thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            self._stop_event.set()
            self._worker_thread.join(timeout=10)
            logger.info("FeedbackAutoProcessor stopped")

    def _worker_thread_alive(self) -> bool:
        return self._worker_thread is not None and self._worker_thread.is_alive()

    def _monitor_loop(self) -> None:
        """Background loop that checks for feedback threshold."""
        while not self._stop_event.is_set():
            try:
                self._check_and_trigger()
            except Exception as e:
                logger.error(f"Error in feedback monitor loop: {e}")

            # Wait for next check or stop signal
            self._stop_event.wait(self.check_interval_seconds)

    def _check_and_trigger(self) -> None:
        """Check if feedback threshold is reached and trigger analysis."""
        # Count unprocessed feedback in database
        db = self.db_session_factory()
        try:
            unprocessed = list_unprocessed_feedback(
                db, project_id=self.project_id, limit=10000
            )
            count = len(unprocessed)

            if count >= self.min_feedback_count and count != self._last_analysis_count:
                logger.info(
                    f"Feedback threshold reached: {count} unprocessed records "
                    f"(threshold={self.min_feedback_count})"
                )
                self._trigger_analysis(db)
                self._last_analysis_count = count
        finally:
            db.close()

    def _trigger_analysis(self, db: Session) -> Optional[AggregateAnalysis]:
        """Run batch analysis on unprocessed feedback."""
        try:
            logger.info(f"Triggering batch analysis for project {self.project_id}")
            result = analyze_batch(db, project_id=self.project_id, limit=1000)
            logger.info(
                f"Batch analysis complete: {result.total_analyzed} records, "
                f"{len(result.pattern_frequency)} patterns"
            )

            # Save analysis report
            self._save_analysis_report(result)

            return result
        except Exception as e:
            logger.error(f"Batch analysis failed: {e}")
            return None

    def _save_analysis_report(self, analysis: AggregateAnalysis) -> Path:
        """Save analysis report to feedback/analysis/ directory."""
        analysis_dir = self._feedback_dir.parent / "analysis"
        analysis_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"analysis_{timestamp}.json"
        filepath = analysis_dir / filename

        report = {
            "project_id": self.project_id,
            "total_analyzed": analysis.total_analyzed,
            "pattern_frequency": analysis.pattern_frequency,
            "stage_distribution": analysis.stage_distribution,
            "top_patterns": analysis.top_patterns,
            "recommendations": analysis.recommendations,
            "generated_at": analysis.generated_at,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved analysis report: {filepath}")
        return filepath

    def trigger_now(self) -> Optional[AggregateAnalysis]:
        """Manually trigger analysis (for CLI/API use)."""
        db = self.db_session_factory()
        try:
            return self._trigger_analysis(db)
        finally:
            db.close()

    def get_status(self) -> Dict[str, Any]:
        """Get current status of the auto processor."""
        db = self.db_session_factory()
        try:
            unprocessed = list_unprocessed_feedback(
                db, project_id=self.project_id, limit=10000
            )
            return {
                "project_id": self.project_id,
                "running": self._worker_thread_alive(),
                "enable_auto_trigger": self.enable_auto_trigger,
                "min_feedback_count": self.min_feedback_count,
                "check_interval_seconds": self.check_interval_seconds,
                "unprocessed_feedback_count": len(unprocessed),
                "last_analysis_count": self._last_analysis_count,
                "next_check_in_seconds": (
                    self.check_interval_seconds
                    if self._worker_thread_alive()
                    else None
                ),
            }
        finally:
            db.close()


def create_auto_processor(
    db_session_factory,
    project_id: int,
    min_feedback_count: int = 10,
    check_interval_seconds: int = 300,
    enable_auto_trigger: bool = True,
) -> FeedbackAutoProcessor:
    """Factory function to create FeedbackAutoProcessor."""
    return FeedbackAutoProcessor(
        db_session_factory=db_session_factory,
        project_id=project_id,
        min_feedback_count=min_feedback_count,
        check_interval_seconds=check_interval_seconds,
        enable_auto_trigger=enable_auto_trigger,
    )


# ── CLI integration ─────────────────────────────────────────────────────────────


def run_feedback_analysis_cli(
    db_session_factory,
    project_id: int,
    limit: int = 500,
) -> AggregateAnalysis:
    """CLI entry point for manual feedback analysis trigger."""
    db = db_session_factory()
    try:
        logger.info(f"Running manual feedback analysis for project {project_id}")
        result = analyze_batch(db, project_id=project_id, limit=limit)
        logger.info(
            f"Analysis complete: {result.total_analyzed} records processed, "
            f"{len(result.recommendations)} recommendations"
        )
        for rec in result.recommendations:
            logger.info(f"  - {rec}")
        return result
    finally:
        db.close()
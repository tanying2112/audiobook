"""Progress emitter for WebSocket real-time updates.

This module provides a clean interface for emitting pipeline progress events
to WebSocket clients. It integrates with the orchestrator's hook system.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..api.websocket import PipelineEventType, emit_pipeline_event, manager

logger = logging.getLogger(__name__)


class ProgressEmitter:
    """Emits pipeline progress events via WebSocket."""

    def __init__(self):
        self._stage_progress: Dict[str, Dict[str, Any]] = {}

    def _build_base_context(
        self,
        project_id: int,
        chapter_index: Optional[int] = None,
        chapter_id: Optional[int] = None,
        paragraph_index: Optional[int] = None,
        paragraph_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Build base context for all events."""
        return {
            "project_id": project_id,
            "chapter_index": chapter_index,
            "chapter_id": chapter_id,
            "paragraph_index": paragraph_index,
            "paragraph_id": paragraph_id,
        }

    async def emit_stage_enter(
        self,
        stage: str,
        project_id: int,
        chapter_index: Optional[int] = None,
        chapter_id: Optional[int] = None,
        paragraph_index: Optional[int] = None,
        paragraph_id: Optional[int] = None,
        total_items: Optional[int] = None,
    ):
        """Emit stage enter event."""
        context = self._build_base_context(
            project_id, chapter_index, chapter_id, paragraph_index, paragraph_id
        )
        if total_items is not None:
            context["total_items"] = total_items

        # Track progress for this stage
        key = f"{project_id}:{chapter_index}:{stage}"
        self._stage_progress[key] = {
            "current": 0,
            "total": total_items or 0,
            "stage": stage,
        }

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_ENTER,
            stage=stage,
            chapter_index=chapter_index,
            chapter_id=chapter_id,
            paragraph_index=paragraph_index,
            progress=0.0,
            data=context,
        )
        logger.info(f"[WS] Stage ENTER: {stage} for project {project_id}")

    async def emit_stage_progress(
        self,
        stage: str,
        project_id: int,
        chapter_index: Optional[int] = None,
        chapter_id: Optional[int] = None,
        paragraph_index: Optional[int] = None,
        current: int = 0,
        total: Optional[int] = None,
        message: Optional[str] = None,
    ):
        """Emit stage progress update."""
        key = f"{project_id}:{chapter_index}:{stage}"
        if key in self._stage_progress:
            self._stage_progress[key]["current"] = current
            if total is not None:
                self._stage_progress[key]["total"] = total

        progress = 0.0
        if total and total > 0:
            progress = min(current / total, 1.0)

        data = self._build_base_context(
            project_id, chapter_index, chapter_id, paragraph_index
        )
        data.update({"current": current, "total": total or 0, "message": message})

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_PROGRESS,
            stage=stage,
            chapter_index=chapter_index,
            chapter_id=chapter_id,
            paragraph_index=paragraph_index,
            progress=progress,
            data=data,
        )

    async def emit_stage_exit(
        self,
        stage: str,
        project_id: int,
        chapter_index: Optional[int] = None,
        chapter_id: Optional[int] = None,
        paragraph_index: Optional[int] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ):
        """Emit stage exit event."""
        key = f"{project_id}:{chapter_index}:{stage}"
        if key in self._stage_progress:
            del self._stage_progress[key]

        data = self._build_base_context(
            project_id, chapter_index, chapter_id, paragraph_index
        )
        if not success:
            data["error"] = error_message

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_EXIT,
            stage=stage,
            chapter_index=chapter_index,
            chapter_id=chapter_id,
            paragraph_index=paragraph_index,
            progress=1.0 if success else 0.0,
            data=data,
        )
        logger.info(f"[WS] Stage EXIT: {stage} for project {project_id} {'OK' if success else 'FAILED'}")

    async def emit_chapter_complete(
        self,
        project_id: int,
        chapter_index: int,
        chapter_id: Optional[int] = None,
        total_chapters: Optional[int] = None,
    ):
        """Emit chapter completion event."""
        progress = 1.0
        if total_chapters and total_chapters > 0:
            progress = chapter_index / total_chapters

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.CHAPTER_COMPLETE,
            stage="pipeline",
            chapter_index=chapter_index,
            chapter_id=chapter_id,
            progress=progress,
            data={"total_chapters": total_chapters, "completed_chapter": chapter_index},
        )
        logger.info(f"[WS] Chapter COMPLETE: ch{chapter_index} for project {project_id}")

    async def emit_paragraph_complete(
        self,
        project_id: int,
        chapter_index: int,
        paragraph_index: int,
        total_paragraphs: Optional[int] = None,
    ):
        """Emit paragraph completion event."""
        progress = 1.0
        if total_paragraphs and total_paragraphs > 0:
            progress = paragraph_index / total_paragraphs

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.PARAGRAPH_COMPLETE,
            stage="synthesize",
            chapter_index=chapter_index,
            paragraph_index=paragraph_index,
            progress=progress,
            data={"total_paragraphs": total_paragraphs},
        )

    async def emit_error(
        self,
        project_id: int,
        stage: str,
        error_message: str,
        chapter_index: Optional[int] = None,
        chapter_id: Optional[int] = None,
        paragraph_index: Optional[int] = None,
    ):
        """Emit error event."""
        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.ERROR,
            stage=stage,
            chapter_index=chapter_index,
            chapter_id=chapter_id,
            paragraph_index=paragraph_index,
            data={"message": error_message},
        )
        logger.error(f"[WS] ERROR: {stage} for project {project_id}: {error_message}")

    async def emit_pipeline_completed(
        self,
        project_id: int,
        total_chapters: Optional[int] = None,
    ):
        """Emit pipeline completion event."""
        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.COMPLETED,
            stage="pipeline",
            progress=1.0,
            data={"total_chapters": total_chapters},
        )
        logger.info(f"[WS] Pipeline COMPLETED for project {project_id}")

    async def emit_pipeline_paused(
        self,
        project_id: int,
    ):
        """Emit pipeline paused event."""
        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.PAUSED,
            stage="pipeline",
            data={},
        )

    async def emit_pipeline_resumed(
        self,
        project_id: int,
    ):
        """Emit pipeline resumed event."""
        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.RESUMED,
            stage="pipeline",
            data={},
        )


# Global emitter instance
progress_emitter = ProgressEmitter()


# Convenience functions for backward compatibility / easy import
async def emit_stage_enter(
    stage: str,
    project_id: int,
    chapter_index: Optional[int] = None,
    chapter_id: Optional[int] = None,
    paragraph_index: Optional[int] = None,
    paragraph_id: Optional[int] = None,
    total_items: Optional[int] = None,
):
    """Emit stage enter event."""
    await progress_emitter.emit_stage_enter(
        stage, project_id, chapter_index, chapter_id, paragraph_index, paragraph_id, total_items
    )


async def emit_stage_progress(
    stage: str,
    project_id: int,
    chapter_index: Optional[int] = None,
    chapter_id: Optional[int] = None,
    paragraph_index: Optional[int] = None,
    current: int = 0,
    total: Optional[int] = None,
    message: Optional[str] = None,
):
    """Emit stage progress update."""
    await progress_emitter.emit_stage_progress(
        stage, project_id, chapter_index, chapter_id, paragraph_index, current, total, message
    )


async def emit_stage_exit(
    stage: str,
    project_id: int,
    chapter_index: Optional[int] = None,
    chapter_id: Optional[int] = None,
    paragraph_index: Optional[int] = None,
    success: bool = True,
    error_message: Optional[str] = None,
):
    """Emit stage exit event."""
    await progress_emitter.emit_stage_exit(
        stage, project_id, chapter_index, chapter_id, paragraph_index, success, error_message
    )


async def emit_chapter_complete(
    project_id: int,
    chapter_index: int,
    chapter_id: Optional[int] = None,
    total_chapters: Optional[int] = None,
):
    """Emit chapter completion event."""
    await progress_emitter.emit_chapter_complete(
        project_id, chapter_index, chapter_id, total_chapters
    )


async def emit_paragraph_complete(
    project_id: int,
    chapter_index: int,
    paragraph_index: int,
    total_paragraphs: Optional[int] = None,
):
    """Emit paragraph completion event."""
    await progress_emitter.emit_paragraph_complete(
        project_id, chapter_index, paragraph_index, total_paragraphs
    )


async def emit_error(
    project_id: int,
    stage: str,
    error_message: str,
    chapter_index: Optional[int] = None,
    chapter_id: Optional[int] = None,
    paragraph_index: Optional[int] = None,
):
    """Emit error event."""
    await progress_emitter.emit_error(
        project_id, stage, error_message, chapter_index, chapter_id, paragraph_index
    )


async def emit_pipeline_completed(
    project_id: int,
    total_chapters: Optional[int] = None,
):
    """Emit pipeline completion event."""
    await progress_emitter.emit_pipeline_completed(project_id, total_chapters)


async def emit_pipeline_paused(project_id: int):
    """Emit pipeline paused event."""
    await progress_emitter.emit_pipeline_paused(project_id)


async def emit_pipeline_resumed(project_id: int):
    """Emit pipeline resumed event."""
    await progress_emitter.emit_pipeline_resumed(project_id)


"""
Celery tasks for batch export operations.

Provides async export execution with progress tracking via Celery states.
"""

import logging
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from celery import states as celery_states

PENDING = celery_states.PENDING
STARTED = celery_states.STARTED
SUCCESS = celery_states.SUCCESS
FAILURE = celery_states.FAILURE
RETRY = celery_states.RETRY

from ..celery_app import celery_app
from ..export import ExportFormat, ExportJob, ExportProgress, export_project
from ..export.batch_exporter import (
    _build_chapter_markers,
    _build_project_metadata,
    _build_subtitle_entries,
    _collect_audio_files,
    _collect_chapter_data,
)
from ..export.m4b import ChapterMarker, M4bMetadata, build_m4b
from ..export.srt import SubtitleConfig, SubtitleEntry, generate_srt
from ..models import AudioSegment, Chapter, Paragraph, Project
from ..utils.gc_manager import cleanup_after_export

logger = logging.getLogger(__name__)


async def _run_export_async(project_id: int, job: ExportJob, db_session=None) -> ExportJob:
    """Run export asynchronously against the real 3-arg ``export_project``.

    ``export_project(project_id, session, job)`` writes progress onto the job
    object itself (batch_exporter.py:254) and has **no** progress-callback
    parameter. Sprint L's ``progress_callback`` plumbing called it with a
    phantom 4th arg → ``TypeError`` on every task → retry×3 → FAILURE.
    ``db_session`` is kept (defaulting to ``None``) as the Celery task-context
    injection point — the caller ``export_project_async`` is ``bind=True`` and
    passes ``self`` — so progress reporting can be re-added without touching
    the call site.
    """
    from ..database import AsyncSessionLocal

    if db_session is None:
        async with AsyncSessionLocal() as db:
            return await export_project(project_id, db, job)
    else:
        return await export_project(project_id, db_session, job)


@celery_app.task(
    bind=True,
    name="src.audiobook_studio.tasks.export_tasks.export_project_async",
    max_retries=3,
    default_retry_delay=60,
)
def export_project_async(self, project_id: int, job_config: Dict[str, Any], db_session_factory=None) -> Dict[str, Any]:
    """
    Async task to export a full project.

    Args:
        project_id: Project ID to export
        job_config: ExportJob configuration as dict
        db_session_factory: Optional DB session factory (for testing)

    Returns:
        Dict with task_id, status, output_paths, error
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Starting export for project {project_id}")

    try:
        # Parse job config
        formats = set()
        for f in job_config.get("formats", ["m4b_srt"]):
            try:
                formats.add(ExportFormat(f.lower()))
            except ValueError:
                logger.warning(f"Unknown format {f}, skipping")

        # Build subtitle config
        subtitle_config = None
        if job_config.get("max_chars_per_line"):
            from ..export.srt import SubtitleConfig

            subtitle_config = SubtitleConfig(
                max_chars_per_line=job_config["max_chars_per_line"],
            )

        # Build mix config
        mix_config = None
        if job_config.get("mix_config"):
            from ..export.audio_ducking import MixConfig

            mix_config = MixConfig(**job_config["mix_config"])

        job = ExportJob(
            project_id=project_id,
            chapter_ids=job_config.get("chapter_ids"),
            formats=formats or {ExportFormat.M4B_SRT},
            bgm_path=job_config.get("bgm_path"),
            include_cover=job_config.get("include_cover", True),
            cover_image=job_config.get("cover_image"),
            normalize=job_config.get("normalize", True),
            subtitle_config=subtitle_config,
            mix_config=mix_config,
            output_dir=job_config.get("output_dir"),
        )

        # Run export with progress tracking
        import asyncio

        result_job = asyncio.run(_run_export_async(project_id, job))

        # Build response
        response = {
            "task_id": task_id,
            "status": result_job.progress.value,
            "output_paths": result_job.output_paths,
            "error": result_job.error,
            "project_id": project_id,
        }

        logger.info(f"[{task_id}] Export completed: {result_job.progress.value}")

        # GC: Clean up temporary segment files after successful export
        if result_job.progress == ExportProgress.COMPLETE:
            try:
                gc_result = cleanup_after_export(project_id, keep_final=True)
                logger.info(
                    f"[{task_id}] GC cleanup: freed {gc_result['freed_bytes']/1024/1024:.2f} MB, deleted {len(gc_result['deleted_files'])} files"
                )
                response["gc_cleanup"] = gc_result
            except Exception as gc_err:
                logger.warning(f"[{task_id}] GC cleanup failed (non-fatal): {gc_err}")
                response["gc_cleanup_error"] = str(gc_err)

        return response

    except Exception as e:
        logger.exception(f"[{task_id}] Export failed: {e}")
        # Retry on transient errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "project_id": project_id,
        }


@celery_app.task(
    bind=True,
    name="src.audiobook_studio.tasks.export_tasks.export_chapter_async",
    max_retries=3,
    default_retry_delay=30,
)
def export_chapter_async(self, project_id: int, chapter_id: int, output_dir: Optional[str] = None) -> Dict[str, Any]:
    """
    Async task to export a single chapter.

    Args:
        project_id: Project ID
        chapter_id: Chapter ID to export
        output_dir: Optional output directory

    Returns:
        Dict with task_id, status, output_path, error
    """
    task_id = self.request.id
    logger.info(f"[{task_id}] Starting chapter export for project {project_id}, chapter {chapter_id}")

    try:
        from ..database import AsyncSessionLocal
        from ..export.batch_exporter import export_chapter

        async def _run():
            async with AsyncSessionLocal() as db:
                return await export_chapter(project_id, chapter_id, db, output_dir)

        import asyncio

        result_path = asyncio.run(_run())

        if result_path:
            response = {
                "task_id": task_id,
                "status": "complete",
                "output_path": result_path,
                "error": None,
            }
        else:
            response = {
                "task_id": task_id,
                "status": "failed",
                "error": "Chapter not found or has no audio segments",
                "output_path": None,
            }

        logger.info(f"[{task_id}] Chapter export completed: {response['status']}")
        return response

    except Exception as e:
        logger.exception(f"[{task_id}] Chapter export failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "output_path": None,
        }


@celery_app.task(name="src.audiobook_studio.tasks.export_tasks.get_export_status")
def get_export_status(task_id: str) -> Dict[str, Any]:
    """
    Get the status of an export task by Celery task ID.

    Args:
        task_id: Celery task ID

    Returns:
        Dict with task_id, state, info (progress meta)
    """
    result = celery_app.AsyncResult(task_id)

    response = {
        "task_id": task_id,
        "state": result.state,
        "info": result.info or {},
    }

    # Map Celery states to our export progress
    state_map = {
        PENDING: "pending",
        STARTED: "processing",
        SUCCESS: "complete",
        FAILURE: "failed",
        RETRY: "retrying",
    }

    response["progress"] = state_map.get(result.state, result.state.lower())

    if isinstance(result.info, dict):
        response["message"] = result.info.get("message", "")
        response["current_stage"] = result.info.get("current_stage", "")
        if "output_paths" in result.info:
            response["output_paths"] = result.info["output_paths"]
        if "error" in result.info:
            response["error"] = result.info["error"]

    if result.state == FAILURE:
        response["error"] = (
            str(result.info) if not isinstance(result.info, dict) else result.info.get("error", "Unknown error")
        )

    return response

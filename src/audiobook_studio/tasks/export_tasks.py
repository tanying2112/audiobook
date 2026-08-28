"""
Celery tasks for batch export operations.

Provides async export execution with progress tracking via Celery states.
"""

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Union

from celery import Celery as CeleryApp
from celery import Task
from celery import states as celery_states

if TYPE_CHECKING:
    from celery import Task as CeleryTask

PENDING = celery_states.PENDING
STARTED = celery_states.STARTED
SUCCESS = celery_states.SUCCESS
FAILURE = celery_states.FAILURE
RETRY = celery_states.RETRY

from ..celery_app import celery_app  # noqa: E402
from ..database import AsyncSessionLocal  # noqa: E402
from ..export import ExportFormat, ExportJob, ExportProgress, export_project  # noqa: E402
from ..export.audio_ducking import MixConfig  # noqa: E402
from ..export.srt import SubtitleConfig  # noqa: E402
from ..utils.gc_manager import cleanup_after_export  # noqa: E402

logger = logging.getLogger(__name__)


def _typed_task(*args: Any, **kwargs: Any) -> Callable[[Callable[..., Dict[str, Any]]], Callable[..., Dict[str, Any]]]:
    """Type-safe wrapper for celery_app.task decorator."""
    return celery_app.task(*args, **kwargs)  # type: ignore


async def _run_export_async(
    project_id: int, job: ExportJob, db_session: Union[AsyncSessionLocal, None] = None
) -> ExportJob:
    """Run export asynchronously against the real 3-arg ``export_project``.

    ``export_project(project_id, session, job)`` writes progress onto the job
    object itself (batch_exporter.py:254) and has **no** progress-callback
    parameter. Sprint L's ``progress_callback`` plumbing called it with a
    phantom 4th arg -> ``TypeError`` on every task -> retry×3 -> FAILURE.
    ``db_session`` is kept (defaulting to ``None``) as the Celery task-context
    injection point -- the caller ``export_project_async`` is ``bind=True`` and
    passes ``self`` -- so progress reporting can be re-added without touching
    the call site.
    """
    if db_session is None:
        async with AsyncSessionLocal() as db:
            return await export_project(project_id, db, job)  # type: ignore
    else:
        return await export_project(project_id, db_session, job)  # type: ignore


def _get_task_result_dict(
    task: Union[Task, "CeleryTask"],
    task_id: str,
    project_id: int,
    status: str,
    output_paths: Optional[Dict[str, str]] = None,
    error: Optional[str] = None,
    **extras: Any,
) -> Dict[str, Any]:
    """Build a standard task result dictionary."""
    result: Dict[str, Any] = {
        "task_id": task_id,
        "status": status,
        "project_id": project_id,
    }
    if output_paths is not None:
        result["output_paths"] = output_paths
    if error is not None:
        result["error"] = error
    result.update(extras)
    return result


@_typed_task(
    bind=True,
    name="src.audiobook_studio.tasks.export_tasks.export_project_async",
    max_retries=3,
    default_retry_delay=60,
)
def export_project_async(
    self: "CeleryTask",
    project_id: int,
    job_config: Dict[str, Any],
    db_session_factory: Optional[Callable[[], AsyncSessionLocal]] = None,
) -> Dict[str, Any]:
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
        formats: set[ExportFormat] = set()
        for f in job_config.get("formats", ["m4b_srt"]):
            try:
                formats.add(ExportFormat(f.lower()))
            except ValueError:
                logger.warning(f"Unknown format {f}, skipping")

        # Build subtitle config
        subtitle_config: Optional[SubtitleConfig] = None
        if job_config.get("max_chars_per_line"):
            subtitle_config = SubtitleConfig(
                max_chars_per_line=job_config["max_chars_per_line"],
            )

        # Build mix config
        mix_config: Optional[MixConfig] = None
        if job_config.get("mix_config"):
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
        result_job = asyncio.run(_run_export_async(project_id, job))

        # Build response
        response = _get_task_result_dict(
            self,
            task_id,
            project_id,
            result_job.progress.value,
            output_paths=result_job.output_paths,
            error=result_job.error,
        )

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
        return _get_task_result_dict(self, task_id, project_id, "failed", error=str(e))


@_typed_task(
    bind=True,
    name="src.audiobook_studio.tasks.export_tasks.export_chapter_async",
    max_retries=3,
    default_retry_delay=30,
)
def export_chapter_async(
    self: "CeleryTask",
    project_id: int,
    chapter_id: int,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
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
        from ..export.batch_exporter import export_chapter

        async def _run() -> Optional[str]:
            async with AsyncSessionLocal() as db:
                return await export_chapter(project_id, chapter_id, db, output_dir)  # type: ignore

        result_path = asyncio.run(_run())

        if result_path:
            response = _get_task_result_dict(self, task_id, project_id, "complete", output_path=result_path)
        else:
            response = _get_task_result_dict(
                self,
                task_id,
                project_id,
                "failed",
                error="Chapter not found or has no audio segments",
                output_path=None,
            )

        logger.info(f"[{task_id}] Chapter export completed: {response['status']}")
        return response

    except Exception as e:
        logger.exception(f"[{task_id}] Chapter export failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return _get_task_result_dict(self, task_id, project_id, "failed", error=str(e), output_path=None)


@celery_app.task(name="src.audiobook_studio.tasks.export_tasks.get_export_status")  # type: ignore
def get_export_status(task_id: str) -> Dict[str, Any]:
    """
    Get the status of an export task by Celery task ID.

    Args:
        task_id: Celery task ID

    Returns:
        Dict with task_id, state, info (progress meta)
    """
    from celery.result import AsyncResult

    result: AsyncResult = celery_app.AsyncResult(task_id)

    response: Dict[str, Any] = {
        "task_id": task_id,
        "state": result.state,
        "info": result.info or {},
    }

    # Map Celery states to our export progress
    state_map: Dict[str, str] = {
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

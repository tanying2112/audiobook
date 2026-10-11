"""
D4 — FastAPI 导出路由 (async SQLAlchemy 2.0)

提供 REST API：
- POST /api/projects/{id}/export — 发起批量导出 (异步 Celery 任务)
- GET /api/projects/{id}/export/status — 查看导出状态
- GET /api/export/tasks/{task_id}/status — 通用任务状态查询
- GET /api/projects/{project_id}/export/files — 列出导出产物
- GET /api/projects/{project_id}/export/download?path=<filename> — 下载导出文件
"""

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Set

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..export import ExportFormat
from ..models import Project
from ..tasks.export_tasks import export_chapter_async, export_project_async, get_export_status
from .dependencies import get_async_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/export", tags=["export"])

# In-process export job registry: task_id → {status, output_paths, error,
# project_id, chapter_count}. Tracks fallback jobs run without a Celery worker
# and makes the status endpoint real (previously a hardcoded "no_export" stub,
# audit finding).
_export_jobs: dict = {}
_project_latest_export: dict = {}


def _celery_worker_available() -> bool:
    """True when at least one Celery worker responds to an inspect ping."""
    try:
        from ..tasks.celery_app import celery_app

        insp = celery_app.control.inspect(timeout=0.5)
        return bool(insp.ping())
    except Exception as e:
        logger.info(f"Celery worker probe failed, using in-process export: {e}")
        return False


async def _run_export_fallback(task_id: str, project_id: int, job_config: dict) -> None:
    """Run the export in-process (no Celery worker) and track its status.

    Mirrors the parsing in tasks/export_tasks.export_project_async and calls
    the same sync 3-arg ``export_project`` in a worker thread.
    """
    from ..database import SessionLocal
    from ..export.audio_ducking import MixConfig
    from ..export.batch_exporter import ExportJob, export_project
    from ..export.srt import SubtitleConfig

    _export_jobs[task_id]["status"] = "running"
    try:
        formats: set[ExportFormat] = set()
        for f in job_config.get("formats") or ["m4b_srt"]:
            try:
                formats.add(ExportFormat(f.lower()))
            except ValueError:
                logger.warning(f"Unknown format {f}, skipping")
        if not formats:
            formats = {ExportFormat.M4B_SRT}

        subtitle_config = None
        if job_config.get("max_chars_per_line"):
            subtitle_config = SubtitleConfig(max_chars_per_line=job_config["max_chars_per_line"])
        mix_config = MixConfig(**job_config["mix_config"]) if job_config.get("mix_config") else None

        job = ExportJob(
            project_id=project_id,
            chapter_ids=job_config.get("chapter_ids"),
            formats=formats,
            bgm_path=job_config.get("bgm_path"),
            include_cover=job_config.get("include_cover", True),
            cover_image=job_config.get("cover_image"),
            normalize=job_config.get("normalize", True),
            subtitle_config=subtitle_config,
            mix_config=mix_config,
            output_dir=job_config.get("output_dir"),
        )

        def _run_sync():
            with SessionLocal() as db:
                return export_project(project_id, db, job)

        import asyncio as _asyncio

        result_job = await _asyncio.to_thread(_run_sync)
        _export_jobs[task_id]["status"] = "complete" if result_job.error is None else "failed"
        _export_jobs[task_id]["output_paths"] = dict(result_job.output_paths)
        _export_jobs[task_id]["error"] = result_job.error
        logger.info(f"In-process export {task_id} finished: {_export_jobs[task_id]['status']}")
    except Exception as e:
        logger.exception(f"In-process export {task_id} failed: {e}")
        _export_jobs[task_id]["status"] = "failed"
        _export_jobs[task_id]["error"] = str(e)


# ── Pydantic schemas ──────────────────────────────────────────────────────


class ExportRequest(BaseModel):
    """导出请求."""

    chapter_ids: Optional[List[int]] = None  # None = 全部章节
    formats: List[str] = ["m4b_srt"]  # m4b, srt, vtt, m4b_srt, all
    bgm_path: Optional[str] = None
    include_cover: bool = True
    cover_image: Optional[str] = None
    normalize: bool = True
    max_chars_per_line: Optional[int] = 40
    output_dir: Optional[str] = None
    mix_config: Optional[dict[str, Any]] = None


class ExportStatusOut(BaseModel):
    """导出状态."""

    status: str
    output_paths: dict = {}
    error: Optional[str] = None
    chapter_count: int = 0
    task_id: Optional[str] = None


class FormatInfo(BaseModel):
    """支持的格式."""

    value: str
    label: str
    description: str


class TaskStatusOut(BaseModel):
    """Celery 任务状态."""

    task_id: str
    state: str
    progress: str
    message: str = ""
    current_stage: str = ""
    output_paths: dict = {}
    error: Optional[str] = None


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("/", response_model=List[FormatInfo])
async def list_export_formats(
    project_id: int,
):
    """列出支持的导出格式."""
    return [
        FormatInfo(
            value="m4b",
            label="M4B (Audiobook)",
            description="含章节标记的 AAC/M4B 格式，兼容 Apple Books",
        ),
        FormatInfo(
            value="srt",
            label="SRT 字幕",
            description="SubRip 字幕格式，含说话人标记",
        ),
        FormatInfo(
            value="vtt",
            label="WebVTT 字幕",
            description="Web Video Text Tracks 格式",
        ),
        FormatInfo(
            value="m4b_srt",
            label="M4B + SRT",
            description="同时导出有声书和字幕",
        ),
        FormatInfo(
            value="all",
            label="全部格式 (含 ZIP 包)",
            description="M4B + SRT/VTT + ZIP 压缩包",
        ),
    ]


@router.post("/", response_model=ExportStatusOut, status_code=status.HTTP_202_ACCEPTED)
async def start_export(
    project_id: int,
    payload: ExportRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """启动项目导出任务 (异步).

    触发 Celery 任务，立即返回 task_id，前端可轮询 /api/export/tasks/{task_id}/status
    """
    # Validate project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Parse formats
    format_set: Set[ExportFormat] = set()
    for f in payload.formats:
        try:
            format_set.add(ExportFormat(f.lower()))
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported format: {f}. Supported: m4b, srt, vtt, m4b_srt, all",
            )

    # Build subtitle config
    if payload.max_chars_per_line:
        from ..export.srt import SubtitleConfig

        SubtitleConfig(
            max_chars_per_line=payload.max_chars_per_line,
        )

    # Build mix config
    if payload.mix_config:
        from ..export.audio_ducking import MixConfig

        MixConfig(**payload.mix_config)

    # Create job config for Celery task
    job_config = {
        "formats": [f.value for f in format_set],
        "chapter_ids": payload.chapter_ids,
        "bgm_path": payload.bgm_path,
        "include_cover": payload.include_cover,
        "cover_image": payload.cover_image,
        "normalize": payload.normalize,
        "max_chars_per_line": payload.max_chars_per_line,
        "output_dir": payload.output_dir,
        "mix_config": payload.mix_config,
    }

    # Submit async task. When no Celery worker is reachable (default config:
    # Redis down or no worker process), fall back to an in-process background
    # export so the API path actually produces files instead of queueing a
    # task that stays PENDING forever (audit finding).
    if _celery_worker_available():
        task = export_project_async.delay(project_id, job_config)
        task_id = task.id
        logger.info(f"Export task queued: {task_id} for project {project_id}")
        _export_jobs[task_id] = {
            "status": "queued",
            "output_paths": {},
            "error": None,
            "project_id": project_id,
            "chapter_count": len(payload.chapter_ids) if payload.chapter_ids else 0,
            "celery": True,
        }
        _project_latest_export[project_id] = task_id
        return ExportStatusOut(
            status="queued",
            task_id=task_id,
            chapter_count=len(payload.chapter_ids) if payload.chapter_ids else 0,
        )

    task_id = str(uuid.uuid4())
    _export_jobs[task_id] = {
        "status": "queued",
        "output_paths": {},
        "error": None,
        "project_id": project_id,
        "chapter_count": len(payload.chapter_ids) if payload.chapter_ids else 0,
        "celery": False,
    }
    _project_latest_export[project_id] = task_id
    background_tasks.add_task(_run_export_fallback, task_id, project_id, job_config)
    logger.info(f"Export task started in-process (no Celery worker): {task_id} for project {project_id}")

    return ExportStatusOut(
        status="queued",
        task_id=task_id,
        chapter_count=len(payload.chapter_ids) if payload.chapter_ids else 0,
    )


@router.get("/status", response_model=ExportStatusOut)
async def get_export_status_endpoint(
    project_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """查看项目的导出状态 (基于最新任务).

    Reads the in-process export registry (real status, audit finding: the old
    endpoint returned a hardcoded "no_export" stub regardless of actual
    exports). Celery tasks are also registered here when they are queued.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    latest_task_id = _project_latest_export.get(project_id)
    if not latest_task_id:
        return ExportStatusOut(
            status="no_export",
            chapter_count=0,
        )

    job = _export_jobs.get(latest_task_id, {})
    return ExportStatusOut(
        status=job.get("status", "unknown"),
        output_paths=job.get("output_paths", {}),
        error=job.get("error"),
        chapter_count=job.get("chapter_count", 0),
        task_id=latest_task_id,
    )


@router.post("/chapter/{chapter_id}", response_model=ExportStatusOut, status_code=status.HTTP_202_ACCEPTED)
async def export_single_chapter(
    project_id: int,
    chapter_id: int,
    output_dir: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_async_db),
):
    """导出一个章节为独立的 M4B 文件 (异步)."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Submit async task
    task = export_chapter_async.delay(project_id, chapter_id, output_dir)

    logger.info(f"Chapter export task queued: {task.id} for project {project_id}, chapter {chapter_id}")

    return ExportStatusOut(
        status="queued",
        task_id=task.id,
        chapter_count=1,
    )


# ── Export artifacts listing + download (P0 HTTP download closure) ──────────


class ExportFileInfo(BaseModel):
    """单个导出产物的元数据."""

    filename: str
    format: str
    size_bytes: int
    # ISO 8601 modification time. Emitted as a datetime (not an epoch float)
    # because the app-wide ISOTimestampMiddleware rewrites any numeric >1e9
    # in JSON responses to an ISO string — sending datetime keeps the wire
    # format predictable either way.
    mtime: datetime
    # Relative path under the project export root (for ?path= on download)
    rel_path: str


class ExportFilesOut(BaseModel):
    project_id: int
    export_dir: str
    files: List[ExportFileInfo] = []


def _export_root_for_project(project_id: int, db_project: Optional[Project] = None) -> Path:
    """Resolve the project export root directory.

    Priority:
    1. The latest in-process export job's recorded output_dir (explicit request
       output_dir, if any, is baked into the recorded paths).
    2. Default convention ``output/project_{id}`` (same as
       ``batch_exporter.export_project`` fallback).

    The returned Path is absolute and does not need to exist.
    """
    latest_task_id = _project_latest_export.get(project_id)
    if latest_task_id:
        job = _export_jobs.get(latest_task_id, {})
        for p in job.get("output_paths", {}).values():
            if isinstance(p, str) and p:
                candidate = Path(p)
                if not candidate.is_dir():
                    candidate = candidate.parent
                return candidate.resolve()
    return Path(f"./output/project_{project_id}").resolve()


def _resolve_export_file(project_id: int, requested_path: str) -> Optional[Path]:
    """Safely resolve a download path under the project export root.

    Returns the resolved absolute path when it exists, is a file, and lies
    strictly inside the project export root (no ``..`` traversal, no symlink
    escape). Returns ``None`` otherwise.

    Pure function (no I/O beyond ``resolve()``), so the traversal guard is
    directly unit-testable.
    """
    root = _export_root_for_project(project_id)
    if not requested_path:
        return None

    # Reject obvious traversal attempts before touching the filesystem.
    candidate = (root / requested_path).resolve()
    if not candidate.is_relative_to(root):
        return None
    if candidate == root:
        return None
    if not candidate.is_file():
        return None
    return candidate


@router.get("/files", response_model=ExportFilesOut)
async def list_export_files(
    project_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """列出该项目最近一次导出的产物文件.

    Scans the export root (latest job's output_dir, or ``output/project_{id}``
    by convention) for known artifact extensions. Only files are listed (no
    directories such as ``mp3_chapters``/``mastered_audio`` are recursed).
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    root = _export_root_for_project(project_id, project)
    files: List[ExportFileInfo] = []
    if root.is_dir():
        for entry in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if not entry.is_file():
                continue
            try:
                stat = entry.stat()
            except OSError:
                continue
            files.append(
                ExportFileInfo(
                    filename=entry.name,
                    format=entry.suffix.lstrip(".") or "bin",
                    size_bytes=stat.st_size,
                    mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                    rel_path=entry.name,
                )
            )
    return ExportFilesOut(project_id=project_id, export_dir=str(root), files=files)


@router.get("/download")
async def download_export_file(
    project_id: int,
    path: str = Query(..., description="Filename relative to the project export root"),
    db: AsyncSession = Depends(get_async_db),
):
    """下载一个导出产物文件.

    The path is resolved against the project export root and must stay inside
    it (traversal attempts → 404). Responds with ``Content-Disposition:
    attachment`` so browsers save the file instead of navigating to it.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    resolved = _resolve_export_file(project_id, path)
    if resolved is None:
        raise HTTPException(status_code=404, detail="Export file not found")

    media_type = "application/octet-stream"
    suffix = resolved.suffix.lower()
    media_map = {
        ".m4b": "audio/m4b",
        ".mp3": "audio/mpeg",
        ".srt": "application/x-subrip",
        ".vtt": "text/vtt",
        ".txt": "text/plain",
        ".zip": "application/zip",
        ".wav": "audio/wav",
        ".m4a": "audio/mp4",
    }
    media_type = media_map.get(suffix, "application/octet-stream")

    return FileResponse(
        path=str(resolved),
        media_type=media_type,
        filename=resolved.name,
        content_disposition_type="attachment",
    )


# ── Global export task status endpoint (not project-scoped) ───────────────

export_tasks_router = APIRouter(prefix="/export/tasks", tags=["export-tasks"])


@export_tasks_router.get("/{task_id}/status", response_model=TaskStatusOut)
def get_task_status(task_id: str):
    """查询任意导出任务的 Celery 状态."""
    # get_export_status only reads celery_app.AsyncResult(task_id) locally;
    # call it synchronously rather than dispatching a Celery task. It isn't in
    # celery_app.task_routes → a .delay().get(timeout=10) routed to the
    # unconsumed default queue → timed out → HTTP 500. Sync call runs the body
    # (a local AsyncResult read) in-process — no broker, no timeout.
    result = get_export_status(task_id)
    return TaskStatusOut(**result)


# Export the router
__all__ = ["router", "export_tasks_router"]

"""
D4 — FastAPI 导出路由

提供 REST API：
- POST /api/projects/{id}/export — 发起批量导出 (异步 Celery 任务)
- GET /api/projects/{id}/export/status — 查看导出状态
- GET /api/export/tasks/{task_id}/status — 通用任务状态查询
"""

import logging
from pathlib import Path
from typing import List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..celery_app import celery_app
from ..export import ExportFormat, ExportJob, ExportProgress
from ..models import Project
from ..tasks.export_tasks import export_chapter_async, export_project_async, get_export_status
from .dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/export", tags=["export"])


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
    mix_config: Optional[dict] = None


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
def list_export_formats(
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
def start_export(
    project_id: int,
    payload: ExportRequest,
    db: Session = Depends(get_db),
):
    """启动项目导出任务 (异步).

    触发 Celery 任务，立即返回 task_id，前端可轮询 /api/export/tasks/{task_id}/status
    """
    # Validate project exists
    project = db.query(Project).filter_by(id=project_id).first()
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
    subtitle_config = None
    if payload.max_chars_per_line:
        from ..export.srt import SubtitleConfig

        subtitle_config = SubtitleConfig(
            max_chars_per_line=payload.max_chars_per_line,
        )

    # Build mix config
    mix_config = None
    if payload.mix_config:
        from ..export.audio_ducking import MixConfig

        mix_config = MixConfig(**payload.mix_config)

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

    # Submit async task
    task = export_project_async.delay(project_id, job_config)

    logger.info(f"Export task queued: {task.id} for project {project_id}")

    return ExportStatusOut(
        status="queued",
        task_id=task.id,
        chapter_count=len(payload.chapter_ids) if payload.chapter_ids else 0,
    )


@router.get("/status", response_model=ExportStatusOut)
def get_export_status_endpoint(
    project_id: int,
    db: Session = Depends(get_db),
):
    """查看项目的导出状态 (基于最新任务)."""
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # In production, query DB for latest export task
    # For now, return no_export status
    return ExportStatusOut(
        status="no_export",
        chapter_count=0,
    )


@router.post("/chapter/{chapter_id}", response_model=ExportStatusOut, status_code=status.HTTP_202_ACCEPTED)
def export_single_chapter(
    project_id: int,
    chapter_id: int,
    output_dir: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """导出一个章节为独立的 M4B 文件 (异步)."""
    project = db.query(Project).filter_by(id=project_id).first()
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

"""
D4 — FastAPI 导出路由

提供 REST API：
- POST /api/projects/{id}/export — 发起批量导出
- GET /api/projects/{id}/export — 查看导出状态
"""

import logging
from enum import Enum
from pathlib import Path
from typing import List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..export import (
    ExportFormat,
    ExportJob,
    ExportProgress,
    export_project,
)
from ..models import Project
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


class ExportStatusOut(BaseModel):
    """导出状态."""
    status: str
    output_paths: dict = {}
    error: Optional[str] = None
    chapter_count: int = 0


class FormatInfo(BaseModel):
    """支持的格式."""
    value: str
    label: str
    description: str


# ── In-memory job store (ephemeral; for MVP only) ─────────────────────────
_export_jobs: dict[str, ExportJob] = {}


# ── Routes ────────────────────────────────────────────────────────────────


@router.get("/", response_model=List[FormatInfo])
def list_export_formats():
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
    """启动项目导出任务.

    异步执行导出，返回任务状态。最终产物保存在服务端输出目录。
    支持格式: m4b, srt, vtt, m4b_srt, all.
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

    # Create and run export job
    job = ExportJob(
        project_id=project_id,
        chapter_ids=payload.chapter_ids,
        formats=format_set,
        bgm_path=payload.bgm_path,
        include_cover=payload.include_cover,
        cover_image=payload.cover_image,
        normalize=payload.normalize,
        subtitle_config=subtitle_config,
        output_dir=payload.output_dir,
    )

    # Execute synchronously for now (blocking in background worker)
    # TODO: migrate to Celery / BackgroundTasks for long-running exports
    try:
        job = export_project(project_id, db, job)
    except Exception as e:
        logger.exception(f"Export failed: {e}")
        job.progress = ExportProgress.FAILED
        job.error = str(e)

    status_str = job.progress.value
    if job.progress == ExportProgress.COMPLETE:
        http_status = status.HTTP_200_OK
    elif job.progress == ExportProgress.FAILED:
        http_status = status.HTTP_500_INTERNAL_SERVER_ERROR
    else:
        http_status = status.HTTP_202_ACCEPTED

    return ExportStatusOut(
        status=status_str,
        output_paths=job.output_paths,
        error=job.error,
        chapter_count=len(payload.chapter_ids) if payload.chapter_ids else 0,
    )


@router.get("/status", response_model=ExportStatusOut)
def get_export_status(
    project_id: int,
    db: Session = Depends(get_db),
):
    """查看最后的导出状态."""
    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # In-memory — in production, persist jobs to DB
    job_key = str(project_id)
    job = _export_jobs.get(job_key)

    if not job:
        return ExportStatusOut(
            status="no_export",
            chapter_count=0,
        )

    return ExportStatusOut(
        status=job.progress.value,
        output_paths=job.output_paths,
        error=job.error,
        chapter_count=0,
    )


@router.post("/chapter/{chapter_id}", status_code=status.HTTP_200_OK)
def export_single_chapter(
    project_id: int,
    chapter_id: int,
    output_dir: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """导出一个章节为独立的 M4B 文件."""
    from ..export.batch_exporter import export_chapter

    project = db.query(Project).filter_by(id=project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result_path = export_chapter(
        project_id=project_id,
        chapter_id=chapter_id,
        session=db,
        output_dir=output_dir,
    )

    if not result_path:
        raise HTTPException(
            status_code=404,
            detail="Chapter not found or has no audio segments",
        )

    return {"path": result_path, "download_url": f"/api/export/download/{Path(result_path).name}"}

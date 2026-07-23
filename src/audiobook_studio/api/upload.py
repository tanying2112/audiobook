"""File Upload API for Audiobook Studio.

Provides endpoints for uploading source files (PDF, EPUB, DOCX, TXT, PNG, JPG, TIFF, BMP, WebP)
with async text extraction and WebSocket progress updates.

Uses Redis for distributed upload sessions and extraction job tracking.
"""

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.dependencies import get_async_db
from ..api.websocket import PipelineEventType, emit_pipeline_event, manager
from ..auth.dependencies import get_current_active_user, require_project_permission
from ..auth.models import RoleName
from ..database import get_async_session
from ..models import Chapter, Project, ProjectSegment
from ..models.user import User
from ..pipeline.extract import extract_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["upload"])

# Configuration
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "100")) * 1024 * 1024  # 100MB default

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
UPLOAD_TTL = int(os.getenv("UPLOAD_TTL", "86400"))  # 24 hours default

# Allowed MIME types
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/epub+zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
    "image/png",
    "image/jpeg",
    "image/jpg",
    "image/tiff",
    "image/bmp",
    "image/webp",
}

ALLOWED_EXTENSIONS = {".pdf", ".epub", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


# ── Request/Response Models ────────────────────────────────────────────────


class UploadInitResponse(BaseModel):
    """Response for upload initialization."""

    upload_id: str
    project_id: int
    filename: str
    file_size: int
    mime_type: str
    status: str = "initialized"
    message: str = "Upload initialized. Start upload with PUT /upload/{upload_id}/chunk"


class UploadChunkRequest(BaseModel):
    """Request for uploading a chunk."""

    upload_id: str
    chunk_index: int
    total_chunks: int
    is_final: bool = False


class UploadCompleteResponse(BaseModel):
    """Response when upload is complete."""

    upload_id: str
    project_id: int
    file_path: str
    file_size: int
    mime_type: str
    status: str = "uploaded"
    extraction_job_id: Optional[str] = None
    message: str = "File uploaded successfully. Extraction started."


class ExtractionJobStatus(BaseModel):
    """Status of an extraction job."""

    job_id: str
    project_id: int
    upload_id: str
    status: str  # pending, running, completed, failed
    progress: float = 0.0
    current_step: str = ""
    extracted_chapters: int = 0
    total_chapters: int = 0
    error: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None


class ExtractionResultResponse(BaseModel):
    """Final extraction result."""

    job_id: str
    project_id: int
    status: str
    chapters_created: int
    total_paragraphs: int
    language: str
    page_count: int
    has_ocr: bool
    ocr_page_ratio: float
    warnings: List[str] = []
    processing_time_seconds: float


# ── Redis Connection Pool ──────────────────────────────────────────────────


import redis.asyncio as redis

_redis_pool: Optional[redis.ConnectionPool] = None
_redis_client: Optional[redis.Redis] = None


async def get_redis() -> redis.Redis:
    """Get or create Redis client with connection pool."""
    global _redis_pool, _redis_client
    if _redis_client is None:
        _redis_pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True, max_connections=20)
        _redis_client = redis.Redis(connection_pool=_redis_pool)
    return _redis_client


async def close_redis():
    """Close Redis connections."""
    global _redis_pool, _redis_client
    if _redis_client:
        await _redis_client.close()
    if _redis_pool:
        await _redis_pool.disconnect()
    _redis_client = None
    _redis_pool = None


# ── Redis Keys ───────────────────────────────────────────────────────────────


def upload_key(upload_id: str) -> str:
    return f"upload:{upload_id}"


def upload_chunks_key(upload_id: str) -> str:
    return f"upload:{upload_id}:chunks"


def extraction_job_key(job_id: str) -> str:
    return f"extraction:{job_id}"


def project_uploads_key(project_id: int) -> str:
    return f"project:{project_id}:uploads"


def project_extractions_key(project_id: int) -> str:
    return f"project:{project_id}:extractions"


# ── Helper Functions ─────────────────────────────────────────────────────────


def validate_file(file: UploadFile) -> None:
    """Validate uploaded file."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type {ext} not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"MIME type {file.content_type} not allowed")


async def save_upload_chunk(
    redis_client: redis.Redis, upload_id: str, chunk: bytes, chunk_index: int, total_chunks: int
) -> None:
    """Save a chunk to the temporary file at the correct offset."""
    session_key = upload_key(upload_id)
    session_data = await redis_client.hgetall(session_key)

    if not session_data:
        raise HTTPException(status_code=404, detail="Upload session not found")

    file_path = session_data["file_path"]
    chunk_size = int(session_data.get("chunk_size", len(chunk)))

    # Calculate offset for this chunk
    offset = chunk_index * chunk_size

    # Write chunk at correct position
    with open(file_path, "r+b") as f:
        f.seek(offset)
        f.write(chunk)

    # Track received chunks
    await redis_client.sadd(upload_chunks_key(upload_id), chunk_index)

    # Update chunks received count
    await redis_client.hincrby(session_key, "chunks_received", 1)
    await redis_client.expire(session_key, UPLOAD_TTL)
    await redis_client.expire(upload_chunks_key(upload_id), UPLOAD_TTL)


async def finalize_upload(redis_client: redis.Redis, upload_id: str) -> str:
    """Finalize upload and return file path."""
    session_key = upload_key(upload_id)
    session_data = await redis_client.hgetall(session_key)

    if not session_data:
        raise HTTPException(status_code=404, detail="Upload session not found")

    # Verify all chunks received
    chunks_received = int(session_data.get("chunks_received", 0))
    total_chunks = int(session_data.get("total_chunks", 0))

    if chunks_received != total_chunks:
        raise HTTPException(status_code=400, detail="Not all chunks received")

    return session_data["file_path"]


async def create_upload_session(
    redis_client: redis.Redis,
    project_id: int,
    filename: str,
    file_size: int,
    mime_type: str,
    user_id: int,
) -> tuple[str, Path]:
    """Create a new upload session in Redis."""
    upload_id = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{upload_id}_{filename}"

    # Create empty file
    file_path.touch()

    # Calculate optimal chunk size for offset calculation
    chunk_size = 1024 * 1024  # 1MB chunks
    total_chunks = (file_size + chunk_size - 1) // chunk_size

    session_data = {
        "project_id": str(project_id),
        "filename": filename,
        "file_size": str(file_size),
        "mime_type": mime_type,
        "file_path": str(file_path),
        "chunks_received": "0",
        "total_chunks": str(total_chunks),
        "chunk_size": str(chunk_size),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "user_id": str(user_id),
        "status": "initialized",
    }

    await redis_client.hset(upload_key(upload_id), mapping=session_data)
    await redis_client.expire(upload_key(upload_id), UPLOAD_TTL)

    # Track upload in project index
    await redis_client.sadd(project_uploads_key(project_id), upload_id)

    logger.info(f"Upload initialized: {upload_id} for project {project_id} ({total_chunks} chunks)")

    return upload_id, file_path


async def get_upload_session(redis_client: redis.Redis, upload_id: str) -> Optional[Dict[str, str]]:
    """Get upload session from Redis."""
    return await redis_client.hgetall(upload_key(upload_id))


async def delete_upload_session(redis_client: redis.Redis, upload_id: str) -> None:
    """Delete upload session and temp file."""
    session_data = await get_upload_session(redis_client, upload_id)
    if session_data:
        # Delete temp file
        file_path = Path(session_data.get("file_path", ""))
        if file_path.exists():
            file_path.unlink()

        # Get project_id before deleting
        project_id = session_data.get("project_id")
        if project_id:
            await redis_client.srem(project_uploads_key(int(project_id)), upload_id)

        # Delete session and chunks
        await redis_client.delete(upload_key(upload_id))
        await redis_client.delete(upload_chunks_key(upload_id))


async def create_extraction_job(
    redis_client: redis.Redis,
    project_id: int,
    upload_id: str,
    file_path: str,
    mime_type: str,
) -> str:
    """Create an extraction job in Redis."""
    job_id = str(uuid.uuid4())

    job_data = {
        "job_id": job_id,
        "project_id": str(project_id),
        "upload_id": upload_id,
        "file_path": file_path,
        "mime_type": mime_type,
        "status": "pending",
        "progress": "0.0",
        "current_step": "initializing",
        "extracted_chapters": "0",
        "total_chapters": "0",
        "error": "",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": "",
    }

    await redis_client.hset(extraction_job_key(job_id), mapping=job_data)
    await redis_client.expire(extraction_job_key(job_id), UPLOAD_TTL)

    # Track extraction in project index
    await redis_client.sadd(project_extractions_key(project_id), job_id)

    return job_id


async def get_extraction_job(redis_client: redis.Redis, job_id: str) -> Optional[Dict[str, str]]:
    """Get extraction job from Redis."""
    return await redis_client.hgetall(extraction_job_key(job_id))


async def update_extraction_job(
    redis_client: redis.Redis,
    job_id: str,
    **updates,
) -> None:
    """Update extraction job fields."""
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    if "status" in updates and updates["status"] in ("completed", "failed"):
        updates["completed_at"] = datetime.now(timezone.utc).isoformat()
    await redis_client.hset(extraction_job_key(job_id), mapping=updates)


async def list_project_extractions(redis_client: redis.Redis, project_id: int) -> List[ExtractionJobStatus]:
    """List all extraction jobs for a project."""
    job_ids = await redis_client.smembers(project_extractions_key(project_id))
    jobs = []
    for job_id in job_ids:
        job_data = await get_extraction_job(redis_client, job_id)
        if job_data:
            jobs.append(ExtractionJobStatus(**job_data))
    return sorted(jobs, key=lambda x: x.created_at, reverse=True)


# ── API Endpoints ──────────────────────────────────────────────────────────


@router.post("/{project_id}/upload/init", response_model=UploadInitResponse)
async def init_upload(
    project_id: int,
    filename: str = Form(...),
    file_size: int = Form(...),
    mime_type: str = Form(...),
    current_user: User = Depends(require_project_permission(RoleName.EDITOR)),
    db: AsyncSession = Depends(get_async_db),
):
    """Initialize a multipart upload session."""
    # Verify project exists and user has access
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate file type
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type {ext} not allowed. Allowed: {', '.join(ALLOWED_EXTENSIONS)}",
        )

    if mime_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail=f"MIME type {mime_type} not allowed")

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail=f"File too large. Max size: {MAX_FILE_SIZE} bytes")

    # Create upload session in Redis
    redis_client = await get_redis()
    upload_id, file_path = await create_upload_session(
        redis_client, project_id, filename, file_size, mime_type, current_user.id
    )

    return UploadInitResponse(
        upload_id=upload_id,
        project_id=project_id,
        filename=filename,
        file_size=file_size,
        mime_type=mime_type,
    )


@router.post("/{project_id}/upload/{upload_id}/chunk")
async def upload_chunk(
    project_id: int,
    upload_id: str,
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    is_final: bool = Form(False),
    file: UploadFile = File(...),
    current_user: User = Depends(require_project_permission(RoleName.EDITOR)),
    db: AsyncSession = Depends(get_async_db),
):
    """Upload a file chunk."""
    redis_client = await get_redis()

    session = await get_upload_session(redis_client, upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    if session["project_id"] != str(project_id):
        raise HTTPException(status_code=400, detail="Project ID mismatch")

    # Verify total_chunks matches
    if int(session.get("total_chunks", 0)) != total_chunks:
        raise HTTPException(status_code=400, detail="Total chunks mismatch")

    # Read chunk data
    chunk_data = await file.read()

    # Save chunk at correct offset
    await save_upload_chunk(redis_client, upload_id, chunk_data, chunk_index, total_chunks)

    # Update progress
    chunks_received = int(await redis_client.scard(upload_chunks_key(upload_id)))
    progress = chunks_received / total_chunks * 100

    # Emit WebSocket progress
    await emit_pipeline_event(
        project_id=project_id,
        event_type=PipelineEventType.STAGE_PROGRESS,
        stage="upload",
        progress=progress / 100,
        data={
            "upload_id": upload_id,
            "chunk_index": chunk_index,
            "total_chunks": total_chunks,
            "progress": progress,
        },
    )

    if is_final:
        # Finalize upload
        file_path = await finalize_upload(redis_client, upload_id)

        # Update session status
        await redis_client.hset(upload_key(upload_id), "status", "uploaded")
        await redis_client.hset(upload_key(upload_id), "completed_at", datetime.now(timezone.utc).isoformat())

        # Start extraction job
        job_id = await create_extraction_job(redis_client, project_id, upload_id, file_path, session["mime_type"])

        return UploadCompleteResponse(
            upload_id=upload_id,
            project_id=project_id,
            file_path=file_path,
            file_size=int(session["file_size"]),
            mime_type=session["mime_type"],
            extraction_job_id=job_id,
        )

    return {
        "status": "chunk_received",
        "chunk_index": chunk_index,
        "progress": progress,
    }


@router.post("/{project_id}/upload", response_model=UploadCompleteResponse)
async def upload_file(
    project_id: int,
    file: UploadFile = File(...),
    current_user: User = Depends(require_project_permission(RoleName.EDITOR)),
    db: AsyncSession = Depends(get_async_db),
):
    """Simple single-request file upload (for smaller files)."""
    # Verify project
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    validate_file(file)

    # Read file content
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File too large")

    # Save file
    upload_id = str(uuid.uuid4())
    filename = file.filename or "unknown"
    file_path = UPLOAD_DIR / f"{upload_id}_{filename}"

    with open(file_path, "wb") as f:
        f.write(content)

    logger.info(f"File uploaded: {file_path} ({len(content)} bytes)")

    # Start extraction in background
    redis_client = await get_redis()
    job_id = await create_extraction_job(
        redis_client,
        project_id,
        upload_id,
        str(file_path),
        file.content_type or "application/octet-stream",
    )

    return UploadCompleteResponse(
        upload_id=upload_id,
        project_id=project_id,
        file_path=str(file_path),
        file_size=len(content),
        mime_type=file.content_type or "application/octet-stream",
        extraction_job_id=job_id,
    )


async def run_extraction(job_id: str, project_id: int, file_path: str, mime_type: str):
    """Run text extraction in background."""
    redis_client = await get_redis()

    job = await get_extraction_job(redis_client, job_id)
    if not job:
        return

    try:
        await update_extraction_job(
            redis_client,
            job_id,
            status="running",
            progress="0.1",
            current_step="extracting_text",
        )

        # Emit progress
        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_ENTER,
            stage="extract",
            progress=0.1,
            data={"job_id": job_id, "step": "extracting_text"},
        )

        # Extract text using pipeline
        result = extract_text(file_path, mime_type)

        await update_extraction_job(
            redis_client,
            job_id,
            progress="0.5",
            current_step="creating_chapters",
        )

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_PROGRESS,
            stage="extract",
            progress=0.5,
            data={"job_id": job_id, "step": "creating_chapters"},
        )

        # Create chapters from extracted text
        from ..database import create_async_session
        from ..models import Project
        from ..schemas.paragraph import ContentRating

        async with create_async_session() as db:
            project = await db.get(Project, project_id)
            if project:
                chapters = split_into_chapters(result.raw_text)
                await update_extraction_job(redis_client, job_id, total_chapters=len(chapters))

                # Save project segments for OCR/content rating tracking
                if mime_type in ("image/png", "image/jpeg", "image/jpg", "image/tiff", "image/bmp", "image/webp"):
                    # For image files, save the whole extracted text as an OCR segment
                    segment = ProjectSegment(
                        project_id=project_id,
                        segment_index=0,
                        source_page=1,
                        source_format=mime_type.split("/")[-1],
                        text=result.raw_text,
                        char_count=len(result.raw_text),
                        is_ocr=result.has_ocr,
                        ocr_confidence=None,  # pytesseract doesn't easily expose this
                        ocr_languages=["chi_sim", "eng"] if result.has_ocr else [],
                        content_rating=ContentRating.GENERAL,
                        detected_language=result.language,
                    )
                    db.add(segment)
                else:
                    # For document files, could save per-page segments in the future
                    # For now, skip segment creation for non-image files
                    pass

                for i, chapter_text in enumerate(chapters):
                    chapter = Chapter(
                        project_id=project_id,
                        index=i + 1,
                        title=f"Chapter {i + 1}",
                        raw_text=chapter_text,
                        extract_status="completed",
                        status="completed",
                    )
                    db.add(chapter)

                    await update_extraction_job(
                        redis_client,
                        job_id,
                        extracted_chapters=i + 1,
                        progress=0.5 + (0.4 * (i + 1) / len(chapters)),
                    )

                await db.commit()

                # Update project status
                project.current_stage = "analyze"
                project.progress = 0.15
                await db.commit()

        # Complete
        await update_extraction_job(
            redis_client,
            job_id,
            status="completed",
            progress="1.0",
            current_step="completed",
        )

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_EXIT,
            stage="extract",
            progress=1.0,
            data={
                "job_id": job_id,
                "chapters_created": int(job.get("extracted_chapters", 0)),
                "total_paragraphs": result.raw_text.count("\n\n") + 1,
                "language": result.language,
                "page_count": result.page_count,
                "has_ocr": result.has_ocr,
                "ocr_page_ratio": result.ocr_page_ratio,
            },
        )

        logger.info(f"Extraction job {job_id} completed for project {project_id}")

    except Exception as e:
        await update_extraction_job(
            redis_client,
            job_id,
            status="failed",
            error=str(e),
        )

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.ERROR,
            stage="extract",
            data={"job_id": job_id, "error": str(e)},
        )

        logger.error(f"Extraction job {job_id} failed: {e}")


def split_into_chapters(text: str) -> List[str]:
    """Split text into chapters (simple heuristic)."""
    import re

    # Try to find chapter markers
    chapter_patterns = [
        r"\n\s*第[一二三四五六七八九十百千万\d]+\s*[章回节]\s*\n",
        r"\n\s*Chapter\s+\d+\s*\n",
        r"\n\s*CHAPTER\s+\d+\s*\n",
        r"\n\s*第\s*\d+\s*章\s*\n",
    ]

    for pattern in chapter_patterns:
        matches = list(re.finditer(pattern, text))
        if len(matches) > 1:
            chapters = []
            for i, match in enumerate(matches):
                start = match.start()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                chapters.append(text[start:end].strip())
            return [c for c in chapters if c]

    # Fallback: split by double newlines, group into chunks
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chapter_size = max(1, len(paragraphs) // 10)  # ~10 chapters
    chapters = []
    for i in range(0, len(paragraphs), chapter_size):
        chapters.append("\n\n".join(paragraphs[i : i + chapter_size]))
    return chapters


@router.get("/{project_id}/upload/{upload_id}/status")
async def get_upload_status(
    project_id: int,
    upload_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Get upload session status."""
    redis_client = await get_redis()
    session = await get_upload_session(redis_client, upload_id)

    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    if session["project_id"] != str(project_id):
        raise HTTPException(status_code=400, detail="Project ID mismatch")

    chunks_received = await redis_client.scard(upload_chunks_key(upload_id))
    total_chunks = int(session.get("total_chunks", 0))
    progress = chunks_received / max(total_chunks, 1) * 100

    return {
        "upload_id": upload_id,
        "project_id": project_id,
        "filename": session["filename"],
        "status": session.get("status", "initialized"),
        "chunks_received": chunks_received,
        "total_chunks": total_chunks,
        "progress": progress,
    }


@router.get("/{project_id}/extraction/{job_id}/status", response_model=ExtractionJobStatus)
async def get_extraction_status(
    project_id: int,
    job_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """Get extraction job status."""
    redis_client = await get_redis()
    job = await get_extraction_job(redis_client, job_id)

    if not job:
        raise HTTPException(status_code=404, detail="Extraction job not found")

    if job["project_id"] != str(project_id):
        raise HTTPException(status_code=400, detail="Project ID mismatch")

    return ExtractionJobStatus(**job)


@router.get("/{project_id}/extractions", response_model=List[ExtractionJobStatus])
async def list_extractions(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_async_db),
):
    """List all extraction jobs for a project."""
    redis_client = await get_redis()
    return await list_project_extractions(redis_client, project_id)


@router.delete("/{project_id}/upload/{upload_id}")
async def cancel_upload(
    project_id: int,
    upload_id: str,
    current_user: User = Depends(require_project_permission(RoleName.EDITOR)),
    db: AsyncSession = Depends(get_async_db),
):
    """Cancel an upload session and cleanup."""
    redis_client = await get_redis()

    session = await get_upload_session(redis_client, upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    if session["project_id"] != str(project_id):
        raise HTTPException(status_code=400, detail="Project ID mismatch")

    await delete_upload_session(redis_client, upload_id)

    return {"message": "Upload cancelled and cleaned up"}

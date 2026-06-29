"""File Upload API for Audiobook Studio.

Provides endpoints for uploading source files (PDF, EPUB, DOCX, TXT)
with async text extraction and WebSocket progress updates.
"""

import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..api.websocket import PipelineEventType, emit_pipeline_event, manager
from ..auth.dependencies import get_current_active_user, require_project_permission
from ..database import get_db
from ..models import Chapter, Project
from ..models.user import User
from ..pipeline.extract import extract_text

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["upload"])

# Configuration
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_FILE_SIZE = int(os.getenv("MAX_UPLOAD_SIZE", "100")) * 1024 * 1024  # 100MB default

# Allowed MIME types
ALLOWED_MIME_TYPES = {
    "application/pdf",
    "application/epub+zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "text/plain",
}

ALLOWED_EXTENSIONS = {".pdf", ".epub", ".docx", ".txt"}


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


# ── In-memory storage for upload sessions (use Redis in production) ────────

# upload_id -> {file_path, metadata, chunks_received, total_chunks}
upload_sessions: Dict[str, Dict[str, Any]] = {}

# job_id -> ExtractionJobStatus
extraction_jobs: Dict[str, ExtractionJobStatus] = {}


# ── Helper Functions ──────────────────────────────────────────────────────


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
        raise HTTPException(
            status_code=400, detail=f"MIME type {file.content_type} not allowed"
        )


async def save_upload_chunk(upload_id: str, chunk: bytes, chunk_index: int) -> None:
    """Save a chunk to the temporary file."""
    session = upload_sessions.get(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    file_path = session["file_path"]

    # Write chunk at correct position
    with open(file_path, "r+b") as f:
        # For simplicity, append chunks (in production, use proper chunk positioning)
        f.seek(0, 2)  # Seek to end
        f.write(chunk)

    session["chunks_received"].add(chunk_index)


def finalize_upload(upload_id: str) -> str:
    """Finalize upload and return file path."""
    session = upload_sessions.get(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    if len(session["chunks_received"]) != session["total_chunks"]:
        raise HTTPException(status_code=400, detail="Not all chunks received")

    return session["file_path"]


# ── API Endpoints ──────────────────────────────────────────────────────────


@router.post("/{project_id}/upload/init", response_model=UploadInitResponse)
async def init_upload(
    project_id: int,
    filename: str = Form(...),
    file_size: int = Form(...),
    mime_type: str = Form(...),
    current_user: User = Depends(require_project_permission("editor")),
    db: Session = Depends(get_db),
):
    """Initialize a multipart upload session."""
    # Verify project exists and user has access
    project = db.query(Project).filter(Project.id == project_id).first()
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
        raise HTTPException(
            status_code=400, detail=f"MIME type {mime_type} not allowed"
        )

    if file_size > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413, detail=f"File too large. Max size: {MAX_FILE_SIZE} bytes"
        )

    # Create upload session
    upload_id = str(uuid.uuid4())
    file_path = UPLOAD_DIR / f"{upload_id}_{filename}"

    # Create empty file for chunked writing
    file_path.touch()

    upload_sessions[upload_id] = {
        "project_id": project_id,
        "filename": filename,
        "file_size": file_size,
        "mime_type": mime_type,
        "file_path": str(file_path),
        "chunks_received": set(),
        "total_chunks": 0,
        "created_at": datetime.now(timezone.utc),
        "user_id": current_user.id,
    }

    logger.info(f"Upload initialized: {upload_id} for project {project_id}")

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
    current_user: User = Depends(require_project_permission("editor")),
    db: Session = Depends(get_db),
):
    """Upload a file chunk."""
    session = upload_sessions.get(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    if session["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Project ID mismatch")

    # Initialize total_chunks on first chunk
    if session["total_chunks"] == 0:
        session["total_chunks"] = total_chunks
    elif session["total_chunks"] != total_chunks:
        raise HTTPException(status_code=400, detail="Total chunks mismatch")

    # Read chunk data
    chunk_data = await file.read()

    # Save chunk
    await save_upload_chunk(upload_id, chunk_data, chunk_index)

    # Update progress
    progress = len(session["chunks_received"]) / total_chunks * 100

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
        file_path = finalize_upload(upload_id)
        session["status"] = "uploaded"
        session["completed_at"] = datetime.now(timezone.utc)

        # Start extraction job
        job_id = await start_extraction_job(
            upload_id, project_id, file_path, session["mime_type"]
        )

        return UploadCompleteResponse(
            upload_id=upload_id,
            project_id=project_id,
            file_path=file_path,
            file_size=session["file_size"],
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
    current_user: User = Depends(require_project_permission("editor")),
    db: Session = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Simple single-request file upload (for smaller files)."""
    # Verify project
    project = db.query(Project).filter(Project.id == project_id).first()
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
    job_id = await start_extraction_job(
        upload_id,
        project_id,
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


async def start_extraction_job(
    upload_id: str, project_id: int, file_path: str, mime_type: str
) -> str:
    """Start an async extraction job."""
    job_id = str(uuid.uuid4())

    job = ExtractionJobStatus(
        job_id=job_id,
        project_id=project_id,
        upload_id=upload_id,
        status="pending",
        progress=0.0,
        current_step="initializing",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    extraction_jobs[job_id] = job

    # Start extraction in background
    import asyncio

    asyncio.create_task(run_extraction(job_id, project_id, file_path, mime_type))

    return job_id


async def run_extraction(job_id: str, project_id: int, file_path: str, mime_type: str):
    """Run text extraction in background."""
    job = extraction_jobs.get(job_id)
    if not job:
        return

    try:
        job.status = "running"
        job.current_step = "extracting_text"
        job.progress = 0.1
        job.updated_at = datetime.now(timezone.utc)

        # Emit progress
        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_ENTER,
            stage="extract",
            progress=0.1,
            data={"job_id": job_id, "step": "extracting_text"},
        )

        # Extract text using pipeline
        result = await extract_text(file_path, mime_type)

        job.progress = 0.5
        job.current_step = "creating_chapters"
        job.updated_at = datetime.now(timezone.utc)

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_PROGRESS,
            stage="extract",
            progress=0.5,
            data={"job_id": job_id, "step": "creating_chapters"},
        )

        # Create chapters from extracted text
        from ..database import SessionLocal
        from ..models import Chapter, Project

        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if project:
                # Simple chapter splitting (by page breaks or fixed size)
                chapters = split_into_chapters(result.raw_text)
                job.total_chapters = len(chapters)

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
                    job.extracted_chapters = i + 1
                    job.progress = 0.5 + (0.4 * (i + 1) / len(chapters))
                    job.updated_at = datetime.now(timezone.utc)

                db.commit()

                # Update project status
                project.current_stage = "analyze"
                project.progress = 0.15
                db.commit()

        finally:
            db.close()

        # Complete
        job.status = "completed"
        job.progress = 1.0
        job.current_step = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.updated_at = datetime.now(timezone.utc)

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_EXIT,
            stage="extract",
            progress=1.0,
            data={
                "job_id": job_id,
                "chapters_created": job.extracted_chapters,
                "total_paragraphs": result.raw_text.count("\n\n") + 1,
                "language": result.language,
                "page_count": result.page_count,
                "has_ocr": result.has_ocr,
                "ocr_page_ratio": result.ocr_page_ratio,
            },
        )

        logger.info(f"Extraction job {job_id} completed for project {project_id}")

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.updated_at = datetime.now(timezone.utc)

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.ERROR,
            stage="extract",
            data={"job_id": job_id, "error": str(e)},
        )

        logger.error(f"Extraction job {job_id} failed: {e}")


def split_into_chapters(text: str) -> List[str]:
    """Split text into chapters (simple heuristic)."""
    # Split by common chapter markers
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
    db: Session = Depends(get_db),
):
    """Get upload session status."""
    session = upload_sessions.get(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    if session["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Project ID mismatch")

    return {
        "upload_id": upload_id,
        "project_id": project_id,
        "filename": session["filename"],
        "status": session.get("status", "initialized"),
        "chunks_received": len(session["chunks_received"]),
        "total_chunks": session["total_chunks"],
        "progress": len(session["chunks_received"])
        / max(session["total_chunks"], 1)
        * 100,
    }


@router.get(
    "/{project_id}/extraction/{job_id}/status", response_model=ExtractionJobStatus
)
async def get_extraction_status(
    project_id: int,
    job_id: str,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get extraction job status."""
    job = extraction_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Extraction job not found")

    if job.project_id != project_id:
        raise HTTPException(status_code=400, detail="Project ID mismatch")

    return job


@router.get("/{project_id}/extractions", response_model=List[ExtractionJobStatus])
async def list_extractions(
    project_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all extraction jobs for a project."""
    jobs = [j for j in extraction_jobs.values() if j.project_id == project_id]
    return sorted(jobs, key=lambda x: x.created_at, reverse=True)


@router.delete("/{project_id}/upload/{upload_id}")
async def cancel_upload(
    project_id: int,
    upload_id: str,
    current_user: User = Depends(require_project_permission("editor")),
    db: Session = Depends(get_db),
):
    """Cancel an upload session and cleanup."""
    session = upload_sessions.get(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")

    if session["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Project ID mismatch")

    # Delete temp file
    file_path = Path(session["file_path"])
    if file_path.exists():
        file_path.unlink()

    # Remove session
    del upload_sessions[upload_id]

    return {"message": "Upload cancelled and cleaned up"}

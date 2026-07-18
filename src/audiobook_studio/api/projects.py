"""FastAPI router for ``Project`` CRUD with Chapter/Paragraph hierarchy.

Provides full CRUD for the HARNESS-aligned entity tree:

- ``/api/projects/`` — Project management
- ``/api/projects/{id}/chapters/`` — Chapter management
- ``/api/projects/{id}/chapters/{ch}/paragraphs/`` — Paragraph detail
- ``/api/projects/{id}/pipeline/`` — Pipeline orchestration
- ``/api/projects/{id}/quality-report`` — Audio quality report
"""

import json
import logging
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..models import Chapter, Paragraph, Project
from ..storage import reports_dir
from .dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects", tags=["projects"])


# ── Pydantic schemas for API responses ────────────────────────────────────────


class ProjectCreate(BaseModel):
    title: str
    author: Optional[str] = None
    genre: Optional[str] = None
    language: Optional[str] = "zh"
    difficulty: Optional[str] = None
    global_style_notes: Optional[str] = None
    story_line_summary: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    title: str
    author: Optional[str] = None
    genre: Optional[str] = None
    language: str
    difficulty: Optional[str] = None
    status: str
    current_stage: Optional[str] = None
    progress: float
    total_cost_usd: float
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class ChapterOut(BaseModel):
    id: int
    project_id: int
    index: int
    title: Optional[str] = None
    status: str
    extract_status: str
    analyze_status: str
    annotate_status: str
    edit_status: str
    route_status: str
    synthesize_status: str
    quality_status: str
    cost_usd: float
    token_count: int
    tts_chars: int

    model_config = ConfigDict(from_attributes=True)


class ParagraphOut(BaseModel):
    id: int
    project_id: int
    chapter_id: int
    chapter_index: int
    index: int
    text: Optional[str] = None
    speaker: Optional[str] = None
    speaker_canonical_name: Optional[str] = None
    is_dialogue: Optional[bool] = None
    emotion: Optional[str] = None
    edited_text: Optional[str] = None
    status: str

    model_config = ConfigDict(from_attributes=True)


# ── Project CRUD ──────────────────────────────────────────────────────────────


@router.post("/", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    """Create a new project."""
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/", response_model=List[ProjectOut])
def list_projects(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all projects."""
    return db.query(Project).offset(skip).limit(limit).all()


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    """Get a single project by ID."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectCreate,
    db: Session = Depends(get_db),
):
    """Update a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    """Delete a project and all related data."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.delete(project)
    db.commit()
    return None


# ── Chapter endpoints ─────────────────────────────────────────────────────────


@router.get("/{project_id}/chapters", response_model=List[ChapterOut])
def list_chapters(
    project_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """List all chapters for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return (
        db.query(Chapter)
        .filter(Chapter.project_id == project_id)
        .order_by(Chapter.index)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get("/{project_id}/chapters/{chapter_id}", response_model=ChapterOut)
def get_chapter(
    project_id: int,
    chapter_id: int,
    db: Session = Depends(get_db),
):
    """Get a single chapter by its DB ID."""
    chapter = (
        db.query(Chapter)
        .filter(
            Chapter.project_id == project_id,
            Chapter.id == chapter_id,
        )
        .first()
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter


# ── Paragraph endpoints ───────────────────────────────────────────────────────


@router.get(
    "/{project_id}/chapters/{chapter_id}/paragraphs",
    response_model=List[ParagraphOut],
)
def list_paragraphs(
    project_id: int,
    chapter_id: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List all paragraphs for a chapter (by chapter DB ID)."""
    chapter = (
        db.query(Chapter)
        .filter(
            Chapter.project_id == project_id,
            Chapter.id == chapter_id,
        )
        .first()
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return (
        db.query(Paragraph)
        .filter(
            Paragraph.project_id == project_id,
            Paragraph.chapter_id == chapter.id,
        )
        .order_by(Paragraph.index)
        .offset(skip)
        .limit(limit)
        .all()
    )


@router.get(
    "/{project_id}/chapters/{chapter_id}/paragraphs/{paragraph_id}",
    response_model=ParagraphOut,
)
def get_paragraph(
    project_id: int,
    chapter_id: int,
    paragraph_id: int,
    db: Session = Depends(get_db),
):
    """Get a single paragraph by its DB ID."""
    para = (
        db.query(Paragraph)
        .filter(
            Paragraph.project_id == project_id,
            Paragraph.chapter_id == chapter_id,
            Paragraph.id == paragraph_id,
        )
        .first()
    )
    if not para:
        raise HTTPException(status_code=404, detail="Paragraph not found")
    return para


@router.put(
    "/{project_id}/chapters/{chapter_id}/paragraphs/{paragraph_id}",
    response_model=ParagraphOut,
)
def update_paragraph(
    project_id: int,
    chapter_id: int,
    paragraph_id: int,
    payload: dict,
    db: Session = Depends(get_db),
):
    """Update a paragraph by its DB ID."""
    para = (
        db.query(Paragraph)
        .filter(
            Paragraph.project_id == project_id,
            Paragraph.chapter_id == chapter_id,
            Paragraph.id == paragraph_id,
        )
        .first()
    )
    if not para:
        raise HTTPException(status_code=404, detail="Paragraph not found")
    update_data = {k: v for k, v in payload.items() if k not in ("id",) and v is not None}
    for field, value in update_data.items():
        setattr(para, field, value)
    db.commit()
    db.refresh(para)
    return para


# ── Quality Report endpoint ─────────────────────────────────────────────────────


class QualityReportSegment(BaseModel):
    """Quality report segment model for API response."""

    segment_id: str
    file_path: str
    duration_ms: int
    silence_detected: bool
    silence_ratio: float
    silence_regions: List[dict]
    corruption_detected: bool
    corruption_error: Optional[str]
    decode_valid: bool
    clipping_detected: bool
    peak_db: float
    rms_db: float
    passed: bool
    issues: List[str]


class QualityReportOut(BaseModel):
    """Quality report response model."""

    project_id: str
    chapter_index: int
    total_segments: int
    passed_segments: int
    failed_segments: int
    segment_results: List[QualityReportSegment]
    overall_passed: bool
    generated_at: str

    model_config = ConfigDict(from_attributes=True)


@router.get("/{project_id}/quality-report", response_model=QualityReportOut)
def get_quality_report(
    project_id: int,
    chapter_index: int = Query(0, ge=0, description="Chapter index (default: 0 for latest)"),
):
    """Get audio quality report for a project chapter.

    Returns the quality check results including silence detection,
    corruption detection, and clipping detection for all segments.
    """
    # Look for quality report in storage/books/{project_id}/reports/quality_report_ch_{chapter_index}.json
    report_path = reports_dir(project_id) / f"quality_report_ch_{chapter_index:03d}.json"

    if not report_path.exists():
        # Try the default quality_report.json (backward compatibility)
        report_path = reports_dir(project_id) / "quality_report.json"

    if not report_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Quality report not found for project {project_id}, chapter {chapter_index}",
        )

    try:
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Convert segment_results to QualityReportSegment models
        segment_results = [
            QualityReportSegment(**sr) for sr in data.get("segment_results", [])
        ]

        return QualityReportOut(
            project_id=str(data["project_id"]),
            chapter_index=data["chapter_index"],
            total_segments=data["total_segments"],
            passed_segments=data["passed_segments"],
            failed_segments=data["failed_segments"],
            segment_results=segment_results,
            overall_passed=data["overall_passed"],
            generated_at=data["generated_at"],
        )
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid quality report format: {e}")
    except KeyError as e:
        raise HTTPException(status_code=500, detail=f"Quality report missing required field: {e}")

@router.post("/{project_id}/chapters/{chapter_id}/paragraphs/{paragraph_id}/regenerate")
async def regenerate_paragraph(
    project_id: int,
    chapter_id: int,
    paragraph_id: int,
    db: Session = Depends(get_db),
):
    """Regenerate a single paragraph's audio (single-sentence re-synthesis).

    This endpoint triggers re-synthesis of a single paragraph's audio without
    re-running the entire pipeline. The new audio is seamlessly merged with
    existing audio segments.
    """
    # Verify the paragraph exists and belongs to the project/chapter
    para = (
        db.query(Paragraph)
        .filter(
            Paragraph.project_id == project_id,
            Paragraph.chapter_id == chapter_id,
            Paragraph.id == paragraph_id,
        )
        .first()
    )
    if not para:
        raise HTTPException(status_code=404, detail="Paragraph not found")

    # Check if there's an existing audio segment
    audio_segment = para.audio_segment
    if not audio_segment:
        raise HTTPException(status_code=400, detail="No audio segment found for this paragraph")

    # Queue the re-synthesis task
    from ..tasks.tts_tasks import synthesize_paragraph_task

    # Queue the task with the paragraph info
    task = synthesize_paragraph_task.delay(
        project_id=project_id,
        chapter_id=chapter_id,
        paragraph_id=paragraph_id,
        force_regenerate=True,
    )

    return {
        "task_id": task.id,
        "status": "queued",
        "message": "Single-sentence re-synthesis queued. The new audio will be seamlessly merged.",
    }


# ── Existing endpoint for backward compatibility ─────────────────────────────────
@router.post("/{project_id}/paragraphs/{paragraph_id}/regenerate")
async def regenerate_paragraph_legacy(
    project_id: int,
    paragraph_id: int,
    db: Session = Depends(get_db),
):
    """Legacy endpoint - redirects to new chapter-aware endpoint."""
    from ..models import Paragraph, Chapter

    para = db.query(Paragraph).filter(
        Paragraph.project_id == project_id,
        Paragraph.id == paragraph_id,
    ).first()
    if not para:
        raise HTTPException(status_code=404, detail="Paragraph not found")

    return await regenerate_paragraph(
        project_id=project_id,
        chapter_id=para.chapter_id,
        paragraph_id=paragraph_id,
        db=db,
    )

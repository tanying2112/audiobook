"""FastAPI router for ``Project`` CRUD with Chapter/Paragraph hierarchy.

Provides full CRUD for the HARNESS-aligned entity tree:

- ``/api/projects/`` — Project management
- ``/api/projects/{id}/chapters/`` — Chapter management
- ``/api/projects/{id}/chapters/{ch}/paragraphs/`` — Paragraph detail
- ``/api/projects/{id}/pipeline/`` — Pipeline orchestration
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..models import Chapter, Paragraph, Project
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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


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


@router.get("/{project_id}/chapters/{chapter_index}", response_model=ChapterOut)
def get_chapter(
    project_id: int,
    chapter_index: int,
    db: Session = Depends(get_db),
):
    """Get a single chapter by its 1-based index."""
    chapter = (
        db.query(Chapter)
        .filter(
            Chapter.project_id == project_id,
            Chapter.index == chapter_index,
        )
        .first()
    )
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    return chapter


# ── Paragraph endpoints ───────────────────────────────────────────────────────


@router.get(
    "/{project_id}/chapters/{chapter_index}/paragraphs",
    response_model=List[ParagraphOut],
)
def list_paragraphs(
    project_id: int,
    chapter_index: int,
    skip: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """List all paragraphs for a chapter."""
    chapter = (
        db.query(Chapter)
        .filter(
            Chapter.project_id == project_id,
            Chapter.index == chapter_index,
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
    "/{project_id}/chapters/{chapter_index}/paragraphs/{paragraph_index}",
    response_model=ParagraphOut,
)
def get_paragraph(
    project_id: int,
    chapter_index: int,
    paragraph_index: int,
    db: Session = Depends(get_db),
):
    """Get a single paragraph by its indices."""
    para = (
        db.query(Paragraph)
        .filter(
            Paragraph.project_id == project_id,
            Paragraph.chapter_index == chapter_index,
            Paragraph.index == paragraph_index,
        )
        .first()
    )
    if not para:
        raise HTTPException(status_code=404, detail="Paragraph not found")
    return para

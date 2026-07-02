"""Pipeline stage execution API endpoints.

Provides endpoints for running individual pipeline stages including
the translate stage for multilingual dubbing.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..api.websocket import PipelineEventType, emit_pipeline_event
from ..database import SessionLocal, get_db
from ..models import AudioSegment, Chapter, Paragraph, Project
from ..pipeline.checkpoint import CheckpointManager
from ..pipeline.orchestrator import run_stage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/pipeline", tags=["pipeline"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class StageRunRequest(BaseModel):
    """Request to run a single pipeline stage."""

    stage: str = Field(
        ...,
        description="Stage name: extract, analyze, annotate, edit, audio_postprocess, synthesize, quality, translate",
    )
    chapter_id: Optional[int] = Field(None, description="Chapter DB ID (required for chapter-level stages)")
    paragraph_id: Optional[int] = Field(None, description="Paragraph DB ID (required for paragraph-level stages)")
    target_difficulty: Optional[str] = Field(None, description="Target difficulty level (A/B/C/D)")
    # Translate-specific parameters
    target_language: Optional[str] = Field(
        None,
        description="Target language code for translate stage (e.g., en-US, es-ES)",
    )
    chapter_indices: Optional[List[int]] = Field(
        None, description="List of chapter indices to translate (for translate stage)"
    )
    book_title: Optional[str] = Field(None, description="Book title for context (translate stage)")
    author: Optional[str] = Field(None, description="Author name for context (translate stage)")


class StageRunResponse(BaseModel):
    """Response for stage execution."""

    stage: str
    status: str  # started, completed, failed
    message: str
    progress: float = 0.0
    result: Optional[Dict[str, Any]] = None


class TranslateRunRequest(BaseModel):
    """Request to run translate and dub stage."""

    target_language: str = Field(..., description="Target language code (e.g., en-US, es-ES, ja-JP)")
    chapter_indices: Optional[List[int]] = Field(
        None,
        description="Chapter indices to translate (1-based). None = all chapters with audio",
    )
    book_title: Optional[str] = Field(None, description="Book title for translation context")
    author: Optional[str] = Field(None, description="Author name for translation context")


class TranslateRunResponse(BaseModel):
    """Response for translate stage execution."""

    status: str  # started, completed, failed
    message: str
    progress: float = 0.0
    total_segments: int = 0
    successful_translations: int = 0
    failed_translations: int = 0
    emotional_continuity_passed: Optional[bool] = None
    semantic_coherence_score: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────


async def _run_translate_stage(
    project_id: int,
    target_language: str,
    chapter_indices: Optional[List[int]] = None,
    book_title: str = "",
    author: str = "",
) -> Dict[str, Any]:
    """Run the translate stage for a project.

    This operates on chapters that have completed synthesis (have audio segments).
    """
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Determine which chapters to translate
        if chapter_indices:
            chapters = (
                db.query(Chapter)
                .filter(Chapter.project_id == project_id, Chapter.index.in_(chapter_indices))
                .order_by(Chapter.index)
                .all()
            )
        else:
            # Default: all chapters that have synthesized audio
            chapters = (
                db.query(Chapter)
                .filter(
                    Chapter.project_id == project_id,
                    Chapter.synthesize_status == "completed",
                )
                .order_by(Chapter.index)
                .all()
            )

        if not chapters:
            return {
                "status": "failed",
                "message": "No chapters found with completed synthesis",
                "total_segments": 0,
                "successful_translations": 0,
                "failed_translations": 0,
            }

        total_segments = 0
        successful_translations = 0
        failed_translations = 0
        all_dubbed_segments = []
        all_reports = []

        for chapter in chapters:
            # Get paragraphs with audio segments for this chapter
            paragraphs = (
                db.query(Paragraph)
                .filter(
                    Paragraph.project_id == project_id,
                    Paragraph.chapter_id == chapter.id,
                    Paragraph.status == "synthesized",
                )
                .order_by(Paragraph.index)
                .all()
            )

            if not paragraphs:
                continue

            # Build segments list from paragraphs with audio
            segments = []
            for para in paragraphs:
                audio_segments = (
                    db.query(AudioSegment)
                    .filter(
                        AudioSegment.paragraph_id == para.id,
                        AudioSegment.is_current == True,
                    )
                    .all()
                )
                for seg in audio_segments:
                    # Attach annotation data to segment for translate
                    seg.text = para.edited_text or para.text
                    seg.annotation = {
                        "speaker_canonical_name": para.speaker_canonical_name,
                        "is_dialogue": para.is_dialogue,
                        "emotion": para.emotion,
                        "emotion_intensity": para.emotion_intensity,
                        "speech_rate": para.speech_rate,
                        "pitch_shift_semitones": para.pitch_shift_semitones,
                        "needs_sfx": para.needs_sfx,
                        "sfx_tags": para.sfx_tags,
                    }
                    segments.append(seg)

            if not segments:
                continue

            total_segments += len(segments)

            # Emit stage enter event
            await emit_pipeline_event(
                project_id=project_id,
                event_type=PipelineEventType.STAGE_ENTER,
                stage="translate",
                chapter_index=chapter.index,
                progress=0.0,
            )

            # Run translate stage using run_stage
            try:
                result = await asyncio.to_thread(
                    run_stage,
                    "translate",
                    db,
                    project_id=project_id,
                    chapter_id=chapter.id,
                    paragraph_id=None,  # translate operates on chapter level
                    target_language=target_language,
                    book_title=book_title or project.title,
                    author=author or project.author,
                    # Pass segments via context (stage handler expects them)
                    segments=segments,
                )

                dubbed_segments, report = result
                all_dubbed_segments.extend(dubbed_segments)
                all_reports.append(report)

                successful_translations += report.get("successful_translations", 0)
                failed_translations += report.get("failed_translations", 0)

                # Emit progress
                await emit_pipeline_event(
                    project_id=project_id,
                    event_type=PipelineEventType.STAGE_PROGRESS,
                    stage="translate",
                    chapter_index=chapter.index,
                    progress=1.0,
                )

            except Exception as e:
                logger.error(f"Translate failed for chapter {chapter.index}: {e}")
                failed_translations += len(segments)
                await emit_pipeline_event(
                    project_id=project_id,
                    event_type=PipelineEventType.ERROR,
                    stage="translate",
                    chapter_index=chapter.index,
                    data={"message": str(e)},
                )

            # Emit stage exit
            await emit_pipeline_event(
                project_id=project_id,
                event_type=PipelineEventType.STAGE_EXIT,
                stage="translate",
                chapter_index=chapter.index,
                progress=1.0,
            )

        return {
            "status": "completed" if successful_translations > 0 else "failed",
            "message": f"Translated {successful_translations}/{total_segments} segments to {target_language}",
            "total_segments": total_segments,
            "successful_translations": successful_translations,
            "failed_translations": failed_translations,
            "emotional_continuity_passed": (all_reports[0].get("emotional_continuity_passed") if all_reports else None),
            "semantic_coherence_score": (all_reports[0].get("semantic_coherence_score") if all_reports else None),
        }

    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/run-stage", response_model=StageRunResponse)
async def run_pipeline_stage(
    project_id: int,
    request: StageRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Run a single pipeline stage.

    This endpoint triggers a specific pipeline stage for a project/chapter/paragraph.
    Progress is emitted via WebSocket.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate stage
    valid_stages = [
        "extract",
        "analyze",
        "annotate",
        "edit",
        "audio_postprocess",
        "synthesize",
        "quality",
        "translate",
    ]
    if request.stage not in valid_stages:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage: {request.stage}. Valid stages: {valid_stages}",
        )

    # For translate stage, delegate to specialized handler
    if request.stage == "translate":
        if not request.target_language:
            raise HTTPException(
                status_code=400,
                detail="target_language is required for translate stage",
            )

        background_tasks.add_task(
            _run_translate_stage,
            project_id=project_id,
            target_language=request.target_language,
            chapter_indices=request.chapter_indices,
            book_title=request.book_title or project.title,
            author=request.author or project.author,
        )

        return StageRunResponse(
            stage="translate",
            status="started",
            message=f"Translation to {request.target_language} started",
            progress=0.0,
        )

    # For other stages, use existing run_stage logic
    # This would be implemented similarly to auto_run.py
    raise HTTPException(
        status_code=501,
        detail=f"Stage '{request.stage}' execution not yet implemented via this endpoint. Use /auto-run for full pipeline.",
    )


@router.post("/translate", response_model=TranslateRunResponse)
async def run_translate(
    project_id: int,
    request: TranslateRunRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Run multilingual translation and dubbing for a project.

    This translates all synthesized chapters to the target language,
    preserving character voices and emotional continuity.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate target language
    supported_languages = [
        "en-US",
        "es-ES",
        "ja-JP",
        "fr-FR",
        "de-DE",
        "zh-CN",
        "zh-TW",
        "ko-KR",
        "pt-BR",
        "it-IT",
        "ru-RU",
    ]
    if request.target_language not in supported_languages:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported language: {request.target_language}. Supported: {supported_languages}",
        )

    # Run translate in background
    background_tasks.add_task(
        _run_translate_stage,
        project_id=project_id,
        target_language=request.target_language,
        chapter_indices=request.chapter_indices,
        book_title=request.book_title or project.title,
        author=request.author or project.author,
    )

    return TranslateRunResponse(
        status="started",
        message=f"Translation to {request.target_language} started",
        progress=0.0,
    )


@router.get("/translate/status")
async def get_translate_status(project_id: int, db: Session = Depends(get_db)):
    """Get the status of translation for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Count translated audio segments (paragraph_id > 10000 indicates translated)
    total_translated = (
        db.query(AudioSegment).filter(AudioSegment.project_id == project_id, AudioSegment.paragraph_id > 10000).count()
    )

    # Count original segments
    total_original = (
        db.query(AudioSegment)
        .filter(
            AudioSegment.project_id == project_id,
            AudioSegment.paragraph_id <= 10000,
            AudioSegment.is_current == True,
        )
        .count()
    )

    return {
        "project_id": project_id,
        "total_original_segments": total_original,
        "total_translated_segments": total_translated,
        "translation_ratio": (total_translated / total_original if total_original > 0 else 0),
    }


@router.get("/translate/languages")
async def get_supported_languages():
    """Get list of supported target languages for translation."""
    return {
        "languages": [
            {"code": "en-US", "name": "English (US)", "native_name": "English"},
            {"code": "es-ES", "name": "Spanish (Spain)", "native_name": "Español"},
            {"code": "ja-JP", "name": "Japanese", "native_name": "日本語"},
            {"code": "fr-FR", "name": "French (France)", "native_name": "Français"},
            {"code": "de-DE", "name": "German (Germany)", "native_name": "Deutsch"},
            {
                "code": "zh-CN",
                "name": "Chinese (Simplified)",
                "native_name": "简体中文",
            },
            {
                "code": "zh-TW",
                "name": "Chinese (Traditional)",
                "native_name": "繁體中文",
            },
            {"code": "ko-KR", "name": "Korean", "native_name": "한국어"},
            {
                "code": "pt-BR",
                "name": "Portuguese (Brazil)",
                "native_name": "Português",
            },
            {"code": "it-IT", "name": "Italian (Italy)", "native_name": "Italiano"},
            {"code": "ru-RU", "name": "Russian", "native_name": "Русский"},
        ]
    }

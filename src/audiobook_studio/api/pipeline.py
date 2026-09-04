"""Pipeline stage execution API endpoints.

Provides endpoints for running individual pipeline stages including
the translate stage for multilingual dubbing.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

from ..api.dependencies import get_async_db
from ..api.websocket import PipelineEventType, emit_pipeline_event
from ..database import create_async_session, get_sync_engine_url
from ..exceptions import DomainError
from ..models import AudioSegment, Chapter, Paragraph, Project
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
    db = create_async_session()
    try:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if not project:
            raise ValueError(f"Project {project_id} not found")

        # Determine which chapters to translate
        if chapter_indices:
            result = await db.execute(
                select(Chapter)
                .where(Chapter.project_id == project_id, Chapter.index.in_(chapter_indices))
                .order_by(Chapter.index)
            )
            chapters = result.scalars().all()
        else:
            # Default: all chapters that have synthesized audio
            result = await db.execute(
                select(Chapter)
                .where(
                    Chapter.project_id == project_id,
                    Chapter.synthesize_status == "completed",
                )
                .order_by(Chapter.index)
            )
            chapters = result.scalars().all()

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
            result = await db.execute(
                select(Paragraph)
                .where(
                    Paragraph.project_id == project_id,
                    Paragraph.chapter_id == chapter.id,
                    Paragraph.status == "synthesized",
                )
                .order_by(Paragraph.index)
            )
            paragraphs = result.scalars().all()

            if not paragraphs:
                continue

            # Build segments list from paragraphs with audio
            segments = []
            for para in paragraphs:
                result = await db.execute(
                    select(AudioSegment).where(
                        AudioSegment.paragraph_id == para.id,
                        AudioSegment.is_current,
                    )
                )
                audio_segments = result.scalars().all()
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
                project_idproject_id=project_id,
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
        await db.close()


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/run-stage", response_model=StageRunResponse)
async def run_pipeline_stage(
    project_id: int,
    request: StageRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """Run a single pipeline stage.

    This endpoint triggers a specific pipeline stage for a project/chapter/paragraph.
    Progress is emitted via WebSocket.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise DomainError(
            message="Project not found",
            error_code="NOT_FOUND",
            stage="pipeline",
            context={"project_id": project_id},
        )

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
        raise DomainError(
            message=f"Invalid stage: {request.stage}. Valid stages: {valid_stages}",
            error_code="VALIDATION_ERROR",
            stage="pipeline",
            context={"stage": request.stage, "valid_stages": valid_stages},
        )

    # Validate chapter_id for stages that require it
    if request.stage in ("extract", "analyze") and not request.chapter_id:
        raise DomainError(
            message=f"chapter_id is required for stage '{request.stage}'",
            error_code="VALIDATION_ERROR",
            stage="pipeline",
            context={"stage": request.stage, "required_field": "chapter_id"},
        )

    # For translate stage, delegate to specialized handler
    if request.stage == "translate":
        if not request.target_language:
            raise DomainError(
                message="target_language is required for translate stage",
                error_code="VALIDATION_ERROR",
                stage="pipeline",
                context={"stage": "translate", "required_field": "target_language"},
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

    # For other stages, run via orchestrator.run_stage in thread pool with sync session
    import asyncio

    from sqlalchemy.orm import Session

    # Create a sync engine for the thread pool  # noqa: E303
    sync_engine = create_engine(get_sync_engine_url(), pool_pre_ping=True)
    SyncSession = sessionmaker(bind=sync_engine, class_=Session, expire_on_commit=False)

    try:
        result = await asyncio.to_thread(
            run_stage,
            request.stage,
            SyncSession(),  # Sync session for the thread
            project_id=project_id,
            chapter_id=request.chapter_id if request.chapter_id else None,
            target_difficulty=request.target_difficulty,
        )
    finally:
        sync_engine.dispose()

    return StageRunResponse(
        stage=request.stage,
        status="completed",
        message=f"Stage {request.stage} completed",
        progress=1.0,
        result={"status": "ok"},
    )


@router.post("/translate", response_model=TranslateRunResponse)
async def run_translate(
    project_id: int,
    request: TranslateRunRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """Run multilingual translation and dubbing for a project.

    This translates all synthesized chapters to the target language,
    preserving character voices and emotional continuity.
    """
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise DomainError(
            message="Project not found",
            error_code="NOT_FOUND",
            stage="pipeline",
            context={"project_id": project_id},
        )

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
        raise DomainError(
            message=f"Unsupported language: {request.target_language}. Supported: {supported_languages}",
            error_code="VALIDATION_ERROR",
            stage="pipeline",
            context={"target_language": request.target_language, "supported_languages": supported_languages},
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
async def get_translate_status(project_id: int, db: AsyncSession = Depends(get_async_db)):
    """Get the status of translation for a project."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise DomainError(
            message="Project not found",
            error_code="NOT_FOUND",
            stage="pipeline",
            context={"project_id": project_id},
        )

    # Count translated audio segments (paragraph_id > 10000 indicates translated)
    total_translated_result = await db.execute(
        select(func.count())
        .select_from(AudioSegment)
        .where(AudioSegment.project_id == project_id, AudioSegment.paragraph_id > 10000)
    )
    total_translated = total_translated_result.scalar() or 0

    # Count original segments
    total_original_result = await db.execute(
        select(func.count())
        .select_from(AudioSegment)
        .where(
            AudioSegment.project_id == project_id,
            AudioSegment.paragraph_id <= 10000,
            AudioSegment.is_current,
        )
    )
    total_original = total_original_result.scalar() or 0

    return {
        "project_id": project_id,
        "total_original_segments": total_original,
        "total_translated_segments": total_translated,
        "translation_ratio": (total_translated / total_original if total_original > 0 else 0),
    }


@router.get("/translate/languages")
async def get_supported_languages():
    """Get list of supported target languages for translation.

    Driven by the centralised language registry (S2.3) so Japanese and
    French are first-class and stay in sync with TTS voice selection.
    """
    from ..languages import SUPPORTED_BCP47_CODES, get_language_info

    languages = [
        {
            "code": code,
            "name": get_language_info(code).display_name,
            "native_name": get_language_info(code).display_name,
        }
        for code in SUPPORTED_BCP47_CODES
    ]
    return {"languages": languages}

"""Template management API endpoints for Golden Sample hub."""

import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from ..database import get_db
from ..models.feedback_record import FeedbackRecord as FeedbackRecordModel
from ..models import Paragraph, TTSEdit, Routing, Quality
from ..schemas import (
    ParagraphAnnotation,
    TtsEditOutput,
    TtsRoutingDecision,
    QualityJudgment,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/templates", tags=["templates"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Schemas
# ─────────────────────────────────────────────────────────────────────────────

class TemplateItem(BaseModel):
    """Single template item from feedback record."""
    id: int
    feedback_id: str
    source: str
    stage: str
    pattern_tags: Optional[List[str]] = None
    diff_summary: Optional[str] = None
    rationale: str
    created_at: str
    input_snapshot: Dict[str, Any]
    llm_output: Dict[str, Any]
    corrected_output: Dict[str, Any]


class TemplateListResponse(BaseModel):
    """Response for template list endpoint."""
    templates: List[TemplateItem] = Field(default_factory=list)
    total_count: int = 0
    pending_count: int = 0


class TemplateConfirmRequest(BaseModel):
    """Request to confirm/reject a template."""
    action: str = Field(..., description="confirm or reject")
    pattern_tags: Optional[List[str]] = None


class TemplateApplyRequest(BaseModel):
    """Request to apply template to project."""
    template_id: int = Field(..., description="Template (feedback record) ID")
    scope: str = Field(..., description="Scope: 'all', 'chapter', 'pattern'")
    chapter_ids: Optional[List[int]] = Field(None, description="Chapter IDs if scope=chapter")
    pattern_filter: Optional[str] = Field(None, description="Pattern tag filter if scope=pattern")


class TemplateApplyProgress(BaseModel):
    """Progress update for template application."""
    processed: int = 0
    total: int = 0
    current_paragraph_id: Optional[int] = None
    current_stage: Optional[str] = None
    status: str = "running"  # running, completed, failed
    error: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

def _feedback_to_template(record: FeedbackRecordModel) -> TemplateItem:
    """Convert FeedbackRecord to TemplateItem."""
    return TemplateItem(
        id=record.id,
        feedback_id=record.feedback_id,
        source=record.source,
        stage=record.stage,
        pattern_tags=record.pattern_tags or [],
        diff_summary=record.diff_summary,
        rationale=record.rationale,
        created_at=record.created_at.isoformat() if record.created_at else datetime.now(timezone.utc).isoformat(),
        input_snapshot=record.input_snapshot,
        llm_output=record.llm_output,
        corrected_output=record.corrected_output,
    )


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=TemplateListResponse)
async def list_templates(
    project_id: int,
    source: Optional[str] = None,
    stage: Optional[str] = None,
    pattern_tag: Optional[str] = None,
    pending_only: bool = False,
    db: Session = Depends(get_db),
):
    """
    Get template queue for project.

    Templates are confirmed feedback records (processed=true, promoted=true)
    that can be applied to other paragraphs.

    Filters:
    - source: Filter by feedback source (human_edit, quality_judge, user_rating)
    - stage: Filter by pipeline stage
    - pattern_tag: Filter by specific pattern tag
    - pending_only: Only show unprocessed feedback (pending confirmation)
    """
    query = db.query(FeedbackRecordModel).filter(FeedbackRecordModel.project_id == project_id)

    if source:
        query = query.filter(FeedbackRecordModel.source == source)

    if stage:
        query = query.filter(FeedbackRecordModel.stage == stage)

    if pattern_tag:
        query = query.filter(FeedbackRecordModel.pattern_tags.contains([pattern_tag]))

    if pending_only:
        # Show unprocessed feedback for confirmation
        query = query.filter(FeedbackRecordModel.processed == False)
    else:
        # Show confirmed templates
        query = query.filter(FeedbackRecordModel.processed == True, FeedbackRecordModel.promoted == True)

    records = query.order_by(FeedbackRecordModel.created_at.desc()).limit(100).all()

    templates = [_feedback_to_template(r) for r in records]

    # Count pending
    pending_count = db.query(FeedbackRecordModel).filter(
        FeedbackRecordModel.project_id == project_id,
        FeedbackRecordModel.processed == False,
    ).count()

    return TemplateListResponse(
        templates=templates,
        total_count=len(templates),
        pending_count=pending_count,
    )


@router.post("/{template_id}/confirm")
async def confirm_template(
    project_id: int,
    template_id: int,
    request: TemplateConfirmRequest,
    db: Session = Depends(get_db),
):
    """
    Confirm or reject a template.

    Confirm: Mark as processed=true, promoted=true (enters Golden Sample candidate queue)
    Reject: Mark as processed=true (not promoted)
    """
    record = db.query(FeedbackRecordModel).filter(
        FeedbackRecordModel.id == template_id,
        FeedbackRecordModel.project_id == project_id,
    ).first()

    if not record:
        raise HTTPException(status_code=404, detail="Template not found")

    if request.action == "confirm":
        record.processed = True
        record.promoted = True
        if request.pattern_tags:
            record.pattern_tags = request.pattern_tags
        logger.info(f"Template {template_id} confirmed for project {project_id}")
    elif request.action == "reject":
        record.processed = True
        record.promoted = False
        logger.info(f"Template {template_id} rejected for project {project_id}")
    else:
        raise HTTPException(status_code=400, detail=f"Invalid action: {request.action}")

    db.commit()
    db.refresh(record)

    return {
        "id": record.id,
        "feedback_id": record.feedback_id,
        "processed": record.processed,
        "promoted": record.promoted,
    }


@router.post("/apply")
async def apply_template(
    project_id: int,
    request: TemplateApplyRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Apply template to project (batch apply to matching paragraphs).

    Scope options:
    - all: Apply to all paragraphs in project
    - chapter: Apply to specific chapters
    - pattern: Apply to paragraphs matching pattern_tag

    Returns a task ID for progress tracking (applied asynchronously).
    """
    # Verify template exists
    template = db.query(FeedbackRecordModel).filter(
        FeedbackRecordModel.id == request.template_id,
        FeedbackRecordModel.project_id == project_id,
    ).first()

    if not template:
        raise HTTPException(status_code=404, detail="Template not found")

    if not template.processed or not template.promoted:
        raise HTTPException(
            status_code=400,
            detail="Template not confirmed. Please confirm template first."
        )

    task_id = f"apply_{project_id}_{request.template_id}_{int(datetime.now().timestamp())}"

    # Schedule background task
    background_tasks.add_task(
        _apply_template_background,
        project_id=project_id,
        template_id=request.template_id,
        scope=request.scope,
        chapter_ids=request.chapter_ids,
        pattern_filter=request.pattern_filter,
        task_id=task_id,
    )

    return {
        "task_id": task_id,
        "status": "queued",
        "scope": request.scope,
    }


async def _apply_template_background(
    project_id: int,
    template_id: int,
    scope: str,
    chapter_ids: Optional[List[int]],
    pattern_filter: Optional[str],
    task_id: str,
):
    """
    Background task for template application.

    This will:
    1. Query matching paragraphs based on scope
    2. For each paragraph, apply the template by creating new records
       (Paragraph update for annotation, TTSEdit for edit, Routing for routing,
       Quality for quality) using the template's corrected_output.
    3. Track progress in a global dictionary.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.exc import SQLAlchemyError
    import os
    from datetime import datetime

    # Import models
    from ..models import Paragraph, TTSEdit, Routing, Quality, FeedbackRecord as FeedbackRecordModel
    from ..schemas import (
        ParagraphAnnotation,
        TtsEditOutput,
        TtsRoutingDecision,
        QualityJudgment,
    )

    # Simple in-memory progress tracking (shared across tasks)
    if not hasattr(_apply_template_background, "progress"):
        _apply_template_background.progress = {}
    _apply_template_background.progress[task_id] = {
        "processed": 0,
        "total": 0,
        "status": "running",
        "error": None,
        "current_paragraph_id": None,
        "current_stage": None,
    }

    # Create a new database session for this background task
    database_url = os.getenv("DATABASE_URL", "sqlite:///./audiobook_studio.db")
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    try:
        # Fetch the template
        template = db.query(FeedbackRecordModel).filter(
            FeedbackRecordModel.id == template_id,
            FeedbackRecordModel.project_id == project_id,
        ).first()
        if not template:
            raise ValueError(f"Template {template_id} not found for project {project_id}")

        if not template.processed or not template.promoted:
            raise ValueError(f"Template {template_id} is not confirmed")

        # Determine target paragraphs
        query = db.query(Paragraph).filter(Paragraph.project_id == project_id)

        if scope == "chapter":
            if chapter_ids:
                query = query.filter(Paragraph.chapter_id.in_(chapter_ids))
            # else: no chapter_ids → treat as "all" for that scope
        elif scope == "pattern":
            # Match paragraphs whose annotation fields overlap with
            # the template's pattern_tags (e.g. "dialogue", "sfx",
            # "emotion:anger", "speaker:Narrator").
            if pattern_filter:
                pattern_tags = [t.strip() for t in pattern_filter.split(",") if t.strip()]
            else:
                pattern_tags = template.pattern_tags or []

            if not pattern_tags:
                # No tags available — fall back to matching all paragraphs
                pass
            else:
                from sqlalchemy import or_
                tag_filters = []
                for tag in pattern_tags:
                    tag_lower = tag.lower()
                    if tag_lower in ("dialogue", "dialog"):
                        tag_filters.append(Paragraph.is_dialogue == True)  # noqa: E712
                    elif tag_lower in ("narration", "narrative"):
                        tag_filters.append(Paragraph.is_dialogue == False)  # noqa: E712
                    elif tag_lower.startswith("emotion:"):
                        emotion_val = tag_lower.split(":", 1)[1]
                        tag_filters.append(Paragraph.emotion.ilike(f"%{emotion_val}%"))
                    elif tag_lower in ("sfx", "sound_effect", "sound-effects"):
                        tag_filters.append(Paragraph.needs_sfx == True)  # noqa: E712
                    elif tag_lower.startswith("speaker:"):
                        speaker_val = tag.split(":", 1)[1]
                        tag_filters.append(
                            Paragraph.speaker_canonical_name.ilike(f"%{speaker_val}%")
                        )
                    else:
                        # Fallback: keyword search in notes column
                        tag_filters.append(Paragraph.notes.ilike(f"%{tag}%"))
                # A paragraph matches if it satisfies ANY of the tag conditions (OR logic)
                if tag_filters:
                    query = query.filter(or_(*tag_filters))
        # else scope == "all": no additional filter

        paragraphs = query.all()
        total = len(paragraphs)

        # Update progress
        _apply_template_background.progress[task_id]["total"] = total

        # Process each paragraph
        for idx, para in enumerate(paragraphs):
            # Update progress
            _apply_template_background.progress[task_id]["processed"] = idx + 1
            _apply_template_background.progress[task_id]["current_paragraph_id"] = para.id
            _apply_template_background.progress[task_id]["current_stage"] = template.stage

            try:
                # Apply template based on stage
                if template.stage == "annotate":
                    _apply_annotation_template(db, para, template.corrected_output)
                elif template.stage == "edit_for_tts":
                    _apply_edit_template(db, para, template.corrected_output)
                elif template.stage == "routing":
                    _apply_routing_template(db, para, template.corrected_output)
                elif template.stage == "quality":
                    _apply_quality_template(db, para, template.corrected_output)
                else:
                    logger.warning(f"Unknown template stage: {template.stage}")
            except Exception as e:
                logger.error(f"Failed to apply template to paragraph {para.id}: {e}")
                # Continue with other paragraphs

        # ── Re-run downstream pipeline stages after corrections ──
        # After applying template, re-run affected downstream stages so
        # the pipeline output stays consistent with the corrected data.
        _rerun_downstream_stages(db, project_id, template.stage, paragraphs)

        # Mark as completed
        _apply_template_background.progress[task_id]["status"] = "completed"
        logger.info(f"Template apply task {task_id} completed")

    except Exception as e:
        logger.error(f"Template apply task {task_id} failed: {e}")
        _apply_template_background.progress[task_id]["status"] = "failed"
        _apply_template_background.progress[task_id]["error"] = str(e)
    finally:
        db.close()


def _apply_annotation_template(db: Session, pa: Paragraph, corrected_output: dict):
    """Apply annotation template: update Paragraph annotation fields."""
    # Map corrected_output to Paragraph fields
    # corrected_output should match ParagraphAnnotation schema
    for field in [
        "speaker_canonical_name",
        "is_dialogue",
        "emotion",
        "emotion_intensity",
        "speech_rate",
        "pitch_shift_semitones",
        "pause_before_ms",
        "pause_after_ms",
        "confidence",
        "needs_sfx",
        "sfx_tags",
        "notes",
    ]:
        if field in corrected_output:
            setattr(pa, field, corrected_output[field])
    # Also update difficulty if present (Paragraph has edit_difficulty and difficulty fields)
    if "difficulty" in corrected_output:
        # Paragraph has both difficulty (legacy) and edit_difficulty
        # We'll set edit_difficulty for consistency with annotation
        pa.edit_difficulty = corrected_output["difficulty"]
    db.add(pa)
    db.commit()


def _apply_edit_template(db: Session, pa: Paragraph, corrected_output: dict):
    """Apply edit template: create new TTSEdit record."""
    # corrected_output should match TtsEditOutput schema
    tts_edit = TTSEdit(
        project_id=pa.project_id,
        chapter_id=pa.chapter_id,
        paragraph_id=pa.id,
        edited_text=corrected_output.get("edited_text", pa.edited_text or pa.text),
        voice=corrected_output.get("voice"),
        changes_made=corrected_output.get("changes_made"),
        forbidden_content_removed=corrected_output.get("forbidden_content_removed"),
        confidence=corrected_output.get("confidence"),
        rationale=corrected_output.get("rationale"),
        difficulty=corrected_output.get("difficulty"),
        forbid_edit=corrected_output.get("forbid_edit", False),
        source=corrected_output.get("source", "template"),
        llm_model=corrected_output.get("llm_model"),
        prompt_version=corrected_output.get("prompt_version"),
    )
    db.add(tts_edit)
    db.commit()
    # Optionally update paragraph's edited_text to latest
    pa.edited_text = tts_edit.edited_text
    pa.edit_changes_made = tts_edit.changes_made
    pa.edit_confidence = tts_edit.confidence
    pa.edit_rationale = tts_edit.rationale
    pa.edit_difficulty = tts_edit.difficulty
    pa.edit_forbid_edit = tts_edit.forbid_edit
    db.add(pa)
    db.commit()


def _apply_routing_template(db: Session, pa: Paragraph, corrected_output: dict):
    """Apply routing template: create new Routing record."""
    # corrected_output should match TtsRoutingDecision schema
    routing = Routing(
        project_id=pa.project_id,
        chapter_id=pa.chapter_id,
        paragraph_id=pa.id,
        engine_choice=corrected_output.get("engine_choice", "kokoro"),
        voice_id=corrected_output.get("voice_id", "kokoro_narrator"),
        prosody_overrides=corrected_output.get("prosody_overrides"),
        fallback_engine=corrected_output.get("fallback_engine", "edge"),
        reasoning=corrected_output.get("reasoning"),
        estimated_cost_usd=corrected_output.get("estimated_cost_usd", 0.0),
        estimated_duration_ms=corrected_output.get("estimated_duration_ms", 5000),
        actual_engine=corrected_output.get("actual_engine"),
        actual_cost_usd=corrected_output.get("actual_cost_usd"),
        actual_duration_ms=corrected_output.get("actual_duration_ms"),
        status=corrected_output.get("status", "completed"),
        voice=corrected_output.get("voice"),
        confidence=corrected_output.get("confidence"),
    )
    db.add(routing)
    db.commit()
    # Update paragraph's routing fields (latest)
    pa.routing_engine = routing.engine_choice
    pa.routing_voice_id = routing.voice_id
    pa.routing_prosody_overrides = routing.prosody_overrides
    pa.routing_fallback = routing.fallback_engine
    pa.routing_reasoning = routing.reasoning
    pa.routing_estimated_cost = routing.estimated_cost_usd
    pa.routing_estimated_duration = routing.estimated_duration_ms
    pa.actual_engine = routing.actual_engine
    pa.actual_cost_usd = routing.actual_cost_usd
    pa.actual_duration_ms = routing.actual_duration_ms
    pa.status = routing.status
    pa.voice = routing.voice
    pa.confidence = routing.confidence
    db.add(pa)
    db.commit()


def _apply_quality_template(db: Session, pa: Paragraph, corrected_output: dict):
    """Apply quality template: create new Quality record linked to latest TTSEdit."""
    # Get latest TTSEdit for this paragraph
    latest_tts_edit = db.query(TTSEdit).filter(
        TTSEdit.paragraph_id == pa.id
    ).order_by(TTSEdit.id.desc()).first()
    if not latest_tts_edit:
        logger.warning(f"No TTSEdit found for paragraph {pa.id}, skipping quality application")
        return

    # corrected_output should match QualityJudgment schema
    quality = Quality(
        project_id=pa.project_id,
        chapter_id=pa.chapter_id,
        paragraph_id=pa.id,
        tts_edit_id=latest_tts_edit.id,
        speaker_clarity=corrected_output.get("speaker_clarity"),
        emotion_match=corrected_output.get("emotion_match"),
        prosody_naturalness=corrected_output.get("prosody_naturalness"),
        text_audio_alignment=corrected_output.get("text_audio_alignment"),
        overall_score=corrected_output.get("overall_score"),
        score=corrected_output.get("score"),
        comments=corrected_output.get("comments"),
        issues=corrected_output.get("issues"),
        fix_suggestions=corrected_output.get("fix_suggestions"),
        needs_regeneration=corrected_output.get("needs_regeneration", False),
        judge_model=corrected_output.get("judge_model"),
        judge_prompt_version=corrected_output.get("judge_prompt_version"),
        audio_file_path=corrected_output.get("audio_file_path"),
        audio_duration_ms=corrected_output.get("audio_duration_ms"),
    )
    db.add(quality)
    db.commit()
    # Update paragraph's quality fields (latest)
    pa.quality_speaker_clarity = quality.speaker_clarity
    pa.quality_emotion_match = quality.emotion_match
    pa.quality_prosody_naturalness = quality.prosody_naturalness
    pa.quality_text_audio_alignment = quality.text_audio_alignment
    pa.quality_overall_score = quality.overall_score
    pa.quality_issues = quality.issues
    pa.quality_fix_suggestions = quality.fix_suggestions
    pa.quality_needs_regeneration = quality.needs_regeneration
    db.add(pa)
    db.commit()


def _rerun_downstream_stages(
    db: Session,
    project_id: int,
    applied_stage: str,
    paragraphs: list,
) -> None:
    """Re-run pipeline stages downstream of the applied template stage.

    After a template correction is applied, downstream stages may produce
    stale results because their input changed. This function re-runs only
    the stages that come AFTER the corrected stage in the pipeline order.

    Pipeline order: annotate → edit → audio_postprocess → synthesize → quality
    """
    from ..pipeline.orchestrator import run_stage

    # Define which stages come after each corrected stage
    downstream_map = {
        "annotate": ["edit", "audio_postprocess", "synthesize", "quality"],
        "edit_for_tts": ["synthesize", "quality"],
        "routing": ["synthesize", "quality"],
        "quality": [],  # Quality is terminal, nothing downstream
    }

    stages_to_rerun = downstream_map.get(applied_stage, [])
    if not stages_to_rerun:
        return

    logger.info(
        "Re-running downstream stages %s after applying %s template to %d paragraphs",
        stages_to_rerun, applied_stage, len(paragraphs),
    )

    for para in paragraphs:
        for stage_name in stages_to_rerun:
            try:
                run_stage(
                    stage_name,
                    db,
                    project_id=project_id,
                    chapter_id=para.chapter_id,
                    paragraph_id=para.id,
                )
                logger.debug(
                    "Re-ran stage '%s' for paragraph %d", stage_name, para.id
                )
            except Exception as e:
                logger.warning(
                    "Downstream re-run failed: stage=%s para=%d error=%s",
                    stage_name, para.id, e,
                )
                # Continue with next stage/paragraph — don't abort the whole batch


@router.get("/apply/{task_id}/progress")
async def get_apply_progress(
    project_id: int,
    task_id: str,
):
    """
    Get progress of template application task.

    Returns progress from in-memory tracking.
    """
    progress = _apply_template_background.progress.get(task_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Task not found")
    return TemplateApplyProgress(**progress)

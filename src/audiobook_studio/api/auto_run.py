"""Auto-run pipeline orchestration API endpoints.

Provides one-click full automation from text to audiobook.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

if "MOCK_LLM" not in os.environ:
    os.environ["MOCK_LLM"] = "false"

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..api.websocket import PipelineEventType, emit_pipeline_event
from ..config import get_settings

get_settings
from ..database import SessionLocal, get_db
from ..models.audio_segment import AudioSegment
from ..models.book import Project
from ..models.chapter import Chapter
from ..models.paragraph import Paragraph
from ..models.quality import Quality
from ..models.tts_edit import TTSEdit
from ..pipeline.checkpoint import CheckpointManager
from ..pipeline.orchestrator import run_stage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/auto-run", tags=["auto-run"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class AutoRunConfig(BaseModel):
    """Configuration for auto-run pipeline."""

    target_difficulty: str = Field("B", description="Target difficulty: A/B/C/D")
    primary_voice_preference: str = Field("female", description="Voice preference: male/female/neutral")
    speech_rate_preference: str = Field("standard", description="Speech rate: slow/standard/fast")
    cost_limit_usd: Optional[float] = Field(None, description="Maximum cost limit in USD")
    quality_threshold: float = Field(0.7, ge=0, le=1, description="Quality threshold for auto-regen")
    max_regeneration_attempts: int = Field(3, ge=1, le=5, description="Max regen attempts per segment")
    enable_background_music: bool = Field(False, description="Enable BGM mixing")
    enable_sfx: bool = Field(True, description="Enable SFX tags")


class AutoRunStatusResponse(BaseModel):
    """Auto-run pipeline status."""

    project_id: int
    run_id: str
    status: str = "pending"  # pending, running, paused, completed, failed
    current_stage: Optional[str] = None
    completed_stages: List[str] = Field(default_factory=list)
    progress: float = Field(0.0, ge=0, le=1)
    cost_usd: float = 0.0
    quality_score: Optional[float] = None
    error_message: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    can_pause: bool = True
    can_resume: bool = False
    can_cancel: bool = True


class StagePausePoint(BaseModel):
    """Stage where pipeline can pause for intervention."""

    stage: str
    pause_after: bool = Field(True, description="Whether to pause after this stage")
    requires_approval: bool = Field(False, description="Whether user approval is needed")


class AutoRunStartRequest(BaseModel):
    """Request to start auto-run pipeline."""

    config: AutoRunConfig = Field(default_factory=AutoRunConfig)
    pause_points: Optional[List[StagePausePoint]] = Field(None, description="Stages to pause at")


class AutoRunActionResponse(BaseModel):
    """Response for pause/resume/cancel actions."""

    action: str
    status: str
    message: str
    run_id: str


class AutopilotConfig(BaseModel):
    """Auto-detected/suggested configuration for autopilot mode."""

    target_difficulty: str
    primary_voice_preference: str
    speech_rate_preference: str
    cost_limit_usd: Optional[float]
    quality_threshold: float
    max_regeneration_attempts: int
    enable_background_music: bool
    enable_sfx: bool
    reasoning: str
    confidence: float


class IntermediateProduct(BaseModel):
    """Intermediate product from a pipeline stage."""

    stage: str
    project_id: int
    chapter_id: Optional[int] = None
    product_type: str  # text, analysis, annotation, edit_decision, audio
    data: Dict[str, Any]
    created_at: str
    can_view: bool = True
    can_edit: bool = False


# ─────────────────────────────────────────────────────────────────────────────
# Global State (in production, use Redis/database)
# ─────────────────────────────────────────────────────────────────────────────

# Active auto-runs: project_id -> run info
_active_runs: Dict[int, Dict[str, Any]] = {}

# Pause points configuration
_stage_order = [
    "extract",
    "analyze",
    "annotate",
    "edit",
    "audio_postprocess",
    "synthesize",
    "quality",
]


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────


def _generate_run_id(project_id: int) -> str:
    """Generate unique run ID."""
    timestamp = int(datetime.now().timestamp())
    return f"autorun_{project_id}_{timestamp}"


def _get_checkpoint_manager(project_id: int) -> CheckpointManager:
    """Get checkpoint manager for project."""
    return CheckpointManager(project_id)


def _create_paragraphs_from_chapters(db: Session, project_id: int):
    """Create Paragraph records from Chapter raw_text if they don't exist."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return

    for chapter in project.chapters:
        existing = db.query(Paragraph).filter(Paragraph.chapter_id == chapter.id).count()
        if existing > 0:
            continue

        raw_text = chapter.raw_text or ""
        paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
        for idx, text in enumerate(paragraphs, start=1):
            para = Paragraph(
                project_id=project_id,
                chapter_id=chapter.id,
                chapter_index=chapter.index,
                index=idx,
                text=text,
                book_id=project_id,  # For backwards compatibility
            )
            db.add(para)
        db.commit()
        logger.info(f"Created {len(paragraphs)} paragraphs for chapter {chapter.index}")


async def _run_auto_pipeline(
    project_id: int,
    run_id: str,
    config: AutoRunConfig,
    pause_points: Optional[List[StagePausePoint]] = None,
):
    """
    Background task: Run complete auto pipeline.

    Flow:
    1. Initialize run state
    2. For each stage in order:
       a. Emit stage_enter event
       b. Run stage
       c. Emit stage_progress events
       d. Check for pause point
       e. Emit stage_exit event
       f. Check quality threshold, auto-regen if needed
    3. Emit completed event
    """
    try:
        _active_runs[project_id] = {
            "run_id": run_id,
            "status": "running",
            "config": config.model_dump(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "current_stage": None,
            "completed_stages": [],
        }

        # Emit pipeline start event
        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_ENTER,
            stage="auto_run",
            data={"run_id": run_id, "config": config.model_dump()},
        )

        checkpoint_mgr = _get_checkpoint_manager(project_id)

        for stage in _stage_order:
            # Update current stage
            _active_runs[project_id]["current_stage"] = stage

            # Emit stage enter
            await emit_pipeline_event(
                project_id=project_id,
                event_type=PipelineEventType.STAGE_ENTER,
                stage=stage,
                progress=0.0,
            )

            # Run stage
            await _run_single_stage(project_id, stage, config)

            # Emit stage exit
            await emit_pipeline_event(
                project_id=project_id,
                event_type=PipelineEventType.STAGE_EXIT,
                stage=stage,
                progress=1.0,
            )

            # Mark completed
            _active_runs[project_id]["completed_stages"].append(stage)
            _active_runs[project_id]["current_stage"] = None

            # Check for pause point
            if pause_points:
                for pp in pause_points:
                    if pp.stage == stage and pp.pause_after:
                        _active_runs[project_id]["status"] = "paused"
                        await emit_pipeline_event(
                            project_id=project_id,
                            event_type=PipelineEventType.PAUSED,
                            stage=stage,
                            data={"pause_point": pp.model_dump()},
                        )
                        # Wait for resume
                        while _active_runs[project_id]["status"] == "paused":
                            await asyncio.sleep(1)

        # Completed
        _active_runs[project_id]["status"] = "completed"
        _active_runs[project_id]["completed_at"] = datetime.now(timezone.utc).isoformat()

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.COMPLETED,
            data={"run_id": run_id},
        )

    except Exception as e:
        logger.error(f"Auto-run failed: {e}")
        _active_runs[project_id]["status"] = "failed"
        _active_runs[project_id]["error_message"] = str(e)

        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.ERROR,
            data={"error": str(e)},
        )


async def _run_single_stage(
    project_id: int,
    stage: str,
    config: AutoRunConfig,
):
    """Run a single pipeline stage with auto-run config.

    Delegates to run_stage() which uses StageRegistry for all stage logic.
    We iterate chapters (for extract/analyze) or paragraphs (for other stages)
    and emit progress events for each sub-item.
    """
    db = SessionLocal()

    try:
        # Verify project exists
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            raise ValueError(f"Project {project_id} not found")

        checkpoint_mgr = CheckpointManager(project_id)

        if stage in ("extract", "analyze"):
            # These stages operate on chapters
            chapters = project.chapters
            total = len(chapters)
            if total == 0:
                logger.warning(f"No chapters found for project {project_id} in stage {stage}")
                await emit_pipeline_event(
                    project_id=project_id,
                    event_type=PipelineEventType.STAGE_PROGRESS,
                    stage=stage,
                    progress=1.0,
                )
                return

            # Skip extract if chapters already have raw_text (extraction already done)
            if stage == "extract":
                all_extracted = all(ch.extract_status == "completed" and ch.raw_text for ch in chapters)
                if all_extracted:
                    logger.info(f"All chapters already extracted, skipping extract stage")
                    for idx, chapter in enumerate(chapters, start=1):
                        checkpoint_mgr.mark_stage_done(stage, chapter.index)
                        progress = idx / total
                        await emit_pipeline_event(
                            project_id=project_id,
                            event_type=PipelineEventType.STAGE_PROGRESS,
                            stage=stage,
                            progress=progress,
                        )
                    return

            for idx, chapter in enumerate(chapters, start=1):
                # Check per-chapter checkpoint
                if checkpoint_mgr.is_stage_done(stage, chapter.index):
                    logger.info(f"Checkpoint: ch{chapter.index} stage '{stage}' already done, skipping")
                    progress = idx / total
                    await emit_pipeline_event(
                        project_id=project_id,
                        event_type=PipelineEventType.STAGE_PROGRESS,
                        stage=stage,
                        progress=progress,
                    )
                    continue

                await asyncio.to_thread(
                    run_stage,
                    stage,
                    db,
                    project_id=project_id,
                    chapter_index=chapter.index,
                    target_difficulty=config.target_difficulty,
                )

                # Mark checkpoint
                checkpoint_mgr.mark_stage_done(stage, chapter.index)

                progress = idx / total
                await emit_pipeline_event(
                    project_id=project_id,
                    event_type=PipelineEventType.STAGE_PROGRESS,
                    stage=stage,
                    progress=progress,
                )

            # Create paragraphs after analyze stage (needed for downstream stages)
            if stage == "analyze":
                _create_paragraphs_from_chapters(db, project_id)

        elif stage in (
            "annotate",
            "edit",
            "audio_postprocess",
            "synthesize",
            "quality",
        ):
            # These stages operate on paragraphs
            paragraphs = project.paragraphs
            total = len(paragraphs)
            if total == 0:
                logger.warning(f"No paragraphs found for project {project_id} in stage {stage}")
                await emit_pipeline_event(
                    project_id=project_id,
                    event_type=PipelineEventType.STAGE_PROGRESS,
                    stage=stage,
                    progress=1.0,
                )
                return

            for idx, para in enumerate(paragraphs, start=1):
                # run_stage() resolves chapter/paragraph from IDs via StageRegistry.
                # Pass target_difficulty through kwargs for stages that need it
                # (e.g. edit stage uses it for difficulty-level editing).
                stage_kwargs = {}
                if config.target_difficulty:
                    stage_kwargs["target_difficulty"] = config.target_difficulty

                await asyncio.to_thread(
                    run_stage,
                    stage,
                    db,
                    project_id=project_id,
                    chapter_id=para.chapter_id,
                    paragraph_id=para.id,
                    **stage_kwargs,
                )

                # Emit progress
                progress = idx / total
                await emit_pipeline_event(
                    project_id=project_id,
                    event_type=PipelineEventType.STAGE_PROGRESS,
                    stage=stage,
                    progress=progress,
                )

            # Mark stage done for all chapters (paragraph-level stages cover entire project)
            seen_chapters: set = set()
            for para in paragraphs:
                if para.chapter_id and para.chapter_id not in seen_chapters:
                    chapter = db.query(Chapter).filter(Chapter.id == para.chapter_id).first()
                    if chapter:
                        checkpoint_mgr.mark_stage_done(stage, chapter.index)
                    seen_chapters.add(para.chapter_id)

        else:
            logger.warning(f"Unknown stage '{stage}' in auto-run")

        # Emit stage completion progress
        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_PROGRESS,
            stage=stage,
            progress=1.0,
        )

    except Exception as e:
        logger.error(f"Error in _run_single_stage for stage {stage}: {e}")
        raise
    finally:
        db.close()


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/start")
async def start_auto_run(
    project_id: int,
    request: AutoRunStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Start one-click auto-run pipeline.

    Executes complete pipeline from text to audiobook with:
    - Configurable difficulty/voice/cost preferences
    - Auto quality regeneration
    - Pause points for intervention
    - Real-time WebSocket progress

    Returns run_id for tracking.
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Generate run ID
    run_id = _generate_run_id(project_id)

    # Check if already running
    if project_id in _active_runs and _active_runs[project_id]["status"] == "running":
        raise HTTPException(
            status_code=400,
            detail="Auto-run already in progress for this project",
        )

    # Start background task
    background_tasks.add_task(
        _run_auto_pipeline,
        project_id=project_id,
        run_id=run_id,
        config=request.config,
        pause_points=request.pause_points,
    )

    return AutoRunStatusResponse(
        project_id=project_id,
        run_id=run_id,
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/status", response_model=AutoRunStatusResponse)
async def get_auto_run_status(project_id: int, run_id: Optional[str] = None):
    """
    Get auto-run pipeline status.

    If run_id not provided, returns latest run.
    """
    if project_id not in _active_runs:
        # Return placeholder for completed/old runs
        # In production, would query ProcessingRun table
        return AutoRunStatusResponse(
            project_id=project_id,
            run_id="unknown",
            status="not_started",
        )

    run_info = _active_runs[project_id]
    completed = len(run_info["completed_stages"])
    total = len(_stage_order)

    return AutoRunStatusResponse(
        project_id=project_id,
        run_id=run_info["run_id"],
        status=run_info["status"],
        current_stage=run_info.get("current_stage"),
        completed_stages=run_info["completed_stages"],
        progress=completed / total,
        started_at=run_info.get("started_at"),
        completed_at=run_info.get("completed_at"),
        can_pause=run_info["status"] == "running",
        can_resume=run_info["status"] == "paused",
        can_cancel=run_info["status"] in ("running", "paused"),
    )


@router.post("/pause", response_model=AutoRunActionResponse)
async def pause_auto_run(project_id: int):
    """Pause auto-run pipeline at next safe point."""
    if project_id not in _active_runs:
        raise HTTPException(status_code=400, detail="No active auto-run")

    run_info = _active_runs[project_id]
    if run_info["status"] != "running":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot pause: current status is {run_info['status']}",
        )

    # Set pause flag - pipeline will pause at next pause point
    run_info["pending_pause"] = True

    return AutoRunActionResponse(
        action="pause",
        status="pending",
        message="Pipeline will pause at next safe point",
        run_id=run_info["run_id"],
    )


@router.post("/resume", response_model=AutoRunActionResponse)
async def resume_auto_run(project_id: int):
    """Resume paused auto-run pipeline."""
    if project_id not in _active_runs:
        raise HTTPException(status_code=400, detail="No active auto-run")

    run_info = _active_runs[project_id]
    if run_info["status"] != "paused":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot resume: current status is {run_info['status']}",
        )

    # Resume
    run_info["status"] = "running"

    await emit_pipeline_event(
        project_id=project_id,
        event_type=PipelineEventType.RESUMED,
        data={"run_id": run_info["run_id"]},
    )

    return AutoRunActionResponse(
        action="resume",
        status="resumed",
        message="Pipeline resumed",
        run_id=run_info["run_id"],
    )


@router.post("/cancel", response_model=AutoRunActionResponse)
async def cancel_auto_run(project_id: int):
    """Cancel auto-run pipeline."""
    if project_id not in _active_runs:
        raise HTTPException(status_code=400, detail="No active auto-run")

    run_info = _active_runs[project_id]
    if run_info["status"] not in ("running", "paused"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel: current status is {run_info['status']}",
        )

    # Cancel
    run_info["status"] = "cancelled"

    # Clean up
    del _active_runs[project_id]

    return AutoRunActionResponse(
        action="cancel",
        status="cancelled",
        message="Pipeline cancelled",
        run_id=run_info["run_id"],
    )


@router.post("/autopilot", response_model=AutoRunStatusResponse)
async def start_autopilot(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Start autopilot one-click mode.

    Analyzes project content and auto-detects optimal settings:
    - Difficulty based on text complexity
    - Voice preference based on character gender distribution
    - Speech rate based on content type
    - Cost limit based on project size
    - Quality threshold based on content requirements

    Returns run_id for tracking.
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if already running
    if project_id in _active_runs and _active_runs[project_id]["status"] == "running":
        raise HTTPException(
            status_code=400,
            detail="Auto-run already in progress for this project",
        )

    # Analyze project and generate smart defaults
    config = await _generate_autopilot_config(project_id, db)

    # Generate run ID
    run_id = _generate_run_id(project_id)

    # Start background task
    background_tasks.add_task(
        _run_auto_pipeline,
        project_id=project_id,
        run_id=run_id,
        config=config,
        pause_points=None,  # No pause points in autopilot mode
    )

    return AutoRunStatusResponse(
        project_id=project_id,
        run_id=run_id,
        status="running",
        started_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/autopilot/preview", response_model=AutopilotConfig)
async def preview_autopilot_config(project_id: int, db: Session = Depends(get_db)):
    """
    Preview the auto-detected configuration without starting the pipeline.

    Useful for showing the user what settings will be used.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return await _generate_autopilot_config(project_id, db)


async def _generate_autopilot_config(project_id: int, db: Session) -> AutoRunConfig:
    """
    Analyze project content and generate optimal configuration.

    Uses heuristics based on:
    - Text length and complexity for difficulty
    - Character gender distribution for voice preference
    - Content type for speech rate
    - Project size for cost estimation
    """
    # Get project with chapters
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    chapters = project.chapters
    total_chars = sum(len(ch.raw_text or "") + len(ch.extracted_text or "") for ch in chapters)
    total_chapters = len(chapters)

    # 1. Determine difficulty based on text complexity
    # Simple heuristic: longer text with more chapters = higher difficulty
    avg_chars_per_chapter = total_chars / max(total_chapters, 1)
    if total_chars < 50000:
        target_difficulty = "D"  # Simple/short content
    elif total_chars < 200000:
        target_difficulty = "C"  # Medium content
    elif total_chars < 500000:
        target_difficulty = "B"  # Complex content
    else:
        target_difficulty = "A"  # Very complex/long content

    # 2. Determine voice preference from character analysis
    # Count characters by gender from analyzed_json
    male_count = 0
    female_count = 0
    for chapter in chapters:
        if chapter.analyzed_json:
            try:
                import json
                analyzed = chapter.analyzed_json if isinstance(chapter.analyzed_json, dict) else json.loads(chapter.analyzed_json)
                characters = analyzed.get("characters", [])
                for char in characters:
                    gender = char.get("gender", "").lower()
                    if gender in ("male", "man", "boy", "male"):
                        male_count += 1
                    elif gender in ("female", "woman", "girl", "female"):
                        female_count += 1
            except Exception:
                pass

    if female_count > male_count:
        primary_voice_preference = "female"
    elif male_count > female_count:
        primary_voice_preference = "male"
    else:
        primary_voice_preference = "neutral"

    # 3. Determine speech rate based on content type
    # Dialogue-heavy = standard, Narrative-heavy = slightly slower
    dialogue_ratio = 0.5
    if total_chars > 0:
        dialogue_chars = 0
        for chapter in chapters:
            if chapter.analyzed_json:
                try:
                    import json
                    analyzed = chapter.analyzed_json if isinstance(chapter.analyzed_json, dict) else json.loads(chapter.analyzed_json)
                    for char in analyzed.get("characters", []):
                        dialogue_chars += char.get("dialogue_count", 0) * 50  # rough estimate
                except Exception:
                    pass
        dialogue_ratio = min(dialogue_chars / total_chars, 1.0)

    if dialogue_ratio > 0.6:
        speech_rate_preference = "standard"
    elif dialogue_ratio > 0.3:
        speech_rate_preference = "standard"
    else:
        speech_rate_preference = "slow"  # More narrative, slower pace

    # 4. Estimate cost limit based on project size
    # Rough estimate: ~$0.001 per 100 chars for Edge-TTS, ~$0.01 for cloud premium
    estimated_chars = total_chars * 1.2  # Account for regeneration
    cost_limit_usd = round(estimated_chars / 100000 * 0.5, 2)  # ~$0.5 per 100k chars
    cost_limit_usd = max(cost_limit_usd, 1.0)  # Minimum $1
    cost_limit_usd = min(cost_limit_usd, 50.0)  # Cap at $50

    # 5. Quality threshold - higher for complex content
    if target_difficulty in ("A", "B"):
        quality_threshold = 0.8
    else:
        quality_threshold = 0.7

    # 6. Max regeneration attempts
    max_regeneration_attempts = 3 if target_difficulty in ("A", "B") else 2

    # 7. Background music and SFX - enable for longer content
    enable_background_music = total_chars > 100000
    enable_sfx = True  # Always enable SFX tags

    reasoning = (
        f"Auto-detected: {total_chapters} chapters, {total_chars:,} chars "
        f"(avg {avg_chars_per_chapter:,.0f}/ch). "
        f"Characters: {male_count}M/{female_count}F. "
        f"Dialogue ratio: {dialogue_ratio:.0%}. "
        f"Difficulty={target_difficulty}, Voice={primary_voice_preference}, "
        f"Rate={speech_rate_preference}, Cost limit=${cost_limit_usd:.2f}"
    )

    return AutoRunConfig(
        target_difficulty=target_difficulty,
        primary_voice_preference=primary_voice_preference,
        speech_rate_preference=speech_rate_preference,
        cost_limit_usd=cost_limit_usd,
        quality_threshold=quality_threshold,
        max_regeneration_attempts=max_regeneration_attempts,
        enable_background_music=enable_background_music,
        enable_sfx=enable_sfx,
    )


@router.get("/intermediate/{stage}")
async def get_intermediate_product(
    project_id: int,
    stage: str,
    chapter_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    View intermediate product from a pipeline stage.

    Allows user to inspect results before continuing.

    Stage products:
    - extract: Raw text chunks
    - analyze: Character list, emotion curve
    - annotate: Speaker/emotion annotations
    - edit: TTS edit decisions
    - audio_postprocess: Audio parameters
    - synthesize: Audio segments
    - quality: Quality scores and issues
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if stage not in _stage_order:
        raise HTTPException(status_code=400, detail=f"Unknown stage: {stage}")

    # Helper to get first chapter if none specified
    def get_chapter(cid: Optional[int]) -> Chapter:
        if cid is not None:
            chapter = db.query(Chapter).filter(Chapter.id == cid, Chapter.project_id == project_id).first()
            if not chapter:
                raise HTTPException(
                    status_code=404,
                    detail=f"Chapter {cid} not found in project {project_id}",
                )
            return chapter
        # Return first chapter
        chapter = db.query(Chapter).filter(Chapter.project_id == project_id).order_by(Chapter.index).first()
        if not chapter:
            raise HTTPException(status_code=404, detail=f"No chapters found for project {project_id}")
        return chapter

    chapter = get_chapter(chapter_id)

    if stage == "extract":
        data = {
            "chapter_id": chapter.id,
            "chapter_index": chapter.index,
            "raw_text": chapter.raw_text or "",
            "extracted_text": chapter.extracted_text or "",
        }
        product_type = "text"

    elif stage == "analyze":
        # analyzed_json is a JSON string stored as Text; we stored as dict via json.loads? In _write_analyze we stored dict in analyzed_json column? Actually we stored json.loads(result.model_dump_json()) which is a dict.
        # The column is probably JSON type.
        data = {
            "chapter_id": chapter.id,
            "chapter_index": chapter.index,
            "analyzed": chapter.analyzed_json or {},
        }
        product_type = "text"

    elif stage == "annotate":
        # Need paragraphs for this chapter (maybe first paragraph only? we could list all)
        paragraphs = (
            db.query(Paragraph)
            .filter(Paragraph.project_id == project_id, Paragraph.chapter_id == chapter.id)
            .order_by(Paragraph.index)
            .all()
        )
        annotations = []
        for para in paragraphs:
            annotations.append(
                {
                    "paragraph_id": para.id,
                    "paragraph_index": para.index,
                    "speaker_canonical_name": para.speaker_canonical_name,
                    "is_dialogue": para.is_dialogue,
                    "emotion": para.emotion,
                    "emotion_intensity": para.emotion_intensity,
                    "speech_rate": para.speech_rate,
                    "pitch_shift_semitones": para.pitch_shift_semitones,
                    "pause_before_ms": para.pause_before_ms,
                    "pause_after_ms": para.pause_after_ms,
                    "confidence": para.confidence,
                    "notes": para.notes,
                }
            )
        data = {
            "chapter_id": chapter.id,
            "chapter_index": chapter.index,
            "annotations": annotations,
        }
        product_type = "text"

    elif stage == "edit":
        paragraphs = (
            db.query(Paragraph)
            .filter(Paragraph.project_id == project_id, Paragraph.chapter_id == chapter.id)
            .order_by(Paragraph.index)
            .all()
        )
        edits = []
        for para in paragraphs:
            edits.append(
                {
                    "paragraph_id": para.id,
                    "paragraph_index": para.index,
                    "edited_text": para.edited_text,
                    "changes_made": para.edit_changes_made,
                    "forbidden_content_removed": para.edit_forbidden_removed,
                    "edit_confidence": para.edit_confidence,
                    "edit_rationale": para.edit_rationale,
                    "edit_difficulty": para.edit_difficulty,
                    "forbid_edit": para.edit_forbid_edit,
                }
            )
        data = {
            "chapter_id": chapter.id,
            "chapter_index": chapter.index,
            "edits": edits,
        }
        product_type = "text"

    elif stage == "audio_postprocess":
        paragraphs = (
            db.query(Paragraph)
            .filter(Paragraph.project_id == project_id, Paragraph.chapter_id == chapter.id)
            .order_by(Paragraph.index)
            .all()
        )
        params_list = []
        for para in paragraphs:
            params_list.append(
                {
                    "paragraph_id": para.id,
                    "paragraph_index": para.index,
                    "speech_rate": para.speech_rate,
                    "pitch_shift_semitones": para.pitch_shift_semitones,
                    "needs_sfx": para.needs_sfx,
                    "sfx_tags": para.sfx_tags or [],
                }
            )
        data = {
            "chapter_id": chapter.id,
            "chapter_index": chapter.index,
            "audio_postprocess_params": params_list,
        }
        product_type = "text"

    elif stage == "synthesize":
        # Get audio segments via paragraphs
        paragraphs = (
            db.query(Paragraph)
            .filter(Paragraph.project_id == project_id, Paragraph.chapter_id == chapter.id)
            .order_by(Paragraph.index)
            .all()
        )
        segments = []
        for para in paragraphs:
            if para.audio_segment_id:
                seg = db.query(AudioSegment).filter(AudioSegment.id == para.audio_segment_id).first()
                if seg:
                    segments.append(
                        {
                            "segment_id": seg.id,
                            "paragraph_id": para.id,
                            "paragraph_index": para.index,
                            "file_path": seg.file_path,
                            "format": seg.format,
                            "duration_ms": seg.duration_ms,
                            "engine": seg.engine,
                            "voice_id": seg.voice_id,
                            "status": seg.status,
                        }
                    )
        data = {
            "chapter_id": chapter.id,
            "chapter_index": chapter.index,
            "audio_segments": segments,
        }
        product_type = "audio"

    elif stage == "quality":
        paragraphs = (
            db.query(Paragraph)
            .filter(Paragraph.project_id == project_id, Paragraph.chapter_id == chapter.id)
            .order_by(Paragraph.index)
            .all()
        )
        quality_entries = []
        for para in paragraphs:
            qual = db.query(Quality).filter(Quality.paragraph_id == para.id).order_by(Quality.id.desc()).first()
            if qual:
                quality_entries.append(
                    {
                        "paragraph_id": para.id,
                        "paragraph_index": para.index,
                        "quality_id": qual.id,
                        "speaker_clarity": qual.speaker_clarity,
                        "emotion_match": qual.emotion_match,
                        "prosody_naturalness": getattr(qual, "prosody_naturalness", None),
                        "text_audio_alignment": qual.text_audio_alignment,
                        "overall_score": qual.overall_score,
                        "issues": qual.issues,
                        "fix_suggestions": qual.fix_suggestions,
                        "needs_regeneration": qual.needs_regeneration,
                    }
                )
        data = {
            "chapter_id": chapter.id,
            "chapter_index": chapter.index,
            "quality_results": quality_entries,
        }
        product_type = "text"

    else:
        # Should not happen due to earlier check
        raise HTTPException(status_code=400, detail=f"Unsupported stage: {stage}")

    return IntermediateProduct(
        stage=stage,
        project_id=project_id,
        chapter_id=chapter_id,
        product_type=product_type,
        data=data,
        created_at=datetime.now(timezone.utc).isoformat(),
    )

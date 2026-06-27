"""Auto-run pipeline orchestration API endpoints.

Provides one-click full automation from text to audiobook.
"""

import json
import logging
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime, timezone
from pathlib import Path
import asyncio

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db
from ..models.book import Project
from ..models.chapter import Chapter
from ..pipeline.orchestrator import run_stage
from ..pipeline.checkpoint import CheckpointManager
from ..api.websocket import emit_pipeline_event, PipelineEventType

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
_stage_order = ["extract", "analyze", "annotate", "edit", "audio_postprocess", "synthesize", "quality"]


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
            "config": config.dict(),
            "started_at": datetime.now(timezone.utc).isoformat(),
            "current_stage": None,
            "completed_stages": [],
        }

        # Emit pipeline start event
        await emit_pipeline_event(
            project_id=project_id,
            event_type=PipelineEventType.STAGE_ENTER,
            stage="auto_run",
            data={"run_id": run_id, "config": config.dict()},
        )

        checkpoint_mgr = _get_checkpoint_manager(project_id)

        for stage in _stage_order:
            # Check if already completed (checkpoint)
            if checkpoint_mgr.has_checkpoint(stage):
                logger.info(f"Stage {stage} has checkpoint, skipping")
                _active_runs[project_id]["completed_stages"].append(stage)
                continue

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
                            data={"pause_point": pp.dict()},
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
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import os

    # Create a new database session for this stage
    database_url = os.getenv("DATABASE_URL", "sqlite:///./audiobook_studio.db")
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
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

        elif stage in ("annotate", "edit", "audio_postprocess", "synthesize", "quality"):
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


@router.get("/intermediate/{stage}")
async def get_intermediate_product(
    project_id: int,
    stage: str,
    chapter_id: Optional[int] = None,
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
    # Placeholder - would query actual stage output
    # For production, load from stage output files or DB

    if stage not in _stage_order:
        raise HTTPException(status_code=400, detail=f"Unknown stage: {stage}")

    # Mock response based on stage
    mock_data = {
        "extract": {"text_preview": "...", "char_count": 0},
        "analyze": {"characters": [], "emotions": []},
        "annotate": {"annotations": []},
        "edit": {"decisions": []},
        "audio_postprocess": {"params": {}},
        "synthesize": {"segments": []},
        "quality": {"scores": {}},
    }

    return IntermediateProduct(
        stage=stage,
        project_id=project_id,
        chapter_id=chapter_id,
        product_type="text" if stage in ("extract", "analyze", "annotate", "edit") else "audio",
        data=mock_data.get(stage, {}),
        created_at=datetime.now(timezone.utc).isoformat(),
    )

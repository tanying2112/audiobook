"""Pipeline orchestrator — wraps each stage with DB persistence and feedback collection.

Keeps pipeline stages pure (no DB awareness) by providing a coordinator
that calls the stage, writes results to the database, and returns the result.

Usage::

    from src.audiobook_studio.pipeline.orchestrator import run_stage

    result = run_stage("extract", session, project_id=123, input=...)
    result = run_stage("annotate", session, project_id=123, chapter_id=1, input=...)
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Union

from sqlalchemy import select
import asyncio
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.websocket import get_pause_event, is_paused, pause_check, PipelineEventType, emit_pipeline_event
from ..pipeline.progress_emitter import (
    emit_stage_enter,
    emit_stage_progress,
    emit_stage_exit,
    emit_chapter_complete,
    emit_paragraph_complete,
    emit_error,
    emit_pipeline_completed,
)
from ..exceptions import AudiobookError, DataLoadError, DataPersistError, StageExecutionError
from ..models import AudioSegment as AudioSegmentModel
from ..models import Chapter, Paragraph, Quality, TTSEdit
from ..schemas import (
    AudioPostProcessParams,
    BookAnalysisOutput,
    ExtractionResult,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
    TtsRoutingDecision,
)
from .analyze_structure import AnalyzeStructurePipeline
from .annotate_paragraph import AnnotateParagraphPipeline
from .audio_postprocess import AudioPostProcessor
from .checkpoint import CheckpointManager
from .edit_for_tts import EditForTtsPipeline
from .extract import ExtractPipeline
from .feedback_collector import FeedbackCollector, StageCapture
from .persistence import (
    write_audio_postprocess,
    write_analyze,
    write_annotate,
    write_edit,
    write_extract,
    write_quality,
    write_synthesize,
)
from .quality_check import QualityCheckPipeline
from .stage_registry import StageRegistry
from .synthesize import SynthesizePipeline

# Backward compatibility aliases for tests
_write_extract = write_extract
_write_analyze = write_analyze
_write_annotate = write_annotate
_write_edit = write_edit
_write_synthesize = write_synthesize
_write_quality = write_quality
_write_audio_postprocess = write_audio_postprocess

# Telemetry integration
try:
    from ..monitoring.telemetry import TelemetryCollector, get_telemetry_collector

    _TELEMETRY_AVAILABLE = True
except ImportError:
    _TELEMETRY_AVAILABLE = False

logger = logging.getLogger(__name__)


# ── Monitoring / Feedback Hooks (Observer Pattern) ──────────────────────────
# Non-invasive callbacks for observability. Called at stage boundaries.
# Extremely lightweight: fire-and-forget, exceptions swallowed, no blocking.

# Internal hook registry
_stage_hooks: List[Callable[..., None]] = []
_pipeline_hooks: List[Callable[..., None]] = []

# Async hook registries (for async hooks that need to be awaited)
_async_stage_hooks: List[Callable[..., Any]] = []
_async_pipeline_hooks: List[Callable[..., Any]] = []


def register_stage_hook(hook: Callable[..., None]) -> None:
    """Register a stage lifecycle hook.

    Hook signature:
        hook(event: str, stage: str, context: dict, result: Any = None, error: Exception = None)

    Events:
        - "stage_enter": Before stage execution
        - "stage_exit": After stage execution (success or error)

    Hooks MUST be non-blocking. Exceptions are caught and logged only.
    """
    if hook not in _stage_hooks:
        _stage_hooks.append(hook)
        logger.debug("Registered stage hook: %s", hook)


def register_async_stage_hook(hook: Callable[..., Any]) -> None:
    """Register an async stage lifecycle hook.

    Hook signature (async):
        hook(event: str, stage: str, context: dict, result: Any = None, error: Exception = None)

    Events:
        - "stage_enter": Before stage execution
        - "stage_exit": After stage execution (success or error)

    Hooks are scheduled as fire-and-forget tasks. Exceptions are caught and logged only.
    """
    if hook not in _async_stage_hooks:
        _async_stage_hooks.append(hook)
        logger.debug("Registered async stage hook: %s", hook)


def register_pipeline_hook(hook: Callable[..., None]) -> None:
    """Register a pipeline-level lifecycle hook.

    Hook signature:
        hook(event: str, context: dict, result: Any = None, error: Exception = None)

    Events:
        - "pipeline_start": Before entire pipeline (when running multiple stages)
        - "pipeline_end": After entire pipeline
    """
    if hook not in _pipeline_hooks:
        _pipeline_hooks.append(hook)
        logger.debug("Registered pipeline hook: %s", hook)


def register_async_pipeline_hook(hook: Callable[..., Any]) -> None:
    """Register an async pipeline-level lifecycle hook.

    Hook signature (async):
        hook(event: str, context: dict, result: Any = None, error: Exception = None)

    Events:
        - "pipeline_start": Before entire pipeline
        - "pipeline_end": After entire pipeline

    Hooks are scheduled as fire-and-forget tasks. Exceptions are caught and logged only.
    """
    if hook not in _async_pipeline_hooks:
        _async_pipeline_hooks.append(hook)
        logger.debug("Registered async pipeline hook: %s", hook)


def _emit_stage_enter(stage: str, context: Dict[str, Any]) -> None:
    """Fire stage-enter hooks (non-blocking)."""
    for h in _stage_hooks:
        try:
            h("stage_enter", stage, context, None, None)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Stage hook error (enter): %s", e)


def _emit_stage_exit(
    stage: str,
    context: Dict[str, Any],
    result: Any = None,
    error: Exception | None = None,
) -> None:
    """Fire stage-exit hooks (non-blocking)."""
    for h in _stage_hooks:
        try:
            h("stage_exit", stage, context, result, error)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Stage hook error (exit): %s", e)


def _emit_pipeline_start(context: Dict[str, Any]) -> None:
    """Fire pipeline-start hooks (non-blocking)."""
    for h in _pipeline_hooks:
        try:
            h("pipeline_start", context, None, None)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Pipeline hook error (start): %s", e)


def _emit_pipeline_end(context: Dict[str, Any], result: Any = None, error: Exception | None = None) -> None:
    """Fire pipeline-end hooks (non-blocking)."""
    for h in _pipeline_hooks:
        try:
            h("pipeline_end", context, result, error)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Pipeline hook error (end): %s", e)


async def _emit_async_stage_enter(stage: str, context: Dict[str, Any]) -> None:
    """Fire async stage-enter hooks (non-blocking, scheduled as tasks)."""
    for h in _async_stage_hooks:
        try:
            asyncio.create_task(h("stage_enter", stage, context, None, None))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Async stage hook error (enter): %s", e)


async def _emit_async_stage_exit(
    stage: str,
    context: Dict[str, Any],
    result: Any = None,
    error: Exception | None = None,
) -> None:
    """Fire async stage-exit hooks (non-blocking, scheduled as tasks)."""
    for h in _async_stage_hooks:
        try:
            asyncio.create_task(h("stage_exit", stage, context, result, error))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Async stage hook error (exit): %s", e)


async def _emit_async_pipeline_start(context: Dict[str, Any]) -> None:
    """Fire async pipeline-start hooks (non-blocking, scheduled as tasks)."""
    for h in _async_pipeline_hooks:
        try:
            asyncio.create_task(h("pipeline_start", context, None, None))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Async pipeline hook error (start): %s", e)


async def _emit_async_pipeline_end(
    context: Dict[str, Any],
    result: Any = None,
    error: Exception | None = None,
) -> None:
    """Fire async pipeline-end hooks (non-blocking, scheduled as tasks)."""
    for h in _async_pipeline_hooks:
        try:
            asyncio.create_task(h("pipeline_end", context, result, error))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Async pipeline hook error (end): %s", e)


# Placeholder logger.info hooks for observability (can be overridden by external registration)
def _default_stage_hook(
    event: str,
    stage: str,
    context: Dict[str, Any],
    result: Any = None,
    error: Exception | None = None,
) -> None:
    """Default logging hook - logs stage lifecycle events at INFO level."""
    if event == "stage_enter":
        logger.info("[HOOK] ▶ Stage ENTER: %s | ctx_keys=%s", stage, list(context.keys()))
    elif event == "stage_exit":
        status = "ERROR" if error else "OK"
        logger.info(
            "[HOOK] ■ Stage EXIT: %s [%s] | result_type=%s",
            stage,
            status,
            type(result).__name__,
        )


# Auto-register default logger hook (can be disabled by clearing _stage_hooks)
_stage_hooks.append(_default_stage_hook)

# ── WebSocket Progress Emitter Hook ────────────────────────────────────────
# Emit real-time progress events to WebSocket clients
async def _websocket_stage_hook(
    event: str,
    stage: str,
    context: Dict[str, Any],
    result: Any = None,
    error: Exception | None = None,
) -> None:
    """WebSocket progress emitter hook."""
    project_id = context.get("project_id")
    chapter_index = context.get("chapter_index")
    chapter_id = context.get("chapter_id")
    paragraph_index = context.get("paragraph_index")
    paragraph_id = context.get("paragraph_id")

    if not project_id:
        return

    try:
        if event == "stage_enter":
            total_items = context.get("kwargs", {}).get("total_items")
            await emit_stage_enter(
                stage=stage,
                project_id=project_id,
                chapter_index=chapter_index,
                chapter_id=chapter_id,
                paragraph_index=paragraph_index,
                paragraph_id=paragraph_id,
                total_items=total_items,
            )
        elif event == "stage_exit":
            success = error is None
            error_message = str(error) if error else None
            await emit_stage_exit(
                stage=stage,
                project_id=project_id,
                chapter_index=chapter_index,
                chapter_id=chapter_id,
                paragraph_index=paragraph_index,
                success=success,
                error_message=error_message,
            )
    except Exception as e:
        # Never let hook errors break the pipeline
        logger.warning(f"WebSocket hook error: {e}")


# Register WebSocket hook - async version
_async_stage_hooks.append(_websocket_stage_hook)

# ── Telemetry Integration ──────────────────────────────────────────────────
# Functions to initialize and register the telemetry collector as pipeline hooks

_telemetry_collector: Optional[TelemetryCollector] = None


def init_telemetry(
    project_id: str,
    pipeline_id: Optional[str] = None,
    output_dir: Optional[str] = None,
    llm_router: Optional[Any] = None,
    synthesize_pipeline: Optional[Any] = None,
) -> Optional[TelemetryCollector]:
    """Initialize the telemetry collector and register it as pipeline hooks.

    Returns the TelemetryCollector instance if telemetry is available, None otherwise.
    """
    global _telemetry_collector
    if not _TELEMETRY_AVAILABLE:
        logger.debug("Telemetry module not available, skipping initialization")
        return None

    # Shutdown existing telemetry if already initialized
    if _telemetry_collector:
        logger.debug("Telemetry already initialized, shutting down existing collector")
        shutdown_telemetry()

    _telemetry_collector = TelemetryCollector(
        project_id=project_id,
        pipeline_id=pipeline_id,
        output_dir=output_dir,
        llm_router=llm_router,
        synthesize_pipeline=synthesize_pipeline,
    )

    # Register as pipeline hooks
    register_pipeline_hook(_telemetry_collector.on_pipeline_start)
    register_pipeline_hook(_telemetry_collector.on_pipeline_end)
    register_stage_hook(_telemetry_collector.on_stage_enter)
    register_stage_hook(_telemetry_collector.on_stage_exit)

    logger.info(f"Telemetry collector initialized for project={project_id}")
    return _telemetry_collector


def get_telemetry() -> Optional[TelemetryCollector]:
    """Get the current telemetry collector instance."""
    return _telemetry_collector


def shutdown_telemetry() -> Optional[Dict[str, Any]]:
    """Shutdown telemetry and return final summary."""
    global _telemetry_collector
    if _telemetry_collector:
        summary = _telemetry_collector.get_summary()
        # Unregister hooks - use indices to avoid bound method identity issues
        global _pipeline_hooks, _stage_hooks
        global _async_pipeline_hooks, _async_stage_hooks
        _pipeline_hooks[:] = [h for h in _pipeline_hooks
                          if h not in (_telemetry_collector.on_pipeline_start, _telemetry_collector.on_pipeline_end)]
        _stage_hooks[:] = [h for h in _stage_hooks
                       if h not in (_telemetry_collector.on_stage_enter, _telemetry_collector.on_stage_exit)]
        _async_pipeline_hooks[:] = [h for h in _async_pipeline_hooks
                                if h not in (_telemetry_collector.on_pipeline_start, _telemetry_collector.on_pipeline_end)]
        _async_stage_hooks[:] = [h for h in _async_stage_hooks
                            if h not in (_telemetry_collector.on_stage_enter, _telemetry_collector.on_stage_exit)]
        _telemetry_collector = None
        return summary
    return None


# ── Public API ────────────────────────────────────────────────────────────────


async def run_stage(
    stage: str,
    db: Union[Session, AsyncSession],
    *,
    project_id: Optional[int] = None,
    chapter_index: Optional[int] = None,
    chapter_id: Optional[int] = None,
    paragraph_index: Optional[int] = None,
    paragraph_id: Optional[int] = None,
    feedback_collector: Optional[FeedbackCollector] = None,
    **kwargs: Any,
) -> Any:
    """Run a pipeline stage and persist its output to the database.

    Parameters
    ----------
    stage:
        One of ``"extract"``, ``"analyze"``, ``"annotate"``, ``"edit"``,
        ``"audio_postprocess"``, ``"synthesize"``, ``"quality"``.
    db:
        SQLAlchemy session for persistence (sync or async).
    project_id:
        Required for stages that create/update Project-level records.
    chapter_index:
        1-based chapter number (required for extract, analyze).
    chapter_id:
        DB primary key of the Chapter (required for annotate/edit/synthesize/quality
        if chapter resolution is needed).
    paragraph_index:
        1-based paragraph index (required for annotate/edit/synthesize/quality).
    paragraph_id:
        DB primary key of the Paragraph (alternative to paragraph_index).
    feedback_collector:
        Optional FeedbackCollector for capturing LLM inputs/outputs for self-iteration.
    **kwargs:
        Forwarded to the pipeline stage's ``run()`` method.

    Returns
    -------
    The pipeline stage result (Pydantic model) and writes side effects to DB.
    """
    # Resolve chapter. Branch on isinstance directly so mypy narrows the
    # Union[Session, AsyncSession] — the sync branch's ``db.query(...)`` is
    # only valid on Session, and AsyncSession lacks it.
    chapter: Optional[Chapter] = None
    if chapter_id:
        if isinstance(db, AsyncSession):
            result = await db.execute(select(Chapter).filter(Chapter.id == chapter_id))
            chapter = result.scalar_one_or_none()
        else:
            chapter = db.query(Chapter).filter(Chapter.id == chapter_id).first()
    elif chapter_index is not None and project_id is not None:
        if isinstance(db, AsyncSession):
            result = await db.execute(
                select(Chapter).filter(
                    Chapter.project_id == project_id,
                    Chapter.index == chapter_index,
                )
            )
            chapter = result.scalar_one_or_none()
        else:
            chapter = (
                db.query(Chapter)
                .filter(
                    Chapter.project_id == project_id,
                    Chapter.index == chapter_index,
                )
                .first()
            )

    # Resolve paragraph
    para: Optional[Paragraph] = None
    if paragraph_id:
        if isinstance(db, AsyncSession):
            para_result = await db.execute(select(Paragraph).filter(Paragraph.id == paragraph_id))
            para = para_result.scalar_one_or_none()
        else:
            para = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    elif paragraph_index is not None and chapter is not None:
        if isinstance(db, AsyncSession):
            para_result = await db.execute(
                select(Paragraph).filter(
                    Paragraph.project_id == project_id,
                    Paragraph.chapter_id == chapter.id,
                    Paragraph.index == paragraph_index,
                )
            )
            para = para_result.scalar_one_or_none()
        else:
            para = (
                db.query(Paragraph)
                .filter(
                    Paragraph.project_id == project_id,
                    Paragraph.chapter_id == chapter.id,
                    Paragraph.index == paragraph_index,
                )
                .first()
            )

    # Build input snapshot for feedback collection
    input_snapshot = {
        "stage": stage,
        "project_id": project_id,
        "chapter_index": chapter_index,
        "chapter_id": chapter.id if chapter else chapter_id,
        "paragraph_index": paragraph_index,
        "paragraph_id": para.id if para else paragraph_id,
        "kwargs": _sanitize_kwargs(kwargs),
    }

    # Create feedback capture context if collector provided
    feedback_capture: Optional[StageCapture] = None
    if feedback_collector and project_id:
        feedback_capture = feedback_collector.capture_stage(
            stage=stage,
            chapter_index=chapter_index,
            paragraph_index=paragraph_index,
            chapter_id=chapter.id if chapter else chapter_id,
            paragraph_id=para.id if para else paragraph_id,
            input_snapshot=input_snapshot,
        )

    # ── Hook: Stage Enter ────────────────────────────────────────────────
    _emit_stage_enter(stage, input_snapshot)

    # ── Pause Check ─────────────────────────────────────────────────────
    if project_id:
        paused = await pause_check(project_id)
        if paused:
            logger.info(f"Pipeline {project_id} was paused, now resumed")

    # ── Stage dispatch via Registry ──────────────────────────────────────
    try:
        # Get stage handler from registry
        handler = StageRegistry.get(stage)

        # Prepare context for stage handler
        context = {
            **kwargs,
            "project_id": project_id,
            "chapter": chapter,
            "paragraph": para,
            "paragraph_index": paragraph_index,
        }

        # Inject raw_text from chapter for analyze stage
        if stage == "analyze" and chapter and not context.get("raw_text"):
            context["raw_text"] = chapter.raw_text or ""

        # Run stage logic
        result = await handler.run(**context)

        # Persist result to database (async). The base ``StageHandler`` only
        # declares the sync ``persist``; the async ``apersist`` is provided by
        # every concrete stage subclass, so fetch it dynamically and guard for
        # None rather than asserting the base declares it (base lives in
        # stage_registry, outside this module's scope).
        apersist = getattr(handler, "apersist", None)
        if apersist is not None:
            await apersist(
                db, project_id, chapter, para, result, chapter_index, paragraph_index
            )

        # Capture feedback
        if feedback_capture:
            feedback_capture.set_llm_output(handler.get_result_snapshot(result))
            # Set source for quality stage
            if stage == "quality":
                feedback_capture.set_source("quality_judge")

        _emit_stage_exit(stage, input_snapshot, result, None)
        await _emit_async_stage_exit(stage, input_snapshot, result, None)
        return result

    except ValueError as e:
        # Wrap ValueError (e.g., unknown stage) in StageExecutionError
        wrapped = StageExecutionError(
            stage=stage,
            reason=str(e),
            original_error=e,
        )
        logger.error(
            "Stage execution failed: %s",
            wrapped.error_code,
            extra={
                "stage": stage,
                "error_code": wrapped.error_code,
                "error_type": wrapped.__class__.__name__,
                "reason": str(e),
            },
        )
        if feedback_capture:
            feedback_capture.set_llm_output({"error": str(e)})
        _emit_stage_exit(stage, input_snapshot, None, wrapped)
        await _emit_async_stage_exit(stage, input_snapshot, None, wrapped)
        raise wrapped

    except AudiobookError as e:
        # Log structured error for AudiobookError exceptions
        logger.error(
            "Stage execution failed: %s",
            e.error_code,
            extra={
                "stage": e.stage or stage,
                "error_code": e.error_code,
                "error_type": e.__class__.__name__,
                "provider": e.provider,
                "context": e.context,
            },
        )
        if feedback_capture:
            feedback_capture.set_llm_output({"error": e.to_dict()})
        _emit_stage_exit(stage, input_snapshot, None, e)
        await _emit_async_stage_exit(stage, input_snapshot, None, e)
        raise

    except Exception as e:
        # Wrap unexpected exceptions in StageExecutionError
        wrapped = StageExecutionError(
            stage=stage,
            reason=str(e),
            original_error=e,
        )
        logger.error(
            "Stage execution failed: %s",
            wrapped.error_code,
            extra={
                "stage": stage,
                "error_code": wrapped.error_code,
                "error_type": wrapped.__class__.__name__,
                "reason": str(e),
            },
        )
        if feedback_capture:
            feedback_capture.set_llm_output({"error": str(e)})
        _emit_stage_exit(stage, input_snapshot, None, wrapped)
        await _emit_async_stage_exit(stage, input_snapshot, None, wrapped)
        raise wrapped


async def run_pipeline(
    stages: List[str],
    db: Union[Session, AsyncSession],
    *,
    project_id: Optional[int] = None,
    chapter_index: Optional[int] = None,
    chapter_id: Optional[int] = None,
    paragraph_index: Optional[int] = None,
    paragraph_id: Optional[int] = None,
    feedback_collector: Optional[FeedbackCollector] = None,
    checkpoint_manager: Optional[CheckpointManager] = None,
    **kwargs: Any,
) -> List[Any]:
    """Run multiple pipeline stages sequentially with hooks and checkpoint support.

    Parameters
    ----------
    stages:
        List of stage names to execute in order.
    db:
        SQLAlchemy session for persistence.
    project_id:
        Required for stages that create/update Project-level records.
    chapter_index:
        1-based chapter number (required for extract, analyze).
    chapter_id:
        DB primary key of the Chapter.
    paragraph_index:
        1-based paragraph index.
    paragraph_id:
        DB primary key of the Paragraph.
    feedback_collector:
        Optional FeedbackCollector for capturing LLM inputs/outputs.
    checkpoint_manager:
        Optional CheckpointManager for resume-from-checkpoint support.
        If provided, completed stages are skipped and progress is tracked.
    **kwargs:
        Forwarded to each stage's ``run()`` method.

    Returns
    -------
    List of results from each stage in order.
    """
    pipeline_context = {
        "stages": stages,
        "project_id": project_id,
        "chapter_index": chapter_index,
        "chapter_id": chapter_id,
        "paragraph_index": paragraph_index,
        "paragraph_id": paragraph_id,
        "kwargs": _sanitize_kwargs(kwargs),
    }

    # Early exit: if all stages are already completed, don't run anything
    if checkpoint_manager and chapter_index is not None:
        all_done = True
        for stage in stages:
            if not checkpoint_manager.is_stage_done(stage, chapter_index, paragraph_index):
                all_done = False
                break
        if all_done:
            if paragraph_index is not None:
                logger.info(
                    "All stages already completed for ch%d p%d, skipping pipeline",
                    chapter_index, paragraph_index,
                )
            else:
                logger.info(f"All stages already completed for ch{chapter_index}, skipping pipeline")
            return []

    _emit_pipeline_start(pipeline_context)
    await _emit_async_pipeline_start(pipeline_context)
    results: List[Any] = []

    try:
        for stage in stages:
            # Pause check between stages.
            # is_paused() is non-blocking (returns a plain bool); only pause_check()
            # below is async (it blocks on an asyncio.Event until resumed).
            if project_id and is_paused(project_id):
                logger.info(f"Pipeline {project_id} paused between stages, waiting...")
                await pause_check(project_id)
                logger.info(f"Pipeline {project_id} resumed")
            # Checkpoint: skip already completed stages
            if checkpoint_manager and chapter_index is not None:
                if checkpoint_manager.is_stage_done(stage, chapter_index, paragraph_index):
                    if paragraph_index is not None:
                        logger.info(
                            "Checkpoint: skipping stage '%s' for ch%d p%d (already done)",
                            stage, chapter_index, paragraph_index,
                        )
                    else:
                        logger.info(
                            "Checkpoint: skipping stage '%s' for ch%d (already done)",
                            stage, chapter_index,
                        )
                    results.append(None)
                    continue

            # Mark stage as started
            if checkpoint_manager and chapter_index is not None:
                checkpoint_manager.mark_stage_started(stage, chapter_index, paragraph_index)

            # run_stage is a coroutine; must be awaited or the result is a
            # never-awaited coroutine object rather than the stage output.
            result = await run_stage(
                stage,
                db,
                project_id=project_id,
                chapter_index=chapter_index,
                chapter_id=chapter_id,
                paragraph_index=paragraph_index,
                paragraph_id=paragraph_id,
                feedback_collector=feedback_collector,
                **kwargs,
            )
            results.append(result)

            # Mark stage as completed
            if checkpoint_manager and chapter_index is not None:
                checkpoint_manager.mark_stage_done(stage, chapter_index, paragraph_index)

        # Emit chapter complete event
        if project_id and chapter_index is not None:
            # Count total chapters for progress
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(emit_chapter_complete(
                    project_id=project_id,
                    chapter_index=chapter_index,
                    chapter_id=chapter_id,
                    total_chapters=kwargs.get("total_chapters", 1),
                ))
            except RuntimeError:
                pass

        # Emit pipeline completed event
        if project_id:
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(emit_pipeline_completed(
                    project_id=project_id,
                    total_chapters=kwargs.get("total_chapters", 1),
                ))
            except RuntimeError:
                pass

        _emit_pipeline_end(pipeline_context, results, None)
        await _emit_async_pipeline_end(pipeline_context, results, None)
        return results
    except Exception as e:
        # Emit pipeline error
        if project_id:
            try:
                import asyncio
                loop = asyncio.get_running_loop()
                loop.create_task(emit_error(
                    project_id=project_id,
                    stage="pipeline",
                    error_message=str(e),
                    chapter_index=chapter_index,
                    chapter_id=chapter_id,
                ))
            except RuntimeError:
                pass
        _emit_pipeline_end(pipeline_context, None, e)
        await _emit_async_pipeline_end(pipeline_context, None, e)
        raise


def _sanitize_kwargs(kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize kwargs for feedback snapshot (remove non-serializable objects)."""
    sanitized = {}
    for k, v in kwargs.items():
        if hasattr(v, "model_dump"):  # Pydantic model
            sanitized[k] = v.model_dump()
        elif hasattr(v, "__dict__"):  # Generic object
            sanitized[k] = str(v)
        else:
            sanitized[k] = v
    return sanitized

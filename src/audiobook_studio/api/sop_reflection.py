"""SOP Reflection API endpoints for Module 4.2.

Provides REST and WebSocket endpoints for:
- Submitting user corrections from frontend (ParagraphEditor/CharacterManager)
- Querying learned rules for a genre
- Triggering manual reflection
- Managing background reflection thread
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from src.audiobook_studio.pipeline.sop_reflection import (
    SOPBackgroundThread,
    UserCorrection,
    apply_learned_rules_on_import,
    get_correction_collector,
    get_genre_detector,
    get_reflection_engine,
    get_rule_applier,
    get_sop_config,
    handle_user_correction_websocket,
    start_sop_background_thread,
    stop_sop_background_thread,
)
from src.audiobook_studio.schemas import BookMeta

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sop", tags=["sop-reflection"])


# ── Request/Response Models ──────────────────────────────────────────────────


class CorrectionRequest(BaseModel):
    """User correction from frontend."""

    project_id: int = Field(..., description="Project ID")
    chapter_index: int = Field(..., description="Chapter index (1-based)")
    paragraph_index: int = Field(..., description="Paragraph index (1-based)")
    field: str = Field(
        ...,
        description="Field corrected: emotion, speech_rate, pitch_shift_semitones, pause_before_ms, pause_after_ms, sfx_tags",
    )
    original_value: Any = Field(..., description="Original value before correction")
    corrected_value: Any = Field(..., description="User-corrected value")
    genre: str = Field(..., description="Genre of the book")
    context: Optional[Dict[str, Any]] = Field(
        default_factory=dict, description="Additional context: speaker, is_dialogue, text_preview"
    )


class CorrectionResponse(BaseModel):
    """Response to correction submission."""

    status: str = Field(..., description="accepted or queue_full")
    queued_count: int = Field(..., description="Current queue size")


class GenreRulesResponse(BaseModel):
    """Learned rules for a genre."""

    genre: str
    rules_applied: bool
    confidence: float
    rules: Dict[str, Any]


class ReflectionTriggerResponse(BaseModel):
    """Response to manual reflection trigger."""

    genre: str
    corrections_analyzed: int
    confidence: float
    reasoning: str
    rules_updated: bool
    proposed_rules: Dict[str, Any]


class BackgroundThreadStatus(BaseModel):
    """Background thread status."""

    running: bool
    check_interval: float
    last_reflections: Dict[str, str]


class ApplyRulesOnImportRequest(BaseModel):
    """Request to apply learned rules on novel import."""

    project_id: int
    book_meta: Dict[str, Any]  # BookMeta as dict
    analyzed_json: Dict[str, Any]


class ApplyRulesOnImportResponse(BaseModel):
    """Response with applied rules."""

    genre: str
    rules_applied: bool
    confidence: float
    rules: Dict[str, Any]


# ── REST Endpoints ───────────────────────────────────────────────────────────


@router.post("/corrections", response_model=CorrectionResponse)
async def submit_correction(correction: CorrectionRequest):
    """Submit a user correction from frontend (ParagraphEditor/CharacterManager)."""
    collector = get_correction_collector()
    data = correction.model_dump()
    success = collector.add_correction_dict(data)

    # Cache project genre
    collector.cache_project_genre(correction.project_id, correction.genre)

    return CorrectionResponse(status="accepted" if success else "queue_full", queued_count=collector.queue_size())


@router.get("/genres/{genre}/rules", response_model=GenreRulesResponse)
async def get_genre_rules(genre: str):
    """Get learned rules for a specific genre."""
    config = get_sop_config()
    rules = config.get_genre_rules(genre)
    genre_config = config.get_genre_config(genre)
    confidence = genre_config.get("learning_stats", {}).get("confidence", 0.5)

    return GenreRulesResponse(
        genre=genre,
        rules_applied=bool(rules),
        confidence=confidence,
        rules=rules,
    )


@router.get("/genres", response_model=List[str])
async def list_genres():
    """List all configured genres."""
    return get_sop_config().list_genres()


@router.post("/reflect/{genre}", response_model=ReflectionTriggerResponse)
async def trigger_reflection(genre: str, max_corrections: int = 100):
    """Manually trigger reflection for a genre."""
    collector = get_correction_collector()
    engine = get_reflection_engine()

    corrections = collector.get_corrections_by_genre(genre, max_size=max_corrections)
    if not corrections:
        raise HTTPException(status_code=404, detail=f"No corrections found for genre '{genre}'")

    result = engine.reflect(genre, corrections)

    # Apply if confidence is high enough
    config = get_sop_config()
    threshold = config.get_confidence_threshold()
    rules_updated = False

    if result.confidence >= threshold and result.proposed_rules:
        rules_updated = config.update_genre_rules(genre, result.proposed_rules, result.confidence, result.reasoning)
        for _ in corrections:
            config.record_correction(genre)

    return ReflectionTriggerResponse(
        genre=genre,
        corrections_analyzed=result.corrections_analyzed,
        confidence=result.confidence,
        reasoning=result.reasoning,
        rules_updated=rules_updated,
        proposed_rules=result.proposed_rules,
    )


@router.get("/background/status", response_model=BackgroundThreadStatus)
async def get_background_status():
    """Get background reflection thread status."""
    global _background_thread
    from src.audiobook_studio.pipeline.sop_reflection import _background_thread as bg_thread

    if bg_thread and bg_thread._thread and bg_thread._thread.is_alive():
        return BackgroundThreadStatus(
            running=True,
            check_interval=bg_thread.check_interval,
            last_reflections=bg_thread._last_reflection,
        )
    return BackgroundThreadStatus(running=False, check_interval=0, last_reflections={})


@router.post("/background/start")
async def start_background_thread(check_interval: float = 30.0, llm_client: Optional[str] = None):
    """Start the background reflection thread."""
    thread = start_sop_background_thread(check_interval=check_interval)
    return {"status": "started", "check_interval": thread.check_interval}


@router.post("/background/stop")
async def stop_background_thread():
    """Stop the background reflection thread."""
    stop_sop_background_thread()
    return {"status": "stopped"}


@router.post("/import/apply-rules", response_model=ApplyRulesOnImportResponse)
async def apply_rules_on_import(request: ApplyRulesOnImportRequest):
    """Apply learned SOP rules when importing a new novel of same genre."""
    book_meta = BookMeta(**request.book_meta)
    result = apply_learned_rules_on_import(request.project_id, book_meta, request.analyzed_json)
    return ApplyRulesOnImportResponse(**result)


@router.get("/config/snapshot")
async def get_config_snapshot():
    """Get full SOP config snapshot for debugging."""
    return get_sop_config().get_config_snapshot()


@router.get("/queue/size")
async def get_queue_size():
    """Get current correction queue size."""
    return {"queue_size": get_correction_collector().queue_size()}


# ── WebSocket Endpoint for Real-time Corrections ─────────────────────────────


@router.websocket("/corrections/ws")
async def sop_corrections_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for real-time user corrections from frontend.

    Client sends correction messages:
    {
        "type": "correction",
        "project_id": 1,
        "chapter_index": 3,
        "paragraph_index": 5,
        "field": "emotion",
        "original_value": "neutral",
        "corrected_value": "tense",
        "genre": "悬疑",
        "context": {"speaker": "侦探", "is_dialogue": true, "text_preview": "凶手就是..."}
    }

    Server responds:
    {
        "type": "ack",
        "status": "accepted",
        "queued_count": 42
    }
    """
    await websocket.accept()
    collector = get_correction_collector()

    try:
        while True:
            data = await websocket.receive_text()
            import json

            message = json.loads(data)

            if message.get("type") == "correction":
                result = await handle_user_correction_websocket(message)
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "ack",
                            "status": result["status"],
                            "queued_count": result["queued_count"],
                        },
                        ensure_ascii=False,
                    )
                )
            elif message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}, ensure_ascii=False))
            else:
                await websocket.send_text(
                    json.dumps(
                        {"type": "error", "message": f"Unknown message type: {message.get('type')}"}, ensure_ascii=False
                    )
                )

    except WebSocketDisconnect:
        logger.info("SOP corrections WebSocket disconnected")
    except Exception as e:
        logger.error(f"SOP corrections WebSocket error: {e}")
        try:
            await websocket.send_text(json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False))
        except Exception:
            pass

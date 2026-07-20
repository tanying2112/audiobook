"""WebSocket endpoints for real-time pipeline progress updates."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])


# ─────────────────────────────────────────────────────────────────────────────
# Connection Manager
# ─────────────────────────────────────────────────────────────────────────────


class ConnectionManager:
    """Manages WebSocket connections for pipeline events."""

    def __init__(self):
        # project_id -> set of WebSocket connections
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        # connection -> project_id mapping
        self.connection_to_project: Dict[WebSocket, int] = {}
        # project_id -> asyncio.Event for pause/resume control
        self.pause_events: Dict[int, asyncio.Event] = {}
        # project_id -> pause state
        self.pause_states: Dict[int, bool] = {}

    async def connect(self, websocket: WebSocket, project_id: int):
        """Accept WebSocket connection and register for project updates."""
        await websocket.accept()
        if project_id not in self.active_connections:
            self.active_connections[project_id] = set()
        self.active_connections[project_id].add(websocket)
        self.connection_to_project[websocket] = project_id
        logger.info(f"WebSocket connected for project {project_id}")

    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection."""
        project_id = self.connection_to_project.pop(websocket, None)
        if project_id and websocket in self.active_connections.get(project_id, set()):
            self.active_connections[project_id].remove(websocket)
            if not self.active_connections[project_id]:
                del self.active_connections[project_id]
            logger.info(f"WebSocket disconnected for project {project_id}")

    async def broadcast_to_project(self, project_id: int, message: dict):
        """Broadcast message to all clients subscribed to a project."""
        connections = self.active_connections.get(project_id, set())
        if not connections:
            return

        data = json.dumps(message, ensure_ascii=False)
        disconnected = set()

        for conn in connections:
            try:
                await conn.send_text(data)
            except Exception as e:
                logger.error(f"Failed to send to WebSocket: {e}")
                disconnected.add(conn)

        # Clean up disconnected clients
        for conn in disconnected:
            self.disconnect(conn)

    async def send_to_connection(self, websocket: WebSocket, message: dict):
        """Send message to a specific connection."""
        try:
            await websocket.send_text(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Failed to send to WebSocket: {e}")


# Global connection manager instance
manager = ConnectionManager()


# ─────────────────────────────────────────────────────────────────────────────
# Event Types
# ─────────────────────────────────────────────────────────────────────────────


class PipelineEventType:
    """Pipeline event type constants."""

    STAGE_ENTER = "stage_enter"
    STAGE_EXIT = "stage_exit"
    STAGE_PROGRESS = "stage_progress"
    CHAPTER_COMPLETE = "chapter_complete"
    PARAGRAPH_COMPLETE = "paragraph_complete"
    ERROR = "error"
    PAUSED = "paused"
    RESUMED = "resumed"
    COMPLETED = "completed"


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.websocket("/pipeline/{project_id}")
async def pipeline_websocket(websocket: WebSocket, project_id: int):
    """
    WebSocket endpoint for real-time pipeline progress updates.

    Clients connect to /api/ws/pipeline/{project_id} to receive:
    - stage_enter/stage_exit events
    - Progress updates per chapter/paragraph
    - Error notifications
    - Completion events

    Example message format:
    {
        "type": "stage_enter",
        "project_id": 1,
        "chapter_id": 5,
        "stage": "annotate",
        "progress": 0.0,
        "timestamp": "2026-06-26T12:00:00Z"
    }
    """
    await manager.connect(websocket, project_id)

    # Send initial connection confirmation
    await manager.send_to_connection(
        websocket,
        {
            "type": "connected",
            "project_id": project_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    try:
        while True:
            # Keep connection alive, handle ping/pong
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Handle client messages (pause, resume, etc.)
                message = json.loads(data)
                await handle_client_message(websocket, project_id, message)
            except asyncio.TimeoutError:
                # Send keepalive
                await manager.send_to_connection(
                    websocket,
                    {
                        "type": "keepalive",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.disconnect(websocket)


async def handle_client_message(websocket: WebSocket, project_id: int, message: dict):
    """Handle incoming messages from WebSocket clients."""
    msg_type = message.get("type")

    if msg_type == "pause":
        # Signal pipeline to pause at next checkpoint
        pause_event = manager.pause_events.get(project_id)
        if pause_event is None:
            pause_event = asyncio.Event()
            manager.pause_events[project_id] = pause_event

        pause_event.set()  # Signal pause
        manager.pause_states[project_id] = True

        # Broadcast pause event to all connections
        await manager.broadcast_to_project(
            project_id,
            {
                "type": PipelineEventType.PAUSED,
                "project_id": project_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

        await manager.send_to_connection(
            websocket,
            {
                "type": "ack",
                "action": "pause",
                "status": "paused",
            },
        )
    elif msg_type == "resume":
        # Signal pipeline to resume
        pause_event = manager.pause_events.get(project_id)
        if pause_event:
            pause_event.clear()  # Clear pause signal
            manager.pause_states[project_id] = False

            # Broadcast resume event
            await manager.broadcast_to_project(
                project_id,
                {
                    "type": PipelineEventType.RESUMED,
                    "project_id": project_id,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )

            await manager.send_to_connection(
                websocket,
                {
                    "type": "ack",
                    "action": "resume",
                    "status": "resumed",
                },
            )
        else:
            await manager.send_to_connection(
                websocket,
                {
                    "type": "ack",
                    "action": "resume",
                    "status": "not_paused",
                },
            )
    elif msg_type == "status":
        # Return current status
        paused = manager.pause_states.get(project_id, False)
        await manager.send_to_connection(
            websocket,
            {
                "type": "status",
                "project_id": project_id,
                "status": "paused" if paused else "running",
                "paused": paused,
            },
        )


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions for Backend Integration
# ─────────────────────────────────────────────────────────────────────────────


async def emit_pipeline_event(
    project_id: int,
    event_type: str,
    stage: Optional[str] = None,
    chapter_id: Optional[int] = None,
    paragraph_index: Optional[int] = None,
    progress: Optional[float] = None,
    data: Optional[Dict[str, Any]] = None,
):
    """
    Emit a pipeline event to all subscribed clients.

    This function should be called by the pipeline orchestrator
    at key points during execution.

    Usage:
        await emit_pipeline_event(
            project_id=1,
            event_type=PipelineEventType.STAGE_ENTER,
            stage="annotate",
            chapter_id=5,
        )
    """
    message = {
        "type": event_type,
        "project_id": project_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if stage is not None:
        message["stage"] = stage
    if chapter_id is not None:
        message["chapter_id"] = chapter_id
    if paragraph_index is not None:
        message["paragraph_index"] = paragraph_index
    if progress is not None:
        message["progress"] = progress
    if data is not None:
        message["data"] = data

    await manager.broadcast_to_project(project_id, message)


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Fallback Endpoint (for polling clients)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/pipeline/{project_id}/events")
async def get_pipeline_events(project_id: int):
    """
    HTTP fallback for clients that don't support WebSocket.

    Returns current pipeline status (polling-based alternative to WebSocket).
    TODO: Implement event log / pub-sub system for actual event history.
    """
    # For now, return placeholder status
    # In production, this would query a status store
    return {
        "project_id": project_id,
        "status": "unknown",
        "current_stage": None,
        "progress": 0.0,
        "note": "WebSocket recommended for real-time updates",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Integration Helpers
# ─────────────────────────────────────────────────────────────────────────────


async def pause_check(project_id: int) -> bool:
    """
    Check if pipeline should pause at current checkpoint.

    Called by pipeline orchestrator between atomic operations.
    Returns True if paused (caller should wait), False if can continue.

    Usage:
        if await pause_check(project_id):
            await manager.pause_events[project_id].wait()  # Wait for resume
    """
    pause_event = manager.pause_events.get(project_id)
    if pause_event and pause_event.is_set():
        # Pipeline should pause - wait for resume signal
        await pause_event.wait()
        return True
    return False


def is_paused(project_id: int) -> bool:
    """Check if a project is currently paused (non-blocking)."""
    return manager.pause_states.get(project_id, False)


def get_pause_event(project_id: int):
    """Get or create the pause event for a project."""
    if project_id not in manager.pause_events:
        manager.pause_events[project_id] = asyncio.Event()
    return manager.pause_events[project_id]

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
# WebSocket protocol version negotiation
# ─────────────────────────────────────────────────────────────────────────────

# Clients advertise the protocol versions they support via the
# ``Sec-WebSocket-Protocol`` handshake header, e.g.
# ``audiobook-progress-v1, audiobook-progress-v2``. The server picks the highest
# mutually supported version, echoes it back in the handshake (``accept``
# subprotocol), and embeds the negotiated ``version`` in every message so clients
# can adapt to wire-format changes without a redeploy.
WS_PROTOCOL_PREFIX = "audiobook-progress"
SUPPORTED_WS_PROTOCOL_VERSIONS = ("v1",)
LATEST_WS_VERSION = "v1"


def _parse_ws_version(subprotocol: str) -> Optional[str]:
    """Extract the version token from a subprotocol name.

    ``audiobook-progress-v1`` -> ``v1``; anything not matching the prefix
    returns ``None``.
    """
    if subprotocol.startswith(WS_PROTOCOL_PREFIX + "-"):
        return subprotocol[len(WS_PROTOCOL_PREFIX) + 1 :]
    return None


def negotiate_ws_subprotocol(client_protocols: Optional[str]) -> Optional[str]:
    """Select the highest mutually supported WebSocket subprotocol.

    ``client_protocols`` is the raw value of the client's
    ``Sec-WebSocket-Protocol`` header (comma-separated). Returns the selected
    subprotocol name (e.g. ``"audiobook-progress-v1"``) or ``None`` when the
    client offered nothing we support. Callers then fall back to advertising the
    server's latest version in the handshake message body so the client can still
    learn it.
    """
    if not client_protocols or not isinstance(client_protocols, str):
        return None
    offered = [p.strip() for p in client_protocols.split(",") if p.strip()]
    best: Optional[str] = None
    best_rank = -1
    for proto in offered:
        version = _parse_ws_version(proto)
        if version in SUPPORTED_WS_PROTOCOL_VERSIONS:
            try:
                rank = int(version.lstrip("v")) if version[:1] == "v" and version[1:].isdigit() else -1
            except (ValueError, IndexError):
                rank = -1
            if rank > best_rank:
                best_rank = rank
                best = proto
    return best


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

    async def connect(self, websocket: WebSocket, project_id: int, subprotocol: Optional[str] = None):
        """Accept WebSocket connection and register for project updates.

        ``subprotocol`` is the negotiated protocol version (e.g.
        ``"audiobook-progress-v1"``) or ``None`` when the client offered nothing
        we support.
        """
        await websocket.accept(subprotocol=subprotocol)
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
# Event Schema (Versioned)
# ─────────────────────────────────────────────────────────────────────────────

from datetime import datetime
from typing import Any, Dict, Literal, Optional, Union

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    """Base event with version field."""

    type: str
    version: str
    timestamp: datetime


# v1 Event Schemas
class V1ConnectedEvent(BaseModel):
    type: Literal["connected"]
    version: Literal["v1"]
    timestamp: datetime
    project_id: int
    protocol: str


class V1KeepaliveEvent(BaseModel):
    type: Literal["keepalive"]
    version: Literal["v1"]
    timestamp: datetime


class V1PingEvent(BaseModel):
    type: Literal["ping"]
    version: Literal["v1"]
    timestamp: datetime


class V1PongEvent(BaseModel):
    type: Literal["pong"]
    version: Literal["v1"]
    timestamp: datetime


class V1PauseEvent(BaseModel):
    type: Literal["pause"]
    version: Literal["v1"]
    timestamp: datetime
    project_id: int


class V1ResumeEvent(BaseModel):
    type: Literal["resume"]
    version: Literal["v1"]
    timestamp: datetime
    project_id: int


class V1StatusEvent(BaseModel):
    type: Literal["status"]
    version: Literal["v1"]
    timestamp: datetime
    project_id: int
    status: str
    paused: bool


class V1AckEvent(BaseModel):
    type: Literal["ack"]
    version: Literal["v1"]
    timestamp: datetime
    action: str
    status: str


class V1ErrorEvent(BaseModel):
    type: Literal["error"]
    version: Literal["v1"]
    timestamp: datetime
    message: str
    code: Optional[str] = None


# Pipeline event types (v1)
class V1PipelineEvent(BaseModel):
    type: Literal[
        "stage_enter",
        "stage_exit",
        "stage_progress",
        "chapter_complete",
        "paragraph_complete",
        "error",
        "paused",
        "resumed",
        "completed",
    ]
    version: Literal["v1"]
    timestamp: datetime
    project_id: int
    stage: Optional[str] = None
    chapter_id: Optional[int] = None
    chapter_index: Optional[int] = None
    paragraph_index: Optional[int] = None
    progress: Optional[float] = None
    data: Optional[Dict[str, Any]] = None


# Union of all v1 events
V1Event = Union[
    V1ConnectedEvent,
    V1KeepaliveEvent,
    V1PingEvent,
    V1PongEvent,
    V1PauseEvent,
    V1ResumeEvent,
    V1StatusEvent,
    V1AckEvent,
    V1ErrorEvent,
    V1PipelineEvent,
]

# Event registry: version -> list of event models
WS_EVENT_SCHEMAS = {
    "v1": {
        "connected": V1ConnectedEvent,
        "keepalive": V1KeepaliveEvent,
        "ping": V1PingEvent,
        "pong": V1PongEvent,
        "pause": V1PauseEvent,
        "resume": V1ResumeEvent,
        "status": V1StatusEvent,
        "ack": V1AckEvent,
        "error": V1ErrorEvent,
        "stage_enter": V1PipelineEvent,
        "stage_exit": V1PipelineEvent,
        "stage_progress": V1PipelineEvent,
        "chapter_complete": V1PipelineEvent,
        "paragraph_complete": V1PipelineEvent,
        "error": V1ErrorEvent,
        "paused": V1PipelineEvent,
        "resumed": V1PipelineEvent,
        "completed": V1PipelineEvent,
    },
}

# Supported versions
SUPPORTED_WS_PROTOCOL_VERSIONS = ("v1",)
LATEST_WS_VERSION = "v1"


def validate_ws_event(version: str, event_data: dict) -> Optional[BaseModel]:
    """Validate event data against the schema for the given version.

    Returns the validated model instance or None if validation fails.
    """
    if version not in WS_EVENT_SCHEMAS:
        return None

    event_type = event_data.get("type")
    if not event_type:
        return None

    schema_map = WS_EVENT_SCHEMAS.get(version, {})
    model = schema_map.get(event_data.get("type"))

    if not model:
        # Fallback: try to find a matching pipeline event
        if event_data.get("type") in {
            "stage_enter",
            "stage_exit",
            "stage_progress",
            "chapter_complete",
            "paragraph_complete",
            "error",
            "paused",
            "resumed",
            "completed",
        }:
            model = V1PipelineEvent
        else:
            return None

    try:
        return model(**event_data)
    except Exception:
        return None


def get_event_schema(version: str, event_type: str):
    """Get the Pydantic model for a given version and event type."""
    if version not in WS_EVENT_SCHEMAS:
        return None
    return WS_EVENT_SCHEMAS[version].get(event_type)


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
    # Version negotiation: pick the highest mutually supported subprotocol and
    # echo it back in the handshake. If the client offered nothing we support,
    # accept without a subprotocol and advertise the latest version in the
    # handshake message body instead.
    client_protocols = websocket.headers.get("sec-websocket-protocol")
    negotiated = negotiate_ws_subprotocol(client_protocols)
    await manager.connect(websocket, project_id, subprotocol=negotiated)

    # Send initial connection confirmation (includes negotiated protocol version)
    await manager.send_to_connection(
        websocket,
        {
            "type": "connected",
            "project_id": project_id,
            "version": LATEST_WS_VERSION,
            "protocol": negotiated or f"{WS_PROTOCOL_PREFIX}-{LATEST_WS_VERSION}",
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
                        "version": LATEST_WS_VERSION,
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

    if msg_type == "ping":
        # Respond with pong for keepalive
        await manager.send_to_connection(
            websocket,
            {
                "type": "pong",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        return

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
    chapter_index: Optional[int] = None,
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
            project_id=123,
            event_type=PipelineEventType.STAGE_ENTER,
            stage="annotate",
            chapter_id=5,
        )
    """
    message = {
        "type": event_type,
        "project_id": project_id,
        "version": LATEST_WS_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if stage is not None:
        message["stage"] = stage
    if chapter_id is not None:
        message["chapter_id"] = chapter_id
    if chapter_index is not None:
        message["chapter_index"] = chapter_index
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

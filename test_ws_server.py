"""Minimal WebSocket test server for v0.3 verification"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Connection Manager
# ─────────────────────────────────────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, Set[WebSocket]] = {}
        self.connection_to_project: Dict[WebSocket, int] = {}
        self.pause_events: Dict[int, asyncio.Event] = {}
        self.pause_states: Dict[int, bool] = {}

    async def connect(self, websocket: WebSocket, project_id: int):
        await websocket.accept()
        if project_id not in self.active_connections:
            self.active_connections[project_id] = set()
        self.active_connections[project_id].add(websocket)
        self.connection_to_project[websocket] = project_id
        logger.info(f"WebSocket connected for project {project_id}")

    def disconnect(self, websocket: WebSocket):
        project_id = self.connection_to_project.pop(websocket, None)
        if project_id and websocket in self.active_connections.get(project_id, set()):
            self.active_connections[project_id].remove(websocket)
            if not self.active_connections[project_id]:
                del self.active_connections[project_id]
            logger.info(f"WebSocket disconnected for project {project_id}")

    async def broadcast_to_project(self, project_id: int, message: dict):
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
        for conn in disconnected:
            self.disconnect(conn)

    async def send_to_connection(self, websocket: WebSocket, message: dict):
        try:
            await websocket.send_text(json.dumps(message, ensure_ascii=False))
        except Exception as e:
            logger.error(f"Failed to send to WebSocket: {e}")

manager = ConnectionManager()

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Event Types
# ─────────────────────────────────────────────────────────────────────────────

class PipelineEventType:
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

@app.websocket("/api/ws/pipeline/{project_id}")
async def pipeline_websocket(websocket: WebSocket, project_id: int):
    await manager.connect(websocket, project_id)

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
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                message = json.loads(data)
                await handle_client_message(websocket, project_id, message)
            except asyncio.TimeoutError:
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
    msg_type = message.get("type")

    if msg_type == "ping":
        await manager.send_to_connection(
            websocket,
            {
                "type": "pong",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        return

    if msg_type == "pause":
        pause_event = manager.pause_events.get(project_id)
        if pause_event is None:
            pause_event = asyncio.Event()
            manager.pause_events[project_id] = pause_event
        pause_event.set()
        manager.pause_states[project_id] = True

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
            {"type": "ack", "action": "pause", "status": "paused"},
        )
    elif msg_type == "resume":
        pause_event = manager.pause_events.get(project_id)
        if pause_event:
            pause_event.clear()
            manager.pause_states[project_id] = False
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
                {"type": "ack", "action": "resume", "status": "resumed"},
            )
        else:
            await manager.send_to_connection(
                websocket,
                {"type": "ack", "action": "resume", "status": "not_paused"},
            )
    elif msg_type == "status":
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
# HTTP Health Endpoint
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/health/ready")
def health_ready():
    return {"status": "ready", "checks": {"websocket": "ok"}}

# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Event Emitter (for testing)
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

# Test endpoint to simulate pipeline progress
@app.post("/api/test/simulate/{project_id}")
async def simulate_pipeline(project_id: int):
    """Simulate pipeline progress for testing WebSocket"""
    stages = ["parse", "annotate", "cast", "tts", "assemble", "export"]
    for stage in stages:
        await emit_pipeline_event(project_id, PipelineEventType.STAGE_ENTER, stage=stage, chapter_id=1)
        await asyncio.sleep(0.5)
        for p in [0.25, 0.5, 0.75, 1.0]:
            await emit_pipeline_event(project_id, PipelineEventType.STAGE_PROGRESS, stage=stage, chapter_id=1, progress=p)
            await asyncio.sleep(0.3)
        await emit_pipeline_event(project_id, PipelineEventType.STAGE_EXIT, stage=stage, chapter_id=1)
    await emit_pipeline_event(project_id, PipelineEventType.COMPLETED)
    return {"status": "simulated"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

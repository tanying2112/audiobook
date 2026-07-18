"""Agent Chat API endpoint for real-time agent interaction.

Provides WebSocket endpoint /ws/agent/chat/{project_id} and HTTP fallback
for conversational agent interface with pipeline context.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..api.websocket import manager as ws_manager
from ..database import get_db
from ..models import Project
from ..models.agent import AgentKnowledge, TaskRecord

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class AgentChatMessage(BaseModel):
    """Single chat message in agent conversation."""

    role: str = Field(..., description="Role: user, assistant, system")
    content: str = Field(..., description="Message content")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentChatRequest(BaseModel):
    """Request to send a message to the agent."""

    project_id: int = Field(..., description="Project ID for context")
    message: str = Field(..., description="User message")
    session_id: Optional[str] = Field(None, description="Optional session ID for continuity")
    context: Dict[str, Any] = Field(default_factory=dict, description="Additional context")


class AgentChatResponse(BaseModel):
    """Response from the agent."""

    session_id: str
    message: str
    agent_type: str = "general"
    actions: list[Dict[str, Any]] = Field(default_factory=list)
    knowledge_updated: bool = False
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AgentStatusResponse(BaseModel):
    """Agent status for a project."""

    project_id: int
    active_sessions: int
    knowledge_entries: int
    recent_tasks: int
    status: str = "ready"


# ─────────────────────────────────────────────────────────────────────────────
# In-Memory Session Storage (use Redis in production)
# ─────────────────────────────────────────────────────────────────────────────

# session_id -> {project_id, messages, created_at, last_active}
agent_sessions: Dict[str, Dict[str, Any]] = {}

# WebSocket connections for agent chat: project_id -> set of WebSockets
agent_chat_connections: Dict[int, set] = {}


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────


def _get_or_create_session(project_id: int, session_id: Optional[str] = None) -> str:
    """Get existing session or create new one."""
    if session_id and session_id in agent_sessions:
        session = agent_sessions[session_id]
        if session["project_id"] == project_id:
            session["last_active"] = datetime.now(timezone.utc).isoformat()
            return session_id

    # Create new session
    new_session_id = f"agent_chat_{project_id}_{uuid.uuid4().hex[:12]}"
    agent_sessions[new_session_id] = {
        "project_id": project_id,
        "messages": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_active": datetime.now(timezone.utc).isoformat(),
    }
    return new_session_id


def _add_message(session_id: str, role: str, content: str, metadata: Optional[Dict] = None):
    """Add a message to session history."""
    if session_id not in agent_sessions:
        return

    message = AgentChatMessage(
        role=role,
        content=content,
        metadata=metadata or {},
    )
    agent_sessions[session_id]["messages"].append(message.model_dump())
    agent_sessions[session_id]["last_active"] = datetime.now(timezone.utc).isoformat()


async def _process_agent_message(
    project_id: int,
    session_id: str,
    user_message: str,
    context: Dict[str, Any],
) -> AgentChatResponse:
    """Process user message and generate agent response.

    This is a simplified implementation. In production, this would integrate
    with the actual agent orchestration system.
    """
    # Add user message to history
    _add_message(session_id, "user", user_message)

    # Get project context
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        project_title = project.title if project else f"Project {project_id}"

        # Get knowledge base entries
        knowledge_count = db.query(AgentKnowledge).filter(AgentKnowledge.topic.contains(str(project_id))).count()

        # Get recent tasks
        recent_tasks = (
            db.query(TaskRecord).filter(TaskRecord.input_data.contains({"project_id": project_id})).limit(5).all()
        )

    finally:
        db.close()

    # Simple response logic based on message content
    message_lower = user_message.lower()

    # Check for specific intents
    if any(kw in message_lower for kw in ["进度", "status", "进度如何", "怎么"]):
        response_text = f"项目《{project_title}》当前状态良好。知识库中有 {knowledge_count} 条记录，最近有 {len(recent_tasks)} 个任务记录。"
        agent_type = "monitor"

    elif any(kw in message_lower for kw in ["章节", "chapter", "内容", "text"]):
        response_text = "我可以帮你查看章节内容、提取文本或分析结构。请告诉我具体想做什么？"
        agent_type = "extractor"

    elif any(kw in message_lower for kw in ["语音", "tts", "合成", "配音", "voice"]):
        response_text = "关于语音合成，我可以帮你选择引擎、调整语速音调、或预览声音。目前支持 Kokoro(本地)、Edge-TTS(云端)等引擎。"
        agent_type = "tts"

    elif any(kw in message_lower for kw in ["质量", "quality", "检查", "评分"]):
        response_text = "质量检查方面，我可以运行质量评估、查看评分报告、或触发重新生成。请指定要检查的章节或段落。"
        agent_type = "quality"

    elif any(kw in message_lower for kw in ["导出", "export", "生成", "打包"]):
        response_text = "导出功能支持多种格式：M4B(有声书)、MP3、WAV、带章节标记的文件。需要我帮你配置导出参数吗？"
        agent_type = "exporter"

    elif any(kw in message_lower for kw in ["帮助", "help", "能做什么", "功能"]):
        response_text = """我是 Audiobook Studio 的智能助手，可以帮你：

📚 **文本处理**：上传 PDF/EPUB/DOCX/TXT/图片，自动提取文本并分章
🎭 **角色分析**：识别说话人、情感、语速等标注信息
🎙️ **语音合成**：多引擎支持(Kokoro/Edge-TTS/Azure/GCP)，声音克隆
✅ **质量控制**：自动评分、问题检测、一键重生成
📦 **导出打包**：M4B/MP3/WAV 多格式，章节标记、封面嵌入
🤖 **全自动流程**：一键从文本到成品有声书

请告诉我你想做什么，或直接描述你的需求！"""
        agent_type = "general"

    else:
        response_text = f"收到你的消息：\"{user_message}\"。作为《{project_title}》的项目助手，我可以帮你处理文本提取、角色分析、语音合成、质量检查、导出等任务。请告诉我具体需求，或输入「帮助」查看功能列表。"
        agent_type = "general"

    # Add assistant response to history
    _add_message(session_id, "assistant", response_text, {"agent_type": agent_type})

    return AgentChatResponse(
        session_id=session_id,
        message=response_text,
        agent_type=agent_type,
        actions=[],
        knowledge_updated=False,
    )


async def _broadcast_agent_event(project_id: int, event: dict):
    """Broadcast agent event to all connected WebSocket clients."""
    if project_id in agent_chat_connections:
        disconnected = set()
        for ws in agent_chat_connections[project_id]:
            try:
                await ws.send_text(json.dumps(event, ensure_ascii=False))
            except Exception:
                disconnected.add(ws)
        for ws in disconnected:
            agent_chat_connections[project_id].discard(ws)


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket Endpoint
# ─────────────────────────────────────────────────────────────────────────────


@router.websocket("/chat/{project_id}")
async def agent_chat_websocket(websocket: WebSocket, project_id: int):
    """
    WebSocket endpoint for real-time agent chat.

    Connect to /api/agent/chat/{project_id} for bidirectional communication.

    Message format (client -> server):
    {
        "type": "message",
        "session_id": "optional-session-id",
        "content": "user message",
        "context": {}
    }

    Message format (server -> client):
    {
        "type": "response",
        "session_id": "...",
        "message": "agent response",
        "agent_type": "general",
        "actions": [],
        "timestamp": "..."
    }

    Other event types:
    - {"type": "connected", "session_id": "..."}
    - {"type": "error", "message": "..."}
    - {"type": "keepalive"}
    """
    await websocket.accept()

    # Register connection
    if project_id not in agent_chat_connections:
        agent_chat_connections[project_id] = set()
    agent_chat_connections[project_id].add(websocket)

    session_id = None

    # Send connection confirmation
    await websocket.send_text(
        json.dumps(
            {
                "type": "connected",
                "project_id": project_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
    )

    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                message_data = json.loads(data)

                msg_type = message_data.get("type", "message")

                if msg_type == "message":
                    content = message_data.get("content", "")
                    session_id = message_data.get("session_id")
                    context = message_data.get("context", {})

                    if not content.strip():
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "type": "error",
                                    "message": "消息内容不能为空",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                },
                                ensure_ascii=False,
                            )
                        )
                        continue

                    # Get or create session
                    session_id = _get_or_create_session(project_id, session_id)

                    # Process message
                    response = await _process_agent_message(project_id, session_id, content, context)

                    # Send response
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "response",
                                "session_id": response.session_id,
                                "message": response.message,
                                "agent_type": response.agent_type,
                                "actions": response.actions,
                                "knowledge_updated": response.knowledge_updated,
                                "timestamp": response.timestamp,
                            },
                            ensure_ascii=False,
                        )
                    )

                elif msg_type == "history":
                    # Return session history
                    if session_id and session_id in agent_sessions:
                        history = agent_sessions[session_id]["messages"]
                    else:
                        history = []
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "history",
                                "session_id": session_id,
                                "messages": history,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                            ensure_ascii=False,
                        )
                    )

                elif msg_type == "status":
                    # Return agent status
                    from ..database import SessionLocal

                    db = SessionLocal()
                    try:
                        project = db.query(Project).filter(Project.id == project_id).first()
                        knowledge_count = db.query(AgentKnowledge).count()
                        recent_tasks = db.query(TaskRecord).limit(10).all()
                    finally:
                        db.close()

                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "status",
                                "project_id": project_id,
                                "project_title": project.title if project else f"Project {project_id}",
                                "knowledge_entries": knowledge_count,
                                "recent_tasks": len(recent_tasks),
                                "active_sessions": len(
                                    [s for s in agent_sessions.values() if s["project_id"] == project_id]
                                ),
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                            ensure_ascii=False,
                        )
                    )

                elif msg_type == "ping":
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "pong",
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                            ensure_ascii=False,
                        )
                    )

            except asyncio.TimeoutError:
                # Send keepalive
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "keepalive",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        },
                        ensure_ascii=False,
                    )
                )

    except WebSocketDisconnect:
        logger.info(f"Agent chat WebSocket disconnected for project {project_id}")
    except Exception as e:
        logger.error(f"Agent chat WebSocket error: {e}")
    finally:
        # Clean up connection
        if project_id in agent_chat_connections:
            agent_chat_connections[project_id].discard(websocket)
            if not agent_chat_connections[project_id]:
                del agent_chat_connections[project_id]


# ─────────────────────────────────────────────────────────────────────────────
# HTTP Endpoints (fallback for non-WebSocket clients)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/chat", response_model=AgentChatResponse)
async def agent_chat_http(request: AgentChatRequest, db: Session = Depends(get_db)):
    """
    HTTP endpoint for agent chat (polling fallback).

    Send a message to the agent and get a response.
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == request.project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get or create session
    session_id = _get_or_create_session(request.project_id, request.session_id)

    # Process message
    response = await _process_agent_message(
        request.project_id,
        session_id,
        request.message,
        request.context,
    )

    return response


@router.get("/chat/{project_id}/history")
async def get_chat_history(project_id: int, session_id: str, db: Session = Depends(get_db)):
    """Get chat history for a session."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if session_id not in agent_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = agent_sessions[session_id]
    if session["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Session does not belong to this project")

    return {
        "session_id": session_id,
        "project_id": project_id,
        "messages": session["messages"],
        "created_at": session["created_at"],
        "last_active": session["last_active"],
    }


@router.get("/chat/{project_id}/sessions")
async def list_chat_sessions(project_id: int, db: Session = Depends(get_db)):
    """List all chat sessions for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    sessions = [
        {
            "session_id": sid,
            "created_at": info["created_at"],
            "last_active": info["last_active"],
            "message_count": len(info["messages"]),
        }
        for sid, info in agent_sessions.items()
        if info["project_id"] == project_id
    ]

    return {"project_id": project_id, "sessions": sorted(sessions, key=lambda x: x["last_active"], reverse=True)}


@router.delete("/chat/{project_id}/sessions/{session_id}")
async def delete_chat_session(project_id: int, session_id: str, db: Session = Depends(get_db)):
    """Delete a chat session."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if session_id not in agent_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = agent_sessions[session_id]
    if session["project_id"] != project_id:
        raise HTTPException(status_code=400, detail="Session does not belong to this project")

    del agent_sessions[session_id]
    return {"message": "Session deleted", "session_id": session_id}


@router.get("/status/{project_id}", response_model=AgentStatusResponse)
async def get_agent_status(project_id: int, db: Session = Depends(get_db)):
    """Get agent status for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    knowledge_count = db.query(AgentKnowledge).count()
    recent_tasks = db.query(TaskRecord).limit(10).all()
    active_sessions = len([s for s in agent_sessions.values() if s["project_id"] == project_id])

    return AgentStatusResponse(
        project_id=project_id,
        active_sessions=active_sessions,
        knowledge_entries=knowledge_count,
        recent_tasks=len(recent_tasks),
        status="ready",
    )


@router.post("/knowledge")
async def add_knowledge(
    project_id: int,
    topic: str,
    knowledge: Dict[str, Any],
    source_agent: str = "user",
    confidence: float = 1.0,
    db: Session = Depends(get_db),
):
    """Add knowledge to the agent knowledge base."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    knowledge_entry = AgentKnowledge(
        id=str(uuid.uuid4()),
        topic=topic,
        knowledge=knowledge,
        source_agent=source_agent,
        confidence_score={"score": confidence, "factors": []},
        created_at=datetime.now(timezone.utc),
        last_accessed=datetime.now(timezone.utc),
    )
    db.add(knowledge_entry)
    db.commit()
    db.refresh(knowledge_entry)

    # Broadcast knowledge update
    await _broadcast_agent_event(
        project_id,
        {
            "type": "knowledge_added",
            "topic": topic,
            "knowledge_id": knowledge_entry.id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )

    return {"id": knowledge_entry.id, "topic": topic, "message": "Knowledge added successfully"}


@router.get("/knowledge/{project_id}")
async def list_knowledge(project_id: int, topic: Optional[str] = None, db: Session = Depends(get_db)):
    """List knowledge entries for a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query = db.query(AgentKnowledge)
    if topic:
        query = query.filter(AgentKnowledge.topic.contains(topic))

    entries = query.order_by(AgentKnowledge.created_at.desc()).limit(50).all()

    return {
        "project_id": project_id,
        "knowledge": [
            {
                "id": e.id,
                "topic": e.topic,
                "knowledge": e.knowledge,
                "source_agent": e.source_agent,
                "confidence_score": e.confidence_score,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "last_accessed": e.last_accessed.isoformat() if e.last_accessed else None,
            }
            for e in entries
        ],
    }
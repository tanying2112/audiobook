"""Agent Chat API endpoint for real-time agent interaction.

Provides WebSocket endpoint /ws/agent/chat/{project_id} and HTTP fallback
for conversational agent interface with pipeline context.

Also provides FSM-based pipeline execution endpoints:
- POST /agent/pipeline/start - Start pipeline (Autopilot/Interactive)
- POST /agent/pipeline/confirm - Confirm human review (Interactive mode)
- GET /agent/pipeline/status - Get pipeline FSM status
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..agent.fsm import PipelineFSM, PipelineMode, PipelineState, _fsm_instances, get_fsm, remove_fsm
from ..agent.tools import TOOL_DEFINITIONS, TOOL_HANDLERS, execute_tool
from ..api.dependencies import get_async_db
from ..api.websocket import manager as ws_manager
from ..database import create_async_session
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
# Pipeline FSM Request/Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class PipelineStartRequest(BaseModel):
    """Request to start pipeline execution."""

    project_id: int = Field(..., description="Project ID")
    mode: str = Field("autopilot", description="Pipeline mode: 'autopilot' or 'interactive'")
    chapter_index: int = Field(1, description="Starting chapter (1-based)")
    chapter_id: Optional[int] = Field(None, description="Optional chapter DB ID")


class PipelineStartResponse(BaseModel):
    """Response from pipeline start."""

    project_id: int
    mode: str
    current_state: str
    status: str  # "running", "paused", "completed", "failed"
    chapter_index: int
    paused_at: Optional[str] = None
    message: str


class PipelineConfirmRequest(BaseModel):
    """Request to confirm human review (Interactive mode)."""

    project_id: int = Field(..., description="Project ID")
    confirmed: bool = Field(True, description="Whether user confirms the annotations")


class PipelineConfirmResponse(BaseModel):
    """Response from human confirmation."""

    project_id: int
    current_state: str
    status: str  # "running", "paused", "completed", "failed"
    message: str


class PipelineStatusResponse(BaseModel):
    """Pipeline FSM status."""

    project_id: int
    mode: str
    current_state: str
    chapter_index: int
    chapter_id: Optional[int] = None
    paused_at: Optional[str] = None
    user_confirmed: bool = False
    error: Optional[str] = None
    completed_stages: list[str] = Field(default_factory=list)


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
    """Process user message and generate agent response with tool calling.

    Uses LLM to determine which tool to call (if any) based on the user's intent.
    """
    # Add user message to history
    _add_message(session_id, "user", user_message)

    # Get project context
    db = create_async_session()
    try:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        project_title = project.title if project else f"Project {project_id}"

        # Get knowledge base entries
        result = await db.execute(select(AgentKnowledge).where(AgentKnowledge.topic.contains(str(project_id))))
        knowledge_count = len(result.scalars().all())

        # Get recent tasks
        result = await db.execute(
            select(TaskRecord).where(TaskRecord.input_data.contains({"project_id": project_id})).limit(5)
        )
        recent_tasks = result.scalars().all()

    finally:
        await db.close()

    # Prepare system prompt with tool definitions
    system_prompt = f"""你是 Audiobook Studio 的智能助手，负责帮助用户完成有声书制作全流程。

项目《{project_title}》(ID: {project_id}) 当前状态：
- 知识库条目: {knowledge_count}
- 最近任务: {len(recent_tasks)}

可用工具：
{json.dumps(TOOL_DEFINITIONS, ensure_ascii=False, indent=2)}

当用户请求需要执行工具时，请返回 JSON 格式的工具调用：
{{
  "tool_calls": [
    {{
      "name": "tool_name",
      "arguments": {{...}}
    }}
  ]
}}

如果不需要工具，直接用自然语言回复。"""

    # Get recent conversation history for context
    history = agent_sessions.get(session_id, {}).get("messages", [])[-10:]
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend([{"role": m["role"], "content": m["content"]} for m in history])
    messages.append({"role": "user", "content": user_message})

    # Call LLM with tools
    try:
        from ..llm.router import LLMRouter, LLMStage

        router = LLMRouter()
        # Use the analyze stage for tool calling (has function calling capability)
        result = await router.call_stage(
            stage=LLMStage.ANALYZE,
            messages=messages,
            functions=TOOL_DEFINITIONS,
            function_call="auto",
            temperature=0.1,
            max_tokens=2048,
        )

        # Check if LLM returned tool calls
        tool_calls = result.get("tool_calls", [])
        if tool_calls:
            # Execute tools
            actions = []
            tool_results = []

            for tool_call in tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["arguments"]

                try:
                    tool_result = await execute_tool(tool_name, tool_args)
                    tool_results.append(tool_result)
                    actions.append(
                        {
                            "tool": tool_name,
                            "args": tool_args,
                            "result": tool_result,
                        }
                    )
                except Exception as e:
                    logger.error(f"Tool {tool_name} failed: {e}")
                    tool_results.append({"error": str(e)})
                    actions.append(
                        {
                            "tool": tool_name,
                            "args": tool_args,
                            "error": str(e),
                        }
                    )

            # Generate response based on tool results
            response_messages = messages + [
                {"role": "assistant", "content": None, "tool_calls": tool_calls},
                *[
                    {"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(tr, ensure_ascii=False)}
                    for tc, tr in zip(tool_calls, tool_results)
                ],
            ]

            final_result = await router.call_stage(
                stage=LLMStage.ANALYZE,
                messages=response_messages,
                temperature=0.3,
                max_tokens=1024,
            )
            response_text = final_result.get("content", "工具执行完成。")
            agent_type = "tool_executor"

        else:
            # No tool calls, use direct response
            response_text = result.get("content", "我明白了。请告诉我具体想做什么？")
            agent_type = "general"
            actions = []

    except Exception as e:
        logger.error(f"Agent processing error: {e}")
        response_text = f"处理消息时出错: {str(e)}"
        agent_type = "error"
        actions = []

    # Add assistant response to history
    _add_message(session_id, "assistant", response_text, {"agent_type": agent_type, "actions": actions})

    return AgentChatResponse(
        session_id=session_id,
        message=response_text,
        agent_type=agent_type,
        actions=actions,
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
                    db = create_async_session()
                    try:
                        result = await db.execute(select(Project).where(Project.id == project_id))
                        project = result.scalar_one_or_none()

                        result = await db.execute(select(AgentKnowledge))
                        knowledge_count = len(result.scalars().all())

                        result = await db.execute(select(TaskRecord).limit(10))
                        recent_tasks = result.scalars().all()
                    finally:
                        await db.close()

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
async def agent_chat_http(request: AgentChatRequest, db: AsyncSession = Depends(get_async_db)):
    """
    HTTP endpoint for agent chat (polling fallback).

    Send a message to the agent and get a response.
    """
    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == request.project_id))
    project = result.scalar_one_or_none()
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
async def get_chat_history(project_id: int, session_id: str, db: AsyncSession = Depends(get_async_db)):
    """Get chat history for a session."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
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
async def list_chat_sessions(project_id: int, db: AsyncSession = Depends(get_async_db)):
    """List all chat sessions for a project."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
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
async def delete_chat_session(project_id: int, session_id: str, db: AsyncSession = Depends(get_async_db)):
    """Delete a chat session."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
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
async def get_agent_status(project_id: int, db: AsyncSession = Depends(get_async_db)):
    """Get agent status for a project."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(select(AgentKnowledge))
    knowledge_count = len(result.scalars().all())
    result = await db.execute(select(TaskRecord).limit(10))
    recent_tasks = result.scalars().all()
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
    db: AsyncSession = Depends(get_async_db),
):
    """Add knowledge to the agent knowledge base."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
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
    await db.commit()
    await db.refresh(knowledge_entry)

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
async def list_knowledge(project_id: int, topic: Optional[str] = None, db: AsyncSession = Depends(get_async_db)):
    """List knowledge entries for a project."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    query = select(AgentKnowledge)
    if topic:
        query = query.where(AgentKnowledge.topic.contains(topic))

    result = await db.execute(query.order_by(AgentKnowledge.created_at.desc()).limit(50))
    entries = result.scalars().all()

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


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline FSM Endpoints (Task 2.2)
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/pipeline/start", response_model=PipelineStartResponse)
async def start_pipeline(request: PipelineStartRequest, db: AsyncSession = Depends(get_async_db)):
    """Start pipeline execution (Autopilot or Interactive mode).

    - Autopilot: runs all stages sequentially to completion
    - Interactive: runs through annotate, then pauses at PENDING_HUMAN_CONFIRM
      waiting for user confirmation via POST /agent/pipeline/confirm
    """
    result = await db.execute(select(Project).where(Project.id == request.project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    mode = PipelineMode(request.mode.lower())
    if mode not in [PipelineMode.AUTOPILOT, PipelineMode.INTERACTIVE]:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'autopilot' or 'interactive'")

    # Create FSM instance
    fsm = get_fsm(
        project_id=request.project_id,
        mode=mode,
        chapter_index=request.chapter_index,
        chapter_id=request.chapter_id,
    )

    # Run pipeline until pause or completion
    result = await fsm.run_until_pause_or_complete()

    return PipelineStartResponse(
        project_id=request.project_id,
        mode=mode.value,
        current_state=result["current_state"],
        status=result["status"],
        chapter_index=result["chapter_index"],
        paused_at=result.get("paused_at"),
        message=f"Pipeline {result['status']} at {result['current_state']}",
    )


@router.post("/pipeline/confirm", response_model=PipelineConfirmResponse)
async def confirm_pipeline(request: PipelineConfirmRequest, db: AsyncSession = Depends(get_async_db)):
    """Confirm human review and continue pipeline (Interactive mode only)."""
    result = await db.execute(select(Project).where(Project.id == request.project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    fsm = get_fsm(request.project_id)

    if fsm.mode != PipelineMode.INTERACTIVE:
        raise HTTPException(status_code=400, detail="Confirm only available in interactive mode")

    if not request.confirmed:
        # User rejected - stop pipeline
        fsm.context.current_state = PipelineState.FAILED
        fsm.context.error = "User rejected annotations"
        remove_fsm(request.project_id)
        return PipelineConfirmResponse(
            project_id=request.project_id,
            current_state=PipelineState.FAILED.value,
            status="failed",
            message="Pipeline stopped: user rejected annotations",
        )

    # Continue after confirmation
    result = await fsm.continue_after_confirmation()

    if result["status"] == "completed":
        remove_fsm(request.project_id)

    return PipelineConfirmResponse(
        project_id=request.project_id,
        current_state=result["current_state"],
        status=result["status"],
        message=f"Pipeline {result['status']} at {result['current_state']}",
    )


@router.get("/pipeline/status/{project_id}", response_model=PipelineStatusResponse)
async def get_pipeline_status(project_id: int, db: AsyncSession = Depends(get_async_db)):
    """Get current pipeline FSM status."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project_id not in _fsm_instances:
        return PipelineStatusResponse(
            project_id=project_id,
            mode="idle",
            current_state="idle",
            chapter_index=0,
        )

    fsm = _fsm_instances[project_id]
    status = fsm.get_status()

    return PipelineStatusResponse(
        project_id=status["project_id"],
        mode=status["mode"],
        current_state=status["current_state"],
        chapter_index=status["chapter_index"],
        chapter_id=status["chapter_id"],
        paused_at=status["paused_at"],
        user_confirmed=status["user_confirmed"],
        error=status["error"],
        completed_stages=status["completed_stages"],
    )


@router.post("/pipeline/stop/{project_id}")
async def stop_pipeline(project_id: int, db: AsyncSession = Depends(get_async_db)):
    """Stop and cleanup pipeline FSM."""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project_id in _fsm_instances:
        _fsm_instances[project_id].stop()
        remove_fsm(project_id)
        return {"message": "Pipeline stopped", "project_id": project_id}

    return {"message": "No active pipeline for project", "project_id": project_id}


# Need to expose _fsm_instances for the endpoints
from ..agent.fsm import _fsm_instances as _agent_fsm_instances

"""LLM API endpoints for chat-based editing and annotation."""

import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..llm.router import get_llm_router

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["llm"])


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class ChatEditRequest(BaseModel):
    """Request for chat-based text editing.

    Tolerant to the frontend payload (types/pipeline.ts ChatEditRequest):
    paragraph_id/paragraph_index are interchangeable, original_text defaults
    to empty (frontend sends the selection via annotation_context), and
    history entries may carry structured suggestion objects.
    """

    paragraph_id: Optional[int] = Field(None, description="Paragraph index or ID")
    paragraph_index: Optional[int] = Field(None, description="Alias for paragraph_id (frontend payload)")
    project_id: int = Field(..., description="Project ID")
    chapter_index: Optional[int] = Field(None, description="Chapter index (frontend payload)")
    original_text: str = Field("", description="Original paragraph text")
    intent: str = Field(..., description="User's editing intent, e.g., 'make it more colloquial'")
    target_stage: Optional[str] = Field(None, description="Target stage: edit/annotate (frontend payload)")
    annotation_context: Optional[Dict[str, Any]] = Field(
        None, description="Current annotation (speaker, emotion, etc.)"
    )
    conversation_history: Optional[List[Dict[str, Any]]] = Field(None, description="Previous conversation turns")
    difficulty: Optional[str] = Field(None, description="Paragraph difficulty (A/B/C/D)")

    @property
    def effective_paragraph_id(self) -> int:
        """Paragraph id with the frontend's paragraph_index alias resolved."""
        if self.paragraph_index is not None:
            return self.paragraph_index
        return self.paragraph_id or 0


class ChatEditResponse(BaseModel):
    """Response from LLM edit suggestion."""

    edited_text: str = Field(..., description="Suggested edited text")
    changes_made: List[str] = Field(default_factory=list, description="List of changes made")
    rationale: str = Field(..., description="LLM's reasoning for the changes")
    confidence: float = Field(0.0, ge=0, le=1, description="Confidence score 0-1")
    forbid_edit: bool = Field(False, description="Whether editing is forbidden (difficulty lock)")


class ChatAnnotateRequest(BaseModel):
    """Request for chat-based annotation adjustment.

    Tolerant to the frontend payload, same as ChatEditRequest.
    """

    paragraph_id: Optional[int] = Field(None, description="Paragraph index or ID")
    paragraph_index: Optional[int] = Field(None, description="Alias for paragraph_id (frontend payload)")
    project_id: int = Field(..., description="Project ID")
    chapter_index: Optional[int] = Field(None, description="Chapter index (frontend payload)")
    original_text: str = Field("", description="Paragraph text")
    current_annotation: Optional[Dict[str, Any]] = Field(None, description="Current annotation")
    user_instruction: str = Field(
        "",
        description="User's instruction, e.g., 'this is said by Zhang San, more angry'",
    )
    intent: Optional[str] = Field(None, description="Alias for user_instruction (frontend payload)")
    target_stage: Optional[str] = Field(None, description="Target stage: edit/annotate (frontend payload)")
    conversation_history: Optional[List[Dict[str, Any]]] = Field(None, description="Previous conversation turns")

    @property
    def effective_paragraph_id(self) -> int:
        """Paragraph id with the frontend's paragraph_index alias resolved."""
        if self.paragraph_index is not None:
            return self.paragraph_index
        return self.paragraph_id or 0


class ChatAnnotateResponse(BaseModel):
    """Response from LLM annotation adjustment."""

    speaker_canonical_name: Optional[str] = Field(None, description="Suggested speaker")
    emotion: Optional[str] = Field(None, description="Suggested emotion")
    emotion_intensity: Optional[float] = Field(None, ge=0, le=1, description="Emotion intensity")
    is_dialogue: Optional[bool] = Field(None, description="Whether it's dialogue")
    speech_rate: Optional[float] = Field(None, description="Speech rate 0.7-1.3")
    pitch_shift: Optional[float] = Field(None, description="Pitch shift in semitones")
    pause_before_ms: Optional[int] = Field(None, description="Pause before in ms")
    pause_after_ms: Optional[int] = Field(None, description="Pause after in ms")
    rationale: str = Field(..., description="LLM's reasoning")
    confidence: float = Field(0.0, ge=0, le=1, description="Confidence score 0-1")
    needs_new_character: bool = Field(False, description="Whether a new character needs to be created")


class BatchAnnotateRequest(BaseModel):
    """Request for batch annotation suggestions."""

    chapter_id: int = Field(..., description="Chapter ID")
    project_id: int = Field(..., description="Project ID")
    paragraph_ids: Optional[List[int]] = Field(None, description="Specific paragraphs to annotate, or None for all")


class BatchAnnotateResponse(BaseModel):
    """Response with batch annotation suggestions."""

    suggestions: List[Dict[str, Any]] = Field(default_factory=list, description="Annotation suggestions per paragraph")
    total_count: int = Field(0, description="Total paragraphs processed")


class AssistantRequest(BaseModel):
    """Request for global AI assistant."""

    question: str = Field(..., description="User's question")
    context: Optional[Dict[str, Any]] = Field(None, description="Current UI context (project, chapter, paragraph)")


class AssistantResponse(BaseModel):
    """Response from AI assistant."""

    answer: str = Field(..., description="LLM's answer")
    suggested_actions: Optional[List[Dict[str, str]]] = Field(None, description="Suggested UI actions")


# ─────────────────────────────────────────────────────────────────────────────
# Prompt Templates
# ─────────────────────────────────────────────────────────────────────────────

CHAT_EDIT_SYSTEM_PROMPT = """You are an expert audiobook text editor assistant. Your role is to help users edit text for TTS narration.

CAPABILITIES:
- Make text more colloquial or formal
- Adjust character voice/tone
- Split long sentences
- Normalize numbers and abbreviations
- Remove sensitive content
- Adjust pacing hints for TTS

CONSTRAINTS:
- If difficulty is 'A' (critical), only fix typos and punctuation - do not change content
- Preserve the original meaning
- Keep edits minimal and natural
- Explain your reasoning clearly

RESPONSE FORMAT:
Return a JSON object with:
{
  "edited_text": "<the edited text>",
  "changes_made": ["change 1", "change 2", ...],
  "rationale": "<why you made these changes>",
  "confidence": 0.95,
  "forbid_edit": false
}"""

CHAT_ANNOTATE_SYSTEM_PROMPT = """You are an expert audiobook annotation assistant. Your role is to help users assign semantic annotations to text for TTS narration.

CAPABILITIES:
- Identify speakers and their canonical names
- Detect emotions and intensity
- Determine if text is dialogue or narration
- Suggest speech rate, pitch, and pauses
- Recognize when a new character is being introduced

EMOTION CATEGORIES:
neutral, happy, sad, angry, afraid, surprised, disgusted, excited, thoughtful, mysterious, dramatic, calm, tired, hopeful

SPEECH RATE: 0.7 (slow) to 1.3 (fast), 1.0 is normal

RESPONSE FORMAT:
Return a JSON object with:
{
  "speaker_canonical_name": "<speaker name or null>",
  "emotion": "<emotion or null>",
  "emotion_intensity": 0.5,
  "is_dialogue": true,
  "speech_rate": 1.0,
  "pitch_shift": 0,
  "pause_before_ms": 300,
  "pause_after_ms": 500,
  "rationale": "<why you chose these annotations>",
  "confidence": 0.9,
  "needs_new_character": false
}"""


# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────


async def stream_json_lines(data_stream: AsyncGenerator[str, None]) -> AsyncGenerator[bytes, None]:
    """Stream JSON lines for SSE."""
    async for chunk in data_stream:
        yield f"data: {chunk}\n\n".encode("utf-8")
    yield b"data: [DONE]\n\n"


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


def _create_chat_client():
    """Create an LLM client for the chat endpoints.

    The bare ``create_client()`` calls the chat endpoints used before never
    worked (create_client requires a model argument). Route through the first
    enabled provider from the routing config — the same default the pipeline
    stages rely on, with key-pool rotation and timeout from the provider.
    """
    router = get_llm_router()
    enabled = router.config.get_all_enabled()
    if not enabled:
        raise HTTPException(status_code=503, detail="No LLM provider configured")
    return router.get_client(enabled[0])


@router.post("/chat-edit")
async def chat_edit(request: ChatEditRequest):
    """
    Chat-based text editing with streaming SSE response.

    User selects text and describes editing intent (e.g., "make it more colloquial").
    LLM returns streaming edit suggestions with diff preview.
    """
    try:
        # Check if editing is forbidden (difficulty lock)
        if request.difficulty == "A":
            # For critical text, only allow minimal fixes
            forbid_edit = True
        else:
            forbid_edit = False

        async def generate_edit() -> AsyncGenerator[str, None]:
            """Generate streaming edit response."""
            llm_client = _create_chat_client()
            message_id = str(uuid.uuid4())

            # Frontend SSE protocol (matches the mock endpoint): thinking →
            # token* → suggestion → done. suggestion must be nested under the
            # "suggestion" key or the frontend parser drops it.
            yield json.dumps({"type": "thinking", "message_id": message_id}, ensure_ascii=False)

            # Build conversation messages
            system_msg = {"role": "system", "content": CHAT_EDIT_SYSTEM_PROMPT}

            # Frontend inline chat sends the selection via annotation_context
            # rather than original_text — resolve both.
            original_text = request.original_text or str((request.annotation_context or {}).get("selected_text") or "")
            context_info = f"""
Original text: {original_text}
Editing intent: {request.intent}
Current annotation: {json.dumps(request.annotation_context) if request.annotation_context else 'None'}
Difficulty: {request.difficulty or 'Unknown'}
"""

            # Build conversation history
            messages = [system_msg]
            if request.conversation_history:
                messages.extend(request.conversation_history)
            messages.append({"role": "user", "content": context_info})

            # LLMClient has no streaming interface — use the standard
            # structured call() (instructor parsing, semantic cache, mock
            # mode) and emit the rationale as a single token update so the
            # frontend accumulator still renders streaming text.
            try:
                result = await asyncio.to_thread(
                    llm_client.call,
                    messages=messages,
                    response_model=ChatEditResponse,
                    temperature=0.7,
                    max_tokens=1000,
                )
            except Exception as e:
                # Surface the real reason as an SSE error event so the
                # frontend popup shows it instead of a bare HTTP 500.
                logger.error(f"Chat edit LLM call failed: {e}")
                yield json.dumps(
                    {"type": "error", "message": f"LLM unavailable: {e}", "code": "LLM_UNAVAILABLE"},
                    ensure_ascii=False,
                )
                return
            parsed = result.output
            edited_text = parsed.edited_text or original_text
            changes_made = list(parsed.changes_made or [])
            rationale = parsed.rationale or ""
            confidence = parsed.confidence
            forbid_edit = bool(parsed.forbid_edit)

            if rationale:
                yield json.dumps({"type": "token", "content": rationale}, ensure_ascii=False)

            # Send suggestion with full parsed data (frontend expects "suggestion" type)
            yield json.dumps(
                {
                    "type": "suggestion",
                    "suggestion": {
                        "kind": "text_edit",
                        "paragraph_id": str(request.effective_paragraph_id),
                        "before": {"original_text": original_text},
                        "after": {"edited_text": edited_text},
                        "changes_made": changes_made,
                        "confidence": confidence,
                        "rationale": rationale,
                        "edited_text": edited_text,
                        "forbid_edit": forbid_edit,
                    },
                    "message_id": message_id,
                },
                ensure_ascii=False,
            )

            # Signal completion (frontend expects "done" type)
            yield json.dumps(
                {
                    "type": "done",
                    "message_id": message_id,
                    "edited_text": edited_text,
                    "changes_made": changes_made,
                    "rationale": rationale,
                    "confidence": confidence,
                    "forbid_edit": forbid_edit,
                },
                ensure_ascii=False,
            )

        return StreamingResponse(
            stream_json_lines(generate_edit()),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as e:
        logger.error(f"Chat edit failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/chat-annotate")
async def chat_annotate(request: ChatAnnotateRequest):
    """
    Chat-based annotation adjustment with streaming SSE response.

    User describes annotation adjustment (e.g., "this is Zhang San, more angry").
    LLM returns streaming annotation suggestions.
    """
    try:

        async def generate_annotation() -> AsyncGenerator[str, None]:
            """Generate streaming annotation response."""
            llm_client = _create_chat_client()
            message_id = str(uuid.uuid4())

            # Same SSE protocol as chat-edit: thinking → token* → suggestion → done.
            yield json.dumps({"type": "thinking", "message_id": message_id}, ensure_ascii=False)

            # Build conversation messages
            system_msg = {"role": "system", "content": CHAT_ANNOTATE_SYSTEM_PROMPT}

            # Frontend streamChatAnnotate sends intent as the instruction alias.
            user_instruction = request.user_instruction or request.intent or ""
            original_text = request.original_text or str((request.current_annotation or {}).get("selected_text") or "")
            context_info = f"""
Text: {original_text}
User instruction: {user_instruction}
Current annotation: {json.dumps(request.current_annotation) if request.current_annotation else 'None'}
"""

            # Build conversation history
            messages = [system_msg]
            if request.conversation_history:
                messages.extend(request.conversation_history)
            messages.append({"role": "user", "content": context_info})

            # Same structured call() as chat-edit — LLMClient has no streaming.
            try:
                result = await asyncio.to_thread(
                    llm_client.call,
                    messages=messages,
                    response_model=ChatAnnotateResponse,
                    temperature=0.5,
                    max_tokens=500,
                )
            except Exception as e:
                logger.error(f"Chat annotate LLM call failed: {e}")
                yield json.dumps(
                    {"type": "error", "message": f"LLM unavailable: {e}", "code": "LLM_UNAVAILABLE"},
                    ensure_ascii=False,
                )
                return
            parsed = result.output
            full_response = parsed.rationale or ""
            if full_response:
                yield json.dumps({"type": "token", "content": full_response}, ensure_ascii=False)

            # Send suggestion (frontend expects "suggestion" type)
            yield json.dumps(
                {
                    "type": "suggestion",
                    "suggestion": {
                        "kind": "annotation_adjust",
                        "paragraph_id": str(request.effective_paragraph_id),
                        "changes_made": [],
                        "confidence": 0.8,
                        "rationale": full_response,
                    },
                    "message_id": message_id,
                },
                ensure_ascii=False,
            )

            # Signal completion (frontend expects "done" type)
            yield json.dumps(
                {
                    "type": "done",
                    "message_id": message_id,
                    "rationale": full_response,
                },
                ensure_ascii=False,
            )

        return StreamingResponse(
            stream_json_lines(generate_annotation()),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    except Exception as e:
        logger.error(f"Chat annotate failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/batch-annotate")
async def batch_annotate(request: BatchAnnotateRequest):
    """
    Batch annotation suggestions for a chapter.

    Scans unannotated paragraphs and suggests annotations.
    """
    try:
        # TODO: Implement batch annotation logic
        # For now, return empty response
        return BatchAnnotateResponse(
            suggestions=[],
            total_count=0,
        )
    except Exception as e:
        logger.error(f"Batch annotate failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/assistant")
async def assistant(request: AssistantRequest):
    """
    Global AI assistant for context-aware Q&A.

    Answers questions about the project, provides suggestions, and can trigger actions.
    """
    try:
        llm_client = _create_chat_client()

        system_msg = {
            "role": "system",
            "content": """You are a helpful AI assistant for an audiobook production studio.

You can help users with:
- Explaining HARNESS system features
- Answering questions about pipeline status
- Suggesting improvements
- Navigating the UI

Be concise and helpful. If the user asks about features that don't exist yet,
acknowledge it's planned but not implemented.""",
        }

        context_info = f"""
User question: {request.question}
Current context: {json.dumps(request.context) if request.context else 'None'}
"""

        messages = [system_msg, {"role": "user", "content": context_info}]

        # LLMClient is not a litellm client — the old direct
        # chat.completions.create(model="sonnet") call never worked. Use the
        # standard structured call() via the routed client.
        result = await asyncio.to_thread(
            llm_client.call,
            messages=messages,
            response_model=AssistantResponse,
            temperature=0.7,
            max_tokens=500,
        )

        answer = result.output.answer

        # Generate suggested actions based on context
        suggested_actions = []
        if "quality" in request.question.lower():
            suggested_actions.append(
                {
                    "label": "View quality report",
                    "action": "navigate:quality",
                }
            )

        return AssistantResponse(
            answer=answer,
            suggested_actions=suggested_actions if suggested_actions else None,
        )

    except Exception as e:
        logger.error(f"Assistant failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


# ─────────────────────────────────────────────────────────────────────────────
# LLM Router Status Endpoint (Phase 5)
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/status")
async def llm_status():
    """Get aggregated LLM router status.

    Returns providers health, key pool stats, circuit breaker states,
    cost tracking, quota registry, and mock mode flag.
    """
    from ..llm.router import get_llm_router

    try:
        router = get_llm_router()
        return router.get_aggregated_status()
    except Exception as e:
        logger.error(f"LLM status endpoint failed: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e

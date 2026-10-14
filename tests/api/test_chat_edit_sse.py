"""SSE protocol tests for /api/llm/chat-edit and /api/llm/chat-annotate.

Red-line main-path check: the REAL route is hit with a fake LLM client
(patched create_client), asserting the event contract the frontend
streamChatEdit parser requires:
  1. first event is {"type": "thinking", ...}
  2. suggestion payload is NESTED under the "suggestion" key (the frontend
     parser reads evt.suggestion — a flat payload is silently dropped)
  3. stream ends with a "done" event
"""

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.audiobook_studio.api.llm import router


class _FakeOutput:
    """Stands in for the instructor-parsed output (ChatEditResponse / ChatAnnotateResponse)."""

    def __init__(self, rationale: str):
        self.edited_text = ""
        self.changes_made: list = []
        self.rationale = rationale
        self.confidence = 0.8
        self.forbid_edit = False


class _FakeCallResult:
    def __init__(self, output):
        self.output = output


class _FakeLLMClient:
    """Mimics llm.client.LLMClient — only the real .call() interface is needed."""

    def __init__(self, tokens):
        self._rationale = "".join(tokens)

    def call(self, *args, **kwargs):
        return _FakeCallResult(_FakeOutput(self._rationale))


@pytest.fixture()
def client(monkeypatch):
    import src.audiobook_studio.api.llm as llm_mod

    monkeypatch.setattr(llm_mod, "_create_chat_client", lambda: _FakeLLMClient(["更口语", "化的改写"]))
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as c:
        yield c


def _sse_events(raw: str):
    """Parse the SSE stream into event dicts (same framing as the frontend)."""
    events = []
    for frame in raw.split("\n\n"):
        data_lines = [line[5:].strip() for line in frame.split("\n") if line.startswith("data:")]
        if not data_lines:
            continue
        payload = "\n".join(data_lines)
        if payload == "[DONE]":
            events.append("[DONE]")
        else:
            events.append(json.loads(payload))
    return events


def test_chat_edit_sse_protocol(client):
    resp = client.post(
        "/llm/chat-edit",
        json={
            # Frontend-shaped payload exactly as useInlineChat → streamChatEdit
            # sends it: paragraph_index alias (no paragraph_id), no original_text
            # (selection arrives via annotation_context), extra target_stage,
            # and history entries carrying structured suggestion objects.
            "project_id": 1,
            "chapter_index": 3,
            "paragraph_index": 9,
            "target_stage": "edit",
            "intent": "更口语化",
            "annotation_context": {"selected_text": "原文内容", "param_field": "edited_text"},
            "conversation_history": [
                {
                    "id": "msg_1",
                    "role": "assistant",
                    "content": "上一轮",
                    "timestamp": "2026-01-01T00:00:00Z",
                    "suggestion": {
                        "kind": "text_edit",
                        "paragraph_id": "9",
                        "before": {},
                        "after": {},
                        "changes_made": [],
                        "confidence": 0.9,
                        "rationale": "r",
                    },
                },
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")

    events = _sse_events(resp.text)

    # 1. thinking first, with a message_id
    assert events[0]["type"] == "thinking"
    assert events[0]["message_id"]

    # 2. token events carry the streamed text
    token_events = [e for e in events if isinstance(e, dict) and e.get("type") == "token"]
    assert "".join(e["content"] for e in token_events) == "更口语化的改写"

    # 3. suggestion is nested under "suggestion" — the frontend reads
    #    evt.suggestion; a flat payload would be dropped silently.
    suggestion_events = [e for e in events if isinstance(e, dict) and e.get("type") == "suggestion"]
    assert len(suggestion_events) == 1
    suggestion = suggestion_events[0]["suggestion"]
    assert suggestion["kind"] == "text_edit"
    assert suggestion["paragraph_id"] == "9"
    assert suggestion["rationale"] == "更口语化的改写"
    # original_text resolved from the annotation_context selection
    assert suggestion["edited_text"] == "原文内容"
    assert suggestion_events[0]["message_id"] == events[0]["message_id"]

    # 4. done event closes the stream
    assert events[-2]["type"] == "done"
    assert events[-1] == "[DONE]"


def test_chat_annotate_sse_protocol(client):
    resp = client.post(
        "/llm/chat-annotate",
        json={
            # Frontend-shaped payload: streamChatAnnotate sends the same
            # ChatEditRequest shape (intent, no user_instruction).
            "project_id": 1,
            "chapter_index": 2,
            "paragraph_index": 3,
            "target_stage": "annotate",
            "intent": "这是张三说的，更愤怒",
        },
    )
    assert resp.status_code == 200

    events = _sse_events(resp.text)
    assert events[0]["type"] == "thinking"
    assert events[0]["message_id"]

    suggestion_events = [e for e in events if isinstance(e, dict) and e.get("type") == "suggestion"]
    assert len(suggestion_events) == 1
    suggestion = suggestion_events[0]["suggestion"]
    assert suggestion["kind"] == "annotation_adjust"
    assert suggestion["paragraph_id"] == "3"
    assert suggestion["rationale"] == "更口语化的改写"
    assert events[-2]["type"] == "done"
    assert events[-1] == "[DONE]"

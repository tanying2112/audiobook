"""Sprint 1 S1-4 coverage: feedback API endpoints (no external dependencies).

Exercises the feedback REST endpoints with in-process calls, isolating any
external persistence/LLM behind the module-level store.
"""

from __future__ import annotations

import asyncio

from src.audiobook_studio.api.feedback import (
    FeedbackCreate,
    create_feedback,
    get_feedback,
    get_feedback_stats,
    list_feedback,
)


def _sample() -> FeedbackCreate:
    return FeedbackCreate(
        source="human_edit",
        stage="edit_for_tts",
        book_id="book-s1-4",
        input_snapshot={"text": "Hello"},
        llm_output={"text": "Hi"},
        corrected_output={"text": "Hello there"},
        rationale="Added greeting for naturalness",
    )


def test_create_feedback_returns_record() -> None:
    """Creating feedback returns a stored record with an id and pattern tags."""
    result = asyncio.run(create_feedback(_sample()))
    assert result.id is not None
    assert result.book_id == "book-s1-4"
    assert "human_edit" in result.pattern_tags


def test_get_feedback_stats_counts_created() -> None:
    """Feedback stats aggregate the created records for a book."""
    created = asyncio.run(create_feedback(_sample()))
    stats = asyncio.run(get_feedback_stats(book_id="book-s1-4"))
    assert stats["total_feedback"] >= 1
    assert created.id is not None


def test_get_feedback_by_id() -> None:
    """Fetching by id returns the matching record."""
    created = asyncio.run(create_feedback(_sample()))
    fetched = asyncio.run(get_feedback(created.id))
    assert fetched.id == created.id
    assert fetched.rationale == "Added greeting for naturalness"

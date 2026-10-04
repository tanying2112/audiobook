"""Tests for S2.6 — eliminate N+1 queries, optimize DB performance.

Verifies:
- list endpoints use explicit selectinload options (contract check, no lazy N+1).
- The slow-query logger is threshold-configurable (off when SLOW_QUERY_MS=0,
  on when >0) using a real in-memory async engine.
"""

import inspect
import sys
from unittest.mock import patch

sys.path.insert(0, "src")

import audiobook_studio.database as db_mod
from audiobook_studio.api import books as books_api
from audiobook_studio.api import projects as projects_api


def test_list_projects_uses_selectinload():
    """list_projects must eager-load chapters/characters/feedback (no N+1)."""
    src = inspect.getsource(projects_api.list_projects)
    assert "selectinload" in src
    assert "Project.chapters" in src
    assert "Project.characters" in src


def test_list_chapters_uses_selectinload():
    """list_chapters must eager-load paragraphs (no N+1 on serialization)."""
    src = inspect.getsource(projects_api.list_chapters)
    assert "selectinload" in src
    assert "Chapter.paragraphs" in src


def test_list_books_uses_selectinload():
    src = inspect.getsource(books_api.list_books)
    assert "selectinload" in src
    assert "LegacyBook.paragraphs" in src


def test_get_book_uses_selectinload():
    src = inspect.getsource(books_api.get_book)
    assert "selectinload" in src


def test_slow_query_logger_disabled_when_threshold_zero():
    """SLOW_QUERY_MS=0 installs no listeners (returns early)."""
    with patch.dict("os.environ", {"SLOW_QUERY_MS": "0"}):
        # Build a real in-memory async engine and confirm no listener fires.
        from sqlalchemy.ext.asyncio import create_async_engine

        with patch("sqlalchemy.event.listens_for") as mock_listens:
            eng = create_async_engine("sqlite+aiosqlite:///:memory:")
            db_mod._install_slow_query_logger(eng)
            # With threshold 0 the function returns before registering anything.
            mock_listens.assert_not_called()


def test_slow_query_logger_enabled_when_threshold_positive():
    """SLOW_QUERY_MS>0 registers before/after cursor listeners."""
    with patch.dict("os.environ", {"SLOW_QUERY_MS": "500"}):
        from sqlalchemy.ext.asyncio import create_async_engine

        with patch("sqlalchemy.event.listens_for") as mock_listens:
            eng = create_async_engine("sqlite+aiosqlite:///:memory:")
            db_mod._install_slow_query_logger(eng)
            # Two listeners: before_cursor_execute + after_cursor_execute.
            assert mock_listens.call_count == 2

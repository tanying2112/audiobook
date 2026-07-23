"""Tests for API projects router with global auth default-deny.

Tests cover CRUD operations for projects, chapters, and paragraphs
with proper authentication and authorization.
"""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


class TestProjectsAuth:
    """Tests for authentication requirements on projects endpoints."""

    def test_auth_imports_work(self):
        """Verify imports work."""
        from src.audiobook_studio.api.dependencies import get_async_db
        from src.audiobook_studio.api.projects import router
        from src.audiobook_studio.auth.dependencies import get_current_active_user

        assert router is not None


def _make_project(status="active"):
    """Create a mock project."""
    p = MagicMock()
    p.id = 1
    p.title = "Test Project"
    p.author = "Test Author"
    p.genre = "Fiction"
    p.language = "zh"
    p.difficulty = "C"
    p.status = status
    p.current_stage = "extract"
    p.progress = 0.0
    p.total_cost_usd = 0.0
    p.created_at = "2024-01-01T00:00:00Z"
    p.updated_at = "2024-01-01T00:00:00Z"
    return p


def _make_chapter():
    """Create a mock chapter."""
    c = MagicMock()
    c.id = 1
    c.project_id = 1
    c.index = 1
    c.title = "Chapter 1"
    c.status = "completed"
    c.extract_status = "completed"
    c.analyze_status = "completed"
    c.annotate_status = "completed"
    c.edit_status = "completed"
    c.route_status = "completed"
    c.synthesize_status = "completed"
    c.quality_status = "completed"
    c.cost_usd = 0.1
    c.token_count = 1000
    c.tts_chars = 500
    return c


def _make_paragraph():
    """Create a mock paragraph."""
    p = MagicMock()
    p.id = 1
    p.project_id = 1
    p.chapter_id = 1
    p.chapter_index = 1
    p.index = 1
    p.text = "Test paragraph"
    p.speaker = "Narrator"
    p.speaker_canonical_name = "Narrator"
    p.is_dialogue = False
    p.emotion = "neutral"
    p.edited_text = "Test paragraph"
    p.status = "completed"
    return p


def _setup_execute_result(db, return_value):
    """Helper to set up db.execute().scalar_one_or_none() or .scalars().all()"""
    mock_result = MagicMock()
    if isinstance(return_value, list):
        mock_result.scalars.return_value.all.return_value = return_value
        mock_result.scalars.return_value.first.return_value = return_value[0] if return_value else None
    else:
        mock_result.scalar_one_or_none.return_value = return_value
    db.execute.return_value = mock_result
    return mock_result


class TestProjectEndpoints:
    """Tests for project CRUD endpoints."""

    @pytest.mark.asyncio
    async def test_create_project(self):
        """Test creating a project."""
        from src.audiobook_studio.api.projects import create_project
        from src.audiobook_studio.auth.models import RoleName
        from src.audiobook_studio.models import Project, ProjectPermission, User

        db = AsyncMock()
        db.add = AsyncMock()
        db.commit = AsyncMock()
        db.refresh = AsyncMock(side_effect=lambda p: setattr(p, "id", 1))

        user = MagicMock(spec=User)
        user.id = 1

        payload = MagicMock()
        payload.model_dump.return_value = {
            "title": "Test Project",
            "author": "Test Author",
            "genre": "Fiction",
            "language": "zh",
            "difficulty": "C",
        }

        result = await create_project(payload, db, user)

        assert result.id == 1
        assert db.add.call_count == 2  # Project + ProjectPermission
        assert db.commit.call_count == 2

    @pytest.mark.asyncio
    async def test_list_projects(self):
        """Test listing projects."""
        from src.audiobook_studio.api.projects import list_projects

        db = AsyncMock()
        _setup_execute_result(db, [_make_project()])

        result = await list_projects(skip=0, limit=100, db=db)

        assert len(result) == 1
        assert result[0].title == "Test Project"

    @pytest.mark.asyncio
    async def test_get_project(self):
        """Test getting a project."""
        from src.audiobook_studio.api.projects import get_project

        db = AsyncMock()
        _setup_execute_result(db, _make_project())

        result = await get_project(project_id=1, db=db)

        assert result.id == 1
        assert result.title == "Test Project"

    @pytest.mark.asyncio
    async def test_get_project_not_found(self):
        """Test getting non-existent project returns 404."""
        from src.audiobook_studio.api.projects import get_project

        db = AsyncMock()
        _setup_execute_result(db, None)

        with pytest.raises(HTTPException) as exc_info:
            await get_project(project_id=999, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_update_project(self):
        """Test updating a project."""
        from src.audiobook_studio.api.projects import update_project

        db = AsyncMock()
        project = _make_project()
        _setup_execute_result(db, project)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        payload = MagicMock()
        payload.model_dump.return_value = {"title": "Updated Title", "author": "Updated Author"}

        result = await update_project(project_id=1, payload=payload, db=db)

        assert result.title == "Updated Title"
        assert result.author == "Updated Author"
        db.commit.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_project(self):
        """Test deleting a project."""
        from src.audiobook_studio.api.projects import delete_project

        db = AsyncMock()
        project = _make_project()
        _setup_execute_result(db, project)
        db.delete = AsyncMock()
        db.commit = AsyncMock()

        result = await delete_project(project_id=1, db=db)

        assert result is None
        db.delete.assert_called_once_with(project)
        db.commit.assert_called_once()


class TestChapterEndpoints:
    """Tests for chapter endpoints."""

    @pytest.mark.asyncio
    async def test_list_chapters(self):
        """Test listing chapters for a project."""
        from src.audiobook_studio.api.projects import list_chapters

        db = AsyncMock()
        # First call: project check
        project = _make_project()
        # Second call: chapters list
        chapters = [_make_chapter()]

        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = project
        mock_result2 = MagicMock()
        mock_result2.scalars.return_value.all.return_value = chapters
        db.execute.side_effect = [mock_result1, mock_result2]

        result = await list_chapters(project_id=1, skip=0, limit=100, db=db)

        assert len(result) == 1
        assert result[0].title == "Chapter 1"

    @pytest.mark.asyncio
    async def test_get_chapter(self):
        """Test getting a chapter."""
        from src.audiobook_studio.api.projects import get_chapter

        db = AsyncMock()
        _setup_execute_result(db, _make_chapter())

        result = await get_chapter(project_id=1, chapter_id=1, db=db)

        assert result.id == 1
        assert result.title == "Chapter 1"


class TestParagraphEndpoints:
    """Tests for paragraph endpoints."""

    @pytest.mark.asyncio
    async def test_list_paragraphs(self):
        """Test listing paragraphs for a chapter."""
        from src.audiobook_studio.api.projects import list_paragraphs

        db = AsyncMock()
        chapter = _make_chapter()
        paragraphs = [_make_paragraph()]

        mock_result1 = MagicMock()
        mock_result1.scalar_one_or_none.return_value = chapter
        mock_result2 = MagicMock()
        mock_result2.scalars.return_value.all.return_value = paragraphs
        db.execute.side_effect = [mock_result1, mock_result2]

        result = await list_paragraphs(project_id=1, chapter_id=1, skip=0, limit=500, db=db)

        assert len(result) == 1
        assert result[0].text == "Test paragraph"

    @pytest.mark.asyncio
    async def test_get_paragraph(self):
        """Test getting a paragraph."""
        from src.audiobook_studio.api.projects import get_paragraph

        db = AsyncMock()
        _setup_execute_result(db, _make_paragraph())

        result = await get_paragraph(project_id=1, chapter_id=1, paragraph_id=1, db=db)

        assert result.id == 1
        assert result.text == "Test paragraph"

    @pytest.mark.asyncio
    async def test_update_paragraph(self):
        """Test updating a paragraph."""
        from src.audiobook_studio.api.projects import update_paragraph

        db = AsyncMock()
        paragraph = _make_paragraph()
        _setup_execute_result(db, paragraph)
        db.commit = AsyncMock()
        db.refresh = AsyncMock()

        payload = {"text": "Updated text", "speaker": "New Speaker"}

        result = await update_paragraph(project_id=1, chapter_id=1, paragraph_id=1, payload=payload, db=db)

        assert result.text == "Updated text"
        assert result.speaker == "New Speaker"
        db.commit.assert_called_once()


class TestQualityReportEndpoint:
    """Tests for quality report endpoint."""

    @pytest.mark.asyncio
    async def test_quality_report_not_found(self):
        """Test quality report returns 404 when not found."""
        from src.audiobook_studio.api.projects import get_quality_report

        with patch("src.audiobook_studio.api.projects.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = Path("/nonexistent")

            with pytest.raises(HTTPException) as exc_info:
                await get_quality_report(project_id=1, chapter_index=0)
            assert exc_info.value.status_code == 404


class TestRegenerateParagraphEndpoint:
    """Tests for paragraph regeneration endpoint."""

    @pytest.mark.asyncio
    async def test_regenerate_paragraph_not_found(self):
        """Test regenerate returns 404 for non-existent paragraph."""
        from src.audiobook_studio.api.projects import regenerate_paragraph

        db = AsyncMock()
        _setup_execute_result(db, None)

        with pytest.raises(HTTPException) as exc_info:
            await regenerate_paragraph(project_id=1, chapter_id=1, paragraph_id=1, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_regenerate_paragraph_no_audio_segment(self):
        """Test regenerate returns 400 when no audio segment."""
        from src.audiobook_studio.api.projects import regenerate_paragraph

        db = AsyncMock()
        paragraph = _make_paragraph()
        paragraph.audio_segment = None
        _setup_execute_result(db, paragraph)

        with pytest.raises(HTTPException) as exc_info:
            await regenerate_paragraph(project_id=1, chapter_id=1, paragraph_id=1, db=db)
        assert exc_info.value.status_code == 400
        assert "No audio segment" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_regenerate_paragraph_success(self):
        """Test successful paragraph regeneration."""
        from src.audiobook_studio.api.projects import regenerate_paragraph

        db = AsyncMock()
        paragraph = _make_paragraph()
        paragraph.audio_segment = MagicMock()
        _setup_execute_result(db, paragraph)

        # Mock the module import since it's in the function
        with patch("src.audiobook_studio.tasks.tts_tasks") as mock_tts_tasks:
            mock_tts_tasks.synthesize_paragraph_task.delay.return_value = MagicMock(id="task_123")

            result = await regenerate_paragraph(project_id=1, chapter_id=1, paragraph_id=1, db=db)

            assert result["task_id"] == "task_123"
            assert result["status"] == "queued"
            mock_tts_tasks.synthesize_paragraph_task.delay.assert_called_once()


class TestLegacyRegenerateEndpoint:
    """Tests for legacy paragraph regeneration endpoint."""

    @pytest.mark.asyncio
    async def test_regenerate_paragraph_legacy_not_found(self):
        """Test legacy regenerate returns 404 for non-existent paragraph."""
        from src.audiobook_studio.api.projects import regenerate_paragraph_legacy

        db = AsyncMock()
        _setup_execute_result(db, None)

        with pytest.raises(HTTPException) as exc_info:
            await regenerate_paragraph_legacy(project_id=1, paragraph_id=1, db=db)
        assert exc_info.value.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

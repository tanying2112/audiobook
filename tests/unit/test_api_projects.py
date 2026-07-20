"""Tests for API projects router with global auth default-deny.

Tests cover CRUD operations for projects, chapters, and paragraphs
with proper authentication and authorization.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.audiobook_studio.main import app


@pytest.fixture
def client():
    """Test client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_db():
    """Mock database session."""
    with patch("src.audiobook_studio.api.projects.get_db") as mock:
        db = MagicMock()
        mock.return_value = iter([db])
        yield db


@pytest.fixture
def mock_user():
    """Mock authenticated user."""
    user = MagicMock()
    user.id = 1
    user.username = "testuser"
    user.email = "test@example.com"
    user.is_active = True
    user.is_superuser = False
    return user


@pytest.fixture
def mock_project(mock_user):
    """Mock project with user ownership."""
    project = MagicMock()
    project.id = 1
    project.title = "Test Project"
    project.author = "Test Author"
    project.genre = "Fiction"
    project.language = "zh"
    project.difficulty = "C"
    project.status = "active"
    project.current_stage = "extract"
    project.progress = 0.0
    project.total_cost_usd = 0.0
    project.created_at = "2024-01-01T00:00:00Z"
    project.updated_at = "2024-01-01T00:00:00Z"
    return project


class TestProjectsAuth:
    """Tests for authentication requirements on projects endpoints."""

    def test_create_project_requires_auth(self, client):
        """POST /projects requires authentication."""
        response = client.post(
            "/projects/", json={"title": "Test Project", "author": "Test Author", "genre": "Fiction", "language": "zh"}
        )
        # Should be 401 or 403 without auth
        assert response.status_code in (401, 403)

    def test_list_projects_requires_auth(self, client):
        """GET /projects requires authentication."""
        response = client.get("/projects/")
        assert response.status_code in (401, 403)

    def test_get_project_requires_auth(self, client):
        """GET /projects/{id} requires authentication."""
        response = client.get("/projects/1")
        assert response.status_code in (401, 403)

    def test_update_project_requires_auth(self, client):
        """PUT /projects/{id} requires authentication."""
        response = client.put("/projects/1", json={"title": "Updated Project"})
        assert response.status_code in (401, 403)

    def test_delete_project_requires_auth(self, client):
        """DELETE /projects/{id} requires authentication."""
        response = client.delete("/projects/1")
        assert response.status_code in (401, 403)

    def test_list_chapters_requires_auth(self, client):
        """GET /projects/{id}/chapters requires authentication."""
        response = client.get("/projects/1/chapters")
        assert response.status_code in (401, 403)

    def test_get_chapter_requires_auth(self, client):
        """GET /projects/{id}/chapters/{ch} requires authentication."""
        response = client.get("/projects/1/chapters/1")
        assert response.status_code in (401, 403)

    def test_list_paragraphs_requires_auth(self, client):
        """GET /projects/{id}/chapters/{ch}/paragraphs requires authentication."""
        response = client.get("/projects/1/chapters/1/paragraphs")
        assert response.status_code in (401, 403)

    def test_get_paragraph_requires_auth(self, client):
        """GET /projects/{id}/chapters/{ch}/paragraphs/{p} requires authentication."""
        response = client.get("/projects/1/chapters/1/paragraphs/1")
        assert response.status_code in (401, 403)

    def test_update_paragraph_requires_auth(self, client):
        """PUT /projects/{id}/chapters/{ch}/paragraphs/{p} requires authentication."""
        response = client.put("/projects/1/chapters/1/paragraphs/1", json={"text": "updated"})
        assert response.status_code in (401, 403)

    def test_quality_report_requires_auth(self, client):
        """GET /projects/{id}/quality-report requires authentication."""
        response = client.get("/projects/1/quality-report")
        assert response.status_code in (401, 403)

    def test_regenerate_paragraph_requires_auth(self, client):
        """POST /projects/{id}/chapters/{ch}/paragraphs/{p}/regenerate requires authentication."""
        response = client.post("/projects/1/chapters/1/paragraphs/1/regenerate")
        assert response.status_code in (401, 403)

    def test_regenerate_paragraph_legacy_requires_auth(self, client):
        """POST /projects/{id}/paragraphs/{p}/regenerate requires authentication."""
        response = client.post("/projects/1/paragraphs/1/regenerate")
        assert response.status_code in (401, 403)


class TestProjectsCRUD:
    """Tests for projects CRUD operations with mocked auth."""

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_create_project_success(self, mock_get_user, client, mock_db, mock_user, mock_project):
        """Test successful project creation."""
        mock_get_user.return_value = mock_user
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock(side_effect=lambda p: setattr(p, "id", 1))

        response = client.post(
            "/projects/",
            json={
                "title": "Test Project",
                "author": "Test Author",
                "genre": "Fiction",
                "language": "zh",
                "difficulty": "C",
                "global_style_notes": "Test notes",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["title"] == "Test Project"
        assert data["author"] == "Test Author"
        assert data["id"] == 1

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_list_projects_success(self, mock_get_user, client, mock_db, mock_user, mock_project):
        """Test listing projects."""
        mock_get_user.return_value = mock_user
        mock_db.query.return_value.offset.return_value.limit.return_value.all.return_value = [mock_project]

        response = client.get("/projects/")

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["title"] == "Test Project"

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_get_project_success(self, mock_get_user, client, mock_db, mock_user, mock_project):
        """Test getting a single project."""
        mock_get_user.return_value = mock_user
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project

        response = client.get("/projects/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["title"] == "Test Project"

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_get_project_not_found(self, mock_get_user, client, mock_db, mock_user):
        """Test getting non-existent project returns 404."""
        mock_get_user.return_value = mock_user
        mock_db.query.return_value.filter.return_value.first.return_value = None

        response = client.get("/projects/999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_update_project_success(self, mock_get_user, client, mock_db, mock_user, mock_project):
        """Test updating a project."""
        mock_get_user.return_value = mock_user
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project

        response = client.put("/projects/1", json={"title": "Updated Title", "author": "Updated Author"})

        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Updated Title"
        assert data["author"] == "Updated Author"

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_delete_project_success(self, mock_get_user, client, mock_db, mock_user, mock_project):
        """Test deleting a project."""
        mock_get_user.return_value = mock_user
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project
        mock_db.delete = MagicMock()
        mock_db.commit = MagicMock()

        response = client.delete("/projects/1")

        assert response.status_code == 204
        mock_db.delete.assert_called_once_with(mock_project)
        mock_db.commit.assert_called_once()

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_update_project_not_found(self, mock_get_user, client, mock_db, mock_user):
        """Test updating non-existent project returns 404."""
        mock_get_user.return_value = mock_user
        mock_db.query.return_value.filter.return_value.first.return_value = None

        response = client.put("/projects/999", json={"title": "New Title"})

        assert response.status_code == 404


class TestChaptersAndParagraphs:
    """Tests for chapters and paragraphs endpoints."""

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_list_chapters_success(self, mock_get_user, client, mock_db, mock_user):
        """Test listing chapters for a project."""
        mock_get_user.return_value = mock_user

        mock_project = MagicMock()
        mock_project.id = 1
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project

        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.project_id = 1
        mock_chapter.index = 1
        mock_chapter.title = "Chapter 1"
        mock_chapter.status = "completed"
        mock_chapter.extract_status = "completed"
        mock_chapter.analyze_status = "completed"
        mock_chapter.annotate_status = "completed"
        mock_chapter.edit_status = "completed"
        mock_chapter.route_status = "completed"
        mock_chapter.synthesize_status = "completed"
        mock_chapter.quality_status = "completed"
        mock_chapter.cost_usd = 0.1
        mock_chapter.token_count = 1000
        mock_chapter.tts_chars = 500

        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_chapter
        ]

        response = client.get("/projects/1/chapters")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["title"] == "Chapter 1"

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_list_paragraphs_success(self, mock_get_user, client, mock_db, mock_user):
        """Test listing paragraphs for a chapter."""
        mock_get_user.return_value = mock_user

        mock_chapter = MagicMock()
        mock_chapter.id = 1
        mock_chapter.project_id = 1
        mock_db.query.return_value.filter.return_value.first.return_value = mock_chapter

        mock_paragraph = MagicMock()
        mock_paragraph.id = 1
        mock_paragraph.project_id = 1
        mock_paragraph.chapter_id = 1
        mock_paragraph.chapter_index = 1
        mock_paragraph.index = 1
        mock_paragraph.text = "Test paragraph"
        mock_paragraph.speaker = "Narrator"
        mock_paragraph.speaker_canonical_name = "Narrator"
        mock_paragraph.is_dialogue = False
        mock_paragraph.emotion = "neutral"
        mock_paragraph.edited_text = "Test paragraph"
        mock_paragraph.status = "completed"

        mock_db.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
            mock_paragraph
        ]

        response = client.get("/projects/1/chapters/1/paragraphs")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["text"] == "Test paragraph"


class TestQualityReport:
    """Tests for quality report endpoint."""

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_quality_report_not_found(self, mock_get_user, client, mock_db, mock_user):
        """Test quality report returns 404 when not found."""
        mock_get_user.return_value = mock_user
        mock_project = MagicMock()
        mock_project.id = 1
        mock_db.query.return_value.filter.return_value.first.return_value = mock_project

        with patch("src.audiobook_studio.api.projects.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = Path("/nonexistent")

            response = client.get("/projects/1/quality-report?chapter_index=0")

            assert response.status_code == 404
            assert "not found" in response.json()["detail"].lower()


class TestRegenerateParagraph:
    """Tests for paragraph regeneration endpoint."""

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_regenerate_paragraph_not_found(self, mock_get_user, client, mock_db, mock_user):
        """Test regenerate returns 404 for non-existent paragraph."""
        mock_get_user.return_value = mock_user

        mock_db.query.return_value.filter.return_value.first.return_value = None

        response = client.post("/projects/1/chapters/1/paragraphs/1/regenerate")

        assert response.status_code == 404


class TestLegacyEndpoint:
    """Tests for legacy regenerate endpoint."""

    @patch("src.audiobook_studio.api.projects.get_current_active_user")
    def test_regenerate_paragraph_legacy_not_found(self, mock_get_user, client, mock_db, mock_user):
        """Test legacy regenerate returns 404 for non-existent paragraph."""
        mock_get_user.return_value = mock_user

        mock_db.query.return_value.filter.return_value.first.return_value = None

        response = client.post("/projects/1/paragraphs/1/regenerate")

        assert response.status_code == 404


# Import Path for tests
from pathlib import Path

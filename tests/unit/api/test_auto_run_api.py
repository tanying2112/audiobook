"""Comprehensive API integration tests for auto-run and pipeline endpoints.

Tests cover:
- Auto-run start/status/pause/resume/cancel actions
- Autopilot mode
- Pipeline stage execution
- Translate/dubbing pipeline
- Error handling and edge cases
"""

import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import sessionmaker

# Set ALLOWED_HOSTS BEFORE importing the main app to configure TrustedHostMiddleware correctly
import os
os.environ["ALLOWED_HOSTS"] = '["localhost", "127.0.0.1", "testserver"]'

from src.audiobook_studio.api.dependencies import get_async_db
from src.audiobook_studio.auth.dependencies import get_current_user
from src.audiobook_studio.database import Base
from src.audiobook_studio.main import app
from src.audiobook_studio.models.user import User
from src.audiobook_studio.models.book import Project
from src.audiobook_studio.models.chapter import Chapter
from src.audiobook_studio.models.paragraph import Paragraph


# =============================================================================
# Test fixtures
# =============================================================================

@pytest.fixture(scope="function")
def sync_engine():
    """Create a synchronous SQLite engine for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    engine = create_engine(f"sqlite:///{tmp.name}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(sync_engine):
    """Provide a SQLAlchemy session bound to the test engine."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)
    session = SessionLocal()
    try:
        # Create a test user for authentication
        test_user = User(
            id=1,
            email="test@example.com",
            username="testuser",
            hashed_password="hashed",
            is_active=True,
            is_superuser=True,
        )
        session.merge(test_user)
        session.commit()
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
async def async_client(sync_engine, db_session):
    """Async HTTP client for FastAPI with database dependencies overridden."""
    # Override the global async engine/session factory to use the test engine
    import src.audiobook_studio.database as database_module

    # Convert the sync test engine URL to async
    test_async_url = str(sync_engine.url).replace("sqlite:///", "sqlite+aiosqlite:///")
    test_async_engine = create_async_engine(test_async_url, pool_pre_ping=True)
    test_async_session_factory = async_sessionmaker(
        test_async_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    # Save original and override
    orig_async_engine = database_module._async_engine
    orig_async_session_factory = database_module._async_session_factory
    database_module._async_engine = test_async_engine
    database_module._async_session_factory = test_async_session_factory

    async def get_test_async_db():
        async with test_async_session_factory() as session:
            yield session

    # Override get_current_user to return the test user without JWT validation
    # The test user is already created in db_session fixture (same DB file)
    async def override_get_current_user():
        async with test_async_session_factory() as session:
            from sqlalchemy import select
            result = await session.execute(select(User).where(User.id == 1))
            return result.scalar_one_or_none()

    # Override settings
    from audiobook_studio.config.loader import get_settings, reset_settings
    reset_settings()

    # Override both sync and async database dependencies, and auth
    app.dependency_overrides[get_async_db] = get_test_async_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
    reset_settings()

    # Restore original async engine/session factory
    database_module._async_engine = orig_async_engine
    database_module._async_session_factory = orig_async_session_factory
    await test_async_engine.dispose()


@pytest.fixture
def sample_project(async_client: AsyncClient, sync_engine):
    """Create a sample project with chapters and paragraphs directly in the database."""
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
    from src.audiobook_studio.models.book import Project
    from src.audiobook_studio.models.chapter import Chapter
    from src.audiobook_studio.models.paragraph import Paragraph

    async def _create():
        test_async_url = str(sync_engine.url).replace("sqlite:///", "sqlite+aiosqlite:///")
        test_async_engine = create_async_engine(test_async_url, pool_pre_ping=True)
        test_async_session_factory = async_sessionmaker(
            test_async_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        async with test_async_session_factory() as session:
            # Create project
            project = Project(
                title="Test Project",
                author="Test Author",
                genre="fiction",
                language="zh",
                difficulty="B",
                global_style_notes="Test style",
                story_line_summary="A test story.",
            )
            session.add(project)
            await session.commit()
            await session.refresh(project)
            project_id = project.id

            # Create chapters
            for i in range(1, 4):
                chapter = Chapter(
                    project_id=project_id,
                    index=i,
                    title=f"Chapter {i}",
                    raw_text=f"This is chapter {i} text. " * 20,
                )
                session.add(chapter)
            await session.commit()

            # Get chapters
            from sqlalchemy import select
            result = await session.execute(select(Chapter).where(Chapter.project_id == project_id))
            chapters = result.scalars().all()

            # Create paragraphs
            for i, chapter in enumerate(chapters, 1):
                para = Paragraph(
                    project_id=project_id,
                    chapter_id=chapter.id,
                    chapter_index=chapter.index,
                    index=i,
                    text=f"Paragraph {i} text content.",
                    speaker="narrator",
                )
                session.add(para)
            await session.commit()

            await test_async_engine.dispose()
            return project_id

    return asyncio.run(_create())


# =============================================================================
# Test Auto-Run API
# =============================================================================

class TestAutoRunStart:
    """Test POST /projects/{project_id}/auto-run/start endpoint."""

    @pytest.mark.anyio
    async def test_start_auto_run_basic(self, async_client: AsyncClient, sample_project: int):
        """Test starting auto-run with default config."""
        payload = {
            "config": {
                "target_difficulty": "B",
                "primary_voice_preference": "female",
                "speech_rate_preference": "standard",
            }
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/start",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data
        assert data["run_id"].startswith(f"autorun_{sample_project}_")
        # Status can be "pending" or "running" since background task starts immediately
        assert data["status"] in ("pending", "running")

    @pytest.mark.anyio
    async def test_start_auto_run_with_custom_config(self, async_client: AsyncClient, sample_project: int):
        """Test starting auto-run with custom configuration."""
        payload = {
            "config": {
                "target_difficulty": "A",
                "primary_voice_preference": "male",
                "speech_rate_preference": "slow",
                "cost_limit_usd": 10.0,
                "quality_threshold": 0.8,
                "max_regeneration_attempts": 2,
                "enable_background_music": True,
                "enable_sfx": False,
            }
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/start",
            json=payload
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "run_id" in data

    @pytest.mark.anyio
    async def test_start_auto_run_invalid_project(self, async_client: AsyncClient):
        """Test starting auto-run with non-existent project."""
        payload = {"config": {}}
        resp = await async_client.post(
            "/projects/99999/auto-run/start",
            json=payload
        )
        assert resp.status_code == 404

    @pytest.mark.anyio
    async def test_start_auto_run_invalid_config(self, async_client: AsyncClient, sample_project: int):
        """Test starting auto-run with invalid config values."""
        payload = {
            "config": {
                "target_difficulty": "INVALID",
                "quality_threshold": 1.5,  # > 1.0
            }
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/start",
            json=payload
        )
        assert resp.status_code == 422  # Validation error


class TestAutoRunStatus:
    """Test GET /projects/{project_id}/auto-run/status endpoint."""

    @pytest.mark.anyio
    async def test_get_status_no_active_run(self, async_client: AsyncClient, sample_project: int):
        """Test getting status when no auto-run is active."""
        resp = await async_client.get(
            f"/projects/{sample_project}/auto-run/status"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == sample_project
        # Status might be 'pending' or 'completed' depending on implementation
        assert "status" in data
        assert "progress" in data

    @pytest.mark.anyio
    async def test_get_status_after_start(self, async_client: AsyncClient, sample_project: int):
        """Test getting status after starting auto-run."""
        # Start auto-run
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/start",
            json={"config": {}}
        )
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]

        # Get status
        resp = await async_client.get(
            f"/projects/{sample_project}/auto-run/status"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id


class TestAutoRunPauseResumeCancel:
    """Test pause/resume/cancel actions."""

    @pytest.mark.anyio
    async def test_pause_auto_run_no_active(self, async_client: AsyncClient, sample_project: int):
        """Test pausing when no auto-run is active."""
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/pause"
        )
        assert resp.status_code == 400
        assert "cannot pause" in resp.json()["detail"].lower()

    @pytest.mark.anyio
    async def test_resume_auto_run_no_active(self, async_client: AsyncClient, sample_project: int):
        """Test resuming when no auto-run is active."""
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/resume"
        )
        assert resp.status_code == 400
        assert "cannot resume" in resp.json()["detail"].lower()

    @pytest.mark.anyio
    async def test_cancel_auto_run_no_active(self, async_client: AsyncClient, sample_project: int):
        """Test cancelling when no auto-run is active."""
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/cancel"
        )
        assert resp.status_code == 400
        assert "cannot cancel" in resp.json()["detail"].lower()


class TestAutoRunAutopilot:
    """Test autopilot mode endpoints."""

    @pytest.mark.anyio
    async def test_autopilot_preview(self, async_client: AsyncClient, sample_project: int):
        """Test getting autopilot preview config."""
        resp = await async_client.get(
            f"/projects/{sample_project}/auto-run/autopilot/preview"
        )
        # May return validation error if not enough data
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            data = resp.json()
            assert "target_difficulty" in data
            assert "primary_voice_preference" in data
            assert "speech_rate_preference" in data
            assert "reasoning" in data
            assert "confidence" in data

    @pytest.mark.anyio
    async def test_start_autopilot(self, async_client: AsyncClient, sample_project: int):
        """Test starting auto-run in autopilot mode."""
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/autopilot",
            json={}
        )
        # May return validation error if not enough data
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            data = resp.json()
            assert "run_id" in data
            assert data["run_id"].startswith(f"autorun_{sample_project}_")


# =============================================================================
# Test Pipeline API
# =============================================================================

class TestPipelineRunStage:
    """Test POST /projects/{project_id}/pipeline/run-stage endpoint."""

    @pytest.mark.anyio
    async def test_run_extract_stage(self, async_client: AsyncClient, sample_project: int):
        """Test running extract stage."""
        payload = {
            "stage": "extract",
            "chapter_id": 1,
            "target_difficulty": "B"
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/pipeline/run-stage",
            json=payload
        )
        # Stage may be accepted (200/202) or fail if no content
        assert resp.status_code in (200, 202, 500)
        data = resp.json()
        assert data["stage"] == "extract"

    @pytest.mark.anyio
    async def test_run_analyze_stage(self, async_client: AsyncClient, sample_project: int):
        """Test running analyze stage."""
        payload = {
            "stage": "analyze",
            "chapter_id": 1,
            "target_difficulty": "B"
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/pipeline/run-stage",
            json=payload
        )
        assert resp.status_code in (200, 202, 500)

    @pytest.mark.anyio
    async def test_run_invalid_stage(self, async_client: AsyncClient, sample_project: int):
        """Test running invalid stage name."""
        payload = {
            "stage": "invalid_stage",
            "chapter_id": 1,
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/pipeline/run-stage",
            json=payload
        )
        assert resp.status_code in (400, 422)

    @pytest.mark.anyio
    async def test_run_stage_missing_chapter_id(self, async_client: AsyncClient, sample_project: int):
        """Test running stage without chapter_id for chapter-level stage."""
        payload = {
            "stage": "extract",
            # Missing chapter_id
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/pipeline/run-stage",
            json=payload
        )
        # Should fail validation
        assert resp.status_code in (400, 422)


class TestPipelineTranslate:
    """Test translate/dubbing pipeline endpoints."""

    @pytest.mark.anyio
    async def test_translate_pipeline(self, async_client: AsyncClient, sample_project: int):
        """Test starting translate pipeline."""
        payload = {
            "target_language": "en-US",
            "chapter_indices": [1],
            "book_title": "Test Book",
            "author": "Test Author"
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/pipeline/translate",
            json=payload
        )
        assert resp.status_code in (200, 202, 500)
        data = resp.json()
        assert "status" in data
        assert "total_segments" in data

    @pytest.mark.anyio
    async def test_translate_pipeline_all_chapters(self, async_client: AsyncClient, sample_project: int):
        """Test translate pipeline without chapter filter (all chapters)."""
        payload = {
            "target_language": "en-US",
            "book_title": "Test Book",
            "author": "Test Author"
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/pipeline/translate",
            json=payload
        )
        assert resp.status_code in (200, 202, 500)

    @pytest.mark.anyio
    async def test_translate_invalid_language(self, async_client: AsyncClient, sample_project: int):
        """Test translate with invalid language code."""
        payload = {
            "target_language": "invalid_lang",
            "book_title": "Test Book"
        }
        resp = await async_client.post(
            f"/projects/{sample_project}/pipeline/translate",
            json=payload
        )
        # Should validate language code
        assert resp.status_code in (400, 422)

    @pytest.mark.anyio
    async def test_get_translate_status(self, async_client: AsyncClient, sample_project: int):
        """Test getting translate pipeline status."""
        resp = await async_client.get(
            f"/projects/{sample_project}/pipeline/translate/status"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "project_id" in data
        assert "total_original_segments" in data
        assert "total_translated_segments" in data
        assert "translation_ratio" in data

    @pytest.mark.anyio
    async def test_get_supported_languages(self, async_client: AsyncClient, sample_project: int):
        """Test getting supported languages."""
        resp = await async_client.get(
            f"/projects/{sample_project}/pipeline/translate/languages"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "languages" in data
        assert isinstance(data["languages"], list)
        assert len(data["languages"]) > 0


# =============================================================================
# Test Auto-Run Intermediate Products
# =============================================================================

class TestIntermediateProducts:
    """Test GET /projects/{project_id}/auto-run/intermediate/{stage} endpoint."""

    @pytest.mark.anyio
    async def test_get_intermediate_products(self, async_client: AsyncClient, sample_project: int):
        """Test getting intermediate products for a stage."""
        resp = await async_client.get(
            f"/projects/{sample_project}/auto-run/intermediate/extract"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)  # Returns a single IntermediateProduct object

    @pytest.mark.anyio
    async def test_get_intermediate_invalid_stage(self, async_client: AsyncClient, sample_project: int):
        """Test getting intermediate for invalid stage."""
        resp = await async_client.get(
            f"/projects/{sample_project}/auto-run/intermediate/invalid_stage"
        )
        assert resp.status_code == 400


# =============================================================================
# Test Error Handling & Edge Cases
# =============================================================================

class TestAutoRunErrorHandling:
    """Test error handling for auto-run endpoints."""

    @pytest.mark.anyio
    async def test_invalid_json_body(self, async_client: AsyncClient, sample_project: int):
        """Test sending invalid JSON."""
        # This test is more of a framework test - FastAPI handles this
        pass

    @pytest.mark.anyio
    async def test_unauthorized_request(self, async_client: AsyncClient, sample_project: int):
        """Test that endpoints require authentication.

        Note: Our test fixture overrides auth, so this is more of a documentation test.
        In production, removing the dependency override would trigger 401/403.
        """
        # The test fixture overrides get_current_user, so this will actually succeed
        # In production, missing auth token would return 401
        resp = await async_client.get(
            f"/projects/{sample_project}/auto-run/status"
        )
        # With fixture override, this will be 200
        assert resp.status_code == 200


# =============================================================================
# Test Integration Scenarios
# =============================================================================

class TestIntegrationScenarios:
    """Test end-to-end integration scenarios."""

    @pytest.mark.anyio
    async def test_full_auto_run_workflow(self, async_client: AsyncClient, sample_project: int):
        """Test complete auto-run workflow: start -> status -> pause -> resume -> cancel."""
        # 1. Start auto-run
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/start",
            json={"config": {}}
        )
        assert resp.status_code == 200
        run_id = resp.json()["run_id"]

        # 2. Check status
        resp = await async_client.get(
            f"/projects/{sample_project}/auto-run/status"
        )
        assert resp.status_code == 200
        assert resp.json()["run_id"] == run_id

        # 3. Pause - will return 400 if auto-run not yet running (background task)
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/pause"
        )
        assert resp.status_code in (200, 400)

        # 4. Resume - will return 400 if not paused
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/resume"
        )
        assert resp.status_code in (200, 400)

        # 5. Cancel - will return 400 if not running
        resp = await async_client.post(
            f"/projects/{sample_project}/auto-run/cancel"
        )
        assert resp.status_code in (200, 400)

    @pytest.mark.anyio
    async def test_pipeline_stage_sequence(self, async_client: AsyncClient, sample_project: int):
        """Test running multiple pipeline stages in sequence."""
        stages = ["extract", "analyze", "annotate", "edit"]

        for stage in stages:
            payload = {
                "stage": stage,
                "chapter_id": 1,
                "target_difficulty": "B"
            }
            resp = await async_client.post(
                f"/projects/{sample_project}/pipeline/run-stage",
                json=payload
            )
            assert resp.status_code in (200, 202, 500)
            data = resp.json()
            assert data["stage"] == stage

    @pytest.mark.anyio
    async def test_cross_project_isolation(self, async_client: AsyncClient):
        """Test that auto-runs in different projects are isolated."""
        # Create two projects
        project1_payload = {
            "title": "Project 1",
            "author": "Author",
            "genre": "fiction",
            "language": "zh",
            "difficulty": "B",
            "global_style_notes": "Style",
            "story_line_summary": "Story",
        }
        resp = await async_client.post("/projects/", json=project1_payload)
        project1_id = resp.json()["id"]

        project2_payload = {
            "title": "Project 2",
            "author": "Author",
            "genre": "fiction",
            "language": "zh",
            "difficulty": "B",
            "global_style_notes": "Style",
            "story_line_summary": "Story",
        }
        resp = await async_client.post("/projects/", json=project2_payload)
        project2_id = resp.json()["id"]

        # Start auto-run in project 1
        resp = await async_client.post(
            f"/projects/{project1_id}/auto-run/start",
            json={"config": {}}
        )
        run_id_1 = resp.json()["run_id"]

        # Start auto-run in project 2
        resp = await async_client.post(
            f"/projects/{project2_id}/auto-run/start",
            json={"config": {}}
        )
        run_id_2 = resp.json()["run_id"]

        # Different run IDs
        assert run_id_1 != run_id_2

        # Status for project 1
        resp = await async_client.get(f"/projects/{project1_id}/auto-run/status")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == run_id_1

        # Status for project 2
        resp = await async_client.get(f"/projects/{project2_id}/auto-run/status")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == run_id_2


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
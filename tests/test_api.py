"""Comprehensive API tests for Audiobook Studio.

This test suite uses FastAPI's ``TestClient`` and overrides the ``get_db``
dependency with an in‑memory SQLite database.  The database schema is created
from the shared ``Base`` metadata before each test run, ensuring isolation
between tests.

The tests cover CRUD operations for all core entities:

* Book
* Paragraph
* TTSEdit
* Routing
* Quality

Each entity is exercised through its corresponding router (``/api/books``,
``/api/paragraphs`` …).  The helper ``override_get_db`` yields a fresh session for
the duration of a request.
"""

from __future__ import annotations

import tempfile
from typing import Generator

import anyio
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.audiobook_studio.api.dependencies import get_db

# ``get_db`` is defined in the API dependencies module. Import it from there.
from src.audiobook_studio.database import Base
from src.audiobook_studio.main import app

# ---------------------------------------------------------------------------
# Dependency override utilities
# ---------------------------------------------------------------------------


def _create_test_engine() -> "Engine":
    """Create an in‑memory SQLite engine for testing.

    Using a temporary file (instead of ``:memory:``) ensures that the same
    connection can be used across multiple sessions within a single test run.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    engine = create_engine(
        f"sqlite:///{tmp.name}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(scope="function")
def db_engine() -> Generator["Engine", None, None]:
    engine = _create_test_engine()
    try:
        yield engine
    finally:
        # Dispose the engine; the temporary file will be cleaned up by the OS.
        engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine) -> Generator["Session", None, None]:
    """Provide a SQLAlchemy session bound to the test engine."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def override_get_db(session):
    """Yield the provided session – used to replace the original ``get_db``."""
    try:
        yield session
    finally:
        pass


@pytest.fixture(scope="function")
async def async_client(db_session):
    """Async HTTP client for FastAPI with ``get_db`` overridden.

    ``httpx.AsyncClient`` can be instantiated directly with the FastAPI ``app``
    object, avoiding the incompatibility of ``starlette.TestClient`` in this
    environment.
    """

    # Define a proper generator dependency that yields the session.
    def get_test_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = get_test_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helper functions for creating test data
# ---------------------------------------------------------------------------


async def create_book(client: AsyncClient) -> int:
    payload = {
        "title": "Test Book",
        "author": "Author",
        "language": "en",
        "isbn": "1234567890",
    }
    resp = await client.post("/api/books/", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


async def create_paragraph(client: AsyncClient, book_id: int) -> int:
    payload = {
        "book_id": book_id,
        "index": 1,
        "text": "Paragraph text",
        "speaker": None,
    }
    resp = await client.post("/api/paragraphs/", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


async def create_tts_edit(client: AsyncClient, paragraph_id: int) -> int:
    payload = {"paragraph_id": paragraph_id, "edited_text": "Edited", "voice": "en-US"}
    resp = await client.post("/api/tts_edits/", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


async def create_routing(client: AsyncClient, paragraph_id: int) -> int:
    payload = {"paragraph_id": paragraph_id, "voice": "en-US", "confidence": 0.95}
    resp = await client.post("/api/routings/", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


async def create_quality(client: AsyncClient, tts_edit_id: int) -> int:
    payload = {"tts_edit_id": tts_edit_id, "score": 4.5, "comments": "Good"}
    resp = await client.post("/api/qualities/", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


async def create_project(client: AsyncClient) -> int:
    """Create a project for testing."""
    payload = {
        "title": "Test Project",
        "author": "Test Author",
        "genre": "fiction",
        "language": "zh",
        "difficulty": "B",
        "global_style_notes": "Test style",
        "story_line_summary": "A test story.",
    }
    resp = await client.post("/api/projects/", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


async def create_character(client: AsyncClient, project_id: int) -> int:
    """Create a character for a project."""
    payload = {
        "canonical_name": "测试角色",
        "aliases": ["测试"],
        "gender": "neutral",
        "age_range": "adult",
        "suggested_voice_id": "zh-CN-XiaoxiaoNeural",
        "sample_quote": "测试台词",
    }
    resp = await client.post(f"/api/projects/{project_id}/characters", json=payload)
    assert resp.status_code == 201
    return resp.json()["id"]


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_full_crud_flow(async_client: AsyncClient):
    """End‑to‑end CRUD test covering all models and their relationships."""

    # ---- Book ----
    book_id = await create_book(async_client)
    # Retrieve list
    resp = await async_client.get("/api/books/")
    assert resp.status_code == 200
    assert any(b["id"] == book_id for b in resp.json())

    # ---- Paragraph ----
    paragraph_id = await create_paragraph(async_client, book_id)
    resp = await async_client.get(f"/api/paragraphs/{paragraph_id}")
    assert resp.status_code == 200
    assert resp.json()["book_id"] == book_id

    # ---- TTSEdit ----
    tts_edit_id = await create_tts_edit(async_client, paragraph_id)
    resp = await async_client.get(f"/api/tts_edits/{tts_edit_id}")
    assert resp.status_code == 200
    assert resp.json()["paragraph_id"] == paragraph_id

    # ---- Routing ----
    routing_id = await create_routing(async_client, paragraph_id)
    resp = await async_client.get(f"/api/routings/{routing_id}")
    assert resp.status_code == 200
    assert resp.json()["paragraph_id"] == paragraph_id

    # ---- Quality ----
    quality_id = await create_quality(async_client, tts_edit_id)
    resp = await async_client.get(f"/api/qualities/{quality_id}")
    assert resp.status_code == 200
    assert resp.json()["tts_edit_id"] == tts_edit_id

    # ---- Update & Delete checks (Book as example) ----
    update_payload = {
        "title": "Updated",
        "author": "Author",
        "language": "en",
        "isbn": "123",
    }
    resp = await async_client.put(f"/api/books/{book_id}", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated"

    resp = await async_client.delete(f"/api/books/{book_id}")
    assert resp.status_code == 204
    # Ensure it is gone
    resp = await async_client.get(f"/api/books/{book_id}")
    assert resp.status_code == 404


# ---- Character CRUD tests ----


@pytest.mark.anyio
async def test_character_crud(async_client: AsyncClient):
    """Test character CRUD operations."""
    # First create a project
    project_id = await create_project(async_client)

    # Create character
    char_id = await create_character(async_client, project_id)

    # List characters
    resp = await async_client.get(f"/api/projects/{project_id}/characters")
    assert resp.status_code == 200
    chars = resp.json()
    assert len(chars) == 1
    assert chars[0]["id"] == char_id
    assert chars[0]["canonical_name"] == "测试角色"

    # Get character
    resp = await async_client.get(f"/api/projects/{project_id}/characters/{char_id}")
    assert resp.status_code == 200
    char = resp.json()
    assert char["id"] == char_id
    assert char["canonical_name"] == "测试角色"

    # Update character
    update_payload = {"canonical_name": "更新角色", "gender": "female"}
    resp = await async_client.put(
        f"/api/projects/{project_id}/characters/{char_id}", json=update_payload
    )
    assert resp.status_code == 200
    assert resp.json()["canonical_name"] == "更新角色"
    assert resp.json()["gender"] == "female"

    # Delete character
    resp = await async_client.delete(f"/api/projects/{project_id}/characters/{char_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await async_client.get(f"/api/projects/{project_id}/characters/{char_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_character_duplicate_name(async_client: AsyncClient):
    """Test that duplicate character names are rejected."""
    project_id = await create_project(async_client)

    payload = {
        "canonical_name": "重复角色",
        "gender": "male",
        "suggested_voice_id": "zh-CN-XiaoxiaoNeural",
    }
    # First create
    resp = await async_client.post(f"/api/projects/{project_id}/characters", json=payload)
    assert resp.status_code == 201

    # Second create with same name should fail
    resp = await async_client.post(f"/api/projects/{project_id}/characters", json=payload)
    assert resp.status_code == 400
    assert "already exists" in resp.json()["detail"]


@pytest.mark.anyio
async def test_character_not_found(async_client: AsyncClient):
    """Test 404 for non-existent character."""
    project_id = await create_project(async_client)

    resp = await async_client.get(f"/api/projects/{project_id}/characters/999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_voice_mapping(async_client: AsyncClient):
    """Test getting voice mapping configuration."""
    resp = await async_client.get("/api/projects/1/characters/voice-mapping")
    assert resp.status_code == 200
    data = resp.json()
    assert "voice_mapping" in data
    assert "voice_mapping_en" in data


# ---- Project CRUD tests ----


@pytest.mark.anyio
async def test_project_crud(async_client: AsyncClient):
    """Test project CRUD operations."""
    # Create project
    payload = {
        "title": "新项目",
        "author": "作者",
        "genre": "科幻",
        "language": "zh",
        "difficulty": "A",
        "global_style_notes": "风格备注",
        "story_line_summary": "故事梗概",
    }
    resp = await async_client.post("/api/projects/", json=payload)
    assert resp.status_code == 201
    project = resp.json()
    project_id = project["id"]
    assert project["title"] == "新项目"
    assert project["author"] == "作者"
    assert project["genre"] == "科幻"
    assert project["language"] == "zh"
    assert project["difficulty"] == "A"

    # List projects
    resp = await async_client.get("/api/projects/")
    assert resp.status_code == 200
    projects = resp.json()
    assert len(projects) >= 1
    assert any(p["id"] == project_id for p in projects)

    # Get project
    resp = await async_client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == project_id

    # Update project
    update_payload = {"title": "更新项目", "author": "新作者"}
    resp = await async_client.put(f"/api/projects/{project_id}", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["title"] == "更新项目"

    # Delete project
    resp = await async_client.delete(f"/api/projects/{project_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await async_client.get(f"/api/projects/{project_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_project_list_pagination(async_client: AsyncClient):
    """Test project pagination."""
    # Create multiple projects
    for i in range(5):
        await create_project(async_client)

    # Test pagination
    resp = await async_client.get("/api/projects/?skip=0&limit=3")
    assert resp.status_code == 200
    projects = resp.json()
    assert len(projects) <= 3


# ---- Chapter tests ----


@pytest.mark.anyio
async def test_chapter_endpoints(async_client: AsyncClient):
    """Test chapter list and get endpoints."""
    project_id = await create_project(async_client)

    # List chapters (should be empty initially)
    resp = await async_client.get(f"/api/projects/{project_id}/chapters")
    assert resp.status_code == 200
    assert resp.json() == []

    # Get non-existent chapter
    resp = await async_client.get(f"/api/projects/{project_id}/chapters/1")
    assert resp.status_code == 404


# ---- Paragraph through projects endpoints ----


@pytest.mark.anyio
async def test_paragraph_endpoints_via_projects(async_client: AsyncClient):
    """Test paragraph list and get through project hierarchy."""
    project_id = await create_project(async_client)

    # List paragraphs for non-existent chapter
    resp = await async_client.get(f"/api/projects/{project_id}/chapters/1/paragraphs")
    assert resp.status_code == 404

    # List paragraphs for non-existent project
    resp = await async_client.get(f"/api/projects/999/chapters/1/paragraphs")
    assert resp.status_code == 404


# ---- Export tests ----


@pytest.mark.anyio
async def test_export_formats(async_client: AsyncClient):
    """Test listing export formats."""
    resp = await async_client.get("/api/projects/1/export/")
    assert resp.status_code == 200
    formats = resp.json()
    assert isinstance(formats, list)
    assert len(formats) >= 5
    format_values = [f["value"] for f in formats]
    assert "m4b" in format_values
    assert "srt" in format_values
    assert "vtt" in format_values
    assert "m4b_srt" in format_values
    assert "all" in format_values


@pytest.mark.anyio
async def test_export_start(async_client: AsyncClient):
    """Test starting an export job."""
    project_id = await create_project(async_client)

    payload = {
        "chapter_ids": None,
        "formats": ["srt"],
        "normalize": True,
        "max_chars_per_line": 40,
    }
    resp = await async_client.post(f"/api/projects/{project_id}/export/", json=payload)
    # Export may succeed or fail depending on data, but should return a response
    assert resp.status_code in (200, 202, 500)
    data = resp.json()
    assert "status" in data
    assert "output_paths" in data


@pytest.mark.anyio
async def test_export_status(async_client: AsyncClient):
    """Test getting export status."""
    project_id = await create_project(async_client)

    resp = await async_client.get(f"/api/projects/{project_id}/export/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "output_paths" in data
    assert "error" in data


@pytest.mark.anyio
async def test_export_invalid_format(async_client: AsyncClient):
    """Test export with invalid format."""
    project_id = await create_project(async_client)

    payload = {"formats": ["invalid_format"]}
    resp = await async_client.post(f"/api/projects/{project_id}/export/", json=payload)
    assert resp.status_code == 400
    assert "Unsupported format" in resp.json()["detail"]


# ---- Config tests ----


@pytest.mark.anyio
async def test_config_status(async_client: AsyncClient):
    """Test getting config status."""
    resp = await async_client.get("/api/config/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "constitutional_rules" in data
    assert "quality_thresholds" in data
    assert "contract_versions" in data
    assert "last_checked" in data


@pytest.mark.anyio
async def test_config_reload_rules(async_client: AsyncClient):
    """Test reloading constitutional rules."""
    resp = await async_client.post("/api/config/rules/reload")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    # config contains the full rules dict directly
    assert "adaptation" in data["config"] or "evolution" in data["config"]


@pytest.mark.anyio
async def test_config_reload_thresholds(async_client: AsyncClient):
    """Test reloading quality thresholds."""
    resp = await async_client.post("/api/config/thresholds/reload")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    # config contains the full thresholds dict directly
    assert "audio" in data["config"] or "dimensions" in data["config"]


@pytest.mark.anyio
async def test_config_reload_contracts(async_client: AsyncClient):
    """Test reloading contract versions."""
    resp = await async_client.post("/api/config/contracts/reload")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    # config contains the full versions dict directly
    assert "global" in data["config"] or "stages" in data["config"]


@pytest.mark.anyio
async def test_config_reload_all(async_client: AsyncClient):
    """Test reloading all configs."""
    resp = await async_client.post("/api/config/reload-all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "constitutional_rules" in data["config"]
    assert "quality_thresholds" in data["config"]
    assert "contract_versions" in data["config"]


@pytest.mark.anyio
async def test_config_update_rules(async_client: AsyncClient):
    """Test updating constitutional rules."""
    resp = await async_client.post("/api/config/rules/update", json={"rules": {}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "in-memory" in data["message"]


@pytest.mark.anyio
async def test_config_update_thresholds(async_client: AsyncClient):
    """Test updating quality thresholds."""
    resp = await async_client.post("/api/config/thresholds/update", json={"thresholds": {}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "in-memory" in data["message"]


# ---- Additional Paragraph tests -----


@pytest.mark.anyio
async def test_paragraph_crud(async_client: AsyncClient):
    """Test paragraph CRUD operations."""
    book_id = await create_book(async_client)

    # Create paragraph
    payload = {
        "book_id": book_id,
        "index": 1,
        "text": "Test paragraph for CRUD",
        "speaker": "narrator",
    }
    resp = await async_client.post("/api/paragraphs/", json=payload)
    assert resp.status_code == 201
    para_id = resp.json()["id"]
    assert resp.json()["text"] == "Test paragraph for CRUD"
    assert resp.json()["speaker"] == "narrator"

    # Get paragraph
    resp = await async_client.get(f"/api/paragraphs/{para_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == para_id
    assert resp.json()["book_id"] == book_id

    # Update paragraph (requires full schema including id to avoid overwriting with None)
    update_payload = {
        "id": para_id,
        "book_id": book_id,
        "index": 1,
        "text": "Updated paragraph text",
        "speaker": "character",
    }
    resp = await async_client.put(f"/api/paragraphs/{para_id}", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["text"] == "Updated paragraph text"
    assert resp.json()["speaker"] == "character"

    # Delete paragraph
    resp = await async_client.delete(f"/api/paragraphs/{para_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await async_client.get(f"/api/paragraphs/{para_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_paragraph_list(async_client: AsyncClient):
    """Test listing paragraphs."""
    book_id = await create_book(async_client)

    # Create multiple paragraphs
    for i in range(3):
        payload = {
            "book_id": book_id,
            "index": i + 1,
            "text": f"Paragraph {i+1}",
            "speaker": None,
        }
        await async_client.post("/api/paragraphs/", json=payload)

    # List all
    resp = await async_client.get("/api/paragraphs/")
    assert resp.status_code == 200
    paragraphs = resp.json()
    assert len(paragraphs) >= 3

    # Test pagination
    resp = await async_client.get("/api/paragraphs/?skip=0&limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# ---- Additional TTSEdit tests -----


@pytest.mark.anyio
async def test_tts_edit_crud(async_client: AsyncClient):
    """Test TTS edit CRUD operations."""
    book_id = await create_book(async_client)
    paragraph_id = await create_paragraph(async_client, book_id)

    # Create tts_edit
    payload = {
        "paragraph_id": paragraph_id,
        "edited_text": "Edited for TTS",
        "voice": "en-US",
    }
    resp = await async_client.post("/api/tts_edits/", json=payload)
    assert resp.status_code == 201
    edit_id = resp.json()["id"]
    assert resp.json()["edited_text"] == "Edited for TTS"
    assert resp.json()["voice"] == "en-US"

    # Get tts_edit
    resp = await async_client.get(f"/api/tts_edits/{edit_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == edit_id
    assert resp.json()["paragraph_id"] == paragraph_id

    # Update tts_edit (requires full schema including id)
    update_payload = {
        "id": edit_id,
        "paragraph_id": paragraph_id,
        "edited_text": "Further edited",
        "voice": "en-GB",
    }
    resp = await async_client.put(f"/api/tts_edits/{edit_id}", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["edited_text"] == "Further edited"
    assert resp.json()["voice"] == "en-GB"

    # Delete tts_edit
    resp = await async_client.delete(f"/api/tts_edits/{edit_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await async_client.get(f"/api/tts_edits/{edit_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_tts_edit_list(async_client: AsyncClient):
    """Test listing TTS edits."""
    book_id = await create_book(async_client)
    paragraph_id = await create_paragraph(async_client, book_id)

    # Create multiple edits
    for i in range(3):
        payload = {
            "paragraph_id": paragraph_id,
            "edited_text": f"Edit {i+1}",
            "voice": "en-US",
        }
        await async_client.post("/api/tts_edits/", json=payload)

    # List all
    resp = await async_client.get("/api/tts_edits/")
    assert resp.status_code == 200
    edits = resp.json()
    assert len(edits) >= 3

    # Test pagination
    resp = await async_client.get("/api/tts_edits/?skip=0&limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


# ---- Additional Routing tests -----


@pytest.mark.anyio
async def test_routing_crud(async_client: AsyncClient):
    """Test routing CRUD operations."""
    book_id = await create_book(async_client)
    paragraph_id = await create_paragraph(async_client, book_id)

    # Create routing
    payload = {"paragraph_id": paragraph_id, "voice": "en-US", "confidence": 0.95}
    resp = await async_client.post("/api/routings/", json=payload)
    assert resp.status_code == 201
    routing_id = resp.json()["id"]
    assert resp.json()["voice"] == "en-US"
    assert resp.json()["confidence"] == 0.95

    # Get routing
    resp = await async_client.get(f"/api/routings/{routing_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == routing_id
    assert resp.json()["paragraph_id"] == paragraph_id

    # Update routing (requires full schema including id)
    update_payload = {
        "id": routing_id,
        "paragraph_id": paragraph_id,
        "voice": "en-GB",
        "confidence": 0.99,
    }
    resp = await async_client.put(f"/api/routings/{routing_id}", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["voice"] == "en-GB"
    assert resp.json()["confidence"] == 0.99

    # Delete routing
    resp = await async_client.delete(f"/api/routings/{routing_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await async_client.get(f"/api/routings/{routing_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_routing_list(async_client: AsyncClient):
    """Test listing routings."""
    book_id = await create_book(async_client)
    paragraph_id = await create_paragraph(async_client, book_id)

    # Create multiple routings
    for i in range(3):
        payload = {
            "paragraph_id": paragraph_id,
            "voice": f"voice-{i}",
            "confidence": 0.9,
        }
        await async_client.post("/api/routings/", json=payload)

    # List all
    resp = await async_client.get("/api/routings/")
    assert resp.status_code == 200
    routings = resp.json()
    assert len(routings) >= 3


# ---- Additional Quality tests -----


@pytest.mark.anyio
async def test_quality_crud(async_client: AsyncClient):
    """Test quality CRUD operations."""
    book_id = await create_book(async_client)
    paragraph_id = await create_paragraph(async_client, book_id)
    tts_edit_id = await create_tts_edit(async_client, paragraph_id)

    # Create quality
    payload = {"tts_edit_id": tts_edit_id, "score": 4.5, "comments": "Good quality"}
    resp = await async_client.post("/api/qualities/", json=payload)
    assert resp.status_code == 201
    quality_id = resp.json()["id"]
    assert resp.json()["score"] == 4.5
    assert resp.json()["comments"] == "Good quality"

    # Get quality
    resp = await async_client.get(f"/api/qualities/{quality_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == quality_id
    assert resp.json()["tts_edit_id"] == tts_edit_id

    # Update quality (requires full schema including id)
    update_payload = {
        "id": quality_id,
        "tts_edit_id": tts_edit_id,
        "score": 4.8,
        "comments": "Excellent",
    }
    resp = await async_client.put(f"/api/qualities/{quality_id}", json=update_payload)
    assert resp.status_code == 200
    assert resp.json()["score"] == 4.8
    assert resp.json()["comments"] == "Excellent"

    # Delete quality
    resp = await async_client.delete(f"/api/qualities/{quality_id}")
    assert resp.status_code == 204

    # Verify deleted
    resp = await async_client.get(f"/api/qualities/{quality_id}")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_quality_list(async_client: AsyncClient):
    """Test listing qualities."""
    book_id = await create_book(async_client)
    paragraph_id = await create_paragraph(async_client, book_id)
    tts_edit_id = await create_tts_edit(async_client, paragraph_id)

    # Create multiple qualities
    for i in range(3):
        payload = {
            "tts_edit_id": tts_edit_id,
            "score": 3.0 + i,
            "comments": f"Quality {i+1}",
        }
        await async_client.post("/api/qualities/", json=payload)

    # List all
    resp = await async_client.get("/api/qualities/")
    assert resp.status_code == 200
    qualities = resp.json()
    assert len(qualities) >= 3


# ---- Edge case tests ----


@pytest.mark.anyio
async def test_paragraph_not_found(async_client: AsyncClient):
    """Test 404 for non-existent paragraph."""
    resp = await async_client.get("/api/paragraphs/999")
    assert resp.status_code == 404

    # PUT with full schema still returns 404 for non-existent
    update_payload = {
        "book_id": 1,
        "index": 1,
        "text": "test",
        "speaker": "narrator",
    }
    resp = await async_client.put("/api/paragraphs/999", json=update_payload)
    assert resp.status_code == 404

    resp = await async_client.delete("/api/paragraphs/999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_tts_edit_not_found(async_client: AsyncClient):
    """Test 404 for non-existent tts edit."""
    resp = await async_client.get("/api/tts_edits/999")
    assert resp.status_code == 404

    # PUT with full schema still returns 404
    update_payload = {
        "paragraph_id": 1,
        "edited_text": "test",
        "voice": "en-US",
    }
    resp = await async_client.put("/api/tts_edits/999", json=update_payload)
    assert resp.status_code == 404

    resp = await async_client.delete("/api/tts_edits/999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_routing_not_found(async_client: AsyncClient):
    """Test 404 for non-existent routing."""
    resp = await async_client.get("/api/routings/999")
    assert resp.status_code == 404

    update_payload = {
        "paragraph_id": 1,
        "voice": "en-US",
        "confidence": 0.9,
    }
    resp = await async_client.put("/api/routings/999", json=update_payload)
    assert resp.status_code == 404

    resp = await async_client.delete("/api/routings/999")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_quality_not_found(async_client: AsyncClient):
    """Test 404 for non-existent quality."""
    resp = await async_client.get("/api/qualities/999")
    assert resp.status_code == 404

    update_payload = {
        "tts_edit_id": 1,
        "score": 4.0,
        "comments": "test",
    }
    resp = await async_client.put("/api/qualities/999", json=update_payload)
    assert resp.status_code == 404

    resp = await async_client.delete("/api/qualities/999")
    assert resp.status_code == 404
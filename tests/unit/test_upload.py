"""Tests for api/upload.py — file upload endpoints, chunked upload, extraction jobs.

Covers:
- Upload initialization (valid/invalid file types, size limits)
- Chunked upload (init, chunk, finalize)
- Simple single-request upload
- Extraction job status tracking
- Upload status and cancellation
- File validation helpers
"""

import sys

sys.path.insert(0, "src")

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Import all models FIRST to register tables with Base
import src.audiobook_studio.models  # noqa: F401

# Import the API router and dependencies
from src.audiobook_studio.api.upload import router as upload_router
from src.audiobook_studio.database import Base
from src.audiobook_studio.database import get_db as upload_get_db

# Create test app
test_app = FastAPI()
test_app.include_router(upload_router)

# Override auth dependencies
from src.audiobook_studio.auth.dependencies import get_current_active_user as real_get_current_active_user
from src.audiobook_studio.auth.dependencies import require_project_permission as real_require_project_permission


async def mock_get_current_active_user():
    from src.audiobook_studio.models.user import User

    user = User(
        id=1,
        username="testuser",
        email="test@example.com",
        hashed_password="hashed",
        is_active=True,
        is_superuser=True,  # Superuser bypasses permission checks
    )
    return user


def mock_require_project_permission(required_role):
    async def permission_checker(project_id: int, current_user=mock_get_current_active_user(), db=None):
        return await mock_get_current_active_user()

    return permission_checker


test_app.dependency_overrides[real_get_current_active_user] = mock_get_current_active_user
test_app.dependency_overrides[real_require_project_permission] = mock_require_project_permission


# Test database setup
@pytest.fixture(scope="function")
def db_engine():
    """Create a file-based SQLite engine for testing."""
    import tempfile

    from src.audiobook_studio.database import Base

    # Debug: check if models are registered
    print(f"Tables in metadata before create_all: {list(Base.metadata.tables.keys())}")

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    engine = create_engine(f"sqlite:///{tmp.name}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)

    # Debug: check tables created
    from sqlalchemy import inspect

    inspector = inspect(engine)
    print(f"Tables created: {inspector.get_table_names()}")

    yield engine
    engine.dispose()
    import os

    os.unlink(tmp.name)


@pytest.fixture(scope="function")
def db_session(db_engine):
    """Provide a SQLAlchemy session bound to the test engine."""
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=db_engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session):
    """FastAPI test client with database override."""

    def get_test_db():
        try:
            yield db_session
        finally:
            pass

    test_app.dependency_overrides[upload_get_db] = get_test_db
    with TestClient(test_app) as client:
        # Debug: check if we can query the database
        from sqlalchemy import inspect, text

        inspector = inspect(db_session.get_bind())
        print(f"Client fixture - tables in session bind: {inspector.get_table_names()}")
        # Debug: try to query project_permissions
        result = db_session.execute(text("SELECT COUNT(*) FROM project_permissions")).scalar()
        print(f"Client fixture - project_permissions count: {result}")
        yield client
    # Only clear the database override, keep auth overrides
    if upload_get_db in test_app.dependency_overrides:
        del test_app.dependency_overrides[upload_get_db]


@pytest.fixture
def mock_user(db_session):
    """Create a real user in the test database."""
    from src.audiobook_studio.models.user import User

    user = User(
        id=1,
        username="testuser",
        email="test@example.com",
        hashed_password="hashed",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def mock_project(db_session, mock_user):
    """Create a real project in the test database with editor permission."""
    from src.audiobook_studio.models import Project
    from src.audiobook_studio.models.user import ProjectPermission

    project = Project(
        id=1,
        title="Test Project",
        author="Test Author",
        language="zh",
        status="completed",
        current_stage="extract",
        progress=0.0,
    )
    db_session.add(project)
    db_session.commit()
    db_session.refresh(project)

    # Grant editor permission to the user
    permission = ProjectPermission(
        user_id=mock_user.id,
        project_id=project.id,
        role="editor",
    )
    db_session.add(permission)
    db_session.commit()

    return project


@pytest.fixture
def auth_headers():
    """Mock auth headers - we'll patch the auth dependency instead."""
    return {"Authorization": "Bearer test_token"}


@pytest.fixture(autouse=True)
def clear_global_state():
    """Clear global state before each test."""
    from src.audiobook_studio.api.upload import extraction_jobs, upload_sessions

    upload_sessions.clear()
    extraction_jobs.clear()
    yield
    upload_sessions.clear()
    extraction_jobs.clear()


@pytest.fixture(autouse=True)
def patch_websocket():
    """Patch WebSocket emit to avoid connection errors."""
    with patch("src.audiobook_studio.api.upload.emit_pipeline_event", new_callable=AsyncMock):
        yield


@pytest.fixture(autouse=True)
def patch_extract_text():
    """Patch extract_text to avoid actual file processing."""
    with patch("src.audiobook_studio.api.upload.extract_text", new_callable=AsyncMock) as mock:
        mock_result = MagicMock()
        mock_result.raw_text = "Chapter 1\n\nContent\n\nChapter 2\n\nMore content"
        mock_result.language = "zh-CN"
        mock_result.page_count = 10
        mock_result.has_ocr = False
        mock_result.ocr_page_ratio = 0.0
        mock.return_value = mock_result
        yield mock


@pytest.fixture(autouse=True)
def patch_upload_dir(tmp_path):
    """Patch upload directory to temp path."""
    with patch("src.audiobook_studio.api.upload.UPLOAD_DIR", tmp_path / "uploads"):
        upload_dir = tmp_path / "uploads"
        upload_dir.mkdir(parents=True, exist_ok=True)
        yield upload_dir


class TestUploadInit:
    """Tests for upload initialization endpoint."""

    def test_init_upload_success(self, client, mock_project):
        """Test successful upload initialization."""
        response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 1024000,
                "mime_type": "application/pdf",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert "upload_id" in data
        assert data["project_id"] == 1
        assert data["filename"] == "test.pdf"
        assert data["file_size"] == 1024000
        assert data["mime_type"] == "application/pdf"
        assert data["status"] == "initialized"

    def test_init_upload_invalid_extension(self, client, mock_project):
        """Test upload initialization with invalid file extension."""
        response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.exe",
                "file_size": 1024000,
                "mime_type": "application/octet-stream",
            },
        )
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_init_upload_invalid_mime_type(self, client, mock_project):
        """Test upload initialization with invalid MIME type."""
        response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 1024000,
                "mime_type": "application/exe",
            },
        )
        assert response.status_code == 400
        assert "MIME type" in response.json()["detail"]

    def test_init_upload_file_too_large(self, client, mock_project):
        """Test upload initialization with file exceeding size limit."""
        response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 200 * 1024 * 1024,  # 200MB > 100MB default
                "mime_type": "application/pdf",
            },
        )
        assert response.status_code == 413
        assert "too large" in response.json()["detail"]

    def test_init_upload_project_not_found(self, client):
        """Test upload initialization for non-existent project."""
        response = client.post(
            "/projects/999/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 1024000,
                "mime_type": "application/pdf",
            },
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_init_upload_all_allowed_types(self, client, mock_project):
        """Test upload initialization with all allowed file types."""
        allowed = [
            ("test.pdf", "application/pdf"),
            ("test.epub", "application/epub+zip"),
            ("test.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
            ("test.txt", "text/plain"),
        ]
        for filename, mime_type in allowed:
            response = client.post(
                "/projects/1/upload/init",
                data={
                    "filename": filename,
                    "file_size": 1024000,
                    "mime_type": mime_type,
                },
            )
            assert response.status_code == 200, f"Failed for {filename}"


class TestUploadChunk:
    """Tests for chunked upload endpoints."""

    def test_upload_chunk_success(self, client, mock_project):
        """Test successful chunk upload."""
        # First initialize upload
        init_response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 2048,
                "mime_type": "application/pdf",
            },
        )
        assert init_response.status_code == 200
        upload_id = init_response.json()["upload_id"]

        # Upload first chunk
        chunk_data = b"chunk1"
        response = client.post(
            f"/projects/1/upload/{upload_id}/chunk",
            data={
                "chunk_index": 0,
                "total_chunks": 2,
                "is_final": "false",
            },
            files={"file": ("chunk0", chunk_data, "application/octet-stream")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "chunk_received"
        assert data["chunk_index"] == 0
        assert "progress" in data

    def test_upload_chunk_final(self, client, mock_project, patch_extract_text):
        """Test final chunk upload triggers extraction."""
        init_response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 2048,
                "mime_type": "application/pdf",
            },
        )
        upload_id = init_response.json()["upload_id"]

        # Upload first chunk
        response = client.post(
            f"/projects/1/upload/{upload_id}/chunk",
            data={
                "chunk_index": 0,
                "total_chunks": 2,
                "is_final": "false",
            },
            files={"file": ("chunk0", b"chunk0", "application/octet-stream")},
        )
        assert response.status_code == 200

        # Upload final chunk
        response = client.post(
            f"/projects/1/upload/{upload_id}/chunk",
            data={
                "chunk_index": 1,
                "total_chunks": 2,
                "is_final": "true",
            },
            files={"file": ("chunk1", b"chunk1", "application/octet-stream")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "uploaded"
        assert "extraction_job_id" in data
        assert data["upload_id"] == upload_id

    def test_upload_chunk_invalid_session(self, client, mock_project):
        """Test chunk upload with invalid upload_id."""
        response = client.post(
            "/projects/1/upload/invalid-id/chunk",
            data={
                "chunk_index": 0,
                "total_chunks": 1,
                "is_final": "true",
            },
            files={"file": ("chunk0", b"data", "application/octet-stream")},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_upload_chunk_project_mismatch(self, client, mock_project):
        """Test chunk upload with project ID mismatch."""
        init_response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 1024,
                "mime_type": "application/pdf",
            },
        )
        upload_id = init_response.json()["upload_id"]

        response = client.post(
            f"/projects/2/upload/{upload_id}/chunk",
            data={
                "chunk_index": 0,
                "total_chunks": 1,
                "is_final": "true",
            },
            files={"file": ("chunk0", b"data", "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "mismatch" in response.json()["detail"]

    def test_upload_chunk_total_chunks_mismatch(self, client, mock_project):
        """Test chunk upload with mismatched total_chunks."""
        init_response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 2048,
                "mime_type": "application/pdf",
            },
        )
        upload_id = init_response.json()["upload_id"]

        # First chunk says 2 total
        client.post(
            f"/projects/1/upload/{upload_id}/chunk",
            data={
                "chunk_index": 0,
                "total_chunks": 2,
                "is_final": "false",
            },
            files={"file": ("chunk0", b"data", "application/octet-stream")},
        )

        # Second chunk says 3 total - should fail
        response = client.post(
            f"/projects/1/upload/{upload_id}/chunk",
            data={
                "chunk_index": 1,
                "total_chunks": 3,
                "is_final": "true",
            },
            files={"file": ("chunk1", b"data", "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "mismatch" in response.json()["detail"]


class TestSimpleUpload:
    """Tests for simple single-request upload endpoint."""

    def test_upload_file_success(self, client, mock_project, patch_extract_text):
        """Test simple file upload."""
        file_content = b"Test file content"
        response = client.post(
            "/projects/1/upload",
            files={"file": ("test.txt", file_content, "text/plain")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "upload_id" in data
        assert data["project_id"] == 1
        assert data["file_size"] == len(file_content)
        assert data["mime_type"] == "text/plain"
        assert "extraction_job_id" in data

    def test_upload_file_too_large(self, client, mock_project):
        """Test simple upload with file too large."""
        large_content = b"x" * (200 * 1024 * 1024)  # 200MB
        response = client.post(
            "/projects/1/upload",
            files={"file": ("test.txt", large_content, "text/plain")},
        )
        assert response.status_code == 413
        assert "too large" in response.json()["detail"]

    def test_upload_file_invalid_type(self, client, mock_project):
        """Test simple upload with invalid file type."""
        response = client.post(
            "/projects/1/upload",
            files={"file": ("test.exe", b"content", "application/octet-stream")},
        )
        assert response.status_code == 400
        assert "not allowed" in response.json()["detail"]

    def test_upload_file_project_not_found(self, client):
        """Test simple upload for non-existent project."""
        response = client.post(
            "/projects/999/upload",
            files={"file": ("test.txt", b"content", "text/plain")},
        )
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]


class TestExtractionJobStatus:
    """Tests for extraction job status endpoints."""

    def test_get_extraction_status_success(self, client, mock_project, patch_extract_text):
        """Test getting extraction job status."""
        # First upload a file to create a job
        response = client.post(
            "/projects/1/upload",
            files={"file": ("test.txt", b"content", "text/plain")},
        )
        job_id = response.json()["extraction_job_id"]

        # Get status
        response = client.get(f"/projects/1/extraction/{job_id}/status")
        assert response.status_code == 200
        data = response.json()
        assert data["job_id"] == job_id
        assert data["project_id"] == 1
        assert "status" in data
        assert "progress" in data

    def test_get_extraction_status_not_found(self, client, mock_project):
        """Test getting status for non-existent job."""
        response = client.get("/projects/1/extraction/nonexistent/status")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_get_extraction_status_project_mismatch(self, client, mock_project, patch_extract_text):
        """Test getting extraction status with project mismatch."""
        response = client.post(
            "/projects/1/upload",
            files={"file": ("test.txt", b"content", "text/plain")},
        )
        job_id = response.json()["extraction_job_id"]

        response = client.get(f"/projects/2/extraction/{job_id}/status")
        assert response.status_code == 400
        assert "mismatch" in response.json()["detail"]

    def test_list_extractions(self, client, mock_project, patch_extract_text):
        """Test listing all extractions for a project."""
        # Upload multiple files
        for i in range(3):
            client.post(
                "/projects/1/upload",
                files={"file": (f"test{i}.txt", f"content{i}".encode(), "text/plain")},
            )

        response = client.get("/projects/1/extractions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3
        # Should be sorted by created_at descending
        assert data[0]["job_id"] != data[1]["job_id"]


class TestUploadStatus:
    """Tests for upload session status endpoint."""

    def test_get_upload_status_success(self, client, mock_project):
        """Test getting upload session status."""
        init_response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 2048,
                "mime_type": "application/pdf",
            },
        )
        upload_id = init_response.json()["upload_id"]

        response = client.get(f"/projects/1/upload/{upload_id}/status")
        assert response.status_code == 200
        data = response.json()
        assert data["upload_id"] == upload_id
        assert data["project_id"] == 1
        assert data["filename"] == "test.pdf"
        assert "status" in data
        assert "chunks_received" in data
        assert "total_chunks" in data
        assert "progress" in data

    def test_get_upload_status_not_found(self, client, mock_project):
        """Test getting status for non-existent upload."""
        response = client.get("/projects/1/upload/nonexistent/status")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_get_upload_status_project_mismatch(self, client, mock_project):
        """Test getting upload status with project mismatch."""
        init_response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 1024,
                "mime_type": "application/pdf",
            },
        )
        upload_id = init_response.json()["upload_id"]

        response = client.get(f"/projects/2/upload/{upload_id}/status")
        assert response.status_code == 400
        assert "mismatch" in response.json()["detail"]


class TestCancelUpload:
    """Tests for upload cancellation endpoint."""

    def test_cancel_upload_success(self, client, mock_project):
        """Test successful upload cancellation."""
        init_response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 1024,
                "mime_type": "application/pdf",
            },
        )
        upload_id = init_response.json()["upload_id"]

        response = client.delete(f"/projects/1/upload/{upload_id}")
        assert response.status_code == 200
        assert "cancelled" in response.json()["message"]

        # Verify upload session is removed
        status_response = client.get(f"/projects/1/upload/{upload_id}/status")
        assert status_response.status_code == 404

    def test_cancel_upload_not_found(self, client, mock_project):
        """Test cancelling non-existent upload."""
        response = client.delete("/projects/1/upload/nonexistent")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_cancel_upload_project_mismatch(self, client, mock_project):
        """Test cancelling upload with project mismatch."""
        init_response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 1024,
                "mime_type": "application/pdf",
            },
        )
        upload_id = init_response.json()["upload_id"]

        response = client.delete(f"/projects/2/upload/{upload_id}")
        assert response.status_code == 400
        assert "mismatch" in response.json()["detail"]


class TestValidationHelpers:
    """Tests for validation helper functions."""

    def test_validate_file_valid_pdf(self):
        """Test validate_file with valid PDF."""
        from src.audiobook_studio.api.upload import validate_file

        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.pdf"
        mock_file.content_type = "application/pdf"
        # Should not raise
        validate_file(mock_file)

    def test_validate_file_valid_epub(self):
        """Test validate_file with valid EPUB."""
        from src.audiobook_studio.api.upload import validate_file

        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.epub"
        mock_file.content_type = "application/epub+zip"
        validate_file(mock_file)

    def test_validate_file_valid_docx(self):
        """Test validate_file with valid DOCX."""
        from src.audiobook_studio.api.upload import validate_file

        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.docx"
        mock_file.content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        validate_file(mock_file)

    def test_validate_file_valid_txt(self):
        """Test validate_file with valid TXT."""
        from src.audiobook_studio.api.upload import validate_file

        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.txt"
        mock_file.content_type = "text/plain"
        validate_file(mock_file)

    def test_validate_file_no_filename(self):
        """Test validate_file with no filename."""
        from fastapi import HTTPException

        from src.audiobook_studio.api.upload import validate_file

        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = None
        mock_file.content_type = "application/pdf"
        with pytest.raises(HTTPException) as exc_info:
            validate_file(mock_file)
        assert exc_info.value.status_code == 400
        assert "No filename provided" in exc_info.value.detail

    def test_validate_file_invalid_extension(self):
        """Test validate_file with invalid extension."""
        from fastapi import HTTPException

        from src.audiobook_studio.api.upload import validate_file

        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.exe"
        mock_file.content_type = "application/octet-stream"
        with pytest.raises(HTTPException) as exc_info:
            validate_file(mock_file)
        assert exc_info.value.status_code == 400
        assert "not allowed" in exc_info.value.detail

    def test_validate_file_invalid_mime_type(self):
        """Test validate_file with invalid MIME type."""
        from fastapi import HTTPException

        from src.audiobook_studio.api.upload import validate_file

        mock_file = MagicMock(spec=UploadFile)
        mock_file.filename = "test.pdf"
        mock_file.content_type = "application/exe"
        with pytest.raises(HTTPException) as exc_info:
            validate_file(mock_file)
        assert exc_info.value.status_code == 400
        assert "MIME type" in exc_info.value.detail


class TestSaveUploadChunk:
    """Tests for save_upload_chunk helper."""

    @pytest.mark.asyncio
    async def test_save_upload_chunk_success(self, patch_upload_dir):
        """Test saving upload chunk."""
        import uuid

        from src.audiobook_studio.api.upload import save_upload_chunk, upload_sessions

        upload_id = str(uuid.uuid4())
        file_path = patch_upload_dir / f"{upload_id}_test.pdf"
        file_path.touch()

        upload_sessions[upload_id] = {
            "file_path": str(file_path),
            "chunks_received": set(),
            "total_chunks": 2,
        }

        await save_upload_chunk(upload_id, b"chunk1", 0)
        assert 0 in upload_sessions[upload_id]["chunks_received"]

        await save_upload_chunk(upload_id, b"chunk2", 1)
        assert 1 in upload_sessions[upload_id]["chunks_received"]

    @pytest.mark.asyncio
    async def test_save_upload_chunk_invalid_session(self):
        """Test saving chunk for invalid session."""
        from fastapi import HTTPException

        from src.audiobook_studio.api.upload import save_upload_chunk

        with pytest.raises(HTTPException) as exc_info:
            await save_upload_chunk("invalid", b"data", 0)
        assert exc_info.value.status_code == 404


class TestFinalizeUpload:
    """Tests for finalize_upload helper."""

    def test_finalize_upload_success(self, patch_upload_dir):
        """Test finalizing upload."""
        import uuid

        from src.audiobook_studio.api.upload import finalize_upload, upload_sessions

        upload_id = str(uuid.uuid4())
        file_path = patch_upload_dir / f"{upload_id}_test.pdf"
        file_path.write_bytes(b"complete file")

        upload_sessions[upload_id] = {
            "file_path": str(file_path),
            "chunks_received": {0, 1},
            "total_chunks": 2,
        }

        result = finalize_upload(upload_id)
        assert result == str(file_path)

    def test_finalize_upload_invalid_session(self):
        """Test finalizing invalid session."""
        from fastapi import HTTPException

        from src.audiobook_studio.api.upload import finalize_upload

        with pytest.raises(HTTPException) as exc_info:
            finalize_upload("invalid")
        assert exc_info.value.status_code == 404

    def test_finalize_upload_missing_chunks(self, patch_upload_dir):
        """Test finalizing with missing chunks."""
        import uuid

        from fastapi import HTTPException

        from src.audiobook_studio.api.upload import finalize_upload, upload_sessions

        upload_id = str(uuid.uuid4())
        file_path = patch_upload_dir / f"{upload_id}_test.pdf"
        file_path.touch()

        upload_sessions[upload_id] = {
            "file_path": str(file_path),
            "chunks_received": {0},
            "total_chunks": 2,
        }

        with pytest.raises(HTTPException) as exc_info:
            finalize_upload(upload_id)
        assert exc_info.value.status_code == 400
        assert "Not all chunks received" in exc_info.value.detail


class TestSplitIntoChapters:
    """Tests for split_into_chapters helper."""

    def test_split_chinese_chapters(self):
        """Test splitting Chinese text with chapter markers."""
        from src.audiobook_studio.api.upload import split_into_chapters

        text = "\n第1章\n内容1\n\n第2章\n内容2\n\n第3章\n内容3"
        chapters = split_into_chapters(text)
        assert len(chapters) == 3
        assert "第1章" in chapters[0]
        assert "第2章" in chapters[1]
        assert "第3章" in chapters[2]

    def test_split_english_chapters(self):
        """Test splitting English text with Chapter markers."""
        from src.audiobook_studio.api.upload import split_into_chapters

        text = "\nChapter 1\nContent 1\n\nChapter 2\nContent 2\n\nChapter 3\nContent 3"
        chapters = split_into_chapters(text)
        assert len(chapters) == 3
        assert "Chapter 1" in chapters[0]
        assert "Chapter 2" in chapters[1]

    def test_split_no_markers_fallback(self):
        """Test fallback splitting when no chapter markers found."""
        from src.audiobook_studio.api.upload import split_into_chapters

        # Create text with many paragraphs but no chapter markers
        paragraphs = [f"Paragraph {i}" for i in range(20)]
        text = "\n\n".join(paragraphs)
        chapters = split_into_chapters(text)
        # Should create ~10 chapters
        assert len(chapters) <= 10
        assert len(chapters) > 1

    def test_split_empty_text(self):
        """Test splitting empty text."""
        from src.audiobook_studio.api.upload import split_into_chapters

        chapters = split_into_chapters("")
        assert chapters == []

    def test_split_single_paragraph(self):
        """Test splitting single paragraph."""
        from src.audiobook_studio.api.upload import split_into_chapters

        chapters = split_into_chapters("Single paragraph only")
        assert len(chapters) == 1
        assert chapters[0] == "Single paragraph only"


class TestStartExtractionJob:
    """Tests for start_extraction_job helper."""

    @pytest.mark.asyncio
    async def test_start_extraction_job(self, patch_upload_dir):
        """Test starting extraction job."""
        from src.audiobook_studio.api.upload import extraction_jobs, start_extraction_job

        job_id = await start_extraction_job("upload123", 1, "/tmp/test.pdf", "application/pdf")

        assert job_id in extraction_jobs
        job = extraction_jobs[job_id]
        assert job.job_id == job_id
        assert job.project_id == 1
        assert job.upload_id == "upload123"
        assert job.status == "pending"
        assert job.progress == 0.0


class TestUploadEdgeCases:
    """Edge case tests for upload endpoints."""

    def test_init_upload_missing_filename(self, client, mock_project):
        """Test init upload with missing filename."""
        response = client.post(
            "/projects/1/upload/init",
            data={
                "file_size": 1024,
                "mime_type": "application/pdf",
            },
        )
        # FastAPI will return 422 for missing required form field
        assert response.status_code == 422

    def test_init_upload_missing_file_size(self, client, mock_project):
        """Test init upload with missing file_size."""
        response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "mime_type": "application/pdf",
            },
        )
        assert response.status_code == 422

    def test_init_upload_missing_mime_type(self, client, mock_project):
        """Test init upload with missing mime_type."""
        response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 1024,
            },
        )
        assert response.status_code == 422

    def test_upload_chunk_missing_file(self, client, mock_project):
        """Test chunk upload without file."""
        init_response = client.post(
            "/projects/1/upload/init",
            data={
                "filename": "test.pdf",
                "file_size": 1024,
                "mime_type": "application/pdf",
            },
        )
        upload_id = init_response.json()["upload_id"]

        response = client.post(
            f"/projects/1/upload/{upload_id}/chunk",
            data={
                "chunk_index": 0,
                "total_chunks": 1,
                "is_final": "true",
            },
            # No file provided
        )
        assert response.status_code == 422

    def test_simple_upload_no_file(self, client, mock_project):
        """Test simple upload without file."""
        response = client.post("/projects/1/upload")
        assert response.status_code == 422


class TestUploadModels:
    """Tests for upload request/response models."""

    def test_upload_init_response(self):
        """Test UploadInitResponse model."""
        from src.audiobook_studio.api.upload import UploadInitResponse

        resp = UploadInitResponse(
            upload_id="test123",
            project_id=1,
            filename="test.pdf",
            file_size=1024,
            mime_type="application/pdf",
        )
        assert resp.upload_id == "test123"
        assert resp.status == "initialized"
        assert "initialized" in resp.message.lower()

    def test_upload_chunk_request(self):
        """Test UploadChunkRequest model."""
        from src.audiobook_studio.api.upload import UploadChunkRequest

        req = UploadChunkRequest(
            upload_id="test123",
            chunk_index=0,
            total_chunks=5,
            is_final=False,
        )
        assert req.chunk_index == 0
        assert req.total_chunks == 5
        assert req.is_final is False

    def test_upload_complete_response(self):
        """Test UploadCompleteResponse model."""
        from src.audiobook_studio.api.upload import UploadCompleteResponse

        resp = UploadCompleteResponse(
            upload_id="test123",
            project_id=1,
            file_path="/tmp/test.pdf",
            file_size=1024,
            mime_type="application/pdf",
            extraction_job_id="job123",
        )
        assert resp.status == "uploaded"
        assert resp.extraction_job_id == "job123"

    def test_extraction_job_status(self):
        """Test ExtractionJobStatus model."""
        from src.audiobook_studio.api.upload import ExtractionJobStatus

        job = ExtractionJobStatus(
            job_id="job123",
            project_id=1,
            upload_id="upload123",
            status="running",
            progress=0.5,
            current_step="extracting",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        assert job.job_id == "job123"
        assert job.status == "running"
        assert job.progress == 0.5

    def test_extraction_result_response(self):
        """Test ExtractionResultResponse model."""
        from src.audiobook_studio.api.upload import ExtractionResultResponse

        resp = ExtractionResultResponse(
            job_id="job123",
            project_id=1,
            status="completed",
            chapters_created=5,
            total_paragraphs=100,
            language="zh-CN",
            page_count=50,
            has_ocr=False,
            ocr_page_ratio=0.0,
            warnings=[],
            processing_time_seconds=10.5,
        )
        assert resp.chapters_created == 5
        assert resp.total_paragraphs == 100
        assert resp.language == "zh-CN"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

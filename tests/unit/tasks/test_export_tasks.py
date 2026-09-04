"""
Tests for Export Tasks (TEST-001: coverage improvement).

Tests for src/audiobook_studio/tasks/export_tasks.py
Focus on testing utility functions and Celery tasks.
Target: 70%+ coverage
"""

import os
import sys

# Restore real celery module (conftest_minimal.py mocks it globally)
if "celery" in sys.modules:
    del sys.modules["celery"]
import celery  # noqa: F401 - ensure real celery is loaded

# Also purge cached export_tasks so it re-imports with real celery
for mod in list(sys.modules):
    if mod.startswith("src.audiobook_studio.tasks"):
        del sys.modules[mod]

# Set TEST_MODE before any imports to use fake services
os.environ["TEST_MODE"] = "true"
os.environ["MOCK_TTS"] = "true"
os.environ["MOCK_LLM"] = "true"

import asyncio as _asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Now import the module under test
from src.audiobook_studio.tasks import export_tasks

_real_asyncio_run = _asyncio.run


class TestExportTaskUtilities:  # noqa: E303
    """Tests for utility functions and constants in export_tasks.py"""

    def test_constants_defined(self):
        """Test that key constants are defined."""
        assert export_tasks.PENDING == "PENDING"
        assert export_tasks.STARTED == "STARTED"
        assert export_tasks.SUCCESS == "SUCCESS"
        assert export_tasks.FAILURE == "FAILURE"
        assert export_tasks.RETRY == "RETRY"


class TestTypedTask:
    """Tests for _typed_task decorator."""

    def test_typed_task_returns_decorator(self):
        """Test _typed_task returns a callable decorator."""
        # The decorator should be callable and return another callable
        result = export_tasks._typed_task()
        assert callable(result)


class TestGetTaskResultDict:
    """Tests for _get_task_result_dict function."""

    def test_get_task_result_dict_minimal(self):
        """Test _get_task_result_dict with minimal args."""
        mock_task = MagicMock()
        mock_task.request.id = "task_123"

        result = export_tasks._get_task_result_dict(mock_task, "task_123", 1, "complete")

        assert result["task_id"] == "task_123"
        assert result["status"] == "complete"
        assert result["project_id"] == 1
        assert "output_paths" not in result
        assert "error" not in result

    def test_get_task_result_dict_with_output_paths(self):
        """Test _get_task_result_dict with output_paths."""
        mock_task = MagicMock()
        mock_task.request.id = "task_123"

        result = export_tasks._get_task_result_dict(
            mock_task, "task_123", 1, "complete", output_paths={"m4b": "/path/to/file.m4b"}
        )

        assert result["output_paths"] == {"m4b": "/path/to/file.m4b"}

    def test_get_task_result_dict_with_error(self):
        """Test _get_task_result_dict with error."""
        mock_task = MagicMock()
        mock_task.request.id = "task_123"

        result = export_tasks._get_task_result_dict(mock_task, "task_123", 1, "failed", error="Export failed")

        assert result["error"] == "Export failed"

    def test_get_task_result_dict_with_extras(self):
        """Test _get_task_result_dict with extra kwargs."""
        mock_task = MagicMock()
        mock_task.request.id = "task_123"

        result = export_tasks._get_task_result_dict(
            mock_task, "task_123", 1, "complete", output_paths={}, error=None, extra_field="extra_value"
        )

        assert result["extra_field"] == "extra_value"


class TestRunExportAsync:
    """Tests for _run_export_async function."""

    @pytest.mark.asyncio
    async def test_run_export_async_calls_export_project(self):
        """Test _run_export_async calls export_project with correct args."""
        project_id = 1
        mock_job = MagicMock()
        mock_job.project_id = project_id

        with patch("src.audiobook_studio.tasks.export_tasks.export_project", new_callable=AsyncMock) as mock_export:
            mock_export.return_value = mock_job
            with patch("src.audiobook_studio.tasks.export_tasks.AsyncSessionLocal") as mock_session:
                mock_db = AsyncMock()
                mock_session.return_value.__aenter__.return_value = mock_db

                result = await export_tasks._run_export_async(project_id, mock_job)

                assert result == mock_job
                mock_export.assert_called_once_with(project_id, mock_db, mock_job)

    @pytest.mark.asyncio
    async def test_run_export_async_uses_provided_session(self):
        """Test _run_export_async uses provided db_session."""
        project_id = 1
        mock_job = MagicMock()
        mock_job.project_id = project_id
        mock_db = AsyncMock()

        with patch("src.audiobook_studio.tasks.export_tasks.export_project", new_callable=AsyncMock) as mock_export:
            mock_export.return_value = mock_job

            result = await export_tasks._run_export_async(project_id, mock_job, mock_db)

            assert result == mock_job
            mock_export.assert_called_once_with(project_id, mock_db, mock_job)


class TestExportProjectAsync:
    """Tests for export_project_async Celery task."""

    def test_export_project_async_minimal_config(self):
        """Test export_project_async with minimal config."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3

        # Create a mock result_job with the expected structure
        mock_result_job = MagicMock()
        mock_result_job.progress = MagicMock()
        mock_result_job.progress.value = "complete"
        mock_result_job.output_paths = {"m4b": "/path/to/output.m4b"}
        mock_result_job.error = None

        with patch("asyncio.run") as mock_run:
            mock_run.return_value = mock_result_job

            result = export_tasks.export_project_async(
                mock_self,
                project_id=1,
                job_config={},
            )

            assert result["status"] == "complete"
            assert result["task_id"] == "task_123"
            assert result["project_id"] == 1

    def test_export_project_async_parses_formats(self):
        """Test export_project_async parses formats correctly."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3

        mock_result_job = MagicMock()
        mock_result_job.progress = MagicMock()
        mock_result_job.progress.value = "complete"
        mock_result_job.output_paths = {}
        mock_result_job.error = None

        with patch("asyncio.run") as mock_run:
            mock_run.return_value = mock_result_job

            export_tasks.export_project_async(
                mock_self,
                project_id=1,
                job_config={"formats": ["m4b_srt", "mp3"]},
            )

            mock_run.assert_called_once()

    def test_export_project_async_handles_unknown_format(self):
        """Test export_project_async handles unknown format gracefully."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3

        mock_result_job = MagicMock()
        mock_result_job.progress = MagicMock()
        mock_result_job.progress.value = "complete"
        mock_result_job.output_paths = {}
        mock_result_job.error = None

        with patch("asyncio.run") as mock_run:
            mock_run.return_value = mock_result_job

            export_tasks.export_project_async(
                mock_self,
                project_id=1,
                job_config={"formats": ["unknown_format"]},
            )

            mock_run.assert_called_once()

    def test_export_project_async_retry_on_failure(self):
        """Test export_project_async retries on failure."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3
        test_exception = Exception("Transient error")
        mock_self.retry.side_effect = lambda exc: (_ for _ in ()).throw(exc)

        with patch("asyncio.run") as mock_run:
            mock_run.side_effect = test_exception

            with pytest.raises(Exception):  # noqa: B017
                export_tasks.export_project_async(
                    mock_self,
                    project_id=1,
                    job_config={},
                )

            mock_self.retry.assert_called_once_with(exc=test_exception)


class TestExportChapterAsync:
    """Tests for export_chapter_async Celery task."""

    def test_export_chapter_async_success(self):
        """Test export_chapter_async returns success on success."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3

        with patch("asyncio.run") as mock_run:
            mock_run.return_value = "/path/to/chapter.m4b"

            result = export_tasks.export_chapter_async(
                mock_self,
                project_id=1,
                chapter_id=5,
            )

            assert result["status"] == "complete"
            assert result["output_path"] == "/path/to/chapter.m4b"

    def test_export_chapter_async_not_found(self):
        """Test export_chapter_async handles chapter not found."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3

        with patch("asyncio.run") as mock_run:
            mock_run.return_value = None

            result = export_tasks.export_chapter_async(
                mock_self,
                project_id=1,
                chapter_id=999,
            )

            assert result["status"] == "failed"
            assert "no audio segments" in result["error"].lower() or "not found" in result["error"].lower()

    def test_export_chapter_async_retry_on_failure(self):
        """Test export_chapter_async retries on failure."""
        mock_self = MagicMock()
        mock_self.request.id = "task_123"
        mock_self.request.retries = 0
        mock_self.max_retries = 3
        test_exception = Exception("Transient error")
        mock_self.retry.side_effect = lambda exc: (_ for _ in ()).throw(exc)

        with patch("asyncio.run") as mock_run:
            mock_run.side_effect = test_exception

            with pytest.raises(Exception):  # noqa: B017
                export_tasks.export_chapter_async(
                    mock_self,
                    project_id=1,
                    chapter_id=5,
                )

            mock_self.retry.assert_called_once_with(exc=test_exception)


class TestGetExportStatus:
    """Tests for get_export_status task."""

    def test_get_export_status_pending(self):
        """Test get_export_status returns pending for pending task."""
        mock_result = MagicMock()
        mock_result.state = "PENDING"
        mock_result.info = {}

        with patch("src.audiobook_studio.tasks.export_tasks.celery_app.AsyncResult", return_value=mock_result):
            with patch("src.audiobook_studio.tasks.export_tasks.PENDING", "PENDING"):
                result = export_tasks.get_export_status("task_123")

                assert result["task_id"] == "task_123"
                assert result["state"] == "PENDING"
                assert result["progress"] == "pending"

    def test_get_export_status_started(self):
        """Test get_export_status returns processing for started task."""
        mock_result = MagicMock()
        mock_result.state = "STARTED"
        mock_result.info = {"message": "Processing chapter 1", "current_stage": "synthesis"}

        with patch("src.audiobook_studio.tasks.export_tasks.celery_app.AsyncResult", return_value=mock_result):
            result = export_tasks.get_export_status("task_123")

            assert result["state"] == "STARTED"
            assert result["progress"] == "processing"
            assert result["message"] == "Processing chapter 1"
            assert result["current_stage"] == "synthesis"

    def test_get_export_status_success(self):
        """Test get_export_status returns complete for successful task."""
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.info = {"output_paths": {"m4b": "/path/to/output.m4b"}}

        with patch("src.audiobook_studio.tasks.export_tasks.celery_app.AsyncResult", return_value=mock_result):
            result = export_tasks.get_export_status("task_123")

            assert result["state"] == "SUCCESS"
            assert result["progress"] == "complete"
            assert result["output_paths"] == {"m4b": "/path/to/output.m4b"}

    def test_get_export_status_failure(self):
        """Test get_export_status returns failed for failed task."""
        mock_result = MagicMock()
        mock_result.state = "FAILURE"
        mock_result.info = {"error": "Export failed"}

        with patch("src.audiobook_studio.tasks.export_tasks.celery_app.AsyncResult", return_value=mock_result):
            result = export_tasks.get_export_status("task_123")

            assert result["state"] == "FAILURE"
            assert result["progress"] == "failed"
            assert result["error"] == "Export failed"

    def test_get_export_status_retry(self):
        """Test get_export_status returns retrying for retried task."""
        mock_result = MagicMock()
        mock_result.state = "RETRY"
        mock_result.info = {"message": "Retrying after error"}

        with patch("src.audiobook_studio.tasks.export_tasks.celery_app.AsyncResult", return_value=mock_result):
            result = export_tasks.get_export_status("task_123")

            assert result["state"] == "RETRY"
            assert result["progress"] == "retrying"

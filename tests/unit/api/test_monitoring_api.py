"""Tests for monitoring API endpoints."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.audiobook_studio.api.monitoring import (
    _load_metrics,
    get_latest_metrics,
    get_metrics_history,
    get_project_metrics,
    list_projects_with_metrics,
    router,
)
from src.audiobook_studio.exceptions import FileNotFoundError, InfrastructureError


@pytest.fixture
def client():
    from fastapi import FastAPI
    from unittest.mock import AsyncMock, MagicMock
    from src.audiobook_studio.api.dependencies import get_async_db
    from src.audiobook_studio.exceptions import FileNotFoundError

    app = FastAPI()
    app.include_router(router)

    @app.exception_handler(FileNotFoundError)
    async def file_not_found_handler(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=404,
            content={"detail": str(exc)},
        )

    # Override the get_async_db dependency for tests
    async def override_get_async_db():
        mock_db = AsyncMock()
        yield mock_db

    app.dependency_overrides[get_async_db] = override_get_async_db

    return TestClient(app)


class TestLoadMetrics:
    """Tests for _load_metrics helper function."""

    def test_load_valid_json(self, tmp_path):
        data = {"key": "value", "number": 42}
        path = tmp_path / "test.json"
        path.write_text(json.dumps(data))
        result = _load_metrics(path)
        assert result == data

    def test_invalid_json_raises_infrastructure_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{ invalid json")
        with pytest.raises(InfrastructureError) as exc_info:
            _load_metrics(path)
        assert "Corrupted metrics file" in exc_info.value.message
        assert exc_info.value.error_code == "INFRASTRUCTURE_ERROR"

    def test_missing_file_raises_infrastructure_error(self, tmp_path):
        path = tmp_path / "nonexistent.json"
        with pytest.raises(InfrastructureError) as exc_info:
            _load_metrics(path)
        assert "Failed to read metrics" in exc_info.value.message


class TestGetProjectMetrics:
    """Tests for get_project_metrics endpoint."""

    @pytest.mark.asyncio
    async def test_returns_chapter_specific_metrics(self, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            chapter_data = {"metadata": {"chapter": 1}}
            (tmp_path / "metrics_summary_ch_001.json").write_text(json.dumps(chapter_data))

            result = await get_project_metrics(project_id=123, chapter_index=1)
            assert result == chapter_data

    @pytest.mark.asyncio
    async def test_fallbacks_to_default_metrics(self, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            default_data = {"metadata": {"default": True}}
            (tmp_path / "metrics_summary.json").write_text(json.dumps(default_data))

            result = await get_project_metrics(project_id=123, chapter_index=99)
            assert result == default_data

    @pytest.mark.asyncio
    async def test_raises_when_no_metrics_file(self, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            with pytest.raises(FileNotFoundError) as exc_info:
                await get_project_metrics(project_id=123, chapter_index=1)
            assert "metrics_summary for project 123" in exc_info.value.context["path"]


class TestGetLatestMetrics:
    """Tests for get_latest_metrics endpoint."""

    @pytest.mark.asyncio
    async def test_returns_latest_by_mtime(self, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            old_data = {"timestamp": "old"}
            new_data = {"timestamp": "new"}
            old_path = tmp_path / "metrics_summary_ch_001.json"
            new_path = tmp_path / "metrics_summary_ch_002.json"

            old_path.write_text(json.dumps(old_data))
            new_path.write_text(json.dumps(new_data))

            import time
            time.sleep(0.01)
            new_path.touch()

            result = await get_latest_metrics(project_id=123)
            assert result == new_data

    @pytest.mark.asyncio
    async def test_includes_default_metrics_summary(self, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            default_data = {"type": "default"}
            (tmp_path / "metrics_summary.json").write_text(json.dumps(default_data))

            result = await get_latest_metrics(project_id=123)
            assert result == default_data

    @pytest.mark.asyncio
    async def test_raises_when_no_files(self, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            with pytest.raises(FileNotFoundError) as exc_info:
                await get_latest_metrics(project_id=123)
            assert "metrics files for project 123" in exc_info.value.context["path"]


class TestGetMetricsHistory:
    """Tests for get_metrics_history endpoint."""

    @pytest.mark.asyncio
    async def test_returns_sorted_history(self, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            for i in range(3):
                data = {"metadata": {"started_at": f"2024-01-0{i+1}", "duration_ms": 1000 * i, "success": True}}
                (tmp_path / f"metrics_summary_ch_{i+1:03d}.json").write_text(json.dumps(data))

            result = await get_metrics_history(project_id=123, limit=10)
            assert len(result["history"]) == 3
            # Should be sorted newest first
            assert result["history"][0]["timestamp"] == "2024-01-03"

    @pytest.mark.asyncio
    async def test_respects_limit(self, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            for i in range(5):
                data = {"metadata": {"started_at": f"2024-01-0{i+1}"}}
                (tmp_path / f"metrics_summary_ch_{i+1:03d}.json").write_text(json.dumps(data))

            result = await get_metrics_history(project_id=123, limit=2)
            assert len(result["history"]) == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_reports_dir(self, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = Path("/nonexistent")

            result = await get_metrics_history(project_id=123)
            assert result == {"history": []}

    @pytest.mark.asyncio
    async def test_skips_corrupted_files(self, tmp_path, caplog):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            (tmp_path / "metrics_summary_ch_001.json").write_text("{bad json")
            (tmp_path / "metrics_summary_ch_002.json").write_text(json.dumps({"metadata": {"started_at": "2024-01-02"}}))

            result = await get_metrics_history(project_id=123, limit=10)
            assert len(result["history"]) == 1
            assert result["history"][0]["timestamp"] == "2024-01-02"
            assert "Failed to load metrics" in caplog.text


class TestListProjectsWithMetrics:
    """Tests for list_projects_with_metrics endpoint."""

    @pytest.mark.asyncio
    async def test_returns_projects_with_metrics(self, tmp_path):
        mock_db = AsyncMock()
        mock_project1 = MagicMock()
        mock_project1.id = 1
        mock_project1.title = "Project 1"
        mock_project2 = MagicMock()
        mock_project2.id = 2
        mock_project2.title = "Project 2"
        mock_project3 = MagicMock()
        mock_project3.id = 3
        mock_project3.title = "Project 3"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_project1, mock_project2, mock_project3]
        mock_db.execute.return_value = mock_result

        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            def reports_dir_side_effect(project_id):
                path = tmp_path / f"project_{project_id}"
                path.mkdir(exist_ok=True)
                if project_id in (1, 2):
                    (path / "metrics_summary.json").write_text(json.dumps({"test": "data"}))
                return path

            mock_reports_dir.side_effect = reports_dir_side_effect

            result = await list_projects_with_metrics(db=mock_db)
            assert len(result["projects"]) == 2
            assert result["projects"][0]["project_id"] == 2  # Most recent first
            assert result["projects"][1]["project_id"] == 1

    @pytest.mark.asyncio
    async def test_excludes_projects_without_metrics(self, tmp_path):
        mock_db = AsyncMock()
        mock_project = MagicMock()
        mock_project.id = 1
        mock_project.title = "Project 1"
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_project]
        mock_db.execute.return_value = mock_result

        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path / "project_1"
            (tmp_path / "project_1").mkdir(exist_ok=True)
            # No metrics files created

            result = await list_projects_with_metrics(db=mock_db)
            assert result == {"projects": []}


class TestMonitoringRouter:
    """Integration tests for monitoring router endpoints."""

    def test_get_project_metrics_endpoint(self, client, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path
            data = {"metadata": {"chapter": 1, "success": True}}
            (tmp_path / "metrics_summary_ch_001.json").write_text(json.dumps(data))

            response = client.get("/monitoring/projects/123/metrics?chapter_index=1")
            assert response.status_code == 200
            assert response.json() == data

    def test_get_project_metrics_404(self, client, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path

            response = client.get("/monitoring/projects/123/metrics")
            assert response.status_code == 404

    def test_get_latest_metrics_endpoint(self, client, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path
            data = {"timestamp": "latest"}
            (tmp_path / "metrics_summary.json").write_text(json.dumps(data))

            response = client.get("/monitoring/projects/123/metrics/latest")
            assert response.status_code == 200
            assert response.json() == data

    def test_get_metrics_history_endpoint(self, client, tmp_path):
        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_reports_dir.return_value = tmp_path
            for i in range(2):
                (tmp_path / f"metrics_summary_ch_{i+1:03d}.json").write_text(
                    json.dumps({"metadata": {"started_at": f"2024-01-0{i+1}"}})
                )

            response = client.get("/monitoring/projects/123/metrics/history?limit=10")
            assert response.status_code == 200
            assert "history" in response.json()
            assert len(response.json()["history"]) == 2

def test_list_projects_with_metrics_endpoint(client, tmp_path):
        from unittest.mock import AsyncMock, MagicMock
        from fastapi import FastAPI
        from src.audiobook_studio.api.dependencies import get_async_db

        with patch("src.audiobook_studio.api.monitoring.reports_dir") as mock_reports_dir:
            mock_project = MagicMock()
            mock_project.id = 9999  # Unique ID to avoid conflicts
            mock_project.title = "Test Project"

            def reports_dir_side_effect(project_id):
                path = tmp_path / f"project_{project_id}"
                path.mkdir(exist_ok=True)
                if project_id == 9999:
                    (path / "metrics_summary.json").write_text(json.dumps({"test": "data"}))
                return path

            mock_reports_dir.side_effect = reports_dir_side_effect

            # Configure the mock db for the list_projects_with_metrics endpoint
            mock_db = AsyncMock()
            mock_result = MagicMock()
            mock_scalars = MagicMock()
            mock_scalars.all.return_value = [mock_project]
            mock_result.scalars.return_value = mock_scalars
            mock_db.execute = AsyncMock(return_value=mock_result)

            # Override the dependency for this specific test
            async def override_get_async_db():
                yield mock_db

            client.app.dependency_overrides[get_async_db] = override_get_async_db

            response = client.get("/monitoring/projects")
            assert response.status_code == 200
            assert len(response.json()["projects"]) == 1
            assert response.json()["projects"][0]["title"] == "Test Project"
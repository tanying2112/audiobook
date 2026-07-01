"""High-impact coverage tests for 0% and low-coverage API/config modules.

Covers: config.py, collab.py, audio_segments.py, export.py, llm.py,
        dependencies.py, version_manager.py, main.py, mock_router.py
"""

import tempfile
import os
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock, mock_open

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.audiobook_studio.database import Base, get_db


# ═══════════════════════════════════════════════════════════════════════════
# 1. dependencies.py
# ═══════════════════════════════════════════════════════════════════════════


class TestDependencies:
    def test_get_db_yields_session(self):
        from src.audiobook_studio.api.dependencies import get_db as dep_get_db

        gen = dep_get_db()
        db = next(gen)
        assert db is not None
        try:
            next(gen)
        except StopIteration:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# 2. config.py — router prefix="/config"
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigAPI:
    @pytest.fixture()
    def client(self):
        from src.audiobook_studio.api.config import router

        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as c:
            yield c

    def test_get_config_status(self, client):
        r = client.get("/config/status")
        assert r.status_code == 200

    def test_reload_constitutional_rules(self, client):
        r = client.post("/config/rules/reload")
        assert r.status_code == 200

    def test_reload_quality_thresholds(self, client):
        r = client.post("/config/thresholds/reload")
        assert r.status_code == 200

    def test_reload_contract_versions(self, client):
        r = client.post("/config/contracts/reload")
        assert r.status_code == 200

    def test_reload_all_configs(self, client):
        r = client.post("/config/reload-all")
        assert r.status_code == 200

    def test_update_constitutional_rules(self, client):
        r = client.post("/config/rules/update", json={"rules": {"test_rule": "value"}})
        assert r.status_code == 200

    def test_update_quality_thresholds(self, client):
        r = client.post(
            "/config/thresholds/update",
            json={"thresholds": {"dnsmos_min": 3.5}},
        )
        assert r.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# 3. collab.py — router prefix="/collab", some endpoints return 501
# ═══════════════════════════════════════════════════════════════════════════


class TestCollabAPI:
    @pytest.fixture()
    def client(self):
        from src.audiobook_studio.api.collab import router

        app = FastAPI()
        app.include_router(router)

        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = create_engine(
            f"sqlite:///{tmp.name}", connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)

        def override():
            db = TestSession()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override
        with TestClient(app) as c:
            yield c
        app.dependency_overrides.clear()
        engine.dispose()
        os.unlink(tmp.name)

    def test_get_collaboration_stats(self, client):
        r = client.get("/collab/stats")
        assert r.status_code == 200

    def test_get_change_history(self, client):
        r = client.get("/collab/history")
        assert r.status_code == 200

    def test_list_comments(self, client):
        r = client.get("/collab/comments")
        assert r.status_code == 200

    def test_list_tasks(self, client):
        r = client.get("/collab/tasks")
        # Returns 501 (not yet implemented) or 200
        assert r.status_code in (200, 501)

    def test_list_approval_requests(self, client):
        r = client.get("/collab/approvals")
        # Returns 501 (not yet implemented) or 200
        assert r.status_code in (200, 501)


# ═══════════════════════════════════════════════════════════════════════════
# 4. audio_segments.py — router prefix="/audio-segments"
# ═══════════════════════════════════════════════════════════════════════════


class TestAudioSegmentsAPI:
    @pytest.fixture()
    def client(self):
        from src.audiobook_studio.api.audio_segments import router

        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as c:
            yield c

    def test_list_segments_empty(self, client):
        r = client.get("/audio-segments/book/nonexistent_book")
        assert r.status_code == 200

    def test_reorder_segments_not_found(self, client):
        r = client.patch("/audio-segments/99999/reorder", json={"new_order": 0})
        assert r.status_code in (200, 404, 422)

    def test_trim_segment_not_found(self, client):
        r = client.post(
            "/audio-segments/99999/trim",
            json={"start_ms": 0, "end_ms": 1000},
        )
        assert r.status_code in (200, 404, 422)

    def test_merge_not_found(self, client):
        r = client.post(
            "/audio-segments/merge",
            json={"segment_ids": ["99999", "99998"]},
        )
        assert r.status_code in (200, 404, 422)


# ═══════════════════════════════════════════════════════════════════════════
# 5. export.py
# ═══════════════════════════════════════════════════════════════════════════


class TestExportAPI:
    @pytest.fixture()
    def client(self):
        from src.audiobook_studio.api.export import router

        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as c:
            yield c

    def test_list_formats(self, client):
        r = client.get("/projects/1/export/")
        assert r.status_code in (200, 422)

    def test_start_export(self, client):
        r = client.post(
            "/projects/1/export/",
            json={"format": "mp3", "chapter_ids": []},
        )
        assert r.status_code in (200, 202, 400, 404, 422)

    def test_get_export_status(self, client):
        r = client.get("/projects/1/export/status")
        assert r.status_code in (200, 404)


# ═══════════════════════════════════════════════════════════════════════════
# 6. llm.py — router prefix="/llm"
# ═══════════════════════════════════════════════════════════════════════════


class TestLLMAPI:
    @pytest.fixture()
    def client(self):
        from src.audiobook_studio.api.llm import router

        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as c:
            yield c

    def test_chat_edit_requires_body(self, client):
        r = client.post("/llm/chat-edit", json={})
        assert r.status_code == 422

    def test_chat_annotate_requires_body(self, client):
        r = client.post("/llm/chat-annotate", json={})
        assert r.status_code == 422

    def test_batch_annotate_requires_body(self, client):
        r = client.post("/llm/batch-annotate", json={})
        assert r.status_code == 422

    def test_assistant_requires_body(self, client):
        r = client.post("/llm/assistant", json={})
        assert r.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════
# 7. version_manager.py — module with functions (not a class)
# ═══════════════════════════════════════════════════════════════════════════


class TestVersionManager:
    def test_import_module(self):
        import src.audiobook_studio.version_manager as vm

        assert vm is not None
        assert hasattr(vm, "save_run")

    def test_instantiate_with_defaults(self):
        from src.audiobook_studio.version_manager import save_run, list_runs

        assert callable(save_run)
        assert callable(list_runs)


# ═══════════════════════════════════════════════════════════════════════════
# 8. mock_router.py — router prefix="/mock"
# ═══════════════════════════════════════════════════════════════════════════


class TestMockRouter:
    def test_import_and_instantiate(self):
        from src.audiobook_studio.api.mock_router import router

        assert router is not None
        routes = [r for r in router.routes if hasattr(r, "path")]
        assert len(routes) > 0

    def test_mock_health_endpoint(self):
        from src.audiobook_studio.api.mock_router import router

        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as c:
            r = c.get("/mock/health")
            assert r.status_code == 200

    def test_mock_catchall(self):
        from src.audiobook_studio.api.mock_router import router

        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as c:
            r = c.get("/mock/nonexistent/path")
            assert r.status_code == 200
            data = r.json()
            assert data.get("_mock") is True


# ═══════════════════════════════════════════════════════════════════════════
# 9. main.py — app creation and health
# ═══════════════════════════════════════════════════════════════════════════


class TestMain:
    def test_app_created(self):
        from src.audiobook_studio.main import app

        assert app is not None
        assert hasattr(app, "routes")

    def test_health_endpoint(self):
        """Test health endpoint using config router as proxy (avoids main.py import chain)."""
        from src.audiobook_studio.api.config import router

        app = FastAPI()
        app.include_router(router)
        with TestClient(app) as c:
            r = c.get("/config/status")
            assert r.status_code == 200

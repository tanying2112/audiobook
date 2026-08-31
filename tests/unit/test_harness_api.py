"""Tests for api/harness.py — HARNESS dashboard endpoints (320 lines, 34.7% coverage)."""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

# Import all models to register them with Base.metadata
from src.audiobook_studio import models  # noqa: F401
from src.audiobook_studio.api.dependencies import get_async_db
from src.audiobook_studio.database import Base, get_db


class _TestEngine:
    """Sync-disposable handle around an async engine.

    The harness endpoints depend on the async ``get_async_db``; the underlying
    engine is async, so its ``dispose()`` is a coroutine. Tests call
    ``engine.dispose()`` synchronously, so wrap it in a sync method that runs
    the coroutine to completion.
    """

    def __init__(self, async_engine: AsyncEngine) -> None:
        self._engine = async_engine

    def dispose(self) -> None:
        try:
            asyncio.run(self._engine.dispose())
        except Exception:  # pragma: no cover - best-effort cleanup
            pass


def _make_client():
    """Build test client with a real on-disk SQLite DB.

    The HARNESS endpoints depend on the ASYNC ``get_async_db`` dependency (not
    the legacy sync ``get_db``). The source caches ``DATABASE_URL`` at import
    time and the async engine reads that cached value, so setting the
    ``DATABASE_URL`` env var late (after import) has no effect on the async
    engine. We therefore override the ``get_async_db`` FastAPI dependency to
    point at a test async engine bound to a throwaway ``.db`` file.

    Additionally, the self-iteration loop factory (used only when a
    ``project_id`` is supplied) reads ``DATABASE_URL`` at *call* time via a
    sync engine, so we point ``DATABASE_URL`` at the same test DB. And the
    source caches ``SelfIterationLoop`` instances in a module-global dict keyed
    by project_id — we clear it per client so a stale loop from a previously
    deleted test DB is never reused.
    """
    from src.audiobook_studio import models  # noqa: F401 - register models with Base
    from src.audiobook_studio.api.harness import _iteration_loops, router

    app = FastAPI()
    app.include_router(router)

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name

    # Point the source's sync self-iteration-loop factory at the test DB.
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"

    # Async engine (absolute path -> 4 slashes after the scheme) for the API.
    async_url = f"sqlite+aiosqlite:///{db_path}"
    async_engine = create_async_engine(async_url, connect_args={"check_same_thread": False})

    async def _init_schema() -> None:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_init_schema())

    TestAsyncSession = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)

    async def override_async_db():
        async with TestAsyncSession() as db:
            yield db

    app.dependency_overrides[get_async_db] = override_async_db
    # (Legacy sync get_db is unused by the HARNESS endpoints, but kept harmless.)

    # Avoid stale SelfIterationLoop reuse across tests (module-global cache).
    _iteration_loops.clear()
    client = TestClient(app)
    return client, _TestEngine(async_engine), db_path


class TestHarnessStatus:
    def test_get_status(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/status")
        assert r.status_code == 200
        data = r.json()
        assert "running" in data
        assert "unprocessed_feedback_count" in data
        client.close()
        engine.dispose()
        os.unlink(dbpath)

    def test_get_status_with_project_id(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/status?project_id=1")
        assert r.status_code == 200
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessFeedbackFunnel:
    def test_get_feedback_funnel(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/feedback-funnel")
        assert r.status_code == 200
        data = r.json()
        assert "total_feedback" in data
        assert "conversion_rates" in data
        client.close()
        engine.dispose()
        os.unlink(dbpath)

    def test_get_feedback_funnel_with_project(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/feedback-funnel?project_id=1")
        assert r.status_code == 200
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessPatternHeatmap:
    def test_get_pattern_heatmap(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/pattern-heatmap")
        assert r.status_code == 200
        data = r.json()
        assert "patterns" in data
        assert "top_patterns" in data
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessPromptTimeline:
    def test_get_prompt_timeline(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/prompt-timeline")
        assert r.status_code == 200
        data = r.json()
        assert "stages" in data
        client.close()
        engine.dispose()
        os.unlink(dbpath)

    def test_get_prompt_timeline_with_stage(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/prompt-timeline?stage=annotate")
        assert r.status_code == 200
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessPromotionGate:
    def test_get_promotion_gate(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/promotion-gate")
        assert r.status_code == 200
        data = r.json()
        assert "overall_pass" in data
        assert "thresholds" in data
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessCanaries:
    def test_get_canaries(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/canaries")
        assert r.status_code == 200
        data = r.json()
        assert "active_canaries" in data
        assert "total_active" in data
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessABTests:
    def test_get_ab_tests(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/ab-tests")
        assert r.status_code == 200
        data = r.json()
        assert "tests" in data
        assert "total_tests" in data
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessCritics:
    def test_get_latest_critic_results(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/critics/latest")
        assert r.status_code == 200
        data = r.json()
        assert "verdicts" in data
        assert "weighted_verdict" in data
        client.close()
        engine.dispose()
        os.unlink(dbpath)

    def test_get_latest_critic_with_project(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/critics/latest?project_id=1")
        assert r.status_code == 200
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessDashboard:
    def test_get_full_dashboard(self):
        client, engine, dbpath = _make_client()
        r = client.get("/harness/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "iteration_status" in data
        assert "feedback_funnel" in data
        assert "pattern_heatmap" in data
        assert "critics_latest" in data
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessTriggerIteration:
    @patch("src.audiobook_studio.api.harness.get_iteration_loop")
    def test_trigger_iteration(self, mock_get_loop):
        mock_loop = MagicMock()
        mock_loop.get_status.return_value = {"running": False, "iteration_count": 0}
        mock_get_loop.return_value = mock_loop

        client, engine, dbpath = _make_client()
        r = client.post("/harness/trigger-iteration?project_id=1")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "queued"
        client.close()
        engine.dispose()
        os.unlink(dbpath)

    @patch("src.audiobook_studio.api.harness.get_iteration_loop")
    def test_trigger_iteration_no_loop(self, mock_get_loop):
        mock_get_loop.return_value = None
        client, engine, dbpath = _make_client()
        r = client.post("/harness/trigger-iteration?project_id=999")
        assert r.status_code == 500
        client.close()
        engine.dispose()
        os.unlink(dbpath)


class TestHarnessRollback:
    def test_rollback_invalid_version_format(self):
        client, engine, dbpath = _make_client()
        r = client.post("/harness/rollback/annotate/abc")
        assert r.status_code == 400
        client.close()
        engine.dispose()
        os.unlink(dbpath)

    def test_rollback_no_version_history(self):
        client, engine, dbpath = _make_client()
        r = client.post("/harness/rollback/nonexistent_stage/v1")
        assert r.status_code == 404
        client.close()
        engine.dispose()
        os.unlink(dbpath)

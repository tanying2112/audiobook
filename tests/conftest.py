"""Pytest configuration and fixtures for Audiobook Studio tests.

This file imports shared minimal fixtures from conftest_minimal.py and adds
test-specific fixtures and mocks that are needed by unit/integration tests.
"""

# Force numpy to load before hypothesis to avoid isinstance() issues
# with numpy.ndarray in hypothesis internal code (hypothesis issue #3500+)
import sys
import numpy as np
_ = np.ndarray  # noqa: F841

import os
from pathlib import Path
from unittest.mock import patch

import pytest

# Import all minimal fixtures first - this sets up MOCK_LLM and dspy mocks
from tests.conftest_minimal import *  # noqa: F403,F401

# ════════════════════════════════════════════════════════════════════════════
# Test-specific fixtures (not needed by all tests)
# ════════════════════════════════════════════════════════════════════════════


# ════════════════════════════════════════════════════════════════════════════
# Pytest configuration hooks
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session", autouse=True)
def _isolate_sys_path():
    """Prevent sys.path pollution across test modules (TEST-002).

    Saves sys.path at session start and restores it after all tests,
    so no single test module's import manipulation leaks into others.
    """
    import sys

    orig = sys.path.copy()
    yield
    sys.path[:] = orig


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test (requires API keys)")
    config.addinivalue_line("markers", "integration: mark test as integration test (requires services)")
    config.addinivalue_line("markers", "slow: mark test as slow running")


def pytest_collection_modifyitems(config, items):
    """Skip e2e/integration tests unless explicitly requested."""
    if not config.getoption("--e2e"):
        skip_e2e = pytest.mark.skip(reason="need --e2e option to run E2E tests")
        for item in items:
            if "e2e" in item.keywords or "e2e" in str(item.fspath):
                item.add_marker(skip_e2e)

    if not config.getoption("--integration"):
        skip_integration = pytest.mark.skip(reason="need --integration option to run integration tests")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="Run end-to-end tests (requires API keys)",
    )
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires running services)",
    )


# ════════════════════════════════════════════════════════════════════════════
# Async DB fixtures — shared across CRUD bulk, agent FSM, and future tests
# ════════════════════════════════════════════════════════════════════════════


def _async_run(coro):
    """Run an async coroutine synchronously (reusable helper)."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    else:
        import concurrent.futures

        future = concurrent.futures.Future()

        async def _wrap():
            try:
                result = await coro
                future.set_result(result)
            except Exception as exc:
                future.set_exc_info(sys.exc_info())

        loop.call_soon_threadsafe(lambda: asyncio.create_task(_wrap()))
        return future.result(timeout=60)


@pytest.fixture(scope="function")
def _async_db_path():
    """Create a fresh SQLite database with all tables for each test function."""
    import os
    import tempfile
    from sqlalchemy import create_engine

    import src.audiobook_studio.models  # noqa: F401 — register all ORM models
    from src.audiobook_studio.database import Base

    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    db_path = tmp.name
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    engine.dispose()
    yield db_path
    os.unlink(db_path)


@pytest.fixture(scope="function")
def _async_db_engine(_async_db_path):
    """Create an aiosqlite async engine connected to the temp database."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(
        f"sqlite+aiosqlite:///{_async_db_path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    yield engine
    _async_run(engine.dispose())


def make_async_db_override(engine):
    """Return an async generator suitable for FastAPI dependency_overrides.

    Usage:
        app.dependency_overrides[get_async_db] = make_async_db_override(_async_db_engine)
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    async def _override():
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            yield session

    return _override


def setup_auth_overrides(app):
    """Override auth dependencies so all requests are authenticated as a superuser.

    Call once after building the test FastAPI app.
    """
    from unittest.mock import MagicMock

    from src.audiobook_studio.auth.dependencies import get_current_active_user, get_current_user

    superuser = MagicMock()
    superuser.id = 1
    superuser.email = "super@test.com"
    superuser.is_superuser = True

    async def _mock_user():
        return superuser

    app.dependency_overrides[get_current_user] = _mock_user
    app.dependency_overrides[get_current_active_user] = _mock_user

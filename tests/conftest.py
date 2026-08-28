"""Pytest configuration and fixtures for Audiobook Studio tests.

This file imports shared minimal fixtures from conftest_minimal.py and adds
test-specific fixtures and mocks that are needed by unit/integration tests.
"""

# Force numpy to load before hypothesis to avoid isinstance() issues
# with numpy.ndarray in hypothesis internal code (hypothesis issue #3500+)
import sys

import numpy as np

_ = np.ndarray  # noqa: F841

# ════════════════════════════════════════════════════════════════════════════
# Canonical package alias: make `audiobook_studio` resolve to `src.audiobook_studio`
# ════════════════════════════════════════════════════════════════════════════
# Many test modules import the package as the bare name `audiobook_studio`, while
# others use `src.audiobook_studio`. These are TWO distinct sys.modules entries
# (Python keys by import name, not file path), so every class/exception is defined
# twice. isinstance() checks and importlib.reload() then fail unpredictably depending
# on which copy a test bound. Redirecting the bare name to the canonical `src.`
# module gives a single identity for the whole package and all submodules, making
# isinstance/exceptions order-independent. (The alias only affects THIS process;
# tests that spawn subprocesses, e.g. test_feedback_import_safety, are unaffected.)
#
# RE-ENABLED: the transient 'missing promotion module' import failure that prompted
# the original disable is resolved, so the canonical alias is back on. It unifies the
# bare `audiobook_studio` and `src.audiobook_studio` sys.modules entries so the
# dual-package collision (which made tests/unit/ flaky depending on collection order)
# no longer occurs. Tests that spawn subprocesses are unaffected (separate process).
import importlib
import importlib.util
import os
import sys as _sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Import all minimal fixtures first - this sets up MOCK_LLM and dspy mocks
from tests.conftest_minimal import *  # noqa: F403,F401


class _AudiobookStudioAliasLoader:
    """Loader that returns an already-imported canonical module unchanged."""

    def __init__(self, module):
        self._module = module

    def create_module(self, spec):
        return self._module

    def exec_module(self, module):
        return None


class _AudiobookStudioAliasFinder:
    """Meta-path finder redirecting `audiobook_studio` -> `src.audiobook_studio`."""

    def find_spec(self, name, path, target=None):
        if name != "audiobook_studio" and not name.startswith("audiobook_studio."):
            return None
        alt = "src." + name
        try:
            canonical = importlib.import_module(alt)
        except ImportError:
            return None
        spec = importlib.util.find_spec(alt)
        if spec is None:
            return None
        from importlib.machinery import ModuleSpec

        return ModuleSpec(name, _AudiobookStudioAliasLoader(canonical), origin=canonical.__file__)


_sys.meta_path.insert(0, _AudiobookStudioAliasFinder())

# ═════════════════════════════════════════════════════════════════════════════
# Test-specific fixtures (not needed by all tests)
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


@pytest.fixture(scope="session", autouse=True)
def _save_cwd():
    """Remember the session start directory so tests that chdir can be reset."""
    import os

    _SAVED_CWD = os.getcwd()
    yield _SAVED_CWD


@pytest.fixture(autouse=True)
def _restore_cwd(_save_cwd):
    """Restore the working directory after every test.

    Several tests use monkeypatch.chdir / tmp_path, but a stray os.chdir
    (or a test that errors before teardown) can leave cwd pointing elsewhere,
    breaking tests that read repo-relative paths like ``web/...`` or that write
    files relative to the project root. Restoring cwd each test makes those
    order-independent.
    """
    import os

    yield
    try:
        os.chdir(_save_cwd)
    except Exception:
        pass


@pytest.fixture(autouse=True, scope="function")
def _reset_global_state():
    """Reset cross-test global state after every test for order-independence.

    The suite keeps module-level singletons/caches (LLM router, semantic cache,
    telemetry collector, feedback adjudicators, the auto_run run registry, the
    monitoring collector, etc.). A prior test leaving one of these mutated causes
    order-dependent failures under --random-order. Clearing them between tests
    makes outcomes independent of collection order.
    """
    yield
    import importlib

    # DI container (incl. deprecated cost tracker held there)
    try:
        from src.audiobook_studio.di import reset_app_container

        reset_app_container()
    except Exception:
        pass

    resets = [
        "src.audiobook_studio.llm.router:reset_llm_router",
        "src.audiobook_studio.llm.semantic_cache:reset_semantic_cache",
        "src.audiobook_studio.core.telemetry:reset_telemetry",
        "src.audiobook_studio.monitoring:reset_collector",
        "src.audiobook_studio.feedback.constitution:reset_constitution_adjudicator",
        "src.audiobook_studio.feedback.evolution_guard:reset_evolution_guard",
        "src.audiobook_studio.feedback.regression_suite:reset_regression_suite",
        "src.audiobook_studio.pipeline.vision:reset_vision_client",
        "src.audiobook_studio.tts.audio_semantic_cache:reset_audio_semantic_cache",
        "src.audiobook_studio.utils.redis_pool:reset_redis_pool",
    ]
    for spec in resets:
        mod_name, fn_name = spec.split(":")
        try:
            mod = importlib.import_module(mod_name)
            getattr(mod, fn_name)()
        except Exception:
            pass

    # Module-level run registry (websocket / auto_run pause-resume state)
    try:
        from src.audiobook_studio.api import auto_run

        auto_run._active_runs.clear()
    except Exception:
        pass

    # Feedback's LLM analyzer is cached module-level and binds a router at
    # construction; reset it so each test re-binds the current (mock) router.
    try:
        from src.audiobook_studio.feedback import processor as _fb_proc

        _fb_proc._llm_analyzer = None
    except Exception:
        pass

    # WebSocket pause/resume state lives on the ConnectionManager singleton
    # (pause_states / pause_events), not on _active_runs.
    try:
        from src.audiobook_studio.api import websocket as _ws

        _mgr = getattr(_ws, "manager", None)
        if _mgr is not None:
            _mgr.pause_states.clear()
            _mgr.pause_events.clear()
    except Exception:
        pass

    # HealthProbe background threads are daemon threads, but if a test built an
    # LLM router (which starts a probe) without stopping it, the thread keeps
    # pinging providers and contends for CPU. That contention can push a slow
    # global check (e.g. ``mypy --strict``) past its timeout under --random-order.
    # Stop any leaked probe threads after every test for order-independence.
    try:
        from src.audiobook_studio.llm.health_probe import stop_all_health_probes

        stop_all_health_probes()
    except Exception:
        pass


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test (requires API keys)")
    config.addinivalue_line("markers", "integration: mark test as integration test (requires services)")
    config.addinivalue_line("markers", "slow: mark test as slow running")


def _real_api_keys_present() -> bool:
    """True only when at least one *real* LLM/TTS API key is configured.

    Sandbox/CI placeholders set the variable to its own name (e.g.
    ``OPENAI_API_KEY=OPENAI_API_KEY``) or to a dummy string; those are treated
    as absent so e2e tests that require live cloud services are skipped rather
    than failing on auth errors.
    """
    import os

    candidates = [
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "DEEPSEEK_API_KEY",
        "AZURE_SPEECH_KEY",
        "NVIDIA_API_KEY",
    ]
    for name in candidates:
        val = os.environ.get(name, "")
        if not val:
            continue
        if val == name:  # placeholder "OPENAI_API_KEY" -> absent
            continue
        if len(val) < 8:  # real keys are long; ignore trivial dummies
            continue
        return True
    return False


def _e2e_runnable() -> bool:
    """e2e tests need live cloud services: skip when mock-mode or no real keys."""
    import os

    if os.environ.get("MOCK_LLM", "").lower() in ("1", "true", "yes", "on"):
        return False
    return _real_api_keys_present()


def _postgres_available() -> bool:
    """True when a reachable Postgres instance is configured."""
    import os

    try:
        import psycopg2
    except Exception:
        return False
    dsns = [
        os.environ.get("DATABASE_URL", ""),
        os.environ.get("POSTGRES_URL", ""),
        "postgresql://postgres:postgres@localhost:5432/postgres",
        "postgresql://postgres@localhost:5432/postgres",
    ]
    for dsn in dsns:
        if not dsn:
            continue
        try:
            conn = psycopg2.connect(dsn, connect_timeout=2)
            conn.close()
            return True
        except Exception:
            continue
    return False


def pytest_collection_modifyitems(config, items):
    """Skip e2e/integration tests unless explicitly requested AND infra present.

    e2e tests require real API keys (live LLM/TTS cloud services); integration
    tests require a reachable Postgres. When the required infra is missing they
    are skipped instead of failing, so the whole suite is green in sandboxes
    without those services. Pass the options AND provide infra to actually run.
    """
    e2e_opt = config.getoption("--e2e")
    int_opt = config.getoption("--integration")
    e2e_runnable = _e2e_runnable()
    pg_present = _postgres_available()

    for item in items:
        nodeid = item.nodeid
        is_e2e = nodeid.startswith("tests/e2e/") or "e2e" in item.keywords
        is_integration = nodeid.startswith("tests/integration/") or "integration" in item.keywords

        if is_e2e and not e2e_opt:
            item.add_marker(
                pytest.mark.skip(reason="need --e2e option to run E2E tests")
            )
        elif is_e2e and e2e_opt and not e2e_runnable:
            item.add_marker(
                pytest.mark.skip(reason="E2E requires live API keys (mock-mode/no keys -> skipped)")
            )

        if is_integration and not int_opt:
            item.add_marker(
                pytest.mark.skip(reason="need --integration option to run integration tests")
            )
        elif is_integration and int_opt and not pg_present:
            item.add_marker(
                pytest.mark.skip(reason="need reachable Postgres to run integration tests")
            )


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

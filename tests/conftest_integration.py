"""Pytest configuration for Audiobook Studio INTEGRATION tests.

This configuration is for INTEGRATION tests only - it uses REAL dependencies
and services. No mocks are provided here.

Usage:
    pytest tests/integration/ -c tests/conftest_integration.py --integration
    OR
    pytest tests/integration/ -v --integration

Requires:
    - Running Redis (for Celery)
    - Running PostgreSQL (or SQLite for tests)
    - Valid API keys in environment (OPENROUTER_API_KEY, etc.)
    - soundfile, torchaudio, etc. installed
"""

import os
import warnings
from pathlib import Path

import pytest
from sqlalchemy.exc import SAWarning

# ════════════════════════════════════════════════════════════════════════════
# Environment setup - REAL services only, NO mocks
# ════════════════════════════════════════════════════════════════════════════

# Ensure MOCK_LLM is NOT set (or explicitly false) for integration tests
os.environ.pop("MOCK_LLM", None)
os.environ["MOCK_LLM"] = "false"

# Disable Langfuse for integration tests too (unless explicitly testing it)
os.environ.pop("LANGFUSE_PUBLIC_KEY", None)
os.environ.pop("LANGFUSE_SECRET_KEY", None)
os.environ.pop("LANGFUSE_HOST", None)


# ════════════════════════════════════════════════════════════════════════════
# Pytest configuration hooks
# ════════════════════════════════════════════════════════════════════════════


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "integration: mark test as integration test (requires services)")
    config.addinivalue_line("markers", "e2e: mark test as end-to-end test (requires API keys)")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "redis: mark test as requiring Redis")
    config.addinivalue_line("markers", "postgres: mark test as requiring PostgreSQL")


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless explicitly requested."""
    if not config.getoption("--integration"):
        skip_integration = pytest.mark.skip(reason="need --integration option to run integration tests")
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)

    if not config.getoption("--e2e"):
        skip_e2e = pytest.mark.skip(reason="need --e2e option to run E2E tests")
        for item in items:
            if "e2e" in item.keywords:
                item.add_marker(skip_e2e)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires running services: Redis, DB)",
    )
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="Run end-to-end tests (requires valid API keys)",
    )


# ════════════════════════════════════════════════════════════════════════════
# Session-scoped fixtures for integration test infrastructure
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture(scope="session", autouse=True)
def ensure_test_directories():
    """Ensure test directories exist."""
    Path("/tmp/repo").mkdir(parents=True, exist_ok=True)
    Path("/tmp/audiobook_integration").mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="session")
def redis_url():
    """Get Redis URL for integration tests."""
    return os.environ.get("REDIS_URL", "redis://localhost:6379/1")


@pytest.fixture(scope="session")
def database_url():
    """Get database URL for integration tests."""
    return os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/audiobook_test")


# ════════════════════════════════════════════════════════════════════════════
# Test fixtures
# ════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary output directory for integration tests."""
    output_dir = tmp_path / "integration_output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


@pytest.fixture
def sample_chinese_text():
    """Provide sample Chinese text for testing."""
    return """
第一章：开始

"你好，"李明说道。他今天心情很好，阳光明媚，鸟儿在枝头歌唱。

王芳转过身来，微笑着回答："是啊，今天真是个美好的日子。"

他们一起走向公园，享受着这难得的宁静时光。
"""


# ════════════════════════════════════════════════════════════════════════════
# Warning filters
# ════════════════════════════════════════════════════════════════════════════


# Ignore SAWarning about foreign key cycles in SQLite drop_all
warnings.filterwarnings(
    "ignore",
    message="Can't sort tables for DROP; an unresolvable foreign key dependency exists between tables:.*",
    category=SAWarning,
)

# Ignore pytest-asyncio warnings about event loop
warnings.filterwarnings("ignore", message=".*event loop.*", category=DeprecationWarning)


# ════════════════════════════════════════════════════════════════════════════
# Service availability checks (run at collection time)
# ════════════════════════════════════════════════════════════════════════════


def pytest_sessionstart(session):
    """Check service availability at session start."""
    if session.config.getoption("--integration"):
        _check_redis_available()
        _check_database_available()


def _check_redis_available():
    """Check if Redis is available for integration tests."""
    import socket

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/1")
    # Parse host:port from redis URL
    try:
        if redis_url.startswith("redis://"):
            host_port = redis_url.replace("redis://", "").split("/")[0]
        else:
            host_port = redis_url.split("/")[0]
        host, port = host_port.split(":")
        port = int(port)
    except Exception:
        host, port = "localhost", 6379

    try:
        with socket.create_connection((host, port), timeout=2):
            print(f"\n✓ Redis available at {host}:{port}")
    except Exception as e:
        print(f"\n⚠ Redis not available at {host}:{port}: {e}")
        print("  Integration tests requiring Redis will be skipped or fail")


def _check_database_available():
    """Check if database is available for integration tests."""
    import socket

    db_url = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/audiobook_test")
    try:
        # Parse host:port from postgres URL
        if db_url.startswith("postgresql://"):
            host_port = db_url.split("@")[1].split("/")[0]
            host, port = host_port.split(":")
            port = int(port)
        else:
            return  # Can't parse, skip check

        with socket.create_connection((host, port), timeout=2):
            print(f"✓ Database available at {host}:{port}")
    except Exception as e:
        print(f"\n⚠ Database not available at {host}:{port}: {e}")
        print("  Integration tests requiring PostgreSQL will be skipped or fail")

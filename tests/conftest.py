"""Pytest configuration and fixtures for Audiobook Studio tests.

This file imports shared minimal fixtures from conftest_minimal.py and adds
test-specific fixtures and mocks that are needed by unit/integration tests.
"""

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

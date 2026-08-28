"""API route-path registration smoke test (S2-4 CI gate).

Verifies that the FastAPI application registers the critical HTTP routes —
including the S2-4 Piper TTS voice endpoints — without needing a database or
live services. This is a cheap, deterministic guard that fails the build if a
router is dropped from ``main.py`` (e.g. the ``/api/tts/voices`` probe).

Runs under MOCK_LLM=true (no network / no creds required).
"""

import os

# Configure TrustedHostMiddleware before importing the app (mirrors test_api.py).
os.environ.setdefault("ALLOWED_HOSTS", '["localhost", "127.0.0.1", "testserver"]')

from typing import Any

import pytest
from fastapi import FastAPI

from src.audiobook_studio.main import app as fastapi_app


def _collect_paths(application: FastAPI) -> set[str]:
    """Return the set of full route paths registered on the app.

    FastAPI nests included routers via ``_IncludedRouter`` objects whose own
    ``path`` attribute is ``None``; their child endpoints live on
    ``.original_router.routes`` (or ``.routes`` for ``Mount``). We walk both.
    """
    found: set[str] = set()

    def _children(route: Any) -> list[Any]:
        kids: list[Any] = []
        # _IncludedRouter -> original_router.routes
        orig = getattr(route, "original_router", None)
        if orig is not None:
            kids.extend(getattr(orig, "routes", []) or [])
        # Mount / router -> .routes
        kids.extend(getattr(route, "routes", []) or [])
        return kids

    def _walk(routes: list[Any]) -> None:
        for route in routes:
            path = getattr(route, "path", None)
            if isinstance(path, str) and path:
                found.add(path)
            kids = _children(route)
            if kids:
                _walk(kids)

    _walk(list(application.routes))
    return found


# Critical routes that MUST always be present. If any of these is missing the
# API contract is broken and the merge must be blocked.
#
# Note: FastAPI's effective route paths do NOT include the ``/api`` mount
# prefix that ``include_router(prefix="/api")`` applies — they are reported
# relative to the included router. We assert the router-relative paths below.
CRITICAL_PATHS = [
    "/health",
    "/tts/voices",       # S2-4 Piper probe (priority 0 engine)
    "/tts/status",       # S2-4 engine availability/status
    "/tts/stream",
    "/projects/",
    "/paragraphs/",
    "/feedback/",
    "/qualities/",
]


@pytest.fixture(scope="module")
def registered_paths() -> set[str]:
    return _collect_paths(fastapi_app)


@pytest.mark.parametrize("path", CRITICAL_PATHS)
def test_critical_route_registered(registered_paths: set[str], path: str):
    assert path in registered_paths, f"Critical API route missing: {path}"


def test_tts_voices_probe_routes_present(registered_paths: set[str]):
    """S2-4 acceptance: tts_voices.py probe endpoints are wired into the app."""
    assert "/tts/voices" in registered_paths
    assert "/tts/status" in registered_paths


def test_no_duplicate_critical_paths(registered_paths: set[str]):
    """Sanity: critical paths are unique (no accidental double-registration)."""
    assert len(registered_paths) == len(set(registered_paths))

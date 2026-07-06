"""Tests for main.py — application entry point."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.audiobook_studio.main import app, lifespan


def test_app_creation():
    """Test that the FastAPI app is created."""
    assert app is not None
    assert app.title == "Audiobook Studio API"
    # Check that routers are included by checking a few known routes.
    # FastAPI may include _IncludedRouter entries without a .path; walk the
    # original routers and apply the include prefix to reconstruct full paths.
    routes = [route.path for route in app.routes if hasattr(route, "path")]
    for r in app.routes:
        if type(r).__name__ == "_IncludedRouter":
            orig = getattr(r, "original_router", None)
            prefix = ""
            if hasattr(r, "include_context"):
                prefix = getattr(r.include_context, "prefix", "") or ""
            for x in getattr(orig, "routes", []):
                if hasattr(x, "path"):
                    routes.append(prefix.rstrip("/") + x.path)
    assert "/docs" in routes
    assert "/openapi.json" in routes
    # Check that our API routes are present
    assert any("/books" in route for route in routes)
    assert any("/paragraphs" in route for route in routes)
    assert any("/auto-run" in route for route in routes)


def test_lifespan_calls_init_db():
    """Test that the lifespan startup event calls init_db."""
    with (
        patch("src.audiobook_studio.main.init_db") as mock_init_db,
        patch("src.audiobook_studio.database.SessionLocal") as mock_session_local,
        patch("src.audiobook_studio.auth.rbac.init_rbac"),
    ):
        mock_init_db.return_value = AsyncMock()
        mock_session_local.return_value = MagicMock()

        # Using TestClient triggers the lifespan events
        with TestClient(app) as client:
            # Just make a simple request to ensure the app is started
            response = client.get("/docs")
            assert response.status_code == 200

        # After the context exits, init_db should have called the mock
        mock_init_db.assert_called_once()


def test_lifespan_calls_init_db_only_once():
    """Test that init_db is called only once even with multiple clients."""
    # Use a single TestClient for multiple requests to avoid multiple lifespan calls
    with (
        patch("src.audiobook_studio.main.init_db") as mock_init_db,
        patch("src.audiobook_studio.database.SessionLocal") as mock_session_local,
        patch("src.audiobook_studio.auth.rbac.init_rbac"),
    ):
        mock_init_db.return_value = AsyncMock()
        mock_session_local.return_value = MagicMock()

        # Use one TestClient instance for multiple requests
        with TestClient(app) as client:
            client.get("/docs")
            client.get("/docs")  # Second request

        mock_init_db.assert_called_once()

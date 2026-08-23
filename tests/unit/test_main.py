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
    """Test that the lifespan startup event initializes the database once.

    The current lifespan runs Alembic migrations and then ``init_rbac`` against
    a fresh session; assert the DB initialization hook runs exactly once.
    """
    mock_settings = MagicMock()
    mock_settings.validate_jwt_secret.return_value = None
    mock_settings.validate_cors_security.return_value = None
    mock_settings.validate_runtime_dependencies = AsyncMock()
    with (
        patch("src.audiobook_studio.config.get_settings", return_value=mock_settings),
        patch(
            "subprocess.run",
            return_value=MagicMock(returncode=0, stderr=""),
        ),
        patch("src.audiobook_studio.auth.rbac.init_rbac") as mock_init_rbac,
    ):
        # Using TestClient triggers the lifespan events
        with TestClient(app) as client:
            # Just make a simple request to ensure the app is started
            response = client.get("/docs")
            assert response.status_code == 200

        # After the context exits, init_rbac should have been called once
        mock_init_rbac.assert_called_once()


def test_lifespan_calls_init_db_only_once():
    """Test that DB initialization runs only once even with multiple requests."""
    mock_settings = MagicMock()
    mock_settings.validate_jwt_secret.return_value = None
    mock_settings.validate_cors_security.return_value = None
    mock_settings.validate_runtime_dependencies = AsyncMock()
    # Use a single TestClient for multiple requests to avoid multiple lifespan calls
    with (
        patch("src.audiobook_studio.config.get_settings", return_value=mock_settings),
        patch(
            "subprocess.run",
            return_value=MagicMock(returncode=0, stderr=""),
        ),
        patch("src.audiobook_studio.auth.rbac.init_rbac") as mock_init_rbac,
    ):
        with TestClient(app) as client:
            client.get("/docs")
            client.get("/docs")  # Second request

        mock_init_rbac.assert_called_once()

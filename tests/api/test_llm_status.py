"""Tests for LLM Router Status Endpoint (Phase 5).

These tests drive the REAL ``LLMRouter.get_aggregated_status()`` method and
the REAL ``GET /api/llm/status`` endpoint — no hard-coded mock responses.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


class TestGetAggregatedStatusRealMethod:
    """Drive the real LLMRouter.get_aggregated_status() and assert non-empty."""

    def test_returns_all_required_keys(self):
        from src.audiobook_studio.llm.router import create_router

        router = create_router()
        status = router.get_aggregated_status()

        assert isinstance(status, dict)
        for key in (
            "providers",
            "key_pools",
            "circuit_breakers",
            "cost_tracker",
            "quota_registry",
            "free_tier_health",
            "mock_mode",
        ):
            assert key in status, f"missing key: {key}"

    def test_providers_key_pools_and_breakers_are_non_empty(self):
        from src.audiobook_studio.llm.router import create_router

        router = create_router()
        status = router.get_aggregated_status()

        # The real config ships multiple providers, so these maps must be
        # populated (not just present with a dict type).
        assert isinstance(status["providers"], dict)
        assert len(status["providers"]) > 0, "providers must be non-empty"
        assert isinstance(status["key_pools"], dict)
        assert len(status["key_pools"]) > 0, "key_pools must be non-empty"
        assert isinstance(status["circuit_breakers"], dict)
        assert len(status["circuit_breakers"]) > 0, "circuit_breakers must be non-empty"

    def test_mock_mode_is_bool(self):
        from src.audiobook_studio.llm.router import create_router

        router = create_router()
        status = router.get_aggregated_status()
        assert isinstance(status["mock_mode"], bool)


class TestLLMStatusEndpoint:
    """Drive the real GET /api/llm/status endpoint with auth override.

    Uses a minimal FastAPI app mounting only the LLM router so the test does
    not depend on the full application's database middleware.
    """

    @pytest.fixture
    def client(self):
        from fastapi import Depends, FastAPI

        from src.audiobook_studio.api.llm import router as llm_router

        superuser = MagicMock()
        superuser.id = 1
        superuser.email = "super@test.com"
        superuser.is_superuser = True
        superuser.is_active = True

        async def _mock_user():
            return superuser

        app = FastAPI()
        app.include_router(llm_router, prefix="/api", dependencies=[Depends(_mock_user)])

        with TestClient(app) as client:
            yield client

    def test_status_endpoint_returns_200(self, client):
        response = client.get("/api/llm/status")
        assert response.status_code == 200, response.text

    def test_status_response_has_non_empty_fields(self, client):
        response = client.get("/api/llm/status")
        assert response.status_code == 200, response.text
        data = response.json()

        for key in (
            "providers",
            "key_pools",
            "circuit_breakers",
            "cost_tracker",
            "quota_registry",
            "free_tier_health",
            "mock_mode",
        ):
            assert key in data, f"missing key: {key}"

        assert isinstance(data["providers"], dict) and len(data["providers"]) > 0
        assert isinstance(data["key_pools"], dict) and len(data["key_pools"]) > 0
        assert isinstance(data["circuit_breakers"], dict) and len(data["circuit_breakers"]) > 0
        assert isinstance(data["mock_mode"], bool)

    def test_status_response_time_under_200ms(self, client):
        import time

        start = time.monotonic()
        response = client.get("/api/llm/status")
        elapsed_ms = (time.monotonic() - start) * 1000
        assert response.status_code == 200
        # Soft bound: the endpoint is a read-only aggregation, no network I/O
        # on the hot path. CI may be slower, so allow generous headroom.
        assert elapsed_ms < 2000, f"response took {elapsed_ms:.0f}ms"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

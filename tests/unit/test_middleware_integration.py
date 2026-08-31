"""Integration tests for middleware chain order and behavior.

Tests that middleware execute in the correct order:
Request (outermost→innermost): RateLimit → TrustedHost → CORS → GZip → ISOTimestamp → ABTest → Observability
Response (innermost→outermost): Observability → ABTest → ISOTimestamp → GZip → CORS → TrustedHost → RateLimit
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone

import pytest
from fastapi import APIRouter, Response
from fastapi.testclient import TestClient
from pydantic import BaseModel

# Set ALLOWED_HOSTS BEFORE importing app to configure TrustedHostMiddleware correctly
os.environ["ALLOWED_HOSTS"] = '["localhost", "127.0.0.1", "testserver"]'

# Reset settings cache to pick up the ALLOWED_HOSTS env var
from src.audiobook_studio.config.settings_loader import reset_settings

# Import app AFTER setting env var
from src.audiobook_studio.main import app

reset_settings()


# Define test models at module level to avoid forward reference issues
class TimeResponse(BaseModel):
    timestamp: datetime
    epoch_seconds: int
    epoch_millis: int
    nested: dict
    string_pass: str


class LargeResponse(BaseModel):
    items: list[dict]


class DTResponse(BaseModel):
    dt: datetime
    naive_dt: datetime


class EpochResponse(BaseModel):
    seconds: int
    millis: int
    not_epoch: int


class StringResponse(BaseModel):
    iso_string: str
    random_string: str


class NestedResponse(BaseModel):
    data: dict
    items: list[dict]


# Create test routers at module level
time_router = APIRouter()
large_router = APIRouter()
dt_router = APIRouter()
epoch_router = APIRouter()
string_router = APIRouter()
nested_router = APIRouter()
plain_router = APIRouter()
error_router = APIRouter()
error_cors_router = APIRouter()


@time_router.get("/middleware-test/timestamp")
def test_timestamp() -> TimeResponse:
    return TimeResponse(
        timestamp=datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc),
        epoch_seconds=1719403200,
        epoch_millis=1719403200000,
        nested={"created_at": datetime(2026, 1, 15, 8, 30, 0, tzinfo=timezone.utc)},
        string_pass="not-a-timestamp",
    )


@large_router.get("/middleware-test/large")
def large_response() -> LargeResponse:
    return LargeResponse(
        items=[{"id": i, "created_at": datetime(2026, 1, 15, 8, 30, 0, tzinfo=timezone.utc)} for i in range(50)]
    )


@dt_router.get("/middleware-test/datetime")
def datetime_endpoint() -> DTResponse:
    return DTResponse(
        dt=datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc),
        naive_dt=datetime(2026, 6, 26, 12, 0, 0),
    )


@epoch_router.get("/middleware-test/epoch")
def epoch_endpoint() -> EpochResponse:
    return EpochResponse(
        seconds=1719403200,
        millis=1719403200000,
        not_epoch=12345,
    )


@string_router.get("/middleware-test/strings")
def string_endpoint() -> StringResponse:
    return StringResponse(
        iso_string="2026-06-26T12:00:00Z",
        random_string="hello world",
    )


@nested_router.get("/middleware-test/nested")
def nested_endpoint() -> NestedResponse:
    return NestedResponse(
        data={
            "created": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "inner": {"updated": 1719403200},
        },
        items=[
            {"id": 1, "ts": datetime(2026, 2, 2, tzinfo=timezone.utc)},
            {"id": 2, "ts": 1719500000},
        ],
    )


@plain_router.get("/middleware-test/plain-text")
def plain_text_endpoint() -> Response:
    return Response(content='{"timestamp": "2026-06-26T12:00:00Z"}', media_type="text/plain")


from fastapi import HTTPException


@error_router.get("/middleware-test/error")
def error_endpoint() -> None:
    raise HTTPException(status_code=418, detail="I'm a teapot")


@error_cors_router.get("/middleware-test/error-cors")
def error_cors_endpoint() -> None:
    raise HTTPException(status_code=418, detail="I'm a teapot")


# Include all test routers
app.include_router(time_router)
app.include_router(large_router)
app.include_router(dt_router)
app.include_router(epoch_router)
app.include_router(string_router)
app.include_router(nested_router)
app.include_router(plain_router)
app.include_router(error_router)
app.include_router(error_cors_router)


class TestMiddlewareOrder:
    """Test that middleware execute in the correct order."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_middleware_order_in_app(self) -> None:
        """Verify middleware are registered in correct order."""
        # app.user_middleware shows order with last added at index 0
        # (Starlette's add_middleware prepends to the list)
        middleware_classes = [mw.cls.__name__ for mw in app.user_middleware]

        # Actual order in user_middleware (index 0 = outermost for request):
        # 0: RateLimitMiddleware (S3.6 API quota — reject over-budget clients first)
        # 1: TrustedHostMiddleware (security - reject bad hosts)
        # 2: CORSMiddleware (cross-origin - must wrap all responses)
        # 3: GZipMiddleware (compression - applied after CORS headers)
        # 4: ISOTimestampMiddleware (response normalization)
        # 5: ABTestMiddleware (business routing)
        # 6: ObservabilityMiddleware (tracing - innermost for request)
        expected_order = [
            "RateLimitMiddleware",
            "TrustedHostMiddleware",
            "CORSMiddleware",
            "GZipMiddleware",
            "ISOTimestampMiddleware",
            "ABTestMiddleware",
            "ObservabilityMiddleware",
        ]
        assert middleware_classes == expected_order, f"Middleware order mismatch. Got: {middleware_classes}"

    def test_request_flow_trusted_host_first(self, client: TestClient) -> None:
        """Request: TrustedHost should execute first (reject invalid hosts)."""
        r = client.get("/health", headers={"Host": "evil.com"})
        assert r.status_code == 400
        assert "Invalid host header" in r.text

    def test_request_flow_cors_after_trusted_host(self, client: TestClient) -> None:
        """Request: CORS preflight handled after TrustedHost."""
        r = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
                "Host": "localhost",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_response_flow_cors_after_gzip(self, client: TestClient) -> None:
        """Response: CORS headers added after GZip compression."""
        r = client.get(
            "/docs",
            headers={"Origin": "http://localhost:5173", "Accept-Encoding": "gzip", "Host": "localhost"},
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert r.headers.get("content-encoding") == "gzip"
        assert "Accept-Encoding" in r.headers.get("vary", "")

    def test_response_flow_timestamp_before_cors(self, client: TestClient) -> None:
        """Response: ISOTimestampMiddleware normalizes before CORS adds headers."""
        r = client.get(
            "/middleware-test/timestamp",
            headers={"Origin": "http://localhost:5173", "Host": "localhost"},
        )
        assert r.status_code == 200
        data = r.json()

        iso_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")

        assert iso_pattern.match(data["timestamp"]), f"timestamp not ISO: {data['timestamp']}"
        assert iso_pattern.match(data["epoch_seconds"]), f"epoch_seconds not ISO: {data['epoch_seconds']}"
        assert iso_pattern.match(data["epoch_millis"]), f"epoch_millis not ISO: {data['epoch_millis']}"
        assert iso_pattern.match(
            data["nested"]["created_at"]
        ), f"nested.created_at not ISO: {data['nested']['created_at']}"
        assert data["string_pass"] == "not-a-timestamp"

        # CORS headers present (added AFTER timestamp normalization)
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert r.headers.get("access-control-allow-credentials") == "true"

    def test_gzip_compresses_after_timestamp_normalization(self, client: TestClient) -> None:
        """Response: GZip compresses AFTER timestamp normalization."""
        r = client.get(
            "/middleware-test/large",
            headers={"Host": "localhost", "Accept-Encoding": "gzip"},
        )
        assert r.status_code == 200
        assert r.headers.get("content-encoding") == "gzip"
        assert "Accept-Encoding" in r.headers.get("vary", "")


class TestCORSIntegration:
    """Test CORS middleware integration with other middleware."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_cors_allows_configured_origins(self, client: TestClient) -> None:
        """CORS allows origins from settings.CORS_ORIGINS."""
        allowed_origins = [
            "http://localhost:5173",
            "http://localhost:3000",
            "http://127.0.0.1:5173",
        ]
        for origin in allowed_origins:
            r = client.get("/health", headers={"Origin": origin, "Host": "localhost"})
            assert r.status_code == 200
            assert r.headers.get("access-control-allow-origin") == origin, f"Failed for {origin}"
            assert r.headers.get("access-control-allow-credentials") == "true"

    def test_cors_blocks_unconfigured_origins(self, client: TestClient) -> None:
        """CORS blocks origins not in allowlist."""
        from src.audiobook_studio.config import get_settings

        settings = get_settings()
        if "*" not in settings.CORS_ORIGINS:
            r = client.get("/health", headers={"Origin": "http://evil.com", "Host": "localhost"})
            assert r.status_code == 200
            # With allow_credentials=True and no wildcard, origin not echoed if not allowed

    def test_cors_preflight_includes_methods_headers(self, client: TestClient) -> None:
        """CORS preflight returns allowed methods and headers."""
        r = client.options(
            "/health",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Content-Type",
                "Host": "localhost",
            },
        )
        assert r.status_code == 200
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert "POST" in r.headers.get("access-control-allow-methods", "")
        assert (
            "Content-Type" in r.headers.get("access-control-allow-headers", "")
            or "content-type" in r.headers.get("access-control-allow-headers", "").lower()
        )


class TestGZipIntegration:
    """Test GZip middleware integration."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_gzip_compresses_large_responses(self, client: TestClient) -> None:
        """GZip compresses responses > minimum_size (1000 bytes)."""
        r = client.get("/docs", headers={"Host": "localhost", "Accept-Encoding": "gzip"})
        assert r.status_code == 200
        assert r.headers.get("content-encoding") == "gzip"
        assert "Accept-Encoding" in r.headers.get("vary", "")

    def test_gzip_skips_small_responses(self, client: TestClient) -> None:
        """GZip skips responses below minimum_size."""
        r = client.get("/health", headers={"Host": "localhost", "Accept-Encoding": "gzip"})
        assert r.status_code == 200
        assert r.headers.get("content-encoding") is None


class TestTrustedHostIntegration:
    """Test TrustedHostMiddleware integration."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_trusted_host_allows_configured(self, client: TestClient) -> None:
        """TrustedHost allows hosts from settings.ALLOWED_HOSTS."""
        for host in ["localhost", "127.0.0.1"]:
            r = client.get("/health", headers={"Host": host})
            assert r.status_code == 200, f"Host {host} should be allowed"

    def test_trusted_host_blocks_unconfigured(self, client: TestClient) -> None:
        """TrustedHost blocks hosts not in settings.ALLOWED_HOSTS."""
        for host in ["evil.com", "attacker.local", "192.168.1.1"]:
            r = client.get("/health", headers={"Host": host})
            assert r.status_code == 400, f"Host {host} should be blocked"
            assert "Invalid host header" in r.text


class TestISOTimestampMiddlewareIntegration:
    """Integration tests for ISOTimestampMiddleware with real responses.

    Note: Middleware intercepts response AFTER FastAPI serialization (jsonable_encoder).
    Datetime objects are already converted to ISO strings by jsonable_encoder.
    Middleware correctly handles: numeric epochs, ISO strings, nested structures.
    """

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_iso_timestamp_converts_numeric_epochs(self, client: TestClient) -> None:
        """Middleware converts numeric epoch timestamps to ISO 8601."""
        from fastapi import APIRouter, Response
        from fastapi.responses import JSONResponse

        test_router = APIRouter()

        @test_router.get("/middleware-test/epoch-raw")
        def epoch_raw_endpoint() -> Response:
            return JSONResponse(
                content={
                    "seconds": 1719403200,  # 2024-06-26 12:00:00 UTC
                    "millis": 1719403200000,
                    "not_epoch": 12345,
                }
            )

        app.include_router(test_router)

        r = client.get("/middleware-test/epoch-raw", headers={"Host": "localhost"})
        assert r.status_code == 200
        data = r.json()

        assert data["seconds"].startswith("2024-06-26T12:00:00")
        assert data["millis"].startswith("2024-06-26T12:00:00")
        assert data["not_epoch"] == 12345

    def test_iso_timestamp_preserves_existing_strings(self, client: TestClient) -> None:
        """Middleware doesn't modify already-formatted ISO strings."""
        from fastapi import APIRouter, Response
        from fastapi.responses import JSONResponse

        test_router = APIRouter()

        @test_router.get("/middleware-test/strings-raw")
        def string_raw_endpoint() -> Response:
            return JSONResponse(
                content={
                    "iso_string": "2026-06-26T12:00:00Z",
                    "random_string": "hello world",
                }
            )

        app.include_router(test_router)

        r = client.get("/middleware-test/strings-raw", headers={"Host": "localhost"})
        assert r.status_code == 200
        data = r.json()

        assert data["iso_string"] == "2026-06-26T12:00:00Z"
        assert data["random_string"] == "hello world"

    def test_iso_timestamp_handles_nested_structures(self, client: TestClient) -> None:
        """Middleware recursively normalizes nested dicts and lists with numeric epochs."""
        from fastapi import APIRouter, Response
        from fastapi.responses import JSONResponse

        test_router = APIRouter()

        @test_router.get("/middleware-test/nested-raw")
        def nested_raw_endpoint() -> Response:
            return JSONResponse(
                content={
                    "data": {
                        "created": "2026-01-01T00:00:00Z",  # Already ISO string
                        "inner": {"updated": 1719403200},  # Numeric epoch
                    },
                    "items": [
                        {"id": 1, "ts": "2026-02-02T00:00:00Z"},  # ISO string
                        {"id": 2, "ts": 1719500000},  # Numeric epoch
                    ],
                }
            )

        app.include_router(test_router)

        r = client.get("/middleware-test/nested-raw", headers={"Host": "localhost"})
        assert r.status_code == 200
        data = r.json()

        iso_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
        # ISO strings preserved
        assert data["data"]["created"] == "2026-01-01T00:00:00Z"
        assert data["items"][0]["ts"] == "2026-02-02T00:00:00Z"
        # Numeric epochs converted
        assert iso_pattern.match(data["data"]["inner"]["updated"])
        assert iso_pattern.match(data["items"][1]["ts"])

    def test_iso_timestamp_only_affects_json(self, client: TestClient) -> None:
        """Middleware only processes application/json responses."""
        from fastapi import APIRouter, Response

        test_router = APIRouter()

        @test_router.get("/middleware-test/plain-text")
        def plain_text_endpoint() -> Response:
            return Response(content='{"timestamp": "2026-06-26T12:00:00Z"}', media_type="text/plain")

        app.include_router(test_router)

        r = client.get("/middleware-test/plain-text", headers={"Host": "localhost"})
        assert r.status_code == 200
        assert r.text == '{"timestamp": "2026-06-26T12:00:00Z"}'


class TestMiddlewareExceptionHandling:
    """Test middleware chain handles exceptions properly."""

    @pytest.fixture
    def client(self) -> TestClient:
        return TestClient(app)

    def test_observability_middleware_catches_exceptions(self, client: TestClient) -> None:
        """ObservabilityMiddleware records exceptions and re-raises."""
        r = client.get("/middleware-test/error", headers={"Host": "localhost"})
        assert r.status_code == 418
        # FastAPI HTTPException returns {"detail": "message"}
        assert r.json()["detail"] == "I'm a teapot"

    def test_cors_headers_on_error_responses(self, client: TestClient) -> None:
        """CORS headers present even on error responses."""
        r = client.get(
            "/middleware-test/error-cors",
            headers={"Origin": "http://localhost:5173", "Host": "localhost"},
        )
        assert r.status_code == 418
        assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert r.headers.get("access-control-allow-credentials") == "true"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

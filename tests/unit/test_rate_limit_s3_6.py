"""Tests for S3.6 — API rate limiting / quota middleware (Cloud Studio).

Verifies the per-client token-bucket middleware returns 429 when a client
exceeds its burst budget, is a no-op when disabled, and exempts health/auth.
"""

from fastapi import FastAPI
from starlette.testclient import TestClient

import src.audiobook_studio.api.rate_limit_middleware as rl


class _FakeSettings:
    RATE_LIMIT_ENABLED = True
    RATE_LIMIT_BURST = 2
    RATE_LIMIT_PER_USER_PER_MINUTE = 60


def _make_app(monkeypatch, enabled=True, burst=2):
    class S:
        RATE_LIMIT_ENABLED = enabled
        RATE_LIMIT_BURST = burst
        RATE_LIMIT_PER_USER_PER_MINUTE = 60

    monkeypatch.setattr(rl, "get_settings", lambda: S())
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    rl.add_rate_limit_middleware(app)
    return app


def test_rate_limit_blocks_after_burst(monkeypatch):
    app = _make_app(monkeypatch, enabled=True, burst=2)
    client = TestClient(app)
    assert client.get("/api/ping").status_code == 200
    assert client.get("/api/ping").status_code == 200
    third = client.get("/api/ping")
    assert third.status_code == 429
    assert third.headers.get("retry-after")


def test_rate_limit_disabled_is_noop(monkeypatch):
    app = _make_app(monkeypatch, enabled=False, burst=0)
    client = TestClient(app)
    # With limiting disabled even a tiny burst allows all requests.
    for _ in range(5):
        assert client.get("/api/ping").status_code == 200


def test_health_exempt_from_rate_limit(monkeypatch):
    app = _make_app(monkeypatch, enabled=True, burst=0)
    client = TestClient(app)
    # /health is exempt even with zero burst.
    assert client.get("/health").status_code == 200

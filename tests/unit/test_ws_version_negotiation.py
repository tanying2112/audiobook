"""Tests for WebSocket protocol version negotiation (M-04)."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.audiobook_studio.api.websocket import LATEST_WS_VERSION, WS_PROTOCOL_PREFIX, negotiate_ws_subprotocol
from src.audiobook_studio.api.websocket import router as ws_router

# ── Pure-function negotiation logic ───────────────────────────────────────────


class TestNegotiateSubprotocol:
    def test_returns_none_when_no_header(self):
        assert negotiate_ws_subprotocol(None) is None
        assert negotiate_ws_subprotocol("") is None

    def test_returns_none_when_non_string(self):
        # Mirrors the AsyncMock case in the endpoint unit test.
        assert negotiate_ws_subprotocol(object()) is None

    def test_selects_single_supported_version(self):
        assert negotiate_ws_subprotocol("audiobook-progress-v1") == "audiobook-progress-v1"

    def test_selects_supported_when_v1_and_unsupported_offered(self):
        # Only v1 is supported; client offers v1 + v2 (unsupported) -> v1 wins.
        offered = "audiobook-progress-v1, audiobook-progress-v2"
        assert negotiate_ws_subprotocol(offered) == "audiobook-progress-v1"

    def test_ignores_unsupported_versions(self):
        # v2/v99 are not in SUPPORTED_WS_PROTOCOL_VERSIONS -> no common version.
        assert negotiate_ws_subprotocol("audiobook-progress-v2") is None
        assert negotiate_ws_subprotocol("audiobook-progress-v99") is None

    def test_ignores_unrelated_subprotocols(self):
        assert negotiate_ws_subprotocol("graphql-ws") is None


# ── End-to-end handshake over TestClient ─────────────────────────────────────

_app = FastAPI()
_app.include_router(ws_router, prefix="/api")


def test_handshake_includes_version_when_client_offers_v1():
    with TestClient(_app) as client:
        with client.websocket_connect(
            "/api/ws/pipeline/1",
            headers={"sec-websocket-protocol": "audiobook-progress-v1"},
        ) as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "connected"
            assert msg["version"] == LATEST_WS_VERSION
            assert msg["protocol"] == f"{WS_PROTOCOL_PREFIX}-v1"


def test_handshake_falls_back_to_latest_when_no_header():
    with TestClient(_app) as client:
        with client.websocket_connect("/api/ws/pipeline/1") as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "connected"
            assert msg["version"] == LATEST_WS_VERSION
            assert msg["protocol"] == f"{WS_PROTOCOL_PREFIX}-{LATEST_WS_VERSION}"


def test_handshake_falls_back_when_client_offers_only_unsupported():
    with TestClient(_app) as client:
        with client.websocket_connect(
            "/api/ws/pipeline/1",
            headers={"sec-websocket-protocol": "audiobook-progress-v99"},
        ) as ws:
            msg = json.loads(ws.receive_text())
            assert msg["type"] == "connected"
            assert msg["version"] == LATEST_WS_VERSION

"""Tests for honest, probed real-clone availability (Track B / audit rec #9).

``real_clone_available()`` must stay False under free + no-GPU (no endpoint
configured) and only flip to True when a real VoxCPM2/CosyVoice backend endpoint
is configured AND answers its ``/health`` probe. We never claim a usable clone
was produced when no real backend is actually serving requests.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.tts import clone as clone_mod
from src.audiobook_studio.tts.clone import (
    _configured_clone_endpoint,
    clone_mode,
    probe_clone_availability,
    real_clone_available,
    refresh_clone_availability,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Reset the module-level probe cache/TTL between tests."""
    clone_mod._CLONE_AVAILABLE_CACHE = None
    clone_mod._CLONE_PROBE_TS = 0.0
    yield
    clone_mod._CLONE_AVAILABLE_CACHE = None
    clone_mod._CLONE_PROBE_TS = 0.0


@pytest.fixture(autouse=True)
def _no_endpoint(monkeypatch):
    """Ensure no clone endpoint is configured by default."""
    monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)
    monkeypatch.delenv("COSYVOICE_ENDPOINT", raising=False)
    monkeypatch.delenv("CLONE_BACKEND_DISABLED", raising=False)
    yield


def test_no_endpoint_means_unavailable_and_preset():
    assert _configured_clone_endpoint() is None
    assert real_clone_available() is False
    assert clone_mode() == "preset"


def test_opt_out_force_disabled(monkeypatch):
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")
    monkeypatch.setenv("CLONE_BACKEND_DISABLED", "true")
    assert _configured_clone_endpoint() is None
    assert real_clone_available() is False
    assert clone_mode() == "preset"


def test_cosyvoice_endpoint_preferred_when_voxcpm2_absent(monkeypatch):
    monkeypatch.setenv("COSYVOICE_ENDPOINT", "http://cosyvoice:5020/")
    assert _configured_clone_endpoint() == "http://cosyvoice:5020"


def test_configured_endpoint_unreachable_is_unavailable(monkeypatch):
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")

    def _boom(*a, **k):
        raise RuntimeError("connection refused")

    with patch.object(clone_mod, "_probe_endpoint_health", _boom):
        assert real_clone_available() is False
        assert clone_mode() == "preset"


def test_healthy_endpoint_makes_clone_available(monkeypatch):
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")

    with patch.object(clone_mod, "_probe_endpoint_health", lambda url: True):
        assert real_clone_available() is True
        assert clone_mode() == "clone"


def test_unhealthy_http_status_is_unavailable(monkeypatch):
    monkeypatch.setenv("COSYVOICE_ENDPOINT", "http://cosyvoice:5020")

    # 404/500 means the backend is not actually serving — must NOT advertise clone.
    with patch.object(clone_mod, "_probe_endpoint_health", lambda url: False):
        assert real_clone_available() is False


def test_probe_uses_real_httpx_client(monkeypatch):
    """The probe really hits ``{endpoint}/health`` via httpx."""
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")
    captured = {}

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, *a, **k):
            captured["args"] = (a, k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url):
            captured["url"] = url
            return _Resp()

    with patch.dict("sys.modules", {"httpx": MagicMock(Client=_Client)}):
        assert probe_clone_availability(force=True) is True
    assert captured["url"] == "http://voxcpm2:5010/health"


def test_cache_is_ttl_bounded(monkeypatch):
    """A fresh probe result is cached until the TTL elapses."""
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")
    calls = {"n": 0}

    def _fake(url):
        calls["n"] += 1
        return True

    with patch.object(clone_mod, "_probe_endpoint_health", _fake):
        # First call probes; immediate second call should hit the cache.
        assert real_clone_available() is True
        assert real_clone_available() is True
        assert calls["n"] == 1
        # Forcing a refresh probes again.
        assert refresh_clone_availability() is True
        assert calls["n"] == 2


def test_missing_httpx_reports_unavailable(monkeypatch):
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://voxcpm2:5010")
    with patch.dict("sys.modules", {"httpx": None}):
        assert real_clone_available() is False

"""Tests for hardware-profile hot-switch integration (M-05)."""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from tests.conftest import setup_auth_overrides

from src.audiobook_studio.api import admin
from src.audiobook_studio.auth.dependencies import get_current_active_user
from src.audiobook_studio.config.hardware_profile import (
    get_hardware_profile,
    reload_hardware_profile,
    reset_hardware_profile,
)


@pytest.fixture()
def client():
    """TestClient with the admin router mounted and auth bypassed."""
    app = FastAPI()
    app.include_router(admin.router, prefix="/api", dependencies=[Depends(get_current_active_user)])
    setup_auth_overrides(app)
    with TestClient(app) as c:
        yield c
    reset_hardware_profile()


# ── Runtime switching (no HTTP) ───────────────────────────────────────────────


def test_reload_hardware_profile_refreshes_singleton():
    profile = reload_hardware_profile()
    assert profile.active_profile
    reset_hardware_profile()


def test_set_active_profile_switches_tier():
    profile = get_hardware_profile()
    original = profile.active_profile
    try:
        profile.set_active_profile("potato")
        assert profile.active_profile == "potato"
        profile.set_active_profile(original)
        assert profile.active_profile == original
    finally:
        reset_hardware_profile()


def test_set_active_profile_rejects_unknown():
    profile = get_hardware_profile()
    with pytest.raises(ValueError):
        profile.set_active_profile("nonexistent_tier")
    reset_hardware_profile()


# ── Admin HTTP endpoints ─────────────────────────────────────────────────────


def test_reload_endpoint(client):
    r = client.post("/api/admin/hardware-profile/reload")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "reloaded"
    assert isinstance(body["active_profile"], str)


def test_switch_endpoint(client):
    r = client.post("/api/admin/hardware-profile/switch", json={"profile": "potato"})
    assert r.status_code == 200
    assert r.json()["active_profile"] == "potato"
    # Restore default so we don't leak state into other tests.
    client.post("/api/admin/hardware-profile/switch", json={"profile": "cloud_hybrid"})


def test_switch_invalid_profile_returns_400(client):
    r = client.post("/api/admin/hardware-profile/switch", json={"profile": "does_not_exist"})
    assert r.status_code == 400

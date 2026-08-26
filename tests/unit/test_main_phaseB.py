"""Phase B structural tests for main.py health/error handlers."""

import asyncio
import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

from starlette.exceptions import HTTPException as StarletteHTTPException

from src.audiobook_studio import main as main_mod


def test_health_check():
    assert main_mod.health_check() == {"status": "ok"}


def test_health_live():
    assert main_mod.health_live() == {"status": "alive"}


def test_error_code_to_status():
    assert main_mod._error_code_to_status("VALIDATION_ERROR") == 422
    assert main_mod._error_code_to_status("FILE_NOT_FOUND") == 404
    assert main_mod._error_code_to_status("QUOTA_EXCEEDED") == 429
    assert main_mod._error_code_to_status("CIRCUIT_OPEN") == 503
    assert main_mod._error_code_to_status("CONFIG_ERROR") == 500
    assert main_mod._error_code_to_status("UNKNOWN") == 500


def test_global_exception_handler_unknown():
    async def go():
        req = MagicMock()
        resp = await main_mod.global_exception_handler(req, ValueError("boom"))
        assert resp.status_code == 500

    _run(go())


def test_global_exception_handler_http():
    async def go():
        req = MagicMock()
        resp = await main_mod.global_exception_handler(
            req, StarletteHTTPException(detail="x", status_code=418)
        )
        assert resp.status_code == 418

    _run(go())


def test_global_exception_handler_structured():
    class FakeErr:
        error_code = "VALIDATION_ERROR"
        message = "bad"

        def to_dict(self):
            return {"code": "VALIDATION_ERROR", "message": "bad"}

    async def go():
        req = MagicMock()
        resp = await main_mod.global_exception_handler(req, FakeErr())
        assert resp.status_code == 422

    _run(go())


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# health_ready (network deps mocked)
# ---------------------------------------------------------------------------


def _fake_settings(redis_url="redis://x", kokoro_path=None, timeout=1.0, llm_ok=True):
    class FakeSettings:
        HEALTH_CHECK_TIMEOUT = timeout
        REDIS_URL = redis_url
        KOKORO_MODEL_PATH = kokoro_path

        def _validate_llm_api_keys(self):
            if not llm_ok:
                raise RuntimeError("invalid key format")
            return None

    return FakeSettings()


def _patch_health_deps(monkeypatch, redis_ping_ok=True, registry=None):
    fake_redis = MagicMock()
    fake_redis.ping = AsyncMock() if redis_ping_ok else AsyncMock(side_effect=Exception("conn refused"))
    fake_redis.aclose = AsyncMock()

    async def _from_url(url):
        return fake_redis

    monkeypatch.setattr("redis.asyncio.from_url", _from_url)

    async def _probe(timeout, registry=None):
        return {"engines": {"kokoro": True}, "details": {}}

    monkeypatch.setattr(
        "src.audiobook_studio.tts.engine.probe_tts_engines", _probe
    )
    container = MagicMock()
    container.get_or_none.return_value = registry
    monkeypatch.setattr(
        "src.audiobook_studio.di.get_app_container", lambda: container
    )


def test_health_ready_ok_with_registry(monkeypatch):
    tmp = tempfile.NamedTemporaryFile(suffix=".bin", delete=False)
    tmp.close()
    monkeypatch.setattr("src.audiobook_studio.config.get_settings", lambda: _fake_settings(kokoro_path=tmp.name))
    _patch_health_deps(monkeypatch, redis_ping_ok=True, registry=object())
    try:
        resp = _run(main_mod.health_ready())
        assert resp.status_code == 200
    finally:
        os.unlink(tmp.name)


def test_health_ready_ok_no_registry(monkeypatch):
    monkeypatch.setattr("src.audiobook_studio.config.get_settings", lambda: _fake_settings(kokoro_path=""))
    _patch_health_deps(monkeypatch, redis_ping_ok=True, registry=None)
    resp = _run(main_mod.health_ready())
    assert resp.status_code == 200


def test_health_ready_degraded(monkeypatch):
    monkeypatch.setattr(
        main_mod,
        "get_settings",
        lambda: _fake_settings(kokoro_path="", llm_ok=False, timeout=0.05),
    )
    _patch_health_deps(monkeypatch, redis_ping_ok=False, registry=None)
    resp = _run(main_mod.health_ready())
    assert resp.status_code == 503


def test_health_ready_tts_probe_error_and_llm_error(monkeypatch):
    monkeypatch.setattr(
        "src.audiobook_studio.config.get_settings",
        lambda: _fake_settings(kokoro_path="", llm_ok=False, timeout=0.05),
    )

    fake_redis = MagicMock()
    fake_redis.ping = AsyncMock()
    fake_redis.aclose = AsyncMock()

    async def _from_url(url):
        return fake_redis

    monkeypatch.setattr("redis.asyncio.from_url", _from_url)

    async def _probe(timeout, registry=None):
        raise RuntimeError("tts probe boom")

    monkeypatch.setattr(
        "src.audiobook_studio.tts.engine.probe_tts_engines", _probe
    )
    container = MagicMock()
    container.get_or_none.return_value = None
    monkeypatch.setattr(
        "src.audiobook_studio.di.get_app_container", lambda: container
    )

    resp = _run(main_mod.health_ready())
    # db + redis healthy, but llm key invalid -> 503 (llm is critical)
    assert resp.status_code == 503


# ---------------------------------------------------------------------------
# lifespan (startup/shutdown; heavy deps mocked)
# ---------------------------------------------------------------------------


def test_lifespan_startup_and_shutdown(monkeypatch):
    fake_settings = MagicMock()
    fake_settings.HEALTH_CHECK_TIMEOUT = 1.0
    fake_settings.validate_jwt_secret = MagicMock()
    fake_settings.validate_cors_security = MagicMock()
    fake_settings.validate_runtime_dependencies = AsyncMock()

    monkeypatch.setattr(
        "src.audiobook_studio.config.get_settings", lambda: fake_settings
    )

    fake_result = MagicMock()
    fake_result.returncode = 0
    fake_result.stderr = ""
    monkeypatch.setattr("subprocess.run", lambda *a, **k: fake_result)

    fake_db = MagicMock()
    monkeypatch.setattr(
        "src.audiobook_studio.database.SessionLocal", lambda: fake_db
    )
    monkeypatch.setattr("src.audiobook_studio.auth.rbac.init_rbac", MagicMock())

    fake_pm = MagicMock()
    fake_pm.load_all_installed.return_value = {"p1": True}
    monkeypatch.setattr(
        "src.audiobook_studio.plugins.get_plugin_manager", lambda: fake_pm
    )

    monkeypatch.setattr(
        "src.audiobook_studio.observability.tracing.shutdown_tracing", MagicMock()
    )
    monkeypatch.setattr(
        "src.audiobook_studio.observability.metrics.shutdown_metrics", MagicMock()
    )

    async def go():
        async with main_mod.lifespan(MagicMock()):
            pass

    _run(go())

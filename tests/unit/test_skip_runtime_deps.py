"""Tests for C2 fix: offline / "potato mode" startup without Redis.

``settings.validate_runtime_dependencies`` previously raised ``RuntimeError``
whenever Redis was unreachable, contradicting the "zero-config / offline"
positioning. With ``SKIP_RUNTIME_DEPS=1`` the non-critical external checks
(Redis, local model files, LLM key formats) degrade to warnings while the
database check remains mandatory.
"""

import asyncio

from src.audiobook_studio.config import get_settings


def test_validate_runtime_deps_skips_redis_when_flag_set(monkeypatch):
    # Potato mode: even with an unreachable Redis URL the startup check must pass.
    monkeypatch.setenv("SKIP_RUNTIME_DEPS", "1")
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1")

    settings = get_settings()
    # Should not raise despite Redis being unreachable. The database check still
    # runs against the (temp) sqlite configured by the test harness.
    asyncio.run(settings.validate_runtime_dependencies(timeout=1))

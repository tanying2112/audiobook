"""Behavior tests for auth/dependencies.py Redis cache helpers.

The existing test_auth_dependencies.py patches _get_cached_user/_cache_user/
_invalidate_user_cache to no-ops via an autouse `mock_redis` fixture, so the
REAL cache-helper code (lines 57-102) and the cached-user branch of
get_current_user (lines 142-168) never run. These tests exercise the real
helpers with an in-memory async fake Redis (no new dependency — CLAUDE.md
rule 8), asserting the real set/get/invalidate lifecycle and the
cached-user→scope/auth-error branches.
"""

import json
from unittest.mock import MagicMock

import pytest

from src.audiobook_studio.auth import dependencies as dep
from src.audiobook_studio.models.user import User


class _FakeRedis:
    """Trivial in-memory async Redis replacement: get/setex/delete/aclose."""

    def __init__(self):
        self.store = {}

    async def get(self, key):
        return self.store.get(key)

    async def setex(self, key, ttl, value):
        self.store[key] = value

    async def delete(self, key):
        self.store.pop(key, None)

    async def aclose(self):
        pass


@pytest.fixture
def fake_redis():
    redis = _FakeRedis()

    async def _factory():
        return redis

    # Patch the Redis factory used by the cache helpers; restore afterwards.
    orig = dep._get_redis
    dep._get_redis = _factory
    try:
        yield redis
    finally:
        dep._get_redis = orig


def _build_user(db_session=None) -> User:
    """A User instance with enough fields to satisfy _cache_user."""
    user = User(
        email="c@example.com",
        username="c",
        hashed_password="h",
        is_active=True,
        is_superuser=False,
    )
    user.id = 7
    user.full_name = "C U"
    user.roles = []  # no roles -> roles list JSON-serialises to []
    return user


class TestCacheUserAndReadBack:
    @pytest.mark.asyncio
    async def test_cache_user_writes_json_then_get_returns_dict(self, fake_redis):
        user = _build_user()
        await dep._cache_user(user)

        # Key is user:cache:<id>; value must be JSON with the user fields.
        raw = fake_redis.store[f"{dep.USER_CACHE_PREFIX}{user.id}"]
        data = json.loads(raw)
        assert data["id"] == 7
        assert data["email"] == "c@example.com"
        assert data["username"] == "c"
        assert data["is_active"] is True
        assert data["is_superuser"] is False
        assert data["roles"] == []

        # _get_cached_user must round-trip the JSON back to a dict.
        cached = await dep._get_cached_user(user.id)
        assert cached is not None
        assert cached["id"] == 7
        assert cached["username"] == "c"

    @pytest.mark.asyncio
    async def test_get_cached_user_miss_returns_none(self, fake_redis):
        # No prior cache_set -> cache miss -> None (and never raises).
        assert await dep._get_cached_user(404) is None

    @pytest.mark.asyncio
    async def test_invalidate_user_cache_deletes_key(self, fake_redis):
        user = _build_user()
        await dep._cache_user(user)
        assert await dep._get_cached_user(user.id) is not None
        await dep._invalidate_user_cache(user.id)
        assert await dep._get_cached_user(user.id) is None


class TestCacheHelperExceptionSuppression:
    """Each helper has a top-level try/except that swallows errors and logs —
    assert it never propagates (graceful degradation), and the suppression
    produces the documented return value."""

    @pytest.mark.asyncio
    async def test_get_cached_user_survives_redis_error(self, monkeypatch):
        async def boom():
            raise RuntimeError("redis down")

        monkeypatch.setattr(dep, "_get_redis", boom)
        # Must not raise; must return None on failure.
        assert await dep._get_cached_user(1) is None

    @pytest.mark.asyncio
    async def test_cache_user_survives_redis_error(self, monkeypatch):
        async def boom():
            raise RuntimeError("redis down")

        monkeypatch.setattr(dep, "_get_redis", boom)
        # Must not raise, returns None.
        assert await dep._cache_user(_build_user()) is None

    @pytest.mark.asyncio
    async def test_invalidate_survives_redis_error(self, monkeypatch):
        async def boom():
            raise RuntimeError("redis down")

        monkeypatch.setattr(dep, "_get_redis", boom)
        assert await dep._invalidate_user_cache(1) is None


class TestGetCurrentUserCachedBranch:
    """Exercises get_current_user's cached-user path (lines 142-168)."""

    @pytest.mark.asyncio
    async def test_cached_active_user_returned(self, fake_redis, monkeypatch):
        from fastapi.security import SecurityScopes

        # Pre-populate the cache with an active user.
        user_data = {
            "id": 7,
            "email": "c@example.com",
            "username": "c",
            "full_name": "C U",
            "is_active": True,
            "is_superuser": False,
            "roles": [],
        }
        await fake_redis.setex(f"{dep.USER_CACHE_PREFIX}7", dep.USER_CACHE_TTL, json.dumps(user_data))

        # Issue a real access token for sub=7.
        from src.audiobook_studio.auth.jwt_handler import jwt_handler

        token = jwt_handler.create_token_pair(user_id=7, username="c")["access_token"]

        scopes = SecurityScopes(scopes=[])
        # db is unused on the cached path but the dependency requires it.
        db = MagicMock()
        user = await dep.get_current_user(security_scopes=scopes, token=token, db=db)

        assert user is not None
        assert user.id == 7
        assert user.email == "c@example.com"
        assert user._cached_roles == []

    @pytest.mark.asyncio
    async def test_cached_inactive_user_raises_400(self, fake_redis):
        from fastapi import HTTPException
        from fastapi.security import SecurityScopes

        user_data = {
            "id": 8,
            "email": "d@example.com",
            "username": "d",
            "full_name": "D",
            "is_active": False,
            "is_superuser": False,
            "roles": [],
        }
        await fake_redis.setex(f"{dep.USER_CACHE_PREFIX}8", dep.USER_CACHE_TTL, json.dumps(user_data))

        from src.audiobook_studio.auth.jwt_handler import jwt_handler

        token = jwt_handler.create_token_pair(user_id=8, username="d")["access_token"]
        scopes = SecurityScopes(scopes=[])
        with pytest.raises(HTTPException) as exc:
            await dep.get_current_user(security_scopes=scopes, token=token, db=MagicMock())
        assert exc.value.status_code == 400
        assert "Inactive user" in exc.value.detail

    @pytest.mark.asyncio
    async def test_cached_user_scope_mismatch_raises_403(self, fake_redis):
        from fastapi import HTTPException
        from fastapi.security import SecurityScopes

        # User has no admin role but the endpoint demands "admin" scope.
        user_data = {
            "id": 9,
            "email": "e@example.com",
            "username": "e",
            "full_name": "E",
            "is_active": True,
            "is_superuser": False,
            "roles": [],
        }
        await fake_redis.setex(f"{dep.USER_CACHE_PREFIX}9", dep.USER_CACHE_TTL, json.dumps(user_data))

        from src.audiobook_studio.auth.jwt_handler import jwt_handler

        # permissions lack "admin"; roles lack "admin".
        token = jwt_handler.create_token_pair(user_id=9, username="e", roles=[], permissions=["project:read"])[
            "access_token"
        ]
        scopes = SecurityScopes(scopes=["admin"])
        with pytest.raises(HTTPException) as exc:
            await dep.get_current_user(security_scopes=scopes, token=token, db=MagicMock())
        assert exc.value.status_code == 403

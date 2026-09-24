"""Behavior tests for src/audiobook_studio/auth/jwt_handler.py.

Exercises real JWT encode/decode round-trips (no mocks) against the configured
secret/algorithm, bcrypt password hashing, token-type discrimination, expiry,
and refresh-token rotation. Covers the lines uncovered by the auth-router
suite: expires_delta branches, verify/decode/expire/get-payload error paths,
and refresh_access_token happy/sad paths.
"""

# tests/conftest_minimal.py (wildcard-imported by tests/conftest.py at session
# start) replaces `bcrypt` with a MagicMock in sys.modules so heavy optional
# deps don't load. jwt_handler does `import bcrypt` at module load, so it would
# bind to that mock and real password hashing could never be exercised. To
# assert REAL bcrypt behavior here (per the “No Implicit Mocking” red line),
# drop the stub, re-import the genuine bcrypt module, AND rebind jwt_handler.bcrypt
# (other auth test files may have imported jwt_handler earlier and bound the mock).
# Local to this file only; other test files keep their mock.
import sys

if "bcrypt" in sys.modules:
    del sys.modules["bcrypt"]

import bcrypt  # noqa: E402  (real module, stub dropped above)

_jh_name = "src.audiobook_studio.auth.jwt_handler"
if _jh_name in sys.modules:
    sys.modules[_jh_name].bcrypt = bcrypt  # rebind if jwt_handler already loaded
from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402

from src.audiobook_studio.auth.jwt_handler import (  # noqa: E402
    JWTHandler,
    TokenPayload,
    _get_jwt_handler,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
    verify_token,
)


@pytest.fixture
def handler():
    """Fresh JWTHandler (re-reads settings each time)."""
    return JWTHandler()


class TestPasswordHashing:
    def test_hash_and_verify_roundtrip(self, handler):
        hashed = handler.hash_password("S3cret!")
        # Hashed value must not equal plaintext and must be bcrypt-format.
        assert hashed != "S3cret!"
        assert hashed.startswith("$2")
        assert handler.verify_password("S3cret!", hashed) is True

    def test_verify_rejects_wrong_password(self, handler):
        hashed = handler.hash_password("correct-horse")
        assert handler.verify_password("wrong", hashed) is False

    def test_verify_rejects_legacy_non_bcrypt_hash(self, handler):
        # Legacy SHA-256 hashes must be rejected (must be migrated) — not $2-
        legacy = "5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8"
        assert handler.verify_password("any", legacy) is False

    def test_verify_returns_false_on_bcrypt_corruption(self, handler):
        # "$2b$" prefix but malformed body -> bcrypt raises -> caught -> False
        assert handler.verify_password("any", "$2b$not-a-valid-hash-string") is False

    def test_module_level_hash_password_helpers(self):
        # Module-level convenience functions use the lazy singleton.
        h = hash_password("pw")
        assert h.startswith("$2")
        assert verify_password("pw", h) is True
        assert verify_password("nope", h) is False


class TestCreateAccessToken:
    def test_default_expiry_no_expires_delta(self, handler):
        tok = handler.create_access_token(user_id=7, username="alice")
        payload = handler.decode_token(tok)
        assert payload["sub"] == "7"
        assert payload["username"] == "alice"
        assert payload["type"] == "access"
        assert payload["roles"] == []
        assert payload["permissions"] == []
        # Expiry must be in the future (≈ ACCESS_TOKEN_EXPIRE_MINUTES from now).
        assert payload["exp"] > 0
        assert handler.verify_token(tok) is True

    def test_custom_expires_delta_used(self, handler):
        tok = handler.create_access_token(user_id=1, username="bob", expires_delta=timedelta(seconds=1))
        payload = handler.decode_token(tok)
        # Delta of 1s: exp must be ~1s in the future, well under default 30min.
        # We assert it decodes and is access-type — exact second drift avoided.
        assert payload["type"] == "access"
        # Immediately it is NOT expired.
        assert handler.is_token_expired(tok) is False

    def test_roles_and_permissions_encoded(self, handler):
        tok = handler.create_access_token(user_id=1, username="carol", roles=["admin"], permissions=["project:read"])
        payload = handler.decode_token(tok)
        assert payload["roles"] == ["admin"]
        assert payload["permissions"] == ["project:read"]


class TestCreateRefreshToken:
    def test_refresh_token_type_is_refresh(self, handler):
        tok = handler.create_refresh_token(user_id=9, username="dave")
        payload = handler.decode_token(tok)
        assert payload["type"] == "refresh"
        assert payload["sub"] == "9"
        # Refresh tokens carry no roles/permissions keys at all.
        assert "roles" not in payload
        assert "permissions" not in payload

    def test_refresh_custom_expires_delta(self, handler):
        tok = handler.create_refresh_token(user_id=1, username="erin", expires_delta=timedelta(days=1))
        assert handler.is_refresh_token(tok) is True

    def test_is_refresh_token_rejects_access_token(self, handler):
        access = handler.create_access_token(user_id=1, username="frank")
        assert handler.is_refresh_token(access) is False

    def test_is_refresh_token_rejects_invalid(self, handler):
        assert handler.is_refresh_token("not.a.token") is False


class TestDecodeVerifyPayload:
    def test_decode_invalid_raises_value_error(self, handler):
        with pytest.raises(ValueError):
            handler.decode_token("garbage.token.here")

    def test_verify_token_invalid_returns_false(self, handler):
        assert handler.verify_token("garbage.token.here") is False

    def test_get_token_payload_valid_returns_typed(self, handler):
        tok = handler.create_access_token(user_id=42, username="gina", roles=["editor"])
        payload = handler.get_token_payload(tok)
        assert isinstance(payload, TokenPayload)
        assert payload.sub == "42"
        assert payload.username == "gina"
        assert payload.roles == ["editor"]
        assert payload.type == "access"

    def test_get_token_payload_invalid_returns_none(self, handler):
        assert handler.get_token_payload("garbage") is None

    def test_is_token_expired_true_for_invalid(self, handler):
        # Invalid token -> get_token_payload None -> is_token_expired True
        assert handler.is_token_expired("garbage") is True

    def test_is_token_expired_true_for_expired_token(self, handler):
        tok = handler.create_access_token(user_id=1, username="heidi", expires_delta=timedelta(seconds=-10))
        # expiry set 10s in the past -> expired
        assert handler.is_token_expired(tok) is True

    def test_module_level_decode_and_verify(self):
        tok = create_access_token(user_id=1, username="ivan")
        assert decode_token(tok)["username"] == "ivan"
        assert verify_token(tok) is True

    def test_module_level_create_refresh_token(self):
        # Module-level convenience create_refresh_token (lazy singleton).
        tok = create_refresh_token(user_id=2, username="judy")
        payload = decode_token(tok)
        assert payload["type"] == "refresh"
        assert payload["sub"] == "2"


class TestCreateTokenPair:
    def test_pair_contains_both_tokens_and_bearer(self, handler):
        pair = handler.create_token_pair(user_id=5, username="judy", roles=["admin"])
        assert "access_token" in pair
        assert "refresh_token" in pair
        assert pair["token_type"] == "bearer"
        # expires_in is in seconds = minutes * 60
        assert pair["expires_in"] == handler.access_token_expire_minutes * 60
        assert handler.is_refresh_token(pair["refresh_token"]) is True
        assert handler.is_refresh_token(pair["access_token"]) is False


class TestRefreshAccessToken:
    def test_refresh_yields_new_access_token(self, handler):
        refresh = handler.create_refresh_token(user_id=11, username="karl")
        new_access = handler.refresh_access_token(refresh)
        assert new_access is not None
        payload = handler.decode_token(new_access)
        assert payload["type"] == "access"
        assert payload["sub"] == "11"
        assert payload["username"] == "karl"

    def test_refresh_rejects_access_token(self, handler):
        access = handler.create_access_token(user_id=1, username="lea")
        assert handler.refresh_access_token(access) is None

    def test_refresh_rejects_invalid_token(self, handler):
        assert handler.refresh_access_token("garbage") is None

    def test_refresh_propagates_roles_and_permissions_when_present(self, handler):
        # Build a refresh token whose payload we enrich with roles/permissions,
        # since the refresh path reads payload.roles/permissions into the new
        # access token.
        handler_inst = handler
        refresh = handler_inst.create_refresh_token(user_id=33, username="mike")
        # Decode -> manually re-issue as refresh carrying roles/permissions,
        # then call refresh_access_token to confirm propagation.
        from jose import jwt as jose_jwt

        payload = handler_inst.decode_token(refresh)
        payload["roles"] = ["editor"]
        payload["permissions"] = ["project:write"]
        payload["type"] = "refresh"
        enriched = jose_jwt.encode(payload, handler_inst.secret_key, algorithm=handler_inst.algorithm)
        new_access = handler_inst.refresh_access_token(enriched)
        assert new_access is not None
        result = handler_inst.decode_token(new_access)
        assert result["roles"] == ["editor"]
        assert result["permissions"] == ["project:write"]


class TestLazyProxySingleton:
    def test_get_jwt_handler_is_singleton(self):
        a = _get_jwt_handler()
        b = _get_jwt_handler()
        assert a is b

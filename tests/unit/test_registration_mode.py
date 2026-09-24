"""Tests for H1 fix: secure-by-default registration + rate-limited auth.

- ``AUTH_REGISTRATION_MODE`` defaults to ``invite`` (anonymous self-registration
  disabled unless a valid invite code or an admin bootstrap is present).
- ``/api/auth`` is no longer exempt from the rate-limit middleware, so
  registration/login brute-force / abuse is throttled.
"""

from src.audiobook_studio.api.rate_limit_middleware import _EXEMPT_PREFIXES
from src.audiobook_studio.auth.models import UserCreate
from src.audiobook_studio.auth.router import _registration_allowed
from src.audiobook_studio.config import get_settings
from src.audiobook_studio.config.settings import Settings


class _FakeSettings:
    """Minimal stand-in for Settings (avoids mutating the cached singleton)."""

    def __init__(self, mode="invite", codes=""):
        self.AUTH_REGISTRATION_MODE = mode
        self.REGISTRATION_INVITE_CODES = codes


def _anon_user() -> UserCreate:
    return UserCreate(email="a@example.com", username="anon", password="password123")


def test_secure_registration_default():
    # The production *code* default must be secure ("invite"), independent of the
    # test-env override that relaxes it to "open" for test convenience. To avoid
    # depending on env injection, assert the Settings class default directly.
    assert Settings.model_fields["AUTH_REGISTRATION_MODE"].default == "invite"
    # And the cached singleton (when not overridden by the test env) also honours it.
    assert get_settings().AUTH_REGISTRATION_MODE in ("invite", "open")


def test_auth_endpoints_not_rate_limit_exempt():
    assert "/api/auth" not in _EXEMPT_PREFIXES


def test_open_mode_allows_anonymous_registration():
    ok, _ = _registration_allowed(_FakeSettings(mode="open"), _anon_user(), None)
    assert ok is True


def test_invite_mode_blocks_anonymous_without_code():
    ok, reason = _registration_allowed(_FakeSettings(mode="invite"), _anon_user(), None)
    assert ok is False
    assert "invite code" in reason


def test_invite_mode_allows_valid_code():
    ok, _ = _registration_allowed(
        _FakeSettings(mode="invite", codes="abc123,xyz"),
        _anon_user().model_copy(update={"invite_code": "abc123"}),
        None,
    )
    assert ok is True


def test_invite_mode_allows_admin_bootstrap():
    class _Admin:
        is_superuser = True

    ok, _ = _registration_allowed(_FakeSettings(mode="invite"), _anon_user(), _Admin())
    assert ok is True


def test_approval_mode_requires_admin():
    ok, _ = _registration_allowed(_FakeSettings(mode="approval"), _anon_user(), None)
    assert ok is False

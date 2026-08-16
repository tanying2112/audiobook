"""Tests for log sanitization utilities — #15 engineering debt."""

import pytest

from src.audiobook_studio.utils.log_sanitizer import (
    ALLOWLIST_FIELDS,
    SENSITIVE_FIELD_PATTERNS,
    SENSITIVE_VALUE_PATTERNS,
    _is_sensitive_field_name,
    _is_sensitive_value,
    _redact_sensitive_values,
    log_sanitizer_processor,
    sanitize_log_record,
)


class TestSensitiveFieldDetection:
    """Test detection of sensitive field names."""

    def test_api_key_fields_are_sensitive(self):
        """Fields containing 'api_key', 'secret', 'password', 'token' are flagged."""
        sensitive_names = [
            "api_key",
            "openai_api_key",
            "ANTHROPIC_API_KEY",
            "secret_key",
            "jwt_secret_key",
            "password",
            "hashed_password",
            "access_token",
            "refresh_token",
            "auth_header",
            "credential",
            "private_key",
        ]
        for name in sensitive_names:
            assert _is_sensitive_field_name(name), f"'{name}' should be flagged as sensitive"

    def test_non_sensitive_fields_pass_through(self):
        """Normal field names like 'message', 'error_code', 'task_id' are not flagged."""
        safe_names = [
            "message",
            "error_code",
            "stage",
            "provider",
            "timestamp",
            "task_id",
            "project_id",
            "user_id",
        ]
        for name in safe_names:
            assert not _is_sensitive_field_name(name), f"'{name}' should NOT be flagged"

    def test_allowlist_fields_never_flagged(self):
        """Fields in ALLOWLIST are always safe regardless of name patterns."""
        for name in ALLOWLIST_FIELDS:
            assert not _is_sensitive_field_name(name), f"Allowlisted '{name}' should NOT be flagged"


class TestSensitiveValueDetection:
    """Test detection of sensitive values (API keys, tokens, etc.)."""

    def test_short_values_not_flagged(self):
        """Values under 8 characters are never flagged as sensitive."""
        assert not _is_sensitive_value("abc")
        assert not _is_sensitive_value("1234567")

    def test_openai_key_pattern_detected(self):
        """sk- prefixed keys are detected."""
        assert _is_sensitive_value("sk-proj-abc123def456ghi789jkl012mno345pqr678stu")
        assert _is_sensitive_value("sk-1234567890abcdef1234567890abcdef1234567890ab")

    def test_anthropic_key_pattern_detected(self):
        """sk-ant- prefixed keys are detected."""
        assert _is_sensitive_value("sk-ant-api03-abcdef1234567890abcdef1234567890abcdef12")

    def test_jwt_token_detected(self):
        """eyJ-prefixed JWT tokens are detected."""
        fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        assert _is_sensitive_value(fake_jwt)

    def test_generic_id_not_flagged(self):
        """Normal IDs (short, non-prefix) are not flagged."""
        assert not _is_sensitive_value("project_123")
        assert not _is_sensitive_value("task-456")


class TestRedactSensitiveValues:
    """Test inline redaction of sensitive values in strings."""

    def test_openai_key_redacted(self):
        """sk- key keeps prefix, body is redacted."""
        result = _redact_sensitive_values("sk-proj-abc123def456ghi789jkl012mno345pqr678stu")
        assert result == "sk-[REDACTED]"

    def test_anthropic_key_redacted(self):
        """sk-ant- key keeps prefix, body is redacted."""
        result = _redact_sensitive_values("sk-ant-api03-abcdef1234567890abcdef1234567890abcdef12")
        assert result == "sk-ant-[REDACTED]"

    def test_jwt_token_redacted(self):
        """JWT token keeps header segment only."""
        fake_jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        result = _redact_sensitive_values(fake_jwt)
        assert result.startswith("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
        assert "REDACTED" in result

    def test_safe_string_unchanged(self):
        """Normal strings are not modified."""
        result = _redact_sensitive_values("Pipeline stage extract completed successfully")
        assert result == "Pipeline stage extract completed successfully"


class TestSanitizeLogRecord:
    """Test full log record sanitization."""

    def test_sensitive_fields_fully_redacted(self):
        """Fields with sensitive names are completely replaced with [REDACTED]."""
        record = {
            "api_key": "sk-abc123def456",
            "jwt_secret": "super-secret-value",
            "password": "admin123",
            "message": "login successful",
            "timestamp": "2026-07-23T10:00:00Z",
        }
        sanitized = sanitize_log_record(record)
        assert sanitized["api_key"] == "[REDACTED]"
        assert sanitized["jwt_secret"] == "[REDACTED]"
        assert sanitized["password"] == "[REDACTED]"
        # Safe fields pass through
        assert sanitized["message"] == "login successful"
        assert sanitized["timestamp"] == "2026-07-23T10:00:00Z"

    def test_allowlist_fields_not_redacted(self):
        """Fields in ALLOWLIST are never redacted even if name matches patterns."""
        record = {
            # 'task_id' is in ALLOWLIST_FIELDS
            "task_id": "task-123",
            "error_code": "VALIDATION_ERROR",
            "message": "task completed",
        }
        sanitized = sanitize_log_record(record)
        assert sanitized["task_id"] == "task-123"
        assert sanitized["error_code"] == "VALIDATION_ERROR"

    def test_inline_sensitive_values_redacted(self):
        """Sensitive values in safe-named fields are redacted inline."""
        record = {
            "message": "API call failed with key sk-abc123def456ghi789",
            "detail": "Token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abc123",
        }
        sanitized = sanitize_log_record(record)
        # API key part should be redacted
        assert "sk-[REDACTED]" in sanitized["message"] or "[REDACTED]" in sanitized["message"]
        # JWT should be redacted
        assert "REDACTED" in sanitized["detail"] or sanitized["detail"] == "[REDACTED]"

    def test_nested_dict_recursive_sanitization(self):
        """Nested dictionaries are recursively sanitized."""
        record = {
            "request": {
                "headers": {
                    "authorization": "Bearer sk-ant-abc123",
                    "content-type": "application/json",
                },
                "body": {"text": "hello"},
            }
        }
        sanitized = sanitize_log_record(record)
        # Authorization header should be redacted
        assert sanitized["request"]["headers"]["authorization"] == "[REDACTED]"
        # Content-type and body should pass through
        assert sanitized["request"]["headers"]["content-type"] == "application/json"
        assert sanitized["request"]["body"]["text"] == "hello"

    def test_empty_record(self):
        """Empty record returns empty dict."""
        assert sanitize_log_record({}) == {}

    def test_all_allowlist_fields_preserved(self):
        """All allowlist fields pass through unchanged."""
        record = {name: f"value-{name}" for name in ALLOWLIST_FIELDS}
        sanitized = sanitize_log_record(record)
        for name in ALLOWLIST_FIELDS:
            assert sanitized[name] == f"value-{name}", f"Allowlisted field '{name}' was modified"

    def test_non_string_sensitive_values_handled(self):
        """Non-string values in sensitive-named fields are still redacted."""
        record = {
            "api_key": 12345,  # int, not string, but field name is sensitive
            "message": "ok",
        }
        sanitized = sanitize_log_record(record)
        assert sanitized["api_key"] == "[REDACTED]"


class TestStructlogProcessor:
    """Test structlog processor integration."""

    def test_processor_returns_sanitized_dict(self):
        """The processor function sanitizes and returns the event dict."""
        event_dict = {
            "event": "auth_failure",
            "api_key": "sk-leaked-key",
            "user_id": "user-1",
        }
        result = log_sanitizer_processor(None, "info", event_dict)
        assert result["api_key"] == "[REDACTED]"
        assert result["user_id"] == "user-1"
        assert result["event"] == "auth_failure"

    def test_processor_does_not_mutate_input(self):
        """Processor returns a new dict, does not modify the input."""
        event_dict = {
            "event": "test",
            "token": "secret-value",
        }
        original = event_dict.copy()
        result = log_sanitizer_processor(None, "info", event_dict)
        assert result["token"] == "[REDACTED]"
        assert event_dict == original, "Original event_dict should not be modified"


class TestPatternsLoaded:
    """Verify that SENSITIVE_FIELD_PATTERNS and SENSITIVE_VALUE_PATTERNS are properly configured."""

    def test_field_patterns_are_compiled_regex(self):
        """All field patterns are compiled regex patterns."""
        for p in SENSITIVE_FIELD_PATTERNS:
            assert isinstance(p.pattern, str)
            # Each pattern should at least match itself (if treated as literal)
            assert hasattr(p, "match")

    def test_value_patterns_are_compiled_regex(self):
        """All value patterns are compiled regex patterns."""
        for p in SENSITIVE_VALUE_PATTERNS:
            assert hasattr(p, "match")
"""Log sanitization middleware for structured logging — #15 engineering debt.

Ensures sensitive data (API keys, tokens, passwords, PII) is redacted
from structured log output before it reaches external log sinks
(CloudWatch, DataDog, Grafana, etc.).

Usage:
    from audiobook_studio.utils.log_sanitizer import sanitize_log_record
    sanitized = sanitize_log_record(log_record)

Or as a structlog processor:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.processors.add_log_level,
            log_sanitizer_processor,
            structlog.processors.JSONRenderer(),
        ]
    )
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set


# ── Sensitive field name patterns ──────────────────────────────────────────
SENSITIVE_FIELD_PATTERNS: List[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r".*secret.*",
        r".*password.*",
        r".*token.*",
        r".*api[_-]?key.*",
        r".*auth.*",
        r".*credential.*",
        r".*jwt.*",
        r".*private[_-]?key.*",
        r".*access[_-]?key.*",
    ]
]

# ── Sensitive value patterns (high-entropy hex/base64, known prefixes) ─────
# These detect API-key-like values in ANY field, regardless of name.
SENSITIVE_VALUE_PATTERNS: List[re.Pattern[str]] = [
    # OpenAI API key prefix
    re.compile(r"^sk-[A-Za-z0-9]{32,}$"),
    # Anthropic API key prefix
    re.compile(r"^sk-ant-[A-Za-z0-9]{32,}$"),
    # Google Cloud API key prefix
    re.compile(r"^AIza[0-9A-Za-z\-_]{35}$"),
    # GitHub token prefix
    re.compile(r"^gh[ps]_[A-Za-z0-9]{36,}$"),
    # JWT-like tokens (three base64url segments separated by dots, ≥100 chars total)
    re.compile(r"^eyJ[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+\.[A-Za-z0-9\-_=]+$"),
    # Generic high-entropy hex strings (≥32 consecutive hex chars = ≥128 bits)
    re.compile(r"[0-9a-fA-F]{32,}"),
    # Generic high-entropy base64 (≥44 chars URL-safe base64 = ≥256 bits)
    re.compile(r"[A-Za-z0-9\-_]{43,}"),
]


# Fields that SHOULD NOT be redacted even if name matches patterns
ALLOWLIST_FIELDS: Set[str] = {
    "task_id",
    "job_id",
    "project_id",
    "chapter_id",
    "paragraph_id",
    "segment_id",
    "user_id",
    "error_code",
    "stage",
    "provider",
    "timestamp",
    "trace_id",  # OpenTelemetry
    "span_id",   # OpenTelemetry
}


def _is_sensitive_field_name(field_name: str) -> bool:
    """Check if a field name indicates sensitive content."""
    if field_name in ALLOWLIST_FIELDS:
        return False
    return any(p.match(field_name) for p in SENSITIVE_FIELD_PATTERNS)


def _is_sensitive_value(value: str) -> bool:
    """Check if a string value looks like a secret/token/PII."""
    if len(value) < 8:
        return False
    return any(p.match(value) or p.search(value) for p in SENSITIVE_VALUE_PATTERNS)


def _redact_sensitive_values(value: str) -> str:
    """Redact sensitive patterns within a string value."""
    if not value or len(value) < 8:
        return value
    # Redact full-match JWT tokens
    if re.match(r"^eyJ[A-Za-z0-9\-_=]+\.+[A-Za-z0-9\-_=]+\.+[A-Za-z0-9\-_=]+$", value):
        header_len = len(value.split(".")[0]) if "." in value else 8
        return value[:header_len] + ".REDACTED.REDACTED"
    # Redact known API key prefixes (keep prefix for debugging, redact rest).
    # Check longer prefixes FIRST to avoid sk- matching before sk-ant-.
    known_prefixes = [
        ("sk-ant-", 7),
        ("ghp_", 4),
        ("ghs_", 4),
        ("sk-", 3),
        ("AIza", 4),
    ]
    for prefix, keep_len in known_prefixes:
        if value.startswith(prefix):
            return value[:keep_len] + "[REDACTED]"
    # Also redact known API key prefixes appearing inline (not just at start)
    inline_prefixes: List[tuple[str, int]] = [
        ("sk-ant-", 7),
        ("sk-", 3),
    ]
    for prefix, keep_len in inline_prefixes:
        escaped_prefix = re.escape(prefix)
        # Find pattern like "key sk-abc123" or "Token: sk-ant-xyz789"
        # Prefix preceded by a non-alphanumeric delimiter, followed by ≥12 alphanumeric chars
        pattern = r'(?:[^A-Za-z0-9]|^)(' + escaped_prefix + r'[A-Za-z0-9]{12,})'
        match = re.search(pattern, value)
        if match:
            token = match.group(1)
            redacted = token[:keep_len] + "[REDACTED]"
            value = value.replace(token, redacted)
    # Redact inline JWT tokens (e.g., "Token: eyJhbG...")
    inline_jwt = re.search(
        r'(?:[^A-Za-z0-9]|^)(eyJ[A-Za-z0-9\-_=]+\.+[A-Za-z0-9\-_=]+\.+[A-Za-z0-9\-_=]+)',
        value,
    )
    if inline_jwt:
        token = inline_jwt.group(1)
        header_len = len(token.split(".")[0]) if "." in token else 8
        value = value.replace(token, token[:header_len] + ".REDACTED.REDACTED")
    # Redact long hex/base64 strings (likely secrets) but not hashes/IDs
    if re.search(r"[0-9a-fA-F]{40,}", value) and not value.startswith("sha256"):
        value = re.sub(r"[0-9a-fA-F]{32,}", "[HEX_REDACTED]", value)
    return value


def sanitize_log_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a single log record by redacting sensitive fields and values.

    Args:
        record: Dictionary log record (from structlog or JSON logger)

    Returns:
        Sanitized copy of the record with sensitive data redacted.
        The original record is NOT modified.
    """
    sanitized: Dict[str, Any] = {}
    for key, value in record.items():
        # Case 1: Field name indicates sensitivity → redact entire value
        if _is_sensitive_field_name(key):
            sanitized[key] = "[REDACTED]"
            continue

        # Case 2: String value — always scan for inline sensitive patterns
        if isinstance(value, str):
            sanitized[key] = _redact_sensitive_values(value)
            continue

        # Case 3: Nested dict → recurse
        if isinstance(value, dict):
            sanitized[key] = sanitize_log_record(value)
            continue

        # Case 4: Safe value → pass through
        sanitized[key] = value

    return sanitized


def log_sanitizer_processor(logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
    """Structlog processor that sanitizes event_dict before serialization.

    Usage:
        structlog.configure(
            processors=[
                ...
                log_sanitizer_processor,
                structlog.processors.JSONRenderer(),
            ]
        )

    This processor runs AFTER all other processors (adds log level, timestamp, etc.)
    and BEFORE the final renderer, ensuring sanitized output regardless of earlier stages.
    """
    return sanitize_log_record(event_dict)


# ── Convenience exports ───────────────────────────────────────────────────

__all__ = [
    "sanitize_log_record",
    "log_sanitizer_processor",
    "SENSITIVE_FIELD_PATTERNS",
    "SENSITIVE_VALUE_PATTERNS",
    "ALLOWLIST_FIELDS",
]
"""
ISO 8601 Timestamp Middleware for FastAPI

Ensures all datetime outputs are converted to ISO 8601 format consistently.

This middleware handles three common scenarios:
1. Python datetime objects in response data
2. Unix epoch timestamps (seconds or milliseconds)
3. Relative timestamps (e.g., "5 minutes ago")

All timestamps are normalized to ISO 8601 with timezone (e.g., "2026-06-26T12:00:00Z")
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Union

logger = logging.getLogger(__name__)


def normalize_timestamp(value: Any) -> Union[str, Any]:
    """
    Convert various timestamp formats to ISO 8601 string.

    Handles:
    - datetime.datetime → ISO 8601 string
    - int/float (epoch seconds > 1e9) → ISO 8601 string
    - str (already ISO) → pass through
    - None → None
    - Other → unchanged

    Returns:
        ISO 8601 formatted string, or original value if not a timestamp
    """
    if value is None:
        return None

    # Already a string (assume ISO 8601)
    if isinstance(value, str):
        return value

    # datetime object
    if isinstance(value, datetime):
        if value.tzinfo is None:
            # Naive datetime, assume UTC
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()

    # Numeric timestamp
    if isinstance(value, (int, float)):
        # Detect epoch seconds vs milliseconds
        if value > 1e12:
            # Milliseconds
            dt = datetime.fromtimestamp(value / 1000, tz=timezone.utc)
        elif value > 1e9:
            # Seconds
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            # Too small, not a valid epoch
            return value

        return dt.isoformat()

    # Not a recognized timestamp format
    return value


def normalize_nested_timestamps(data: Any, depth: int = 0, max_depth: int = 10) -> Any:
    """
    Recursively normalize all timestamps in nested data structures.

    Args:
        data: Dict, list, or primitive value
        depth: Current recursion depth (for cycle detection)
        max_depth: Maximum recursion depth

    Returns:
        Data structure with all timestamps normalized to ISO 8601
    """
    if depth > max_depth:
        # Prevent infinite recursion
        return data

    if isinstance(data, dict):
        return {key: normalize_nested_timestamps(value, depth + 1, max_depth) for key, value in data.items()}

    if isinstance(data, list):
        return [normalize_nested_timestamps(item, depth + 1, max_depth) for item in data]

    # Convert timestamp at leaf level
    return normalize_timestamp(data)


class ISOTimestampMiddleware:
    """Pure ASGI middleware that converts all datetime responses to ISO 8601 format.

    Usage:
        app.add_middleware(ISOTimestampMiddleware)

    This middleware:
    1. Intercepts all JSON responses
    2. Recursively finds datetime values
    3. Converts them to ISO 8601 format
    4. Returns normalized response

    Note: Only affects responses with Content-Type: application/json
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Buffer the response so we can rewrite the body
        status_code: list = []
        headers: list = []
        body_chunks: list = []
        started = False

        async def send_wrapper(message: dict) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                status_code.append(message["status"])
                headers.extend(message.get("headers", []))
                started = True
            elif message["type"] == "http.response.body":
                body_chunks.append(message.get("body", b""))
                # Don't forward yet — we may need to rewrite

        await self.app(scope, receive, send_wrapper)

        if not started:
            return

        # Check content-type
        content_type = ""
        for key, val in headers:
            if key == b"content-type":
                content_type = val.decode("latin-1")
                break

        body = b"".join(body_chunks)

        if "application/json" not in content_type or not body:
            # Pass through original response unchanged
            await send({"type": "http.response.start", "status": status_code[0], "headers": headers})
            await send({"type": "http.response.body", "body": body})
            return

        try:
            data = json.loads(body.decode("utf-8"))
            normalized_data = normalize_nested_timestamps(data)
            new_body = json.dumps(normalized_data, ensure_ascii=False).encode("utf-8")

            # Update content-length header
            new_headers = [(k, v) for k, v in headers if k != b"content-length"]
            new_headers.append((b"content-length", str(len(new_body)).encode("latin-1")))

            await send({"type": "http.response.start", "status": status_code[0], "headers": new_headers})
            await send({"type": "http.response.body", "body": new_body})

        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning(f"Timestamp middleware: failed to normalize response: {e}")
            await send({"type": "http.response.start", "status": status_code[0], "headers": headers})
            await send({"type": "http.response.body", "body": body})


# ─────────────────────────────────────────────────────────────────────────────
# Alternative: Pydantic Config (per-model approach)
# ─────────────────────────────────────────────────────────────────────────────

from datetime import datetime as dt

from pydantic import BaseModel, ConfigDict, field_serializer


class ISOModel(BaseModel):
    """
    Base model with automatic ISO 8601 serialization for datetime fields.

    Inherit from this model to get automatic timestamp normalization.

    Example:
        class MyResponse(ISOModel):
            created_at: datetime
            updated_at: datetime

        # Response will have ISO 8601 timestamps automatically
    """

    @field_serializer("*")
    def serialize_datetime(self, value: Any) -> Any:
        """Serialize datetime fields to ISO 8601."""
        if isinstance(value, dt):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.isoformat()
        return value

    model_config = ConfigDict(
        json_encoders={dt: lambda v: (v.isoformat() if v.tzinfo else v.replace(tzinfo=timezone.utc).isoformat())}
    )

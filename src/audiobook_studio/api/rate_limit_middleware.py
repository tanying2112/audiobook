"""API rate-limiting middleware — S3.6 (Cloud Studio quota / rate limit).

Per-user (or per-IP fallback) token-bucket rate limiting for the REST API.
Reuses the distributed-friendly :class:`TokenBucket` from ``tts.rate_limiter``.
Honours ``settings.RATE_LIMIT_ENABLED`` so it is a no-op unless Cloud Studio
mode turns it on. Returns HTTP 429 when a client exceeds its budget.

Free-resource: in-memory buckets per worker; for multi-worker deployments a
Redis-backed bucket (already supported by ``tts.rate_limiter``) can be slotted
in without changing this middleware's contract.
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..config import get_settings
from ..tts.rate_limiter import TokenBucket

# Endpoints that should never be rate-limited (auth, health).
_EXEMPT_PREFIXES = ("/health", "/docs", "/openapi.json", "/redoc", "/api/auth")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter applied to every non-exempt request."""

    def __init__(self, app, **kwargs) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self._settings = get_settings()
        self._buckets: dict[str, TokenBucket] = defaultdict(
            lambda: TokenBucket(
                capacity=self._settings.RATE_LIMIT_BURST,
                refill_rate=self._settings.RATE_LIMIT_PER_USER_PER_MINUTE / 60.0,
            )
        )

    def _client_key(self, request: Request) -> str:
        # Prefer the authenticated principal; fall back to IP. The auth
        # dependency stores the user id on the request state when present.
        user_id = getattr(request.state, "user_id", None)
        if user_id:
            return f"u:{user_id}"
        client = request.client
        return f"ip:{client.host if client else 'unknown'}"

    async def dispatch(self, request: Request, call_next: Callable) -> object:
        path = request.url.path
        if not self._settings.RATE_LIMIT_ENABLED or path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        key = self._client_key(request)
        bucket = self._buckets[key]
        if not bucket.consume(1):
            import math

            available = bucket.get_available()
            needed = 1.0 - available
            retry_after = max(1, int(math.ceil(needed / bucket.refill_rate))) if bucket.refill_rate > 0 else 1
            return JSONResponse(
                status_code=429,
                content={"error": {"code": "RATE_LIMITED", "message": "Too many requests"}},
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)


def add_rate_limit_middleware(app) -> None:  # type: ignore[no-untyped-def]
    """Attach the rate-limit middleware to a FastAPI app (idempotent)."""
    app.add_middleware(RateLimitMiddleware)

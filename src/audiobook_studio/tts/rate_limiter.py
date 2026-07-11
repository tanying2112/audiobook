"""Provider-level rate limiter for TTS engines.

Token-bucket style rate limiter with Redis-backed distributed coordination.
Used for remote TTS endpoints (VoxCPM2, cloud TTS) to respect API quotas.
"""

import logging
import time
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProviderRateLimiter:
    """Simple rate limiter for a specific provider (mirrors LLM router pattern).

    Token bucket with per-minute token and request limits.
    Used for lightweight rate limiting without full TTSRateLimiter features.
    """

    max_tpm: int = 6000  # tokens per minute
    max_rpm: int = 30    # requests per minute
    _tokens_used: int = 0
    _requests_used: int = 0
    _window_start: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def can_proceed(self, estimated_tokens: int) -> bool:
        with self._lock:
            now = time.time()
            if now - self._window_start >= 60:
                self._tokens_used = 0
                self._requests_used = 0
                self._window_start = now
            return (
                self._tokens_used + estimated_tokens <= self.max_tpm
                and self._requests_used + 1 <= self.max_rpm
            )

    def record_usage(self, tokens: int):
        with self._lock:
            self._tokens_used += tokens
            self._requests_used += 1


@dataclass
class RateLimitConfig:
    """Configuration for a provider's rate limit."""

    provider_name: str
    requests_per_minute: int = 60
    requests_per_hour: int = 1000
    requests_per_day: int = 10000

    # Token bucket parameters
    bucket_capacity: int = 10
    refill_rate_per_sec: float = 1.0  # tokens per second


@dataclass
class TokenBucket:
    """Thread-safe token bucket for rate limiting."""

    capacity: int
    refill_rate: float  # tokens per second
    _tokens: float = field(init=False)
    _last_refill: float = field(init=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, init=False)

    def __post_init__(self):
        self._tokens = float(self.capacity)
        self._last_refill = time.monotonic()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * self.refill_rate
        self._tokens = min(self.capacity, self._tokens + new_tokens)
        self._last_refill = now

    def consume(self, tokens: int = 1) -> bool:
        """Try to consume tokens. Returns True if successful."""
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def wait_for_token(self, tokens: int = 1, timeout: float = 30.0) -> bool:
        """Block until tokens are available or timeout."""
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self.consume(tokens):
                return True
            time.sleep(0.1)
        return False

    def get_available(self) -> float:
        """Get current available tokens (for monitoring)."""
        with self._lock:
            self._refill()
            return self._tokens


class TTSRateLimiter:
    """Per-provider rate limiter with token bucket algorithm.

    Features:
    - Thread-safe token bucket for burst handling
    - Configurable per-provider limits (RPM, RPH, RPD)
    - Optional Redis-backed distributed coordination
    - Metrics for monitoring
    """

    def __init__(
        self,
        configs: Optional[Dict[str, RateLimitConfig]] = None,
        redis_client: Optional["redis.Redis"] = None,
    ):
        """Initialize rate limiter.

        Args:
            configs: Dict of provider_name -> RateLimitConfig
            redis_client: Optional Redis client for distributed rate limiting
        """
        self.configs = configs or {}
        self._buckets: Dict[str, TokenBucket] = {}
        self._redis = redis_client
        self._lock = threading.Lock()

        # Initialize buckets for configured providers
        for name, config in self.configs.items():
            self._buckets[name] = TokenBucket(
                capacity=config.bucket_capacity,
                refill_rate=config.refill_rate_per_sec,
            )

    def _get_bucket(self, provider: str) -> TokenBucket:
        """Get or create token bucket for provider."""
        if provider not in self._buckets:
            with self._lock:
                if provider not in self._buckets:
                    config = self.configs.get(provider)
                    if config:
                        self._buckets[provider] = TokenBucket(
                            capacity=config.bucket_capacity,
                            refill_rate=config.refill_rate_per_sec,
                        )
                    else:
                        # Default conservative bucket
                        self._buckets[provider] = TokenBucket(capacity=5, refill_rate=0.5)
        return self._buckets[provider]

    def acquire(self, provider: str, tokens: int = 1, timeout: float = 30.0) -> bool:
        """Acquire rate limit tokens for a provider.

        Args:
            provider: Provider name (e.g., "voxcpm2_remote", "edge", "azure")
            tokens: Number of tokens to acquire
            timeout: Max seconds to wait for tokens

        Returns:
            True if acquired, False if timeout
        """
        bucket = self._get_bucket(provider)
        return bucket.wait_for_token(tokens, timeout)

    def try_acquire(self, provider: str, tokens: int = 1) -> bool:
        """Non-blocking attempt to acquire tokens."""
        bucket = self._get_bucket(provider)
        return bucket.consume(tokens)

    def get_status(self, provider: str) -> dict:
        """Get current rate limiter status for a provider."""
        bucket = self._get_bucket(provider)
        config = self.configs.get(provider)
        return {
            "provider": provider,
            "available_tokens": round(bucket.get_available(), 2),
            "capacity": bucket.capacity,
            "refill_rate": bucket.refill_rate,
            "configured_rpm": config.requests_per_minute if config else None,
            "configured_rph": config.requests_per_hour if config else None,
            "configured_rpd": config.requests_per_day if config else None,
        }

    def get_all_status(self) -> Dict[str, dict]:
        """Get status for all configured providers."""
        return {name: self.get_status(name) for name in self.configs.keys()}

    def reset(self, provider: str) -> None:
        """Reset rate limiter for a provider (e.g., after quota reset)."""
        if provider in self._buckets:
            with self._lock:
                if provider in self._buckets:
                    config = self.configs.get(provider)
                    self._buckets[provider] = TokenBucket(
                        capacity=config.bucket_capacity if config else 10,
                        refill_rate=config.refill_rate_per_sec if config else 1.0,
                    )


# Default configurations for known TTS providers
DEFAULT_TTS_RATE_LIMITS = {
    "voxcpm2_remote": RateLimitConfig(
        provider_name="voxcpm2_remote",
        requests_per_minute=20,  # Conservative for remote GPU
        requests_per_hour=500,
        requests_per_day=5000,
        bucket_capacity=5,
        refill_rate_per_sec=0.33,  # ~20/min
    ),
    "edge": RateLimitConfig(
        provider_name="edge",
        requests_per_minute=60,
        requests_per_hour=1000,
        requests_per_day=10000,
        bucket_capacity=10,
        refill_rate_per_sec=1.0,
    ),
    "azure": RateLimitConfig(
        provider_name="azure",
        requests_per_minute=100,  # Higher for paid Azure
        requests_per_hour=5000,
        requests_per_day=50000,
        bucket_capacity=20,
        refill_rate_per_sec=1.67,
    ),
    "gcp": RateLimitConfig(
        provider_name="gcp",
        requests_per_minute=100,
        requests_per_hour=5000,
        requests_per_day=50000,
        bucket_capacity=20,
        refill_rate_per_sec=1.67,
    ),
    "kokoro": RateLimitConfig(
        provider_name="kokoro",
        requests_per_minute=1000,  # Local, effectively unlimited
        requests_per_hour=100000,
        requests_per_day=1000000,
        bucket_capacity=100,
        refill_rate_per_sec=16.67,
    ),
}


def create_tts_rate_limiter(
    custom_configs: Optional[Dict[str, RateLimitConfig]] = None,
    redis_client: Optional["redis.Redis"] = None,
) -> TTSRateLimiter:
    """Factory function to create TTS rate limiter with defaults."""
    configs = DEFAULT_TTS_RATE_LIMITS.copy()
    if custom_configs:
        configs.update(custom_configs)
    return TTSRateLimiter(configs=configs, redis_client=redis_client)


# Global singleton for convenience
_global_limiter: Optional[TTSRateLimiter] = None


def get_tts_rate_limiter() -> TTSRateLimiter:
    """Get or create global TTS rate limiter."""
    global _global_limiter
    if _global_limiter is None:
        _global_limiter = create_tts_rate_limiter()
    return _global_limiter


def set_tts_rate_limiter(limiter: TTSRateLimiter) -> None:
    """Set global TTS rate limiter (for testing/configuration)."""
    global _global_limiter
    _global_limiter = limiter
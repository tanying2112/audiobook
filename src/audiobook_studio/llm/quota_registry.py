"""Quota Registry for free-tier LLM API quota management.

Tracks per-provider quotas, integrates with circuit breaker and health probe,
provides quota-aware routing decisions for free-tier providers.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class QuotaConfig:
    """Configuration for a provider's free tier quota."""

    provider_name: str
    daily_limit: int = 0
    requests_per_minute: int = 0
    requests_per_day: int = 0
    tokens_per_minute: int = 0
    tokens_per_day: int = 0
    reset_time_utc: str = "00:00"  # Daily reset time in UTC


@dataclass
class QuotaUsage:
    """Current usage statistics for a provider."""

    provider_name: str
    requests_today: int = 0
    tokens_today: int = 0
    requests_this_minute: int = 0
    tokens_this_minute: int = 0
    last_reset_date: date = field(default_factory=date.today)
    last_reset_minute: int = field(default_factory=lambda: int(time.time() / 60))
    last_successful_request: Optional[float] = None
    consecutive_failures: int = 0
    total_failures_today: int = 0


class QuotaRegistry:
    """Registry for tracking and managing free-tier API quotas."""

    def __init__(self):
        self._configs: Dict[str, QuotaConfig] = {}
        self._usage: Dict[str, QuotaUsage] = {}
        self._lock = threading.Lock()

        # Default configurations for known free-tier providers
        self._register_defaults()

    def _register_defaults(self):
        """Register default quota configs for known providers."""
        defaults = [
            QuotaConfig(
                provider_name="gemini_flash",
                daily_limit=1500,  # 1500 requests/day free
                requests_per_minute=15,
                requests_per_day=1500,
                tokens_per_minute=30000,
                tokens_per_day=1000000,
            ),
            QuotaConfig(
                provider_name="groq_70b",
                daily_limit=1000,
                requests_per_minute=30,
                requests_per_day=1000,
                tokens_per_minute=6000,
                tokens_per_day=100000,
            ),
            QuotaConfig(
                provider_name="groq_8b",
                daily_limit=2000,
                requests_per_minute=30,
                requests_per_day=2000,
                tokens_per_minute=6000,
                tokens_per_day=100000,
            ),
            QuotaConfig(
                provider_name="cerebras",
                daily_limit=1000,
                requests_per_minute=60,
                requests_per_day=1000,
                tokens_per_minute=100000,
                tokens_per_day=1000000,
            ),
            QuotaConfig(
                provider_name="opencode_zen",
                daily_limit=500,
                requests_per_minute=20,
                requests_per_day=500,
                tokens_per_minute=50000,
                tokens_per_day=500000,
            ),
            QuotaConfig(
                provider_name="siliconcloud",
                daily_limit=1000000,  # Very generous free tier
                requests_per_minute=60,
                requests_per_day=1000000,
                tokens_per_minute=50000,
                tokens_per_day=10000000,
            ),
            QuotaConfig(
                provider_name="zhipu_glm",
                daily_limit=1000,
                requests_per_minute=60,
                requests_per_day=1000,
                tokens_per_minute=50000,
                tokens_per_day=1000000,
            ),
            QuotaConfig(
                provider_name="nvidia_nemotron",
                daily_limit=500,
                requests_per_minute=20,
                requests_per_day=500,
                tokens_per_minute=4000,
                tokens_per_day=100000,
            ),
            QuotaConfig(
                provider_name="openrouter",
                daily_limit=1000,
                requests_per_minute=20,
                requests_per_day=1000,
                tokens_per_minute=5000,
                tokens_per_day=100000,
            ),
            QuotaConfig(
                provider_name="alibaba_bailian",
                daily_limit=1000,
                requests_per_minute=100,
                requests_per_day=1000,
                tokens_per_minute=50000,
                tokens_per_day=1000000,
            ),
            QuotaConfig(
                provider_name="github_models",
                daily_limit=500,
                requests_per_minute=30,
                requests_per_day=500,
                tokens_per_minute=10000,
                tokens_per_day=100000,
            ),
            QuotaConfig(
                provider_name="cloudflare_ai",
                daily_limit=100000,  # Generous free tier
                requests_per_minute=30,
                requests_per_day=100000,
                tokens_per_minute=10000,
                tokens_per_day=1000000,
            ),
            QuotaConfig(
                provider_name="ollama_qwen25",
                daily_limit=999999999,  # Local, unlimited
                requests_per_minute=100,
                requests_per_day=999999999,
                tokens_per_minute=100000,
                tokens_per_day=999999999,
            ),
            QuotaConfig(
                provider_name="ollama_llama31",
                daily_limit=999999999,
                requests_per_minute=100,
                requests_per_day=999999999,
                tokens_per_minute=100000,
                tokens_per_day=999999999,
            ),
        ]
        for config in defaults:
            self.register_config(config)

    def register_config(self, config: QuotaConfig):
        """Register a quota configuration for a provider."""
        with self._lock:
            self._configs[config.provider_name] = config
            if config.provider_name not in self._usage:
                self._usage[config.provider_name] = QuotaUsage(provider_name=config.provider_name)

    def get_config(self, provider_name: str) -> Optional[QuotaConfig]:
        """Get quota configuration for a provider."""
        with self._lock:
            return self._configs.get(provider_name)

    def get_usage(self, provider_name: str) -> Optional[QuotaUsage]:
        """Get current usage for a provider."""
        with self._lock:
            return self._usage.get(provider_name)

    def _check_reset(self, usage: QuotaUsage):
        """Check and perform daily/minute resets if needed."""
        now = time.time()
        today = date.today()
        current_minute = int(now / 60)

        # Daily reset
        if usage.last_reset_date != today:
            usage.requests_today = 0
            usage.tokens_today = 0
            usage.total_failures_today = 0
            usage.last_reset_date = today

        # Minute reset
        if usage.last_reset_minute != current_minute:
            usage.requests_this_minute = 0
            usage.tokens_this_minute = 0
            usage.last_reset_minute = current_minute

    def can_make_request(self, provider_name: str, estimated_tokens: int = 1000) -> bool:
        """Check if a request can be made within quota limits."""
        with self._lock:
            config = self._configs.get(provider_name)
            usage = self._usage.get(provider_name)

            if not config or not usage:
                return True  # No limits configured, allow

            self._check_reset(usage)

            # Check daily limits
            if config.requests_per_day > 0 and usage.requests_today >= config.requests_per_day:
                logger.debug(f"Quota exceeded: {provider_name} daily request limit ({config.requests_per_day})")
                return False

            if config.tokens_per_day > 0 and usage.tokens_today >= config.tokens_per_day:
                logger.debug(f"Quota exceeded: {provider_name} daily token limit ({config.tokens_per_day})")
                return False

            # Check minute limits
            if config.requests_per_minute > 0 and usage.requests_this_minute >= config.requests_per_minute:
                logger.debug(f"Quota exceeded: {provider_name} per-minute request limit ({config.requests_per_minute})")
                return False

            if config.tokens_per_minute > 0 and usage.tokens_this_minute + estimated_tokens > config.tokens_per_minute:
                logger.debug(f"Quota exceeded: {provider_name} per-minute token limit ({config.tokens_per_minute})")
                return False

            return True

    def record_request(self, provider_name: str, tokens_used: int = 0, success: bool = True):
        """Record a request for quota tracking."""
        with self._lock:
            usage = self._usage.get(provider_name)
            if not usage:
                return

            self._check_reset(usage)

            if success:
                usage.requests_today += 1
                usage.requests_this_minute += 1
                usage.tokens_today += tokens_used
                usage.tokens_this_minute += tokens_used
                usage.last_successful_request = time.time()
                usage.consecutive_failures = 0
            else:
                usage.consecutive_failures += 1
                usage.total_failures_today += 1

    def get_quota_status(self, provider_name: str) -> Dict:
        """Get detailed quota status for a provider."""
        with self._lock:
            config = self._configs.get(provider_name)
            usage = self._usage.get(provider_name)

            if not config or not usage:
                return {
                    "provider": provider_name,
                    "configured": False,
                    "healthy": True,
                }

            self._check_reset(usage)

            daily_request_pct = 0
            daily_token_pct = 0
            minute_request_pct = 0
            minute_token_pct = 0

            if config.requests_per_day > 0:
                daily_request_pct = round(usage.requests_today / config.requests_per_day * 100, 1)
            if config.tokens_per_day > 0:
                daily_token_pct = round(usage.tokens_today / config.tokens_per_day * 100, 1)
            if config.requests_per_minute > 0:
                minute_request_pct = round(usage.requests_this_minute / config.requests_per_minute * 100, 1)
            if config.tokens_per_minute > 0:
                minute_token_pct = round(usage.tokens_this_minute / config.tokens_per_minute * 100, 1)

            return {
                "provider": provider_name,
                "configured": True,
                "daily": {
                    "requests_used": usage.requests_today,
                    "requests_limit": config.requests_per_day,
                    "requests_pct": daily_request_pct,
                    "tokens_used": usage.tokens_today,
                    "tokens_limit": config.tokens_per_day,
                    "tokens_pct": daily_token_pct,
                },
                "minute": {
                    "requests_used": usage.requests_this_minute,
                    "requests_limit": config.requests_per_minute,
                    "requests_pct": minute_request_pct,
                    "tokens_used": usage.tokens_this_minute,
                    "tokens_limit": config.tokens_per_minute,
                    "tokens_pct": minute_token_pct,
                },
                "health": {
                    "consecutive_failures": usage.consecutive_failures,
                    "total_failures_today": usage.total_failures_today,
                    "last_successful_request": usage.last_successful_request,
                },
                "healthy": daily_request_pct < 95 and daily_token_pct < 95
                    and minute_request_pct < 90 and minute_token_pct < 90
                    and usage.consecutive_failures < 5,
            }

    def get_all_statuses(self) -> Dict[str, Dict]:
        """Get quota status for all registered providers."""
        # Get snapshot of provider names to avoid holding lock while calling get_quota_status
        with self._lock:
            provider_names = list(self._configs.keys())

        # Build statuses without holding the lock
        return {name: self.get_quota_status(name) for name in provider_names}

    def get_healthy_providers(self) -> List[str]:
        """Get list of providers with available quota."""
        # Get snapshot of provider names to avoid holding lock while calling get_quota_status
        with self._lock:
            provider_names = list(self._configs.keys())

        # Build statuses without holding the lock
        return [name for name in provider_names if self.get_quota_status(name).get("healthy", True)]

    def get_quota_health_score(self, provider_name: str) -> float:
        """Get a health score (0-1) for a provider based on quota availability."""
        status = self.get_quota_status(provider_name)
        if not status.get("configured", False):
            return 1.0

        daily_pct = max(status["daily"]["requests_pct"], status["daily"]["tokens_pct"])
        minute_pct = max(status["minute"]["requests_pct"], status["minute"]["tokens_pct"])

        # Score decreases as usage approaches limits
        daily_score = max(0, 1 - daily_pct / 100)
        minute_score = max(0, 1 - minute_pct / 100)

        # Failure penalty
        failure_penalty = min(0.5, status["health"]["consecutive_failures"] * 0.1)

        return max(0, min(daily_score, minute_score) - failure_penalty)


# Backward compatibility shims (DEPRECATED)
# Use get_app_container().get(QuotaRegistry) instead
def get_quota_registry() -> QuotaRegistry:
    """Deprecated: use get_app_container().get(QuotaRegistry)"""
    from ..di import get_app_container
    return get_app_container().get(QuotaRegistry)


def init_quota_registry() -> QuotaRegistry:
    """Deprecated: container manages lifecycle"""
    return get_quota_registry()

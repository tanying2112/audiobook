"""Health Probe for LLM provider availability detection.

Periodically pings provider endpoints to detect outages, quota exhaustion,
and latency degradation. Results feed into circuit breaker and routing decisions.
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)


@dataclass
class HealthStatus:
    """Health status for a single provider."""

    provider: str
    is_healthy: bool = True
    latency_ms: float = 0.0
    last_check: datetime = field(default_factory=datetime.now)
    error_message: Optional[str] = None
    quota_remaining: Optional[int] = None
    quota_limit: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "is_healthy": self.is_healthy,
            "latency_ms": round(self.latency_ms, 1),
            "last_check": self.last_check.isoformat(),
            "error_message": self.error_message,
            "quota_remaining": self.quota_remaining,
            "quota_limit": self.quota_limit,
        }


class HealthProbe:
    """Periodic health probe for LLM providers."""

    def __init__(
        self,
        providers: List[Any],
        interval_s: float = 300.0,
        timeout_s: float = 10.0,
    ):
        self.providers = {p.name: p for p in providers}
        self.interval_s = interval_s
        self.timeout_s = timeout_s
        self.statuses: Dict[str, HealthStatus] = {}
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        for p in providers:
            self.statuses[p.name] = HealthStatus(provider=p.name)

    def start(self):
        """Start background health probe thread."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._probe_loop, daemon=True)
        self._thread.start()
        logger.info(f"Health probe started (interval={self.interval_s}s)")

    def stop(self):
        """Stop background health probe thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        logger.info("Health probe stopped")

    def _probe_loop(self):
        """Background loop that probes providers periodically."""
        while not self._stop_event.is_set():
            self._probe_all()
            self._stop_event.wait(self.interval_s)

    def _probe_all(self):
        """Probe all registered providers."""
        for name, provider in self.providers.items():
            try:
                self._probe_provider(name, provider)
            except Exception as e:
                self.statuses[name] = HealthStatus(
                    provider=name,
                    is_healthy=False,
                    error_message=str(e),
                )

    def _probe_provider(self, name: str, provider: Any):
        """Probe a single provider with a lightweight /models request."""
        base_url = getattr(provider, "base_url", None)
        if not base_url:
            self.statuses[name] = HealthStatus(provider=name, is_healthy=True)
            return

        api_key = provider.get_api_key()
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        start = time.time()
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                # Ollama uses /api/tags endpoint instead of /models
                if base_url == "http://localhost:11434" or base_url and "11434" in base_url:
                    resp = client.get(f"{base_url}/api/tags", headers=headers)
                else:
                    resp = client.get(f"{base_url}/models", headers=headers)
                latency = (time.time() - start) * 1000

                quota_remaining = None
                quota_limit = None
                if "x-ratelimit-remaining" in resp.headers:
                    try:
                        quota_remaining = int(resp.headers["x-ratelimit-remaining"])
                    except (ValueError, TypeError):
                        pass
                if "x-ratelimit-limit" in resp.headers:
                    try:
                        quota_limit = int(resp.headers["x-ratelimit-limit"])
                    except (ValueError, TypeError):
                        pass

                self.statuses[name] = HealthStatus(
                    provider=name,
                    is_healthy=resp.status_code == 200,
                    latency_ms=latency,
                    quota_remaining=quota_remaining,
                    quota_limit=quota_limit,
                )
                if resp.status_code != 200:
                    logger.warning(f"Health probe [{name}] status={resp.status_code}")
        except httpx.TimeoutException:
            self.statuses[name] = HealthStatus(
                provider=name,
                is_healthy=False,
                latency_ms=(time.time() - start) * 1000,
                error_message="timeout",
            )
        except Exception as e:
            self.statuses[name] = HealthStatus(
                provider=name,
                is_healthy=False,
                error_message=str(e),
            )

    def probe_now(self, name: str) -> HealthStatus:
        """Immediately probe a specific provider and return status."""
        if name not in self.providers:
            return HealthStatus(provider=name, is_healthy=False, error_message="not found")
        self._probe_provider(name, self.providers[name])
        return self.statuses[name]

    def get_status(self, name: str) -> HealthStatus:
        """Get cached health status for a provider."""
        return self.statuses.get(name, HealthStatus(provider=name, is_healthy=True))

    def get_all_statuses(self) -> Dict[str, HealthStatus]:
        """Get all cached health statuses."""
        return dict(self.statuses)

    def is_healthy(self, name: str) -> bool:
        """Check if a provider is healthy."""
        status = self.statuses.get(name)
        return status.is_healthy if status else True

    def get_healthy_providers(self) -> List[str]:
        """Get list of healthy provider names."""
        return [name for name, s in self.statuses.items() if s.is_healthy]

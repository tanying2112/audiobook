"""Health Probe for LLM provider availability detection.

Periodically pings provider endpoints to detect outages, quota exhaustion,
and latency degradation. Results feed into circuit breaker and routing decisions.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# When set (e.g. by the test harness), HealthProbe never spawns its background
# thread. The real probe pings live provider endpoints; under unit tests the
# configured providers are frequently MagicMocks whose ``base_url`` is truthy,
# so the probe would mark them unhealthy asynchronously and the router would
# skip them at the ``is_healthy`` guard. That races with ``router.call`` (a
# query succeeds in isolated runs but is skipped under heavy load), producing
# order-dependent failures. Disabling the thread keeps probe state empty (every
# provider treated as healthy) and removes a CPU-contending daemon thread that
# can push slow global checks (mypy --strict) past their timeout.
_DISABLE_ENV = "AUDIOBOOK_DISABLE_HEALTH_PROBE"


def is_probe_disabled() -> bool:
    """True when the health-probe background thread should be suppressed."""
    return os.environ.get(_DISABLE_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


# Registry of HealthProbe instances with a live background thread. Used by the
# test harness (and operational shutdown) to guarantee no probe thread leaks
# across tests. A leaked daemon thread keeps pinging providers and contends for
# CPU, which can push slow global checks (e.g. mypy --strict) past their timeout.
_active_probes: "set[HealthProbe]" = set()


def stop_all_health_probes() -> None:
    """Stop every currently-running HealthProbe background thread.

    Safe to call multiple times / when none are running.
    """
    for probe in list(_active_probes):
        try:
            probe.stop()
        except Exception:  # pragma: no cover - defensive
            pass
    _active_probes.clear()


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
        self._registered = False

        for p in providers:
            self.statuses[p.name] = HealthStatus(provider=p.name)

    def start(self):
        """Start background health probe thread.

        No-op when the probe is disabled via ``AUDIOBOOK_DISABLE_HEALTH_PROBE``
        (see :func:`is_probe_disabled`) – the probe is left in a healthy state
        without spawning any thread.
        """
        if is_probe_disabled():
            logger.info("Health probe disabled by env, not starting thread")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._probe_loop, daemon=True)
        self._thread.start()
        _active_probes.add(self)
        self._registered = True
        logger.info(f"Health probe started (interval={self.interval_s}s)")

    def stop(self):
        """Stop background health probe thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5.0)
        if self._registered:
            _active_probes.discard(self)
            self._registered = False
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

        # Resolve health-check path: explicit health_path wins; Ollama has no
        # /models so it falls to /api/tags; otherwise default to /models
        # (OpenAI-compatible). Anthropic gateways (fcc) set health_path=/health.
        import os as _os

        health_path = getattr(provider, "health_path", None) or "/models"
        if base_url == "http://localhost:11434" or (base_url and "11434" in base_url):
            if not getattr(provider, "health_path", None):
                health_path = "/api/tags"

        start = time.time()
        try:
            with httpx.Client(timeout=self.timeout_s) as client:
                resp = client.get(f"{base_url}{health_path}", headers=headers)
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

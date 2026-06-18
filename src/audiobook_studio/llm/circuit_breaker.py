"""Circuit Breaker for LLM provider failure isolation.

Three-state machine: CLOSED (normal) → OPEN (blocked) → HALF_OPEN (testing)
- CLOSED: Normal operation, counting failures
- OPEN: Provider blocked, skipping all calls
- HALF_OPEN: Testing with limited calls, promoting back to CLOSED on success
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreaker:
    """Three-state circuit breaker for provider failure isolation."""

    provider_name: str
    failure_threshold: int = 3
    recovery_timeout_s: float = 120.0
    half_open_max_calls: int = 1

    state: Literal["closed", "open", "half_open"] = "closed"
    failure_count: int = 0
    last_failure_time: float = 0.0
    half_open_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def can_proceed(self) -> bool:
        """Check if a call is allowed through the circuit breaker."""
        with self._lock:
            if self.state == "closed":
                return True
            if self.state == "open":
                elapsed = time.time() - self.last_failure_time
                if elapsed >= self.recovery_timeout_s:
                    self.state = "half_open"
                    self.half_open_calls = 0
                    logger.info(
                        f"Circuit breaker [{self.provider_name}] "
                        f"OPEN → HALF_OPEN after {elapsed:.0f}s cooldown"
                    )
                    return True
                return False
            # half_open: allow limited calls
            return self.half_open_calls < self.half_open_max_calls

    def record_success(self):
        """Record a successful call."""
        with self._lock:
            if self.state == "half_open":
                self.state = "closed"
                self.failure_count = 0
                self.half_open_calls = 0
                logger.info(
                    f"Circuit breaker [{self.provider_name}] "
                    f"HALF_OPEN → CLOSED (success)"
                )
            elif self.state == "closed":
                self.failure_count = max(0, self.failure_count - 1)

    def record_failure(self):
        """Record a failed call."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == "half_open":
                self.state = "open"
                logger.warning(
                    f"Circuit breaker [{self.provider_name}] "
                    f"HALF_OPEN → OPEN (failure during recovery)"
                )
            elif self.failure_count >= self.failure_threshold:
                self.state = "open"
                logger.warning(
                    f"Circuit breaker [{self.provider_name}] "
                    f"CLOSED → OPEN ({self.failure_count} consecutive failures)"
                )

    def reset(self):
        """Manually reset the circuit breaker to closed state."""
        with self._lock:
            self.state = "closed"
            self.failure_count = 0
            self.half_open_calls = 0
            logger.info(f"Circuit breaker [{self.provider_name}] manually reset to CLOSED")

    def get_status(self) -> dict:
        """Get current circuit breaker status."""
        return {
            "provider": self.provider_name,
            "state": self.state,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "recovery_timeout_s": self.recovery_timeout_s,
            "seconds_since_last_failure": (
                round(time.time() - self.last_failure_time, 1)
                if self.last_failure_time > 0
                else None
            ),
        }

"""API Key Pool for multi-key rotation across LLM providers.

Supports round_robin and weighted rotation strategies to maximize
throughput by distributing load across multiple API keys per provider.
"""

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class KeySlot:
    """A single API key with its usage stats."""

    key: str
    env_var: str
    requests_count: int = 0
    failure_count: int = 0
    last_used: float = 0.0
    cooldown_until: float = 0.0

    @property
    def is_available(self) -> bool:
        """Check if this key is available (not in cooldown)."""
        return time.time() >= self.cooldown_until

    def record_use(self) -> None:
        """Record a successful use."""
        self.requests_count += 1
        self.last_used = time.time()

    def record_failure(self, cooldown_s: float = 60.0) -> None:
        """Record a failure and apply cooldown."""
        self.failure_count += 1
        self.cooldown_until = time.time() + cooldown_s


class ApiKeyPool:
    """Multi-key rotation manager for a single provider."""

    def __init__(
        self,
        provider_name: str,
        primary_key_env: str,
        pool_key_envs: Optional[List[str]] = None,
        strategy: str = "round_robin",
        cooldown_s: float = 60.0,
    ) -> None:
        self.provider_name = provider_name
        self.strategy = strategy
        self.cooldown_s = cooldown_s
        self._lock = threading.Lock()
        self._index = 0

        self.keys: List[KeySlot] = []

        primary_key = os.getenv(primary_key_env, "")
        if primary_key:
            self.keys.append(KeySlot(key=primary_key, env_var=primary_key_env))

        for env_var in pool_key_envs or []:
            key = os.getenv(env_var, "")
            if key:
                self.keys.append(KeySlot(key=key, env_var=env_var))

    @property
    def size(self) -> int:
        """Number of available keys."""
        return len(self.keys)

    def get_key(self) -> Optional[str]:
        """Get the next available API key using the configured strategy."""
        if not self.keys:
            return None

        with self._lock:
            available = [k for k in self.keys if k.is_available]
            if not available:
                logger.warning(
                    f"All keys for {self.provider_name} in cooldown, "
                    f"using least-cooldown key"
                )
                available = sorted(self.keys, key=lambda k: k.cooldown_until)

            if self.strategy == "round_robin":
                key_slot = available[self._index % len(available)]
                self._index = (self._index + 1) % len(available)
            else:  # weighted or fallback to round_robin
                key_slot = min(
                    available,
                    key=lambda k: (k.failure_count, k.requests_count),
                )

            key_slot.record_use()
            return key_slot.key

    def record_failure(self) -> None:
        """Record a failure for the current key (applies cooldown)."""
        with self._lock:
            for key_slot in self.keys:
                if key_slot.last_used > 0 and key_slot.is_available:
                    key_slot.record_failure(self.cooldown_s)
                    break

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        return {
            "provider": self.provider_name,
            "strategy": self.strategy,
            "total_keys": len(self.keys),
            "available_keys": sum(1 for k in self.keys if k.is_available),
            "total_requests": sum(k.requests_count for k in self.keys),
            "total_failures": sum(k.failure_count for k in self.keys),
        }


class KeyPoolManager:
    """Manages ApiKeyPools across multiple providers."""

    def __init__(self) -> None:
        self._pools: Dict[str, ApiKeyPool] = {}
        self._lock = threading.Lock()

    def register(
        self,
        provider_name: str,
        primary_key_env: str,
        pool_key_envs: Optional[List[str]] = None,
        strategy: str = "round_robin",
        cooldown_s: float = 60.0,
    ) -> None:
        """Register a key pool for a provider."""
        with self._lock:
            self._pools[provider_name] = ApiKeyPool(
                provider_name=provider_name,
                primary_key_env=primary_key_env,
                pool_key_envs=pool_key_envs or [],
                strategy=strategy,
                cooldown_s=cooldown_s,
            )

    def get_key(self, provider_name: str) -> Optional[str]:
        """Get next API key for a provider."""
        pool = self._pools.get(provider_name)
        if pool:
            return pool.get_key()
        return None

    def record_failure(self, provider_name: str) -> None:
        """Record a failure for a provider's current key."""
        pool = self._pools.get(provider_name)
        if pool:
            pool.record_failure()

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """Get stats for all pools."""
        return {name: pool.get_stats() for name, pool in self._pools.items()}

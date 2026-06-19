"""Enhanced LLM Router with config-based routing, prompt compression, and extensible provider support.

Features:
- Config-driven provider management (YAML-based)
- Prompt compression for token limit handling
- Extensible provider registry (cloud + local)
- Automatic fallback with rate limit awareness
- Per-provider rate limit tracking
- Dynamic provider registration
- Circuit breaker for failure isolation
- Health probe for provider availability
- Multi-key rotation pool
- Token budget prediction
- Kill Switch heuristic fallback
"""

import json
import logging
import os
import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

from ..schemas import (
    BookAnalysisOutput,
    ExtractionResult,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
    TtsRoutingDecision,
)
from .circuit_breaker import CircuitBreaker
from .client import LLMCallResult, LLMClient, LLMClientConfig, create_client
from .config_loader import LLMProvidersConfig, ProviderConfig, ProviderType, StageName
from .health_probe import HealthProbe, HealthStatus
from .key_pool import KeyPoolManager

# Langfuse monitoring - use lazy import to avoid circular dependency
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from ..monitoring.langfuse_client import (
        init_langfuse,
        is_enabled as langfuse_is_enabled,
        observe_llm_call,
        span,
    )

# trace_function is imported at runtime in the lazy decorator below

# Runtime imports will be done in functions



def _lazy_trace_function(stage: str):
    """Lazy-loading decorator for trace_function to avoid import-time errors."""
    def decorator(func):
        from functools import wraps
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                from ..monitoring.langfuse_client import trace_function
                return trace_function(name=func.__name__, stage=stage)(func)(*args, **kwargs)
            except Exception:
                # If langfuse not available or any error, run without tracing
                return func(*args, **kwargs)
        return wrapper
    return decorator

logger = logging.getLogger(__name__)

T = TypeVar("T")


@dataclass
class ModelConfig:
    """Configuration for a single model."""

    name: str
    provider: str = ""
    priority: int = 0
    enabled: bool = True
    max_daily_cost_usd: float = 10.0
    temperature: float = 0.1
    max_tokens: int = 4000
    max_tpm: int = 6000  # Tokens per minute limit
    max_rpm: int = 30  # Requests per minute limit


@dataclass
class StageRoutingConfig:
    """Routing configuration for a pipeline stage."""

    stage: str
    models: List[ModelConfig]  # Ordered by priority
    fallback_model: Optional[str] = None


@dataclass
class ProviderRateLimiter:
    """Rate limiter for a specific provider."""

    max_tpm: int = 6000
    max_rpm: int = 30
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
class CostTracker:
    """Tracks costs per model per day with thread safety."""

    _costs: Dict[str, Dict[date, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _daily_limits: Dict[str, float] = field(default_factory=dict)
    _alert_threshold: float = 0.8

    def add_cost(self, model: str, cost_usd: float):
        today = date.today()
        with self._lock:
            self._costs[model][today] += cost_usd

    def get_daily_cost(self, model: str, day: Optional[date] = None) -> float:
        if day is None:
            day = date.today()
        with self._lock:
            return self._costs[model].get(day, 0.0)

    def get_total_daily_cost(self, day: Optional[date] = None) -> float:
        if day is None:
            day = date.today()
        with self._lock:
            total = 0.0
            for model_costs in self._costs.values():
                total += model_costs.get(day, 0.0)
            return total

    def set_daily_limit(self, model: str, limit_usd: float):
        with self._lock:
            self._daily_limits[model] = limit_usd

    def is_limit_exceeded(self, model: str) -> bool:
        limit = self._daily_limits.get(model, float("inf"))
        current = self.get_daily_cost(model)
        return current >= limit

    def is_alert_threshold(self, model: str) -> bool:
        limit = self._daily_limits.get(model, float("inf"))
        current = self.get_daily_cost(model)
        return current >= limit * self._alert_threshold

    def get_status(self) -> Dict[str, Any]:
        today = date.today()
        with self._lock:
            status = {}
            for model in set(
                list(self._costs.keys()) + list(self._daily_limits.keys())
            ):
                current = self._costs[model].get(today, 0.0)
                limit = self._daily_limits.get(model, None)
                status[model] = {
                    "daily_cost_usd": round(current, 6),
                    "daily_limit_usd": limit,
                    "limit_exceeded": current >= (limit or float("inf")),
                    "alert_triggered": limit
                    and current >= limit * self._alert_threshold,
                    "usage_pct": round(current / limit * 100, 1) if limit else 0,
                }
            return status


_cost_tracker = CostTracker()


def get_cost_tracker() -> CostTracker:
    return _cost_tracker


def reset_cost_tracker():
    global _cost_tracker
    _cost_tracker = CostTracker()


class PromptCompressor:
    """Compress prompts to fit within token limits."""

    def __init__(self, config: LLMProvidersConfig):
        self.config = config
        self.max_tokens = config.prompt_compression.max_input_tokens
        self.strategy = config.prompt_compression.truncate_strategy
        self.remove_few_shot = config.prompt_compression.remove_few_shot_when_long
        self.min_few_shot = config.prompt_compression.min_few_shot_examples
        self.schema_mode = config.prompt_compression.schema_injection_mode

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (4 chars per token for Chinese, 3 for English)."""
        chinese = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
        total = len(text)
        return int(chinese / 4 + (total - chinese) / 3)

    def compress(self, prompt: str, schema_json: str, few_shot: str) -> tuple[str, int]:
        """Compress prompt to fit within token limits."""
        schema_tokens = self.estimate_tokens(schema_json)
        few_shot_tokens = self.estimate_tokens(few_shot)
        prompt_base_tokens = self.estimate_tokens(prompt)

        total = schema_tokens + few_shot_tokens + prompt_base_tokens

        if total <= self.max_tokens:
            return prompt, total

        # Need to compress
        if self.remove_few_shot and few_shot_tokens > 0:
            # Remove few-shot examples first
            few_shot = ""
            few_shot_tokens = 0
            total = schema_tokens + prompt_base_tokens

        if total > self.max_tokens:
            # Truncate prompt based on strategy
            if self.strategy == "head":
                # Keep beginning
                ratio = self.max_tokens / total
                keep_chars = int(len(prompt) * ratio * 0.9)
                prompt = prompt[:keep_chars] + "\n[截断...]"
            elif self.strategy == "tail":
                # Keep end
                ratio = self.max_tokens / total
                keep_chars = int(len(prompt) * ratio * 0.9)
                prompt = "[截断...]\n" + prompt[-keep_chars:]
            else:  # smart - keep both ends
                ratio = self.max_tokens / total
                keep_chars = int(len(prompt) * ratio * 0.9)
                half = keep_chars // 2
                prompt = prompt[:half] + "\n[中间省略...]\n" + prompt[-half:]

        final_tokens = self.estimate_tokens(prompt) + schema_tokens + few_shot_tokens
        return prompt, final_tokens


class LLMRouter:
    def __init__(self, mock_mode: bool = False, config_path: str = None):
        self.mock_mode = mock_mode
        self.clients = {}
        self.rate_limiters = {}
        self.cost_tracker = get_cost_tracker()

        # Load provider config
        self.config = LLMProvidersConfig.load(config_path)
        self.prompt_compressor = PromptCompressor(self.config)

        # Initialize Langfuse tracing - lazy import to avoid circular dependency
        if not mock_mode:
            self.langfuse_public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
            self.langfuse_secret_key = os.getenv("LANGFUSE_SECRET_KEY")
            self.langfuse_host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
            self._langfuse_initialized = False
            self._init_langfuse()
        else:
            self.langfuse_public_key = None
            self.langfuse_secret_key = None
            self.langfuse_host = None
            self._langfuse_initialized = True  # Skip initialization in mock mode

        # Circuit breakers per provider
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}

        # Health probe
        self.health_probe: Optional[HealthProbe] = None

        # Key pool manager
        self.key_pool = KeyPoolManager()

        # Free tier tracking
        self._free_quota_success: Dict[str, int] = defaultdict(int)
        self._free_quota_fail: Dict[str, int] = defaultdict(int)

        # Initialize components for each provider
        for provider in self.config.get_all_enabled():
            self.rate_limiters[provider.name] = ProviderRateLimiter(
                max_tpm=provider.max_tokens_per_minute,
                max_rpm=provider.max_requests_per_minute,
            )
            self.circuit_breakers[provider.name] = CircuitBreaker(
                provider_name=provider.name,
                failure_threshold=3,
                recovery_timeout_s=120.0,
            )

            # Register key pool
            self.key_pool.register(
                provider_name=provider.name,
                primary_key_env=provider.api_key_env or "",
                pool_key_envs=provider.api_key_pool_env,
                strategy=provider.key_rotation_strategy,
            )

            # Load daily limits from config
            self.cost_tracker.set_daily_limit(
                provider.name, provider.max_daily_cost_usd
            )

        # Initialize Langfuse lazy attributes
        self._langfuse_enabled_cached = False

        # Start health probe
        enabled_providers = self.config.get_all_enabled()
        if enabled_providers:
            self.health_probe = HealthProbe(
                providers=enabled_providers,
                interval_s=300.0,
                timeout_s=10.0,
            )
            if not mock_mode:
                try:
                    self.health_probe.start()
                except Exception:
                    logger.warning("Failed to start health probe")

    def _init_langfuse(self):
        """Lazy initialization of Langfuse."""
        if self._langfuse_initialized:
            return
        try:
            from ..monitoring.langfuse_client import init_langfuse
            init_langfuse(
                public_key=self.langfuse_public_key,
                secret_key=self.langfuse_secret_key,
                host=self.langfuse_host,
                enabled=True,
            )
            self._langfuse_initialized = True
        except Exception as e:
            logger.warning(f"Failed to initialize Langfuse: {e}")

    def _is_langfuse_enabled(self) -> bool:
        """Check if Langfuse is enabled (cached)."""
        if not self._langfuse_enabled_cached:
            try:
                from ..monitoring.langfuse_client import is_enabled as langfuse_is_enabled
                self._langfuse_enabled_cached = langfuse_is_enabled()
            except Exception:
                self._langfuse_enabled_cached = False
        return self._langfuse_enabled_cached

    def get_client(self, provider: ProviderConfig) -> LLMClient:
        key = provider.name
        if key not in self.clients:
            # Initialize Langfuse if not already done
            if self.langfuse_public_key and self.langfuse_secret_key and not self._langfuse_initialized:
                self._init_langfuse()
            self.clients[key] = create_client(
                provider.get_litellm_model_name(),
                mock_mode=self.mock_mode,
                api_base=provider.base_url,
                langfuse_public_key=self.langfuse_public_key,
                langfuse_secret_key=self.langfuse_secret_key,
                langfuse_host=self.langfuse_host,
                langfuse_enabled=self._is_langfuse_enabled(),
            )
        return self.clients[key]

    def _build_messages(
        self, stage: StageName, prompt: str, schema_json: str, few_shot: str
    ) -> list:
        return [
            {
                "role": "system",
                "content": f"你是专业的有声书{stage.value}专家。请严格按照 JSON Schema 输出。",
            },
            {"role": "user", "content": prompt},
        ]

    def _get_few_shot(self, stage: StageName) -> str:
        return "（暂无示例）"

    def _get_schema_json(self, response_model) -> str:
        return json.dumps(response_model.model_json_schema(), ensure_ascii=False)

    def _select_provider(
        self, providers: List[ProviderConfig], estimated_tokens: int
    ) -> Optional[ProviderConfig]:
        """Select the best available provider with multi-layer filtering."""
        from ..monitoring.langfuse_client import span

        with span("router.select_provider", metadata={"estimated_tokens": estimated_tokens}) as s:
            for provider in providers:
                # Layer 1: Circuit breaker check
                cb = self.circuit_breakers.get(provider.name)
                if cb and not cb.can_proceed():
                    logger.debug(f"Circuit breaker open for {provider.name}, skipping")
                    continue

                # Layer 2: Rate limit check
                if not self.rate_limiters[provider.name].can_proceed(estimated_tokens):
                    logger.debug(f"Rate limit near for {provider.name}, skipping")
                    continue

                # Layer 3: Cost limit check
                if self.cost_tracker.is_limit_exceeded(provider.name):
                    logger.debug(f"Daily cost limit exceeded for {provider.name}")
                    continue

                # Layer 4: Health probe check (if available)
                if self.health_probe and not self.health_probe.is_healthy(provider.name):
                    logger.debug(
                        f"Health probe reports {provider.name} unhealthy, skipping"
                    )
                    continue

                # Layer 5: Free quota prediction (for free-tier providers)
                if provider.max_daily_cost_usd == 0:
                    success = self._free_quota_success.get(provider.name, 0)
                    fail = self._free_quota_fail.get(provider.name, 0)
                    total = success + fail
                    if total > 10 and (fail / total) > 0.3:
                        logger.debug(
                            f"Free tier {provider.name} has high failure rate "
                            f"({fail}/{total}), skipping"
                        )
                        continue

                if s:
                    s.update(metadata={"selected_provider": provider.name})
                return provider

            if s:
                s.update(metadata={"selected_provider": None})
            return None

    def _heuristic_fallback(self, stage: str, response_model) -> Optional[Any]:
        """Kill Switch: pure rule-based fallback when ALL LLM providers fail."""
        from ..monitoring.langfuse_client import span

        with span("router.heuristic_fallback", metadata={"stage": stage}) as s:
            logger.warning(
                f"All LLM providers failed for stage {stage}, using heuristic fallback"
            )

            if stage == "annotate":
                result = ParagraphAnnotation(
                    paragraph_index=0,
                    speaker_canonical_name="_narrator_",
                    is_dialogue=False,
                    emotion="neutral",
                    emotion_intensity=0.3,
                    speech_rate=1.0,
                    pitch_shift_semitones=0,
                    confidence=0.2,
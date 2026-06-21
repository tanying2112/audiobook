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
    FeedbackAnalysis,
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
from .quota_registry import QuotaRegistry, get_quota_registry

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

from .utils import LLMParseError, validate_and_parse_llm_response


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


# Hardware profile integration
from ..config.hardware_profile import get_hardware_profile, HardwareProfile
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
    def __init__(self, mock_mode: bool = False, config_path: str = None, hardware_profile: Optional[HardwareProfile] = None):
        self.mock_mode = mock_mode
        self.clients = {}
        self.rate_limiters = {}
        self.cost_tracker = get_cost_tracker()

        # Load provider config
        self.config = LLMProvidersConfig.load(config_path)
        
        # Hardware profile integration for stage-specific model routing
        self.hardware_profile = hardware_profile or get_hardware_profile()
        
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

        # Quota registry for free-tier management
        self.quota_registry = get_quota_registry()

        # Free tier tracking (legacy, kept for backward compatibility)
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
        """Build messages with explicit JSON output requirement."""
        system_content = (
            f"你是专业的有声书{stage.value}专家。"
            f"请严格按照 JSON Schema 输出，不要包含任何额外文本、解释或代码块标记。"
            f"输出必须是有效的 JSON 对象。"
        )
        return [
            {"role": "system", "content": system_content},
            {"role": "user", "content": prompt},
        ]

    def _get_few_shot(self, stage: StageName) -> str:
        return "（暂无示例）"

    def _get_schema_json(self, response_model) -> str:
        return json.dumps(response_model.model_json_schema(), ensure_ascii=False)

    def _apply_hardware_profile_routing(
        self, stage: str, providers: List[ProviderConfig], stage_models: List[Dict[str, Any]]
    ) -> List[ProviderConfig]:
        """Reorder and filter providers based on hardware profile stage model map.

        Args:
            stage: Pipeline stage name
            providers: Available providers from config
            stage_models: Hardware profile model mapping for this stage (list of dicts with provider, model, priority)

        Returns:
            Reordered and filtered list of providers
        """
        if not stage_models:
            return providers

        # Build a mapping of provider name -> config for quick lookup
        provider_map = {p.name: p for p in providers}

        # Build ordered list based on hardware profile priority
        ordered = []
        seen = set()

        for model_config in stage_models:
            provider_name = model_config.get("provider")
            model_name = model_config.get("model")
            priority = model_config.get("priority", 999)

            if provider_name in provider_map and provider_name not in seen:
                provider = provider_map[provider_name]
                # Update the model if specified in hardware profile
                if model_name:
                    # We can't easily change the model at runtime with LiteLLM
                    # But we can note the preferred model
                    provider.extra_params = provider.extra_params or {}
                    provider.extra_params["hardware_profile_model"] = model_name
                    provider.extra_params["hardware_profile_priority"] = priority
                ordered.append(provider)
                seen.add(provider_name)

        # Add remaining providers not in hardware profile (lower priority)
        for p in providers:
            if p.name not in seen:
                ordered.append(p)

        return ordered

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

                # Layer 5: Quota registry check (for free-tier providers)
                quota_status = self.quota_registry.get_quota_status(provider.name)
                if quota_status.get("configured", False) and not quota_status.get("healthy", True):
                    logger.debug(
                        f"Quota exhausted or unhealthy for {provider.name}: "
                        f"daily_pct={quota_status['daily']['requests_pct']}%, "
                        f"minute_pct={quota_status['minute']['requests_pct']}%"
                    )
                    continue

                # Layer 6: Free quota prediction (legacy, kept for backward compatibility)
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

    def _heuristic_fallback(self, stage: str, response_model, segment_id: str, **context) -> Optional[Any]:
        """Kill Switch: pure rule-based fallback when ALL LLM providers fail.

        Returns a valid instance matching the response_model for each stage.

        Args:
            stage: Pipeline stage name
            response_model: Pydantic model class for the expected output
            segment_id: The segment ID being processed (REQUIRED for judge stage)
            **context: Additional context
        """
        from ..monitoring.langfuse_client import span

        with span("router.heuristic_fallback", metadata={"stage": stage, "segment_id": segment_id}) as s:
            logger.warning(
                f"All LLM providers failed for stage {stage} (segment_id={segment_id}), using heuristic fallback"
            )

            if stage == "analyze":
                # Return a valid BookAnalysisOutput for analyze stage
                from ..schemas import BookMeta, CharacterVoiceBinding, EmotionSnapshot
                result = BookAnalysisOutput(
                    book_meta=BookMeta(
                        title="Unknown Book",
                        author="Unknown Author",
                        genre="小说",
                        difficulty="B",
                        language="zh",
                        era="现代",
                        total_chapters_estimated=10,
                    ),
                    character_voice_map=[
                        CharacterVoiceBinding(
                            canonical_name="旁白",
                            aliases=[],
                            gender="neutral",
                            age_range="adult",
                            suggested_voice_id="kokoro_narrator",
                            sample_quote="这是旁白的样本文本。",
                        )
                    ],
                    emotion_snapshots=[
                        EmotionSnapshot(
                            chapter=1,
                            dominant_emotion="neutral",
                            intensity=0.5,
                            notes="启发式兜底：无法获取LLM分析结果",
                        )
                    ],
                    story_line_summary="启发式兜底：无法获取LLM分析结果，使用默认故事大纲。这是一个关于主角在未知世界中探索冒险、克服重重困难、最终实现自我成长与超越的励志故事。故事包含丰富的情感变化、生动的场景描写和深刻的主题内涵，适合有声书演绎。",
                    global_style_notes="启发式兜底：使用默认文风备注，保持平实叙述风格，对话自然流畅。",
                )
            elif stage == "annotate":
                result = ParagraphAnnotation(
                    paragraph_index=0,
                    speaker_canonical_name="_narrator_",
                    is_dialogue=False,
                    emotion="neutral",
                    emotion_intensity=0.3,
                    speech_rate=1.0,
                    pitch_shift_semitones=0,
                    confidence=0.2,
                    difficulty="B",
                    needs_sfx=False,
                    sfx_tags=[],
                    notes="heuristic_fallback_no_llm_available",
                )
            elif stage == "edit":
                result = TtsEditOutput(
                    edited_text="",
                    changes_made=["heuristic_fallback_no_llm_available"],
                    forbidden_content_removed=[],
                    confidence=0.2,
                    rationale="All LLM providers unavailable, using heuristic",
                )
            elif stage == "judge":
                # segment_id is now a REQUIRED parameter
                result = QualityJudgment(
                    segment_id=segment_id,
                    speaker_clarity=0.5,
                    emotion_match=0.5,
                    prosody_naturalness=0.5,
                    text_audio_alignment=0.5,
                    overall_score=0.5,
                    issues=["wrong_speaker"],
                    fix_suggestions=[],
                    needs_regeneration=True,
                    contract_version=1,
                    judge_model="heuristic_fallback",
                    judge_prompt_version="heuristic_v1",
                )
            else:
                result = None

            if s:
                s.update(metadata={"fallback_used": result is not None})
            return result

    @_lazy_trace_function(stage="llm")
    def call(self, stage: str, response_model, messages: list, **kwargs):
        stage_enum = StageName(stage)
        
        # Get providers from config
        providers = self.config.get_providers_for_stage(stage_enum)
        
        # Apply hardware profile stage model mapping if available
        if self.hardware_profile:
            stage_models = self.hardware_profile.get_llm_stage_models(stage)
            if stage_models:
                # Filter and reorder providers based on hardware profile priority
                providers = self._apply_hardware_profile_routing(stage, providers, stage_models)

        if not providers:
            if self.mock_mode:
                return self._create_mock_result(response_model, stage, **kwargs)
            raise ValueError(f"No providers configured for stage: {stage}")

        # Mock mode short-circuit: return mock result immediately without trying real providers
        if self.mock_mode:
            return self._create_mock_result(response_model, stage, **kwargs)

        # Build and compress prompt - preserve system message for JSON enforcement
        user_prompt = messages[-1]["content"] if messages else ""
        compressed_prompt, estimated_tokens = self.prompt_compressor.compress(
            user_prompt, self._get_schema_json(response_model), ""
        )

        # Rebuild messages with compressed prompt - preserves system message
        messages = self._build_messages(stage_enum, compressed_prompt, "", "")

        # Try each provider in priority order
        for provider in providers:
            if not self.rate_limiters[provider.name].can_proceed(estimated_tokens):
                logger.warning(f"Rate limit near for {provider.name}, skipping")
                continue

            if self.cost_tracker.is_limit_exceeded(provider.name):
                logger.warning(f"Daily cost limit exceeded for {provider.name}")
                continue

            # Circuit breaker check
            cb = self.circuit_breakers.get(provider.name)
            if cb and not cb.can_proceed():
                logger.warning(f"Circuit breaker open for {provider.name}, skipping")
                continue

            # Health probe check
            if self.health_probe and not self.health_probe.is_healthy(provider.name):
                logger.warning(
                    f"Health probe reports {provider.name} unhealthy, skipping"
                )
                continue

            # Quota registry check before making request
            if not self.quota_registry.can_make_request(provider.name, estimated_tokens):
                logger.warning(f"Quota exceeded for {provider.name}, skipping")
                continue

            client = self.get_client(provider)
            try:
                # Pass full messages list to preserve system message (JSON enforcement)
                result = client.call(
                    prompt=messages,
                    response_model=response_model,
                    temperature=kwargs.get("temperature", 0.1),
                    max_tokens=kwargs.get("max_tokens", 4000),
                )

                # Validate the result matches expected model
                if result.output is None:
                    logger.warning(f"Provider {provider.name} returned None output for stage {stage}")
                    raise ValueError("LLM returned None output")

                # Defensive JSON parsing validation
                # The raw_response should be validated before Pydantic validation
                if hasattr(result, 'raw_response') and result.raw_response is not None:
                    from .client import validate_and_parse_llm_response
                    try:
                        validate_and_parse_llm_response(
                            result.raw_response, response_model, stage
                        )
                    except LLMParseError as e:
                        logger.warning(f"Provider {provider.name} returned invalid JSON for stage {stage}: {e}")
                        raise

                self.rate_limiters[provider.name].record_usage(
                    result.tokens_in + result.tokens_out
                )
                self.cost_tracker.add_cost(provider.name, result.cost_usd)

                # Record success for circuit breaker
                if cb:
                    cb.record_success()

                # Track free tier usage
                if provider.max_daily_cost_usd == 0:
                    self._free_quota_success[provider.name] += 1

                # Record quota usage
                self.quota_registry.record_request(
                    provider.name,
                    tokens_used=result.tokens_in + result.tokens_out,
                    success=True
                )

                # Langfuse tracing - lazy import
                if self._is_langfuse_enabled():
                    try:
                        from ..monitoring.langfuse_client import observe_llm_call
                        observe_llm_call(
                            stage=stage,
                            model=result.model,
                            provider=provider.name,
                            prompt_tokens=result.tokens_in,
                            completion_tokens=result.tokens_out,
                            total_tokens=result.tokens_in + result.tokens_out,
                            cost_usd=result.cost_usd,
                            latency_ms=result.latency_ms,
                            metadata={
                                "schema_compliance": result.schema_compliance,
                                "contract_version": result.contract_version,
                            },
                        )
                    except Exception as e:
                        logger.debug(f"Langfuse observe failed: {e}")

                logger.info(
                    f"LLM call [{stage}] provider={provider.name} "
                    f"model={result.model} tokens={result.tokens_in}/{result.tokens_out} "
                    f"cost=${result.cost_usd:.6f} latency={result.latency_ms}ms "
                    f"schema_ok={result.schema_compliance}"
                )

                return result
            except Exception as e:
                logger.warning(
                    f"Provider {provider.name} failed for stage {stage}: {e}"
                )
                # Record failure for circuit breaker
                if cb:
                    cb.record_failure()
                # Record failure for free tier tracking
                if provider.max_daily_cost_usd == 0:
                    self._free_quota_fail[provider.name] += 1
                # Record quota failure
                self.quota_registry.record_request(
                    provider.name,
                    tokens_used=0,
                    success=False
                )
                continue

        # All providers failed — Kill Switch heuristic fallback
        # Pass segment_id for judge stage (required)
        segment_id = "unknown"
        if stage == "judge":
            # Try to extract segment_id from kwargs
            segment_id = kwargs.get("segment_id", "unknown")
        fallback = self._heuristic_fallback(stage, response_model, segment_id=segment_id)
        if fallback:
            return LLMCallResult(
                output=fallback,
                model="heuristic_fallback",
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=0,
                schema_compliance=False,
                raw_response=fallback,
            )

        raise RuntimeError(f"All providers failed for stage {stage}")

    def _create_mock_result(self, response_model, stage: str, **kwargs):
        # Create appropriate mock result based on response_model type
        # Pass kwargs (e.g., segment_id) to mock creation
        if response_model == ParagraphAnnotation:
            mock_output = ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="旁白",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                pause_before_ms=300,
                pause_after_ms=500,
                confidence=0.9,
                difficulty="B",
                needs_sfx=False,
                sfx_tags=[],
                notes="Mock annotation for testing",
            )
        elif response_model == BookAnalysisOutput:
            from ..schemas import BookMeta, CharacterVoiceBinding, EmotionSnapshot

            mock_output = BookAnalysisOutput(
                book_meta=BookMeta(
                    title="Test Book",
                    author="Test Author",
                    genre="小说",
                    difficulty="B",
                    language="zh",
                    era="现代",
                    total_chapters_estimated=10,
                ),
                character_voice_map=[
                    CharacterVoiceBinding(
                        canonical_name="旁白",
                        aliases=[],
                        gender="neutral",
                        age_range="adult",
                        suggested_voice_id="v1",
                        sample_quote="这是一个测试样本。",
                    )
                ],
                emotion_snapshots=[
                    EmotionSnapshot(
                        chapter=1,
                        dominant_emotion="neutral",
                        intensity=0.5,
                        notes="测试情感快照",
                    )
                ],
                story_line_summary="这是一个用于测试的模拟故事主线摘要，包含足够的字符数以满足最小长度要求一百字以上。故事讲述了一个主角在现代都市中经历各种冒险和成长的过程，通过重重困难最终实现自我超越的励志历程，展现了人性的光辉与坚韧。",
                global_style_notes="测试全局文风备注：保持平实叙述风格，对话自然流畅。",
            )
        elif response_model == ExtractionResult:
            mock_output = ExtractionResult(
                raw_text="Test extraction text",
                language="zh",
                page_count=1,
            )
        elif response_model == TtsEditOutput:
            mock_output = TtsEditOutput(
                paragraph_text="Test paragraph",
                phonemes=["t", "e", "s", "t"],
                pitch_contour=[0],
                energy_contour=[0.5],
                duration_ms=1000,
                ssml_markup="<speak>Test paragraph</speak>",
            )
        elif response_model == QualityJudgment:
            mock_output = QualityJudgment(
                segment_id=kwargs.get("segment_id", "mock_segment"),
                speaker_clarity=0.8,
                emotion_match=0.8,
                prosody_naturalness=0.8,
                text_audio_alignment=0.8,
                overall_score=0.8,
                issues=[],
                fix_suggestions=[],
                needs_regeneration=False,
                contract_version=1,
                judge_model="mock-model",
                judge_prompt_version="mock_v1",
            )
        elif response_model == FeedbackAnalysis:
            mock_output = FeedbackAnalysis(
                pattern_tags=["dialogue_attribution"],
                semantic_summary="[Mock] LLM 错误标注了对话归属，修正后明确了说话人身份。",
                severity="medium",
                actionable_instruction="标注对话时必须从上下文推断说话人，若引号内无明确主语则检查前文对话。",
                root_cause="prompt 缺少对话归属推断的明确规则",
                confidence=0.85,
            )
        else:
            # For any other response model, try to create a default instance
            try:
                mock_output = response_model()
            except Exception:
                # If we can't create an instance, return None to indicate failure
                return None

        return LLMCallResult(
            output=mock_output,
            model="mock-model",
            tokens_in=10,
            tokens_out=10,
            cost_usd=0.0,
            latency_ms=100,
            schema_compliance=True,
            contract_version=1,
            raw_response=None,
        )

    def get_free_tier_health(self) -> dict:
        """Expose free tier health status for Promotion Gate and monitoring."""
        enabled = self.config.get_all_enabled()
        free_providers = [p for p in enabled if p.max_daily_cost_usd == 0]

        healthy_count = 0
        total_success = 0
        total_fail = 0

        for p in free_providers:
            success = self._free_quota_success.get(p.name, 0)
            fail = self._free_quota_fail.get(p.name, 0)
            total_success += success
            total_fail += fail

            cb = self.circuit_breakers.get(p.name)
            if cb and cb.state == "closed":
                healthy_count += 1
            elif self.health_probe and self.health_probe.is_healthy(p.name):
                healthy_count += 1

        total = total_success + total_fail
        success_rate = total_success / total if total > 0 else 1.0

        # Check local model availability
        local_available = any(
            p.provider == ProviderType.OLLAMA and p.enabled for p in enabled
        )

        # Overall health assessment
        if success_rate >= 0.95 and healthy_count >= len(free_providers) * 0.5:
            overall = "green"
        elif success_rate >= 0.8:
            overall = "yellow"
        else:
            overall = "red"

        return {
            "total_free_providers": len(free_providers),
            "healthy_free_providers": healthy_count,
            "free_quota_success_rate": round(success_rate, 4),
            "free_quota_success": total_success,
            "free_quota_fail": total_fail,
            "local_model_available": local_available,
            "overall_health": overall,
            "circuit_breaker_states": {
                name: cb.get_status()
                for name, cb in self.circuit_breakers.items()
                if name in [p.name for p in free_providers]
            },
        }

    def get_quota_status(self, provider_name: str = None) -> dict:
        """Get quota registry status for all or a specific provider."""
        if provider_name:
            return self.quota_registry.get_quota_status(provider_name)
        return self.quota_registry.get_all_statuses()

    def get_quota_healthy_providers(self) -> List[str]:
        """Get list of providers with available quota."""
        return self.quota_registry.get_healthy_providers()

    def get_quota_health_score(self, provider_name: str) -> float:
        """Get health score for a provider based on quota availability."""
        return self.quota_registry.get_quota_health_score(provider_name)

    def get_cost_status(self):
        return self.cost_tracker.get_status()

    @property
    def stage_configs(self) -> Dict[str, StageRoutingConfig]:
        """Backward compatibility: expose stage configs as StageRoutingConfig."""
        configs = {}
        for stage in StageName:
            providers = self.config.get_providers_for_stage(stage)
            if providers:
                configs[stage.value] = StageRoutingConfig(
                    stage=stage.value,
                    models=[
                        ModelConfig(
                            name=p.name,
                            priority=p.priority,
                            enabled=p.enabled,
                            max_daily_cost_usd=p.max_daily_cost_usd,
                            temperature=0.1,
                            max_tokens=4000,
                        )
                        for p in providers
                    ],
                    fallback_model=providers[-1].name if providers else None,
                )
        return configs


def create_router(mock_mode: bool = None, config_path: str = None, hardware_profile: Optional[HardwareProfile] = None) -> LLMRouter:
    if mock_mode is None:
        mock_mode = os.getenv("MOCK_LLM", "false").lower() == "true"
    return LLMRouter(mock_mode=mock_mode, config_path=config_path, hardware_profile=hardware_profile)

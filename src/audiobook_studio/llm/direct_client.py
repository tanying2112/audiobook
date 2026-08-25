"""Direct Provider Client - Native OpenAI/Anthropic SDK integration.

Bypasses LiteLLM gateway to eliminate ~200ms overhead per call.
Supports structured output via instructor-compatible parsing.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Import shared validation utilities
from .utils import LLMParseError, validate_and_parse_llm_response

# LLM semantic cache (lazy-resolved; no-op unless LLM_SEMANTIC_CACHE_ENABLED=true)
from .semantic_cache import (
    cached_llm_lookup,
    cached_llm_store,
    get_semantic_cache,
)

T = TypeVar("T", bound=BaseModel)


class DirectProviderType(str, Enum):
    """Supported direct provider types (bypassing LiteLLM)."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


# Model pricing (USD per 1M tokens) - for direct provider calls
DIRECT_MODEL_PRICING = {
    # OpenAI models
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "gpt-3.5-turbo": {"input": 0.50, "output": 1.50},
    # Anthropic models
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.25, "output": 1.25},
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    # Free tier models (via OpenAI-compatible APIs)
    "gpt-4o-mini-free": {"input": 0.00, "output": 0.00},
}


@dataclass
class DirectProviderClientConfig:
    """Configuration for Direct Provider Client."""

    provider: DirectProviderType
    model: str
    temperature: float = 0.1
    max_tokens: int = 4000
    max_retries: int = 3
    timeout: int = 60  # seconds
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    # Optional headers for custom gateways
    extra_headers: Optional[Dict[str, str]] = None

    @property
    def mock_mode(self) -> bool:
        """Check if mock mode is enabled via environment variable."""
        return os.getenv("MOCK_LLM", "false").lower() == "true"


@dataclass
class LLMCallResult:
    """Result of an LLM call with metadata."""

    output: Optional[BaseModel]
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    schema_compliance: bool
    contract_version: int = 1
    raw_response: Any = None


class DirectProviderClient:
    """Direct LLM client using native OpenAI/Anthropic SDKs.

    Eliminates LiteLLM gateway overhead (~200ms per call) by calling
    provider APIs directly with instructor for structured outputs.
    """

    def __init__(self, config: DirectProviderClientConfig):
        self.config = config
        self._client = None
        self._init_client()

    def _init_client(self):
        """Initialize native provider SDK client."""
        if self.config.mock_mode:
            self._client = None
            return

        if self.config.provider == DirectProviderType.OPENAI:
            self._init_openai_client()
        elif self.config.provider == DirectProviderType.ANTHROPIC:
            self._init_anthropic_client()
        else:
            raise ValueError(f"Unsupported provider: {self.config.provider}")

    def _init_openai_client(self):
        """Initialize OpenAI client with instructor for structured output."""
        try:
            import instructor
            from openai import AsyncOpenAI

            # Create base OpenAI client
            base_client = AsyncOpenAI(
                api_key=self.config.api_key or os.getenv("OPENAI_API_KEY"),
                base_url=self.config.api_base,
                timeout=self.config.timeout,
                default_headers=self.config.extra_headers,
            )

            # Wrap with instructor for structured output parsing
            self._client = instructor.from_openai(base_client, mode=instructor.Mode.JSON)
            logger.info(f"Initialized OpenAI direct client for model: {self.config.model}")
        except ImportError as e:
            logger.error(f"OpenAI SDK not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            raise

    def _init_anthropic_client(self):
        """Initialize Anthropic client with instructor for structured output."""
        try:
            import instructor
            from anthropic import AsyncAnthropic

            # Create base Anthropic client
            base_client = AsyncAnthropic(
                api_key=self.config.api_key or os.getenv("ANTHROPIC_API_KEY"),
                base_url=self.config.api_base,
                timeout=self.config.timeout,
                default_headers=self.config.extra_headers,
            )

            # Wrap with instructor for structured output parsing
            self._client = instructor.from_anthropic(base_client, mode=instructor.Mode.JSON)
            logger.info(f"Initialized Anthropic direct client for model: {self.config.model}")
        except ImportError as e:
            logger.error(f"Anthropic SDK not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize Anthropic client: {e}")
            raise

    def _build_messages(self, prompt: Any) -> List[Dict[str, str]]:
        """Build messages list from prompt (string or messages list)."""
        if isinstance(prompt, list):
            return prompt
        return [{"role": "user", "content": str(prompt)}]

    def _calculate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Calculate cost based on model pricing."""
        pricing = DIRECT_MODEL_PRICING.get(self.config.model, {"input": 0, "output": 0})
        cost = (tokens_in / 1_000_000) * pricing.get("input", 0)
        cost += (tokens_out / 1_000_000) * pricing.get("output", 0)
        return cost

    def call(
        self,
        prompt: Any,
        response_model: Type[T],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMCallResult:
        """
        Synchronous call to LLM with structured output parsing.

        Args:
            prompt: String prompt or list of messages
            response_model: Pydantic model for structured output
            temperature: Override default temperature
            max_tokens: Override default max_tokens
            **kwargs: Additional arguments passed to provider API

        Returns:
            LLMCallResult with parsed output and metadata
        """
        # --- LLM semantic cache (no-op when disabled) ---
        _sem_cache = get_semantic_cache()
        if _sem_cache is not None:
            _cached = cached_llm_lookup(
                _sem_cache,
                prompt=prompt,
                response_model=response_model,
                model=self.config.model,
                temperature=(temperature if temperature is not None else self.config.temperature),
                max_tokens=(max_tokens if max_tokens is not None else self.config.max_tokens),
            )
            if _cached is not None:
                return _cached

        temp = temperature if temperature is not None else self.config.temperature
        max_tok = max_tokens if max_tokens is not None else self.config.max_tokens
        result: Any = None
        if self.config.mock_mode:
            result = self._mock_call(prompt, response_model)
        else:
            messages = self._build_messages(prompt)

            start = time.time()
            try:
                # Run async call in event loop
                if self.config.provider == DirectProviderType.OPENAI:
                    result = asyncio.run(self._call_openai(messages, response_model, temp, max_tok, **kwargs))
                elif self.config.provider == DirectProviderType.ANTHROPIC:
                    result = asyncio.run(self._call_anthropic(messages, response_model, temp, max_tok, **kwargs))
                else:
                    raise ValueError(f"Unsupported provider: {self.config.provider}")

                latency_ms = int((time.time() - start) * 1000)

                # Extract token usage from result
                tokens_in = getattr(result, "_raw_usage", {}).get("prompt_tokens", 0)
                tokens_out = getattr(result, "_raw_usage", {}).get("completion_tokens", 0)

                # If instructor didn't populate usage, try to get from raw response
                if tokens_in == 0 and tokens_out == 0:
                    raw_resp = getattr(result, "_raw_response", None)
                    if raw_resp:
                        usage = getattr(raw_resp, "usage", None)
                        if usage:
                            tokens_in = getattr(usage, "prompt_tokens", 0)
                            tokens_out = getattr(usage, "completion_tokens", 0)

                cost_usd = self._calculate_cost(tokens_in, tokens_out)

                logger.info(
                    f"Direct LLM call [{self.config.provider.value}] model={self.config.model} "
                    f"tokens={tokens_in}/{tokens_out} cost=${cost_usd:.6f} latency={latency_ms}ms"
                )

                result = LLMCallResult(
                    output=result,
                    model=self.config.model,
                    tokens_in=tokens_in,
                    tokens_out=tokens_out,
                    cost_usd=cost_usd,
                    latency_ms=latency_ms,
                    schema_compliance=True,
                    raw_response=getattr(result, "_raw_response", None),
                )

            except Exception as e:
                latency_ms = int((time.time() - start) * 1000)
                logger.error(f"Direct LLM call failed [{self.config.provider.value}]: {e} (latency={latency_ms}ms)")
                raise
        if _sem_cache is not None:
            cached_llm_store(
                _sem_cache,
                prompt=prompt,
                result=result,
                response_model=response_model,
                model=self.config.model,
                temperature=temp,
                max_tokens=max_tok,
            )
        return result

    async def call_async(
        self,
        prompt: Any,
        response_model: Type[T],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMCallResult:
        """Async version of call for use in async contexts."""
        if self.config.mock_mode:
            return self._mock_call(prompt, response_model)

        messages = self._build_messages(prompt)
        temp = temperature if temperature is not None else self.config.temperature
        max_tok = max_tokens if max_tokens is not None else self.config.max_tokens

        start = time.time()
        try:
            if self.config.provider == DirectProviderType.OPENAI:
                result = await self._call_openai(messages, response_model, temp, max_tok, **kwargs)
            elif self.config.provider == DirectProviderType.ANTHROPIC:
                result = await self._call_anthropic(messages, response_model, temp, max_tok, **kwargs)
            else:
                raise ValueError(f"Unsupported provider: {self.config.provider}")

            latency_ms = int((time.time() - start) * 1000)

            tokens_in = getattr(result, "_raw_usage", {}).get("prompt_tokens", 0)
            tokens_out = getattr(result, "_raw_usage", {}).get("completion_tokens", 0)

            if tokens_in == 0 and tokens_out == 0:
                raw_resp = getattr(result, "_raw_response", None)
                if raw_resp:
                    usage = getattr(raw_resp, "usage", None)
                    if usage:
                        tokens_in = getattr(usage, "prompt_tokens", 0)
                        tokens_out = getattr(usage, "completion_tokens", 0)

            cost_usd = self._calculate_cost(tokens_in, tokens_out)

            logger.info(
                f"Direct LLM call [{self.config.provider.value}] model={self.config.model} "
                f"tokens={tokens_in}/{tokens_out} cost=${cost_usd:.6f} latency={latency_ms}ms"
            )

            return LLMCallResult(
                output=result,
                model=self.config.model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                schema_compliance=True,
                raw_response=getattr(result, "_raw_response", None),
            )

        except Exception as e:
            latency_ms = int((time.time() - start) * 1000)
            logger.error(f"Direct LLM call failed [{self.config.provider.value}]: {e} (latency={latency_ms}ms)")
            raise

    async def _call_openai(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> T:
        """Call OpenAI API with structured output."""
        # Use instructor's parse method for structured output
        result = await self._client.chat.completions.parse(
            model=self.config.model,
            messages=messages,
            response_model=response_model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return result

    async def _call_anthropic(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> T:
        """Call Anthropic API with structured output."""
        # Convert messages to Anthropic format (system + user)
        system_msg = ""
        user_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_msg = msg["content"]
            else:
                user_messages.append(msg)

        # Use instructor's parse method for structured output
        result = await self._client.messages.create(
            model=self.config.model,
            system=system_msg if system_msg else None,
            messages=user_messages,
            response_model=response_model,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        return result

    def _mock_call(self, prompt: Any, response_model: Type[T]) -> LLMCallResult:
        """Mock LLM call for testing."""
        from src.audiobook_studio.schemas import (
            BookAnalysisOutput,
            ExtractionResult,
            ParagraphAnnotation,
            QualityJudgment,
            TtsEditOutput,
            TtsRoutingDecision,
        )

        # Create appropriate mock based on response model
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
            from src.audiobook_studio.schemas import BookMeta, CharacterVoiceBinding, EmotionSnapshot

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
                raw_text="Mock extracted text",
                language="zh",
                page_count=1,
            )
        elif response_model == QualityJudgment:
            mock_output = QualityJudgment(
                segment_id="mock_seg",
                speaker_clarity=0.9,
                emotion_match=0.9,
                prosody_naturalness=0.9,
                text_audio_alignment=0.9,
                overall_score=0.9,
                issues=[],
                fix_suggestions=[],
                needs_regeneration=False,
                contract_version=1,
                judge_model="mock-model",
                judge_prompt_version="mock_v1",
            )
        elif response_model == TtsEditOutput:
            mock_output = TtsEditOutput(
                edited_text="这是模拟编辑后的文本，用于测试。",
                changes_made=["heuristic_fallback_no_llm_available"],
                forbidden_content_removed=[],
                confidence=0.8,
                rationale="LLM unavailable, using heuristic fallback",
            )
        elif response_model == TtsRoutingDecision:
            mock_output = TtsRoutingDecision(
                segment_id="mock_seg",
                engine_choice="kokoro",
                voice_id="v1",
                prosody_overrides=None,
                fallback_engine="edge",
                reasoning="Mock",
                estimated_cost_usd=0.0,
                estimated_duration_ms=1000,
            )
        else:
            # Try to create default instance
            try:
                mock_output = response_model()
            except Exception:
                mock_output = None

        return LLMCallResult(
            output=mock_output,
            model=self.config.model,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=1,
            schema_compliance=True,
            raw_response=mock_output.model_dump() if hasattr(mock_output, "model_dump") else {},
        )


def create_direct_client(config: DirectProviderClientConfig) -> DirectProviderClient:
    """Factory function to create DirectProviderClient."""
    return DirectProviderClient(config)

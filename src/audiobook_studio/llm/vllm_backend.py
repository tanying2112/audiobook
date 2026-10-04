"""vLLM Backend - Local inference with KV cache and speculative decoding.

Provides high-performance local LLM inference using vLLM with:
- KV Cache for reduced memory and faster generation
- Chunked Prefill for long context handling
- Prefix Caching for repeated prompts
- Speculative Decoding for faster generation
- OpenAI-compatible API for easy integration
"""

import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Import shared validation utilities

T = TypeVar("T", bound=BaseModel)


# Model pricing (USD per 1M tokens) - local models are free
VLLM_MODEL_PRICING = {
    # All local models have $0.00 pricing
    "qwen2.5:14b": {"input": 0.00, "output": 0.00},
    "qwen2.5:7b": {"input": 0.00, "output": 0.00},
    "qwen2.5:32b": {"input": 0.00, "output": 0.00},
    "llama3.1:8b": {"input": 0.00, "output": 0.00},
    "llama3.1:70b": {"input": 0.00, "output": 0.00},
    "gemma2:9b": {"input": 0.00, "output": 0.00},
    "gemma2:27b": {"input": 0.00, "output": 0.00},
    "mistral:7b": {"input": 0.00, "output": 0.00},
    "mistral:8x7b": {"input": 0.00, "output": 0.00},
    "phi3:14b": {"input": 0.00, "output": 0.00},
    "phi3:mini": {"input": 0.00, "output": 0.00},
}


@dataclass
class VLLMBackendConfig:
    """Configuration for vLLM Backend."""

    model: str
    host: str = "localhost"
    port: int = 8000
    temperature: float = 0.1
    max_tokens: int = 4000
    max_retries: int = 3
    timeout: int = 60  # seconds
    # vLLM specific options
    max_model_len: int = 32768
    gpu_memory_utilization: float = 0.9
    enable_chunked_prefill: bool = True
    enable_prefix_caching: bool = True
    # Speculative decoding
    speculative_model: Optional[str] = None
    num_speculative_tokens: int = 5

    @property
    def base_url(self) -> str:
        """Get the base URL for the vLLM server."""
        return f"http://{self.host}:{self.port}/v1"

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


class VLLMBackend:
    """vLLM Backend for high-performance local inference.

    Uses vLLM's OpenAI-compatible API with:
    - KV Cache for efficient attention computation
    - Chunked Prefill for long contexts
    - Prefix Caching for repeated prefixes
    - Speculative Decoding (optional) for faster generation
    """

    def __init__(self, config: VLLMBackendConfig):
        self.config = config
        self._client = None
        self._init_client()

    def _init_client(self):
        """Initialize OpenAI-compatible client for vLLM."""
        if self.config.mock_mode:
            self._client = None
            return

        try:
            import instructor
            from openai import AsyncOpenAI

            # Create base OpenAI client pointing to vLLM
            base_client = AsyncOpenAI(
                api_key="vllm",  # vLLM accepts any non-empty key
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )

            # Wrap with instructor for structured output parsing
            self._client = instructor.from_openai(base_client, mode=instructor.Mode.JSON)
            logger.info(f"Initialized vLLM backend for model: {self.config.model} at {self.config.base_url}")
            logger.info(
                f"vLLM features: chunked_prefill={self.config.enable_chunked_prefill}, "
                f"prefix_caching={self.config.enable_prefix_caching}, "
                f"speculative={self.config.speculative_model is not None}"
            )
        except ImportError as e:
            logger.error(f"OpenAI SDK or instructor not installed: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to initialize vLLM client: {e}")
            raise

    def _build_messages(self, prompt: Any) -> List[Dict[str, str]]:
        """Build messages list from prompt (string or messages list)."""
        if isinstance(prompt, list):
            return prompt
        return [{"role": "user", "content": str(prompt)}]

    def _calculate_cost(self, tokens_in: int, tokens_out: int) -> float:
        """Calculate cost based on model pricing (always $0 for local models)."""
        pricing = VLLM_MODEL_PRICING.get(self.config.model, {"input": 0, "output": 0})
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
        Synchronous call to vLLM with structured output parsing.

        Args:
            prompt: String prompt or list of messages
            response_model: Pydantic model for structured output
            temperature: Override default temperature
            max_tokens: Override default max_tokens
            **kwargs: Additional arguments passed to vLLM API

        Returns:
            LLMCallResult with parsed output and metadata
        """
        if self.config.mock_mode:
            return self._mock_call(prompt, response_model)

        messages = self._build_messages(prompt)
        temp = temperature if temperature is not None else self.config.temperature
        max_tok = max_tokens if max_tokens is not None else self.config.max_tokens

        start = time.time()
        try:
            # Run async call safely (works both inside and outside a running loop)
            from ..utils.async_utils import run_async_safe

            result = run_async_safe(self._call_async(messages, response_model, temp, max_tok, **kwargs))

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
                f"vLLM call model={self.config.model} "
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
            logger.error(f"vLLM call failed: {e} (latency={latency_ms}ms)")
            raise

    async def _call_async(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[T],
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> T:
        """Call vLLM API with structured output."""
        # instructor 1.x: use `create` + `response_model` (NOT the legacy `parse`).
        result = await self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
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
                notes="Mock annotation from vLLM",
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
                raw_text="Mock extracted text from vLLM",
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
                judge_model="vllm-mock",
                judge_prompt_version="mock_v1",
            )
        elif response_model == TtsEditOutput:
            mock_output = TtsEditOutput(
                edited_text="这是模拟编辑后的文本，用于测试 vLLM。",
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
            except TypeError:
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


def create_vllm_backend(config: VLLMBackendConfig) -> VLLMBackend:
    """Factory function to create VLLMBackend."""
    return VLLMBackend(config)

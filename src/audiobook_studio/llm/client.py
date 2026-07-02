"""LLM Client - Unified interface for all LLM providers using LiteLLM + Instructor.

Provides structured output parsing with Pydantic models, automatic retries,
token/cost tracking, and fallback support.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

import instructor
from litellm import completion
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ..schemas import (
    BookAnalysisOutput,
    ExtractionResult,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
    TtsRoutingDecision,
)

logger = logging.getLogger(__name__)

from .constitutional_rules import apply_constitutional_rules

# Import shared validation utilities
from .utils import LLMParseError, validate_and_parse_llm_response

T = TypeVar("T", bound=BaseModel)

# Model pricing (USD per 1M tokens) - approximate
# Free tier models have $0.00 pricing
MODEL_PRICING = {
    "gemini-2.0-flash": {"input": 0.075, "output": 0.30},
    "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "claude-3-5-sonnet": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku": {"input": 0.25, "output": 1.25},
    "groq/llama-3.1-70b-versatile": {"input": 0.59, "output": 0.79},
    "groq/llama-3.1-8b-instant": {"input": 0.05, "output": 0.08},
    "deepseek-chat": {"input": 0.14, "output": 0.28},
    "openrouter/auto": {"input": 0.50, "output": 1.50},
    "nvidia/nemotron-3-ultra": {"input": 0.00, "output": 0.00},
    "opencode-zen/gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # Free tier models - $0.00 pricing
    "cerebras/llama-3.3-70b": {"input": 0.00, "output": 0.00},
    "openai/qwen-max": {"input": 0.00, "output": 0.00},
    "openai/glm-4-flash": {"input": 0.00, "output": 0.00},
    "openai/Qwen/Qwen2.5-72B-Instruct": {"input": 0.00, "output": 0.00},
    "openai/mistral-small-latest": {"input": 0.00, "output": 0.00},
    "openai/ernie-speed-128k": {"input": 0.00, "output": 0.00},
    "openai/doubao-pro-32k": {"input": 0.00, "output": 0.00},
    "openai/hunyuan-standard": {"input": 0.00, "output": 0.00},
    "huggingface/Qwen/Qwen2.5-72B-Instruct": {"input": 0.00, "output": 0.00},
    "openrouter/meta-llama/llama-3.1-8b-instruct:free": {"input": 0.00, "output": 0.00},
    "openai/@cf/meta/llama-3.3-70b": {"input": 0.00, "output": 0.00},
    "openai/gpt-4o-mini": {"input": 0.00, "output": 0.00},
    "ollama/qwen2.5:14b": {"input": 0.00, "output": 0.00},
    "ollama/llama3.1:8b": {"input": 0.00, "output": 0.00},
}


@dataclass
class LLMCallResult:
    """Result of an LLM call with metadata."""

    output: BaseModel
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    schema_compliance: bool
    contract_version: int = 1
    raw_response: Any = None


@dataclass
class LLMClientConfig:
    """Configuration for LLM client."""

    model: str
    temperature: float = 0.1
    max_tokens: int = 4000
    max_retries: int = 3
    timeout: Optional[int] = 60  # None or 0 = no timeout (for local Ollama)
    mock_data_dir: str = "tests/golden"
    api_base: Optional[str] = None
    # Langfuse configuration
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_enabled: bool = False

    @property
    def mock_mode(self) -> bool:
        """Check if mock mode is enabled via environment variable."""
        return os.getenv("MOCK_LLM", "false").lower() == "true"


class LLMClient:
    """Unified LLM client with Instructor for structured outputs."""

    def __init__(self, config: LLMClientConfig):
        self.config = config
        self._client = None
        self._mock_cache: Dict[str, Any] = {}
        self._langfuse = None
        self._init_client()
        self._init_langfuse()
        if config.mock_mode:
            self._load_mock_data()

    def _init_client(self):
        """Initialize LiteLLM + Instructor client."""
        if not self.config.mock_mode:
            # Use JSON mode for better compatibility with local models like Ollama
            self._client = instructor.from_litellm(completion, mode=instructor.Mode.JSON)
        else:
            self._client = None

    def _init_langfuse(self):
        """Initialize Langfuse client if enabled and available."""
        if not self.config.langfuse_enabled:
            return
        try:
            from langfuse import Langfuse

            self._langfuse = Langfuse(
                public_key=self.config.langfuse_public_key,
                secret_key=self.config.langfuse_secret_key,
                host=self.config.langfuse_host,
            )
            logger.info("Langfuse client initialized")
        except ImportError:
            logger.warning("Langfuse not installed, disabling")
        except Exception as e:
            logger.warning(f"Failed to initialize Langfuse: {e}")
            self._langfuse = None

    def _load_mock_data(self):
        """Load mock data for testing."""
        import json

        mock_dir = Path(self.config.mock_data_dir)
        if mock_dir.exists():
            # Look for both .json and .jsonl files
            for file in mock_dir.rglob("*.json"):
                with open(file) as f:
                    self._mock_cache[file.stem] = json.load(f)
            for file in mock_dir.rglob("*.jsonl"):
                with open(file) as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            # Use the expected_output as mock data
                            if "expected_output" in data:
                                self._mock_cache[file.stem] = data["expected_output"]
                            else:
                                self._mock_cache[file.stem] = data

    def call(self, *args, **kwargs) -> LLMCallResult:
        """
        Call LLM with structured output parsing.

        Compatible calling conventions:
        - call(prompt, response_model, **kwargs)  # positional
        - call(prompt="...", response_model=..., **kwargs)  # keyword prompt
        - call(text="...", response_model=..., **kwargs)    # keyword text
        - call(content="...", response_model=..., **kwargs) # keyword content

        The prompt is extracted from the first positional arg or from
        prompt=, text=, or content= keyword arguments.
        """
        # Extract prompt from various possible sources
        prompt = None
        response_model = None

        # Handle positional arguments: (prompt, response_model, ...)
        if args:
            prompt = args[0]
            if len(args) > 1:
                response_model = args[1]

        # Handle keyword arguments (override positional if provided)
        if "prompt" in kwargs:
            prompt = kwargs.pop("prompt")
        elif "text" in kwargs:
            prompt = kwargs.pop("text")
        elif "content" in kwargs:
            prompt = kwargs.pop("content")
        elif "messages" in kwargs:
            prompt = kwargs.pop("messages")

        if "response_model" in kwargs:
            response_model = kwargs.pop("response_model")

        # Extract temperature and max_tokens from kwargs so they don't
        # conflict with the explicit keyword args in the create() call below.
        # Caller-provided values override self.config defaults.
        _temperature = kwargs.pop("temperature", self.config.temperature)
        _max_tokens = kwargs.pop("max_tokens", self.config.max_tokens)

        # If prompt is a list (messages), convert to string for mock lookup
        prompt_str = prompt
        if isinstance(prompt, list):
            prompt_str = " ".join(str(m.get("content", "")) for m in prompt)

        # Validate required parameters
        if prompt is None:
            raise ValueError(
                "prompt is required (pass as first positional arg, "
                "or use prompt=, text=, or content= keyword argument)"
            )
        if response_model is None:
            raise ValueError("response_model is required")

        if self.config.mock_mode:
            return self._mock_call(prompt_str, response_model)

        start = time.time()
        try:
            # Accept either a string prompt or a full messages list
            # If prompt is a list, use it as the messages directly
            if isinstance(prompt, list):
                messages = prompt
            else:
                # Default to user message only (backward compatibility)
                messages = [{"role": "user", "content": prompt}]

            call_kwargs = dict(kwargs)
            if self.config.api_base:
                call_kwargs["api_base"] = self.config.api_base
            # Pass timeout to LiteLLM: None or 0 = no timeout (for local Ollama)
            if self.config.timeout is not None and self.config.timeout > 0:
                call_kwargs["timeout"] = self.config.timeout
            else:
                call_kwargs["timeout"] = None  # No timeout for local models
            result = self._client.chat.completions.create(
                model=self.config.model,
                messages=messages,
                response_model=response_model,
                temperature=_temperature,
                max_tokens=_max_tokens,
                **call_kwargs,
            )
            latency_ms = int((time.time() - start) * 1000)

            # Get raw response for validation
            # When using instructor with JSON mode, result is already parsed
            # and result directly is the Pydantic model
            raw_response = getattr(result, "_raw_response", None)
            _skip_validation = False  # Flag to skip validation for instructor-parsed responses

            if raw_response is not None:
                # Extract token usage from ModelResponse
                usage_obj = getattr(raw_response, "usage", None)
                if usage_obj is not None:
                    usage_dict = getattr(usage_obj, "model_dump", lambda: {})()
                    tokens_in = usage_dict.get("prompt_tokens", 0) if isinstance(usage_dict, dict) else 0
                    tokens_out = usage_dict.get("completion_tokens", 0) if isinstance(usage_dict, dict) else 0
                else:
                    tokens_in = 0
                    tokens_out = 0

                # Extract content string from ModelResponse for validation
                choices = getattr(raw_response, "choices", [])
                if choices:
                    message = getattr(choices[0], "message", None)
                    raw_response = getattr(message, "content", "{}") if message else "{}"
                else:
                    raw_response = "{}"
            else:
                # Result is already a Pydantic model from instructor
                # Skip validate_and_parse_llm_response since instructor already validated
                _skip_validation = True
                raw_response = {}
                tokens_in = 0
                tokens_out = 0

            # Defensive JSON parsing validation (skip if already validated by instructor)
            if not _skip_validation and raw_response:  # Only validate if we have raw_response to check
                try:
                    validate_and_parse_llm_response(raw_response, response_model, "unknown")
                except LLMParseError as e:
                    logger.warning(f"LLM returned invalid JSON: {e}")
                    raise

            # Calculate cost
            cost_usd = 0.0
            model_pricing = MODEL_PRICING.get(self.config.model, {"input": 0, "output": 0})
            if tokens_in > 0:
                cost_usd += (tokens_in / 1_000_000) * model_pricing.get("input", 0)
            if tokens_out > 0:
                cost_usd += (tokens_out / 1_000_000) * model_pricing.get("output", 0)

            # Apply constitutional rules
            ruled_output = apply_constitutional_rules(result, context={"model": self.config.model})
            return LLMCallResult(
                output=ruled_output,
                model=self.config.model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost_usd,
                latency_ms=latency_ms,
                schema_compliance=True,
                raw_response=raw_response,
            )
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    def _mock_call(self, prompt: str, response_model: Type[T]) -> LLMCallResult:
        """Mock LLM call for testing."""
        import copy

        # Return mock data if available
        for key, data in self._mock_cache.items():
            if key in prompt.lower():
                return LLMCallResult(
                    output=response_model(**data),
                    model=self.config.model,
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                    latency_ms=1,
                    schema_compliance=True,
                    raw_response=data,
                )
        # Return minimal valid mock based on response_model type
        from ..schemas import (
            BookAnalysisOutput,
            ExtractionResult,
            ParagraphAnnotation,
            QualityJudgment,
            TtsEditOutput,
            TtsRoutingDecision,
        )

        if response_model == BookAnalysisOutput:
            from ..schemas import BookAnalysisOutput, BookMeta, CharacterVoiceBinding, EmotionSnapshot

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
                    ),
                    CharacterVoiceBinding(
                        canonical_name="主角",
                        aliases=[],
                        gender="male",
                        age_range="adult",
                        suggested_voice_id="v2",
                        sample_quote="主角的测试台词。",
                    ),
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
            from ..schemas import ExtractionResult

            mock_output = ExtractionResult(
                raw_text="Mock extracted text",
                language="zh",
                page_count=1,
                has_ocr=False,
                ocr_page_ratio=0.0,
                warnings=[],
            )
        elif response_model == ParagraphAnnotation:
            from ..schemas import ParagraphAnnotation

            mock_output = ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="旁白",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                needs_sfx=False,
                sfx_tags=[],
                pause_before_ms=300,
                pause_after_ms=500,
                confidence=0.9,
                difficulty="B",
                notes="heuristic_fallback_no_llm_available",
            )
        elif response_model == QualityJudgment:
            from ..schemas import QualityJudgment

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
            )
        elif response_model == TtsEditOutput:
            from ..schemas import TtsEditOutput

            mock_output = TtsEditOutput(
                edited_text="这是模拟编辑后的文本，用于测试。",
                changes_made=["heuristic_fallback_no_llm_available"],
                forbidden_content_removed=[],
                confidence=0.8,
                rationale="LLM unavailable, using heuristic fallback",
            )
        elif response_model == TtsRoutingDecision:
            from ..schemas import TtsRoutingDecision

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
        elif response_model == "FeedbackAnalysis":
            from ..schemas import FeedbackAnalysis

            mock_output = FeedbackAnalysis(
                pattern_tags=["mock_feedback_tag"],
                semantic_summary="[Mock] Feedback analysis for testing purposes.",
                severity="medium",
                actionable_instruction="Mock actionable instruction for testing.",
                root_cause="Mock root cause for testing.",
                confidence=0.85,
            )
        else:
            # Try to create a default instance, but handle list types gracefully
            try:
                mock_output = response_model()
            except (TypeError, Exception):
                # For types that can't be instantiated without arguments (like list),
                # or Pydantic models with required fields, return None
                mock_output = None
        return LLMCallResult(
            output=mock_output,
            model=self.config.model,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=1,
            schema_compliance=True,
            raw_response=(mock_output.model_dump() if hasattr(mock_output, "model_dump") else {}),
        )


def create_client(
    model: str,
    temperature: float = 0.1,
    max_tokens: int = 4000,
    max_retries: int = 3,
    timeout: Optional[int] = 60,  # None or 0 = no timeout
    api_base: Optional[str] = None,
    langfuse_public_key: Optional[str] = None,
    langfuse_secret_key: Optional[str] = None,
    langfuse_host: str = "https://cloud.langfuse.com",
    langfuse_enabled: bool = False,
) -> LLMClient:
    """Factory function to create LLM client."""
    config = LLMClientConfig(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=max_retries,
        timeout=timeout,
        api_base=api_base,
        langfuse_public_key=langfuse_public_key,
        langfuse_secret_key=langfuse_secret_key,
        langfuse_host=langfuse_host,
        langfuse_enabled=langfuse_enabled,
    )
    return LLMClient(config)

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
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# Optional Langfuse integration
try:
    from langfuse import Langfuse

    LANGFUSE_AVAILABLE = True
except ImportError:
    LANGFUSE_AVAILABLE = False
    Langfuse = None  # type: ignore

from ..schemas import (
    BookAnalysisOutput,
    ExtractionResult,
    ParagraphAnnotation,
    QualityJudgment,
    TtsEditOutput,
    TtsRoutingDecision,
)

logger = logging.getLogger(__name__)

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
    timeout: int = 60
    mock_mode: bool = False
    mock_data_dir: str = "tests/golden"
    api_base: Optional[str] = None
    # Langfuse configuration
    langfuse_public_key: Optional[str] = None
    langfuse_secret_key: Optional[str] = None
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_enabled: bool = False


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
            self._client = instructor.from_litellm(completion)
        else:
            self._client = None

    def _init_langfuse(self):
        """Initialize Langfuse client if enabled and available."""
        if not self.config.langfuse_enabled or not LANGFUSE_AVAILABLE:
            return
        try:
            self._langfuse = Langfuse(
                public_key=self.config.langfuse_public_key,
                secret_key=self.config.langfuse_secret_key,
                host=self.config.langfuse_host,
            )
            logger.info("Langfuse client initialized")
        except Exception as e:
            logger.warning(f"Failed to initialize Langfuse: {e}")
            self._langfuse = None

    def _load_mock_data(self):
        """Load mock responses from golden dataset (few_shot.jsonl format)."""
        import glob
        import hashlib

        for filepath in glob.glob(
            f"{self.config.mock_data_dir}/**/*.jsonl", recursive=True
        ):
            # Extract stage from path: .../prompts/<stage>/few_shot.jsonl
            stage = Path(filepath).parent.name
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    data = json.loads(line)
                    # Generate hash from input data for matching
                    input_data = data.get("input", {})
                    input_str = json.dumps(
                        input_data, sort_keys=True, ensure_ascii=False
                    )
                    input_hash = hashlib.md5(input_str.encode()).hexdigest()[:8]
                    key = f"{stage}:{input_hash}"
                    self._mock_cache[key] = data.get("expected_output")
        logger.info(f"Loaded {len(self._mock_cache)} mock responses")

    def _calculate_cost(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Calculate estimated cost in USD."""
        pricing = MODEL_PRICING.get(model, {"input": 1.0, "output": 3.0})
        return (
            tokens_in * pricing["input"] + tokens_out * pricing["output"]
        ) / 1_000_000

    def _get_mock_response(self, stage: str, input_data: Dict) -> Optional[BaseModel]:
        """Get mock response for testing - returns first available for stage."""
        # In mock mode, return first available response for the stage
        for key, value in self._mock_cache.items():
            if key.startswith(f"{stage}:"):
                logger.info(f"Using mock response for {key}")
                return value

        # If no cached mock, create a minimal valid response for the stage
        if stage == "analyze":
            from ..schemas import (
                BookAnalysisOutput,
                BookMeta,
                CharacterVoiceBinding,
                EmotionSnapshot,
            )

            return BookAnalysisOutput(
                book_meta=BookMeta(
                    title="Mock Title",
                    author="Mock Author",
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
                        suggested_voice_id="zh-CN-YunjianNeural",
                        sample_quote="测试样本",
                    ),
                    CharacterVoiceBinding(
                        canonical_name="主角",
                        aliases=[],
                        gender="male",
                        age_range="young",
                        suggested_voice_id="zh-CN-YunxiNeural",
                        sample_quote="测试样本",
                    ),
                ],
                emotion_snapshots=[
                    EmotionSnapshot(
                        chapter=1,
                        dominant_emotion="neutral",
                        intensity=0.5,
                        notes="mock",
                    ),
                ],
                story_line_summary="这是一个用于测试的模拟故事摘要，包含足够的字符数以满足最小长度要求，用于验证模拟模式下的结构化输出合规性。这个摘要需要至少一百个字符才能通过验证，所以我继续添加更多文本来确保长度足够。为了确保长度超过一百个字符，我在这里额外添加了一些填充文本内容。",
                global_style_notes="Mock style notes.",
            )

        if stage == "judge":
            from ..schemas import QualityJudgment

            return QualityJudgment(
                segment_id="mock_segment",
                speaker_clarity=0.95,
                emotion_match=0.93,
                prosody_naturalness=0.92,
                text_audio_alignment=0.96,
                overall_score=0.94,
                issues=[],
                fix_suggestions=[],
                needs_regeneration=False,
            )

        if stage == "annotate":
            from ..schemas import ParagraphAnnotation

            return ParagraphAnnotation(
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
                notes="Mock annotation",
            )

        if stage == "edit":
            from ..schemas import TtsEditOutput

            return TtsEditOutput(
                edited_text="Mock edited text",
                changes_made=["mock_mode_no_changes"],
                forbidden_content_removed=[],
                confidence=0.9,
                rationale="Mock mode: no actual editing",
            )

        if stage == "route":
            from ..schemas import TtsRoutingDecision

            return TtsRoutingDecision(
                segment_id="mock_ch1_p0",
                engine_choice="kokoro",
                voice_id="zh-CN-Xiaoyi",
                prosody_overrides={"rate": "1.0", "pitch": "0st"},
                fallback_engine="edge",
                reasoning="Mock mode: using Kokoro local engine",
                estimated_cost_usd=0.0,
                estimated_duration_ms=3000,
            )

        if stage == "extract":
            from ..schemas import ExtractionResult

            return ExtractionResult(
                raw_text="Mock extracted text for testing...",
                language="zh",
                page_count=5,
                has_ocr=False,
                ocr_page_ratio=0.0,
                warnings=[],
            )

        return None

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def call(
        self,
        response_model: Type[T],
        messages: List[Dict[str, str]],
        stage: str,
        **kwargs,
    ) -> LLMCallResult:
        """Call LLM with structured output parsing.

        Args:
            response_model: Pydantic model for structured output
            messages: List of message dicts (role, content)
            stage: Pipeline stage name for logging/mock lookup
            **kwargs: Additional litellm parameters

        Returns:
            LLMCallResult with parsed output and metadata
        """
        start_time = time.time()

        # Mock mode: return cached response
        if self.config.mock_mode:
            mock = self._get_mock_response(stage, {"messages": messages})
            if mock:
                return LLMCallResult(
                    output=mock,
                    model=self.config.model,
                    tokens_in=0,
                    tokens_out=0,
                    cost_usd=0.0,
                    latency_ms=int((time.time() - start_time) * 1000),
                    schema_compliance=True,
                    contract_version=1,
                    raw_response=mock,
                )

        # Prepare call parameters
        call_kwargs = {
            "model": self.config.model,
            "messages": messages,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "timeout": self.config.timeout,
            "response_model": response_model,
            **kwargs,
        }
        if self.config.api_base:
            call_kwargs["api_base"] = self.config.api_base

        try:
            # Make the call with Instructor
            response = self._client.chat.completions.create(**call_kwargs)

            # Extract usage info
            usage = getattr(response, "_raw_response", None)
            tokens_in = 0
            tokens_out = 0
            if usage and hasattr(usage, "usage"):
                tokens_in = usage.usage.prompt_tokens or 0
                tokens_out = usage.usage.completion_tokens or 0

            cost = self._calculate_cost(self.config.model, tokens_in, tokens_out)
            latency = int((time.time() - start_time) * 1000)

            # Validate schema compliance
            schema_ok = isinstance(response, response_model)

            result = LLMCallResult(
                output=response,
                model=self.config.model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency,
                schema_compliance=schema_ok,
                contract_version=1,
                raw_response=response,
            )

            # Report to Langfuse
            self._report_langfuse_trace(
                stage=stage,
                model=self.config.model,
                messages=messages,
                response=response,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency,
                schema_ok=schema_ok,
                success=True,
                error=None,
            )

            logger.info(
                f"LLM call [{stage}] model={self.config.model} "
                f"tokens={tokens_in}/{tokens_out} cost=${cost:.6f} "
                f"latency={latency}ms schema_ok={schema_ok} contract_version={result.contract_version}"
            )

            return result

        except Exception as e:
            logger.error(f"LLM call failed [{stage}] model={self.config.model}: {e}")

            # Report error to Langfuse
            self._report_langfuse_trace(
                stage=stage,
                model=self.config.model,
                messages=messages,
                response=None,
                tokens_in=0,
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=int((time.time() - start_time) * 1000),
                schema_ok=False,
                success=False,
                error=str(e),
            )

            raise

    def _report_langfuse_trace(
        self,
        stage: str,
        model: str,
        messages: List[Dict[str, str]],
        response: Optional[Any],
        tokens_in: int,
        tokens_out: int,
        cost_usd: float,
        latency_ms: int,
        schema_ok: bool,
        success: bool,
        error: Optional[str] = None,
    ):
        """Report LLM call trace to Langfuse."""
        if not self._langfuse:
            return

        try:
            # Prepare trace data
            trace_name = f"pipeline_stage_{stage}"

            # Calculate cost if not provided
            if cost_usd == 0 and tokens_in > 0:
                cost_usd = self._calculate_cost(model, tokens_in, tokens_out)

            # Create trace
            trace = self._langfuse.trace(
                name=trace_name,
                metadata={
                    "stage": stage,
                    "model": model,
                    "schema_compliance": schema_ok,
                    "cost_usd": cost_usd,
                    "latency_ms": latency_ms,
                    "success": success,
                },
                input=messages,
                output=str(response) if response else None,
            )

            # Add generation
            trace.generation(
                name=f"{stage}_generation",
                model=model,
                input=messages,
                output=response,
                usage={
                    "input": tokens_in,
                    "output": tokens_out,
                    "total": tokens_in + tokens_out,
                },
                cost=cost_usd,
                metadata={
                    "latency_ms": latency_ms,
                    "schema_compliance": schema_ok,
                    "error": error,
                },
            )

            # Flush to ensure data is sent
            self._langfuse.flush()

        except Exception as e:
            # Don't fail the main call if Langfuse reporting fails
            logger.debug(f"Langfuse trace reporting failed: {e}")

    async def acall(
        self,
        response_model: Type[T],
        messages: List[Dict[str, str]],
        stage: str,
        **kwargs,
    ) -> LLMCallResult:
        """Async version of call (not implemented, falls back to sync)."""
        return self.call(response_model, messages, stage, **kwargs)


def create_client(
    model: str,
    mock_mode: bool = False,
    temperature: float = 0.1,
    max_tokens: int = 4000,
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
        mock_mode=mock_mode,
        api_base=api_base,
        langfuse_public_key=langfuse_public_key,
        langfuse_secret_key=langfuse_secret_key,
        langfuse_host=langfuse_host,
        langfuse_enabled=langfuse_enabled,
    )
    return LLMClient(config)

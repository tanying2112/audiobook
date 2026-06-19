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

from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

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
            import instructor
            from litellm import completion
            self._client = instructor.from_litellm(completion)
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
            for file in mock_dir.glob("*.json"):
                with open(file) as f:
                    self._mock_cache[file.stem] = json.load(f)

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
        
        if "response_model" in kwargs:
            response_model = kwargs.pop("response_model")
        
        # Validate required parameters
        if prompt is None:
            raise ValueError(
                "prompt is required (pass as first positional arg, "
                "or use prompt=, text=, or content= keyword argument)"
            )
        if response_model is None:
            raise ValueError("response_model is required")
        
        if self.config.mock_mode:
            return self._mock_call(prompt, response_model)

        start = time.time()
        try:
            result = self._client.chat.completions.create(
                model=self.config.model,
                messages=[{"role": "user", "content": prompt}],
                response_model=response_model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                **kwargs
            )
            latency_ms = int((time.time() - start) * 1000)
            return LLMCallResult(
                output=result,
                model=self.config.model,
                tokens_in=0,  # TODO: track from response
                tokens_out=0,
                cost_usd=0.0,
                latency_ms=latency_ms,
                schema_compliance=True,
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
                )
        # Return minimal valid mock
        return LLMCallResult(
            output=response_model(),
            model=self.config.model,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            latency_ms=1,
            schema_compliance=True,
        )


def create_client(
    model: str,
    mock_mode: bool = False,
    api_base: Optional[str] = None,
    langfuse_public_key: Optional[str] = None,
    langfuse_secret_key: Optional[str] = None,
    langfuse_host: str = "https://cloud.langfuse.com",
    langfuse_enabled: bool = False,
) -> LLMClient:
    """Factory function to create LLM client."""
    config = LLMClientConfig(
        model=model,
        mock_mode=mock_mode,
        api_base=api_base,
        langfuse_public_key=langfuse_public_key,
        langfuse_secret_key=langfuse_secret_key,
        langfuse_host=langfuse_host,
        langfuse_enabled=langfuse_enabled,
    )
    return LLMClient(config)

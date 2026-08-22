"""LLM integration package.

Contains:
- client: Unified LLM client with LiteLLM + Instructor
- direct_client: Native OpenAI/Anthropic SDK client (bypasses LiteLLM)
- vllm_backend: High-performance local inference with vLLM
- router: Multi-provider routing with fallback and cost tracking
- judge: LLM-as-a-Judge for quality evaluation
- circuit_breaker: Failure isolation for providers
"""

from .circuit_breaker import CircuitBreaker
from .client import LLMCallResult, LLMClient, LLMClientConfig, create_client
from .config_loader import StageName
from .direct_client import (
    DirectProviderClient,
    DirectProviderClientConfig,
    DirectProviderType,
    LLMCallResult as DirectLLMCallResult,
    create_direct_client,
)
from .judge import JudgeConfig, LLMJudge, create_judge
from .router import CostTracker, LLMRouter, ModelConfig, StageRoutingConfig, create_router, get_cost_tracker
from .utils import LLMParseError, validate_and_parse_llm_response
from .vllm_backend import (
    VLLMBackend,
    VLLMBackendConfig,
    LLMCallResult as VLLMLLMCallResult,
    create_vllm_backend,
)

__all__ = [
    "LLMClient",
    "LLMCallResult",
    "LLMClientConfig",
    "create_client",
    "DirectProviderClient",
    "DirectProviderClientConfig",
    "DirectProviderType",
    "DirectLLMCallResult",
    "create_direct_client",
    "VLLMBackend",
    "VLLMBackendConfig",
    "VLLMLLMCallResult",
    "create_vllm_backend",
    "LLMParseError",
    "validate_and_parse_llm_response",
    "LLMRouter",
    "CostTracker",
    "ModelConfig",
    "StageRoutingConfig",
    "StageName",
    "get_cost_tracker",
    "create_router",
    "LLMJudge",
    "JudgeConfig",
    "create_judge",
    "CircuitBreaker",
]

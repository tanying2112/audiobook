"""LLM integration package.

Contains:
- client: Unified LLM client with LiteLLM + Instructor
- router: Multi-provider routing with fallback and cost tracking
- judge: LLM-as-a-Judge for quality evaluation
"""

from .client import LLMCallResult, LLMClient, LLMClientConfig, create_client
from .judge import JudgeConfig, LLMJudge, create_judge
from .router import (
    CostTracker,
    LLMRouter,
    ModelConfig,
    StageRoutingConfig,
    create_router,
    get_cost_tracker,
)
from .utils import LLMParseError, validate_and_parse_llm_response

__all__ = [
    "LLMClient",
    "LLMCallResult",
    "LLMClientConfig",
    "create_client",
    "LLMParseError",
    "validate_and_parse_llm_response",
    "LLMRouter",
    "CostTracker",
    "ModelConfig",
    "StageRoutingConfig",
    "get_cost_tracker",
    "create_router",
    "LLMJudge",
    "JudgeConfig",
    "create_judge",
]

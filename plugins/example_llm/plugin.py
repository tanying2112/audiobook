"""Example third-party LLM provider plugin.

This plugin registers an OpenAI-compatible LLM provider.
It demonstrates how a third-party can add LLM providers without modifying core code.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from audiobook_studio.llm.config_loader import ProviderConfig, ProviderType, StageName
from audiobook_studio.plugins import PluginContext

logger = logging.getLogger(__name__)


@dataclass
class ExampleLLMConfig:
    """Configuration for Example LLM provider."""
    api_key_env: str
    base_url: str
    model: str
    priority: int = 50
    stages: List[str] = None

    def __post_init__(self):
        if self.stages is None:
            self.stages = ["extract", "analyze", "annotate", "edit", "judge", "translate"]


def create_example_llm_provider() -> ProviderConfig:
    """Factory function that creates a ProviderConfig from environment.

    This is called by LLMProvidersConfig.load() to supplement YAML-defined providers.
    """
    # Read config from environment (set by user in .env or docker)
    api_key_env = os.getenv("EXAMPLE_LLM_API_KEY_ENV", "EXAMPLE_LLM_API_KEY")
    base_url = os.getenv("EXAMPLE_LLM_BASE_URL", "https://api.example.com/v1")
    model = os.getenv("EXAMPLE_LLM_MODEL", "example-llm-model-1")
    priority = int(os.getenv("EXAMPLE_LLM_PRIORITY", "50"))
    stages_str = os.getenv("EXAMPLE_LLM_STAGES", "extract,analyze,annotate,edit,judge,translate")
    stages = [StageName(s.strip()) for s in stages_str.split(",") if s.strip()]

    api_key = os.getenv(api_key_env, "")

    return ProviderConfig(
        name="example_llm",
        provider=ProviderType.OPENAI,  # Use OpenAI protocol for OpenAI-compatible API
        model=model,
        api_key_env=api_key_env,
        base_url=base_url,
        priority=priority,
        max_tokens_per_minute=10000,
        max_requests_per_minute=60,
        timeout_seconds=60,
        stages=stages,
        enabled=bool(api_key),
        extra_params={},
    )


def register(ctx: PluginContext) -> None:
    """Plugin entrypoint - called by PluginManager."""
    ctx.register_llm_provider(
        provider_name="example_llm",
        factory=create_example_llm_provider,
        config_schema=ExampleLLMConfig,
        default_config={
            "api_key_env": "EXAMPLE_LLM_API_KEY",
            "base_url": "https://api.example.com/v1",
            "model": "example-llm-model-1",
            "priority": 50,
            "stages": ["extract", "analyze", "annotate", "edit", "judge", "translate"],
        },
    )
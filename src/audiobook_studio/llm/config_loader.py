# LLM Provider Config Loader
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class ProviderType(Enum):
    GROQ = "groq"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"
    OLLAMA = "ollama"
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    CEREBRAS = "cerebras"
    ALIBABA = "alibaba"
    ZHIPU = "zhipu"
    SILICONCLOUD = "siliconcloud"
    MISTRAL = "mistral"
    VOLCENGINE = "volcengine"
    TENCENT = "tencent"
    COHERE = "cohere"
    TOGETHER = "together"
    HUGGINGFACE = "huggingface"
    BAIDU_QIANFAN = "baidu_qianfan"
    CLOUDFLARE = "cloudflare"
    GITHUB = "github"
    DUCK2API = "duck2api"


class StageName(Enum):
    EXTRACT = "extract"
    ANALYZE = "analyze"
    ANNOTATE = "annotate"
    EDIT = "edit"
    ROUTE = "route"
    JUDGE = "judge"


@dataclass
class ProviderConfig:
    name: str
    provider: ProviderType
    model: str
    api_key_env: Optional[str] = None
    api_key_pool_env: List[str] = field(default_factory=list)
    key_rotation_strategy: str = "round_robin"
    base_url: Optional[str] = None
    priority: int = 100
    max_tokens_per_minute: int = 10000
    max_requests_per_minute: int = 60
    max_daily_cost_usd: float = 10.0
    stages: List[StageName] = field(default_factory=list)
    enabled: bool = True
    extra_params: Dict[str, Any] = field(default_factory=dict)

    def get_api_key(self) -> Optional[str]:
        if self.api_key_env:
            return os.getenv(self.api_key_env)
        return None

    def get_api_key_pool(self) -> List[str]:
        """Get all API keys from pool (primary + additional)."""
        keys = []
        if self.api_key_env:
            key = os.getenv(self.api_key_env)
            if key:
                keys.append(key)
        for env_var in self.api_key_pool_env:
            key = os.getenv(env_var)
            if key:
                keys.append(key)
        return keys

    def get_litellm_model_name(self) -> str:
        """Get the model name as expected by LiteLLM."""
        prefix_map = {
            ProviderType.GROQ: "groq/",
            ProviderType.DEEPSEEK: "deepseek/",
            ProviderType.OPENROUTER: "openrouter/",
            ProviderType.OLLAMA: "ollama/",
            ProviderType.GEMINI: "gemini/",
            ProviderType.OPENAI: "",
            ProviderType.ANTHROPIC: "anthropic/",
            ProviderType.CEREBRAS: "openai/",
            ProviderType.ALIBABA: "openai/",
            ProviderType.ZHIPU: "openai/",
            ProviderType.SILICONCLOUD: "openai/",
            ProviderType.MISTRAL: "openai/",
            ProviderType.VOLCENGINE: "openai/",
            ProviderType.TENCENT: "openai/",
            ProviderType.COHERE: "cohere/",
            ProviderType.TOGETHER: "openai/",
            ProviderType.HUGGINGFACE: "huggingface/",
            ProviderType.BAIDU_QIANFAN: "openai/",
            ProviderType.CLOUDFLARE: "openai/",
            ProviderType.GITHUB: "openai/",
            ProviderType.DUCK2API: "openai/",
        }
        prefix = prefix_map.get(self.provider, "")
        return f"{prefix}{self.model}"


@dataclass
class PromptCompressionConfig:
    max_input_tokens: int = 4000
    truncate_strategy: str = "smart"
    remove_few_shot_when_long: bool = True
    min_few_shot_examples: int = 1
    schema_injection_mode: str = "minimal"


@dataclass
class FallbackConfig:
    max_retries_per_provider: int = 2
    retry_on_rate_limit: bool = True
    retry_on_timeout: bool = True
    timeout_seconds: int = 60
    exponential_backoff_base: float = 2.0


@dataclass
class CostControlConfig:
    daily_limit_usd: float = 10.0
    alert_threshold: float = 0.8
    track_per_stage: bool = True


@dataclass
class LLMProvidersConfig:
    providers: List[ProviderConfig]
    prompt_compression: PromptCompressionConfig
    fallback: FallbackConfig
    cost_control: CostControlConfig

    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "LLMProvidersConfig":
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "llm_providers.yaml"

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        providers = []
        for p in data.get("providers", []):
            providers.append(
                ProviderConfig(
                    name=p["name"],
                    provider=ProviderType(p["provider"]),
                    model=p["model"],
                    api_key_env=p.get("api_key_env"),
                    api_key_pool_env=p.get("api_key_pool_env", []),
                    key_rotation_strategy=p.get("key_rotation_strategy", "round_robin"),
                    base_url=p.get("base_url"),
                    priority=p.get("priority", 100),
                    max_tokens_per_minute=p.get("max_tokens_per_minute", 10000),
                    max_requests_per_minute=p.get("max_requests_per_minute", 60),
                    stages=[StageName(s) for s in p.get("stages", [])],
                    enabled=p.get("enabled", True),
                    extra_params=p.get("extra_params", {}),
                )
            )

        # Sort by priority
        providers.sort(key=lambda p: p.priority)

        pc = data.get("prompt_compression", {})
        fallback = data.get("fallback", {})
        cost = data.get("cost_control", {})

        return cls(
            providers=providers,
            prompt_compression=PromptCompressionConfig(**pc),
            fallback=FallbackConfig(**fallback),
            cost_control=CostControlConfig(**cost),
        )

    def get_providers_for_stage(self, stage: StageName) -> List[ProviderConfig]:
        """Get enabled providers that support a specific stage, sorted by priority."""
        return [p for p in self.providers if p.enabled and stage in p.stages]

    def get_all_enabled(self) -> List[ProviderConfig]:
        return [p for p in self.providers if p.enabled]

"""PluginContext — the API surface handed to third-party plugin ``register(ctx)``.

Plugins receive a read-only context with registration methods. The context is
scoped to the plugin being loaded and validated (no arbitrary code execution
beyond the registration calls themselves).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, Type

from .manifest import PluginManifest, PluginType

logger = logging.getLogger(__name__)


# ======================================================================
# Type aliases for plugin author convenience
# ======================================================================

# TTS Engine factory: callable that returns a TTSEngine instance.
# The config dict is whatever the plugin's config_schema accepts.
TTSEngineFactory = Callable[..., "TTSEngine"]

# LLM Provider factory: callable that returns a ProviderConfig (or dict).
LLMProviderFactory = Callable[..., "ProviderConfig"]

# Pipeline stage function signature
StageFn = Callable[..., Any]


# Forward reference types for registration (avoid circular imports)
class TTSEngine(Protocol):
    """Minimal protocol for plugin-author type hints."""

    engine_name: str

    async def synthesize(self, payload: Any, output_path: Any) -> Any: ...
    async def submit(self, task_id: str, payload: Any) -> bool: ...
    async def get_status(self, task_id: str) -> Any: ...
    async def get_result(self, task_id: str) -> Any: ...
    async def cancel(self, task_id: str) -> bool: ...
    async def stream(self, payload: Any) -> Any: ...
    async def health_check(self) -> Dict[str, Any]: ...
    async def close(self) -> None: ...


class ProviderConfig(Protocol):
    """Minimal protocol for plugin-author type hints."""

    name: str
    provider: str
    model: str


# ======================================================================
# PluginContext — handed to register(ctx)
# ======================================================================


@dataclass(frozen=True)
class PluginContext:
    """API surface given to a plugin's ``register(ctx)`` function.

    Usage:
        def register(ctx: PluginContext):
            ctx.register_tts_engine("my_tts", MyEngine, config_schema=MyConfig)
            ctx.register_llm_provider("my_llm", create_provider_config)
    """

    # The manifest of the plugin currently being loaded
    manifest: PluginManifest

    # ------------------------------------------------------------------
    # TTS Engine Registration
    # ------------------------------------------------------------------
    def register_tts_engine(
        self,
        engine_name: str,
        factory: TTSEngineFactory,
        *,
        config_schema: Optional[Type[Any]] = None,
        default_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a TTS engine factory.

        The factory will be invoked by ``EngineRegistry.initialize()`` with
        the config dict from unified config (key = engine_name).

        Args:
            engine_name: Unique identifier (e.g., "kokoro", "edge", "my_tts").
            factory: Async callable returning a TTSEngine instance.
            config_schema: Optional Pydantic model for config validation/docs.
            default_config: Default config values (merged under user config).
        """
        from .registry import get_plugin_manager

        mgr = get_plugin_manager()
        mgr.register_tts_engine_factory(
            plugin_name=self.manifest.name,
            engine_name=engine_name,
            factory=factory,
            config_schema=config_schema,
            default_config=default_config,
        )

    # ------------------------------------------------------------------
    # LLM Provider Registration
    # ------------------------------------------------------------------
    def register_llm_provider(
        self,
        provider_name: str,
        factory: LLMProviderFactory,
        *,
        config_schema: Optional[Type[Any]] = None,
        default_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register an LLM provider factory.

        The factory will be invoked by ``LLMProvidersConfig.load()`` to
        supplement/replace YAML-defined providers.

        Args:
            provider_name: Unique identifier (e.g., "my_gateway", "custom_llm").
            factory: Callable returning a ProviderConfig instance.
            config_schema: Optional Pydantic model for config validation/docs.
            default_config: Default config values.
        """
        from .registry import get_plugin_manager

        mgr = get_plugin_manager()
        mgr.register_llm_provider_factory(
            plugin_name=self.manifest.name,
            provider_name=provider_name,
            factory=factory,
            config_schema=config_schema,
            default_config=default_config,
        )

    # ------------------------------------------------------------------
    # Pipeline Stage Registration
    # ------------------------------------------------------------------
    def register_pipeline_stage(
        self,
        stage_name: str,
        factory: StageFn,
        *,
        config_schema: Optional[Type[Any]] = None,
        default_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Register a pipeline stage function.

        The stage will be available to the orchestrator as an alternative
        implementation for the named stage (e.g., "extract", "analyze").

        Args:
            stage_name: Pipeline stage identifier.
            factory: Callable returning the stage implementation.
            config_schema: Optional Pydantic model for config validation/docs.
            default_config: Default config values.
        """
        from .registry import get_plugin_manager

        mgr = get_plugin_manager()
        mgr.register_pipeline_stage_factory(
            plugin_name=self.manifest.name,
            stage_name=stage_name,
            factory=factory,
            config_schema=config_schema,
            default_config=default_config,
        )

        # Bridge the plugin factory into the runtime StageRegistry so the
        # orchestrator can dispatch to it via StageRegistry.get(stage_name)
        # exactly like a built-in stage. Lazy import avoids a cycle between the
        # plugins and pipeline packages at import time.
        try:
            from ..pipeline.stage_registry import StageRegistry

            StageRegistry.register_factory(stage_name, factory)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to register stage '%s' into StageRegistry: %s",
                stage_name,
                exc,
            )

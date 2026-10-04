"""Plugin registry and manager — the core of the plugin ecosystem.

Maintains:
- Discovered plugin manifests
- Installed/enabled plugin state (from config/installed_plugins.json)
- Registered factories (TTS engines, LLM providers, pipeline stages)

The manager loads plugins on demand (when EngineRegistry / LLMProvidersConfig
initializes) and caches the registered factories for lookup.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Type

from .manifest import (
    PluginManifest,
    discover_plugins,
    read_installed_names,
)

logger = logging.getLogger(__name__)


# ======================================================================
# Factory registration records
# ======================================================================


@dataclass(frozen=True)
class TTSEngineFactoryRecord:
    """Record of a registered TTS engine factory."""

    plugin_name: str
    engine_name: str
    factory: Callable[..., Any]
    config_schema: Optional[Type[Any]] = None
    default_config: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMProviderFactoryRecord:
    """Record of a registered LLM provider factory."""

    plugin_name: str
    provider_name: str
    factory: Callable[..., Any]
    config_schema: Optional[Type[Any]] = None
    default_config: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineStageFactoryRecord:
    """Record of a registered pipeline stage factory."""

    plugin_name: str
    stage_name: str
    factory: Callable[..., Any]
    config_schema: Optional[Type[Any]] = None
    default_config: Dict[str, Any] = field(default_factory=dict)


# ======================================================================
# PluginRegistry — simple lookup for registered factories
# ======================================================================


class PluginRegistry:
    """Read-only view of registered plugin factories."""

    def __init__(
        self,
        tts_engines: Dict[str, TTSEngineFactoryRecord],
        llm_providers: Dict[str, LLMProviderFactoryRecord],
        pipeline_stages: Dict[str, PipelineStageFactoryRecord],
    ):
        self._tts_engines = tts_engines
        self._llm_providers = llm_providers
        self._pipeline_stages = pipeline_stages

    # TTS
    def get_tts_engine_factory(self, engine_name: str) -> Optional[TTSEngineFactoryRecord]:
        return self._tts_engines.get(engine_name)

    def list_tts_engine_names(self) -> List[str]:
        return list(self._tts_engines.keys())

    # LLM
    def get_llm_provider_factory(self, provider_name: str) -> Optional[LLMProviderFactoryRecord]:
        return self._llm_providers.get(provider_name)

    def list_llm_provider_names(self) -> List[str]:
        return list(self._llm_providers.keys())

    # Pipeline
    def get_pipeline_stage_factory(self, stage_name: str) -> Optional[PipelineStageFactoryRecord]:
        return self._pipeline_stages.get(stage_name)

    def list_pipeline_stage_names(self) -> List[str]:
        return list(self._pipeline_stages.keys())


# ======================================================================
# PluginManager — discovery, loading, registration
# ======================================================================


class PluginManager:
    """Manages plugin discovery, installation state, and factory registration."""

    _instance: Optional["PluginManager"] = None
    _initialized: bool = False

    def __new__(cls) -> "PluginManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True

        # Discovered manifests (from plugins/ dir)
        self._manifests: Dict[str, PluginManifest] = {}

        # Installed/enabled state
        self._installed_names: List[str] = []

        # Registered factories
        self._tts_engine_factories: Dict[str, TTSEngineFactoryRecord] = {}
        self._llm_provider_factories: Dict[str, LLMProviderFactoryRecord] = {}
        self._pipeline_stage_factories: Dict[str, PipelineStageFactoryRecord] = {}

        # Load state
        self._loaded_plugins: set[str] = set()
        self._load_errors: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Discovery & Installation
    # ------------------------------------------------------------------

    def discover(self, plugins_dir: Optional[Path] = None) -> List[PluginManifest]:
        """Discover and cache plugin manifests."""
        self._manifests = {m.name: m for m in discover_plugins(plugins_dir)}
        return list(self._manifests.values())

    def get_manifest(self, name: str) -> Optional[PluginManifest]:
        return self._manifests.get(name)

    def list_manifests(self) -> List[PluginManifest]:
        return list(self._manifests.values())

    def load_installed(self, installed_path: Optional[Path] = None) -> None:
        """Read installed plugin names from config/installed_plugins.json."""
        self._installed_names = read_installed_names(installed_path)

    def is_installed(self, name: str) -> bool:
        return name in self._installed_names

    def is_enabled(self, name: str) -> bool:
        return self.is_installed(name)

    # ------------------------------------------------------------------
    # Factory Registration (called from PluginContext)
    # ------------------------------------------------------------------

    def register_tts_engine_factory(
        self,
        plugin_name: str,
        engine_name: str,
        factory: Callable[..., Any],
        *,
        config_schema: Optional[Type[Any]] = None,
        default_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        if engine_name in self._tts_engine_factories:
            existing = self._tts_engine_factories[engine_name].plugin_name
            logger.warning(
                "TTS engine '%s' already registered by plugin '%s'; " "overriding with '%s'",
                engine_name,
                existing,
                plugin_name,
            )
        self._tts_engine_factories[engine_name] = TTSEngineFactoryRecord(
            plugin_name=plugin_name,
            engine_name=engine_name,
            factory=factory,
            config_schema=config_schema,
            default_config=default_config or {},
        )
        logger.info("Registered TTS engine '%s' from plugin '%s'", engine_name, plugin_name)

    def register_llm_provider_factory(
        self,
        plugin_name: str,
        provider_name: str,
        factory: Callable[..., Any],
        *,
        config_schema: Optional[Type[Any]] = None,
        default_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        if provider_name in self._llm_provider_factories:
            existing = self._llm_provider_factories[provider_name].plugin_name
            logger.warning(
                "LLM provider '%s' already registered by plugin '%s'; " "overriding with '%s'",
                provider_name,
                existing,
                plugin_name,
            )
        self._llm_provider_factories[provider_name] = LLMProviderFactoryRecord(
            plugin_name=plugin_name,
            provider_name=provider_name,
            factory=factory,
            config_schema=config_schema,
            default_config=default_config or {},
        )
        logger.info("Registered LLM provider '%s' from plugin '%s'", provider_name, plugin_name)

    def register_pipeline_stage_factory(
        self,
        plugin_name: str,
        stage_name: str,
        factory: Callable[..., Any],
        *,
        config_schema: Optional[Type[Any]] = None,
        default_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        if stage_name in self._pipeline_stage_factories:
            existing = self._pipeline_stage_factories[stage_name].plugin_name
            logger.warning(
                "Pipeline stage '%s' already registered by plugin '%s'; " "overriding with '%s'",
                stage_name,
                existing,
                plugin_name,
            )
        self._pipeline_stage_factories[stage_name] = PipelineStageFactoryRecord(
            plugin_name=plugin_name,
            stage_name=stage_name,
            factory=factory,
            config_schema=config_schema,
            default_config=default_config or {},
        )
        logger.info("Registered pipeline stage '%s' from plugin '%s'", stage_name, plugin_name)

    # ------------------------------------------------------------------
    # Plugin Loading (imports entry module, calls register(ctx))
    # ------------------------------------------------------------------

    def load_plugin(self, name: str) -> bool:
        """Load a single plugin by name (import entry module, call register).

        Returns True on success, False on failure (errors are logged).
        """
        if name in self._loaded_plugins:
            return True

        manifest = self._manifests.get(name)
        if manifest is None:
            logger.warning("Plugin '%s' not discovered", name)
            return False

        if not manifest.is_loadable:
            logger.info("Plugin '%s' has no loadable entrypoint", name)
            return True  # Not an error

        try:
            # Add plugin directory to sys.path for import
            import sys

            plugin_dir = Path(manifest.directory) if manifest.directory else None
            if plugin_dir and str(plugin_dir) not in sys.path:
                sys.path.insert(0, str(plugin_dir))

            # Use unique module name to avoid sys.modules collision
            module_name = f"audiobook_studio.plugins.{manifest.name}.{manifest.entry_module}"
            entry_dir = Path(manifest.directory) if manifest.directory else Path.cwd()
            spec = importlib.util.spec_from_file_location(module_name, entry_dir / f"{manifest.entry_module}.py")
            if spec is None or spec.loader is None:
                raise ImportError(f"Could not load spec for {manifest.entry_module}")
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)
        except (ImportError, OSError) as exc:
            # OSError covers FileNotFoundError when the entry module is missing
            # on disk (broken plugin package) — fail the plugin, not the suite.
            self._load_errors[name] = f"Import failed: {exc}"
            logger.error("Failed to import plugin '%s' entry module %s: %s", name, manifest.entry_module, exc)
            return False

        register_fn = getattr(module, "register", None)
        if register_fn is None:
            self._load_errors[name] = "No register(ctx) function in entry module"
            logger.error("Plugin '%s' entry module has no register(ctx)", name)
            return False

        from .context import PluginContext

        ctx = PluginContext(manifest=manifest)
        try:
            register_fn(ctx)
            self._loaded_plugins.add(name)
            logger.info("Plugin '%s' loaded successfully", name)
            return True
        except Exception as exc:
            self._load_errors[name] = f"register() failed: {exc}"
            logger.exception("Plugin '%s' register() raised: %s", name, exc)
            return False

    def load_all_installed(self) -> Dict[str, bool]:
        """Load all installed+enabled plugins.

        Returns a mapping of plugin_name -> success(bool).
        """
        self.discover()
        self.load_installed()
        results: Dict[str, bool] = {}
        for name in self._installed_names:
            if not self.is_enabled(name):
                logger.info("Plugin '%s' installed but disabled, skipping", name)
                continue
            results[name] = self.load_plugin(name)
        return results

    # ------------------------------------------------------------------
    # Registry Access (for EngineRegistry / LLMProvidersConfig)
    # ------------------------------------------------------------------

    def get_registry(self) -> PluginRegistry:
        """Get a snapshot registry of all currently registered factories."""
        return PluginRegistry(
            tts_engines=dict(self._tts_engine_factories),
            llm_providers=dict(self._llm_provider_factories),
            pipeline_stages=dict(self._pipeline_stage_factories),
        )

    def get_tts_engine_factories(self) -> Dict[str, TTSEngineFactoryRecord]:
        return dict(self._tts_engine_factories)

    def get_llm_provider_factories(self) -> Dict[str, LLMProviderFactoryRecord]:
        return dict(self._llm_provider_factories)

    def get_pipeline_stage_factories(self) -> Dict[str, PipelineStageFactoryRecord]:
        return dict(self._pipeline_stage_factories)

    # ------------------------------------------------------------------
    # Metadata / Diagnostics
    # ------------------------------------------------------------------

    def get_load_errors(self) -> Dict[str, str]:
        return dict(self._load_errors)

    def list_loaded_plugins(self) -> List[str]:
        return list(self._loaded_plugins)


def get_plugin_manager() -> PluginManager:
    """Singleton accessor."""
    return PluginManager()

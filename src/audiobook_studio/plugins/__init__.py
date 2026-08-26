"""Audiobook Studio Plugin Ecosystem.

Third-party plugins can register:
- TTS engines (implementing TTSEngine protocol)
- LLM providers (via ProviderConfig)
- Pipeline stages (callables matching StageFn signature)

Usage (in plugin entry module):
    from audiobook_studio.plugins import get_plugin_manager, PluginContext

    def register(ctx: PluginContext):
        ctx.register_tts_engine("my_tts", MyTTSEngine, config_schema=MyConfig)
        ctx.register_llm_provider("my_llm", ProviderConfig(...))

The plugin manager discovers plugins in:
- ./plugins/ (repo root, user/community plugins)
- ./src/audiobook_studio/plugins/ (bundled/core plugins, if any)

Installation is via the marketplace API (config/installed_plugins.json).
"""
from .manifest import PluginManifest, PluginType, discover_plugins, read_installed_names, list_installed_plugins as _list_installed_plugins_detail
from .context import PluginContext
from .registry import PluginRegistry, get_plugin_manager

__all__ = [
    "PluginManifest",
    "PluginType",
    "PluginContext",
    "PluginRegistry",
    "get_plugin_manager",
    "discover_plugins",
    "list_installed_plugins",
    "read_installed_names",
]

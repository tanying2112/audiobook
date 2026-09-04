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

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .context import PluginContext
from .manifest import (
    DEFAULT_INSTALLED_PATH,
    DEFAULT_PLUGINS_DIR,
    PluginManifest,
    PluginType,
    discover_plugins,
)
from .manifest import list_installed_plugins as _list_installed_plugins_detail
from .manifest import (
    parse_manifest,
    read_installed_names,
)
from .registry import PluginManager, PluginRegistry, get_plugin_manager

__all__ = [
    "PluginManifest",
    "PluginType",
    "PluginContext",
    "PluginRegistry",
    "PluginManager",
    "get_plugin_manager",
    "discover_plugins",
    "list_installed_plugins",
    "parse_manifest",
    "read_installed_names",
]


# ─────────────────────────────────────────────────────────────────────────────
# Marketplace facade (S3.5): module-level install management.
#
# 路径为模块级变量，测试/marketplace 可 monkeypatch 以隔离到临时目录；
# 函数体在调用时读取当前值（而非闭包默认值）。
# ─────────────────────────────────────────────────────────────────────────────

PLUGINS_DIR = DEFAULT_PLUGINS_DIR
INSTALLED_PLUGINS_PATH = DEFAULT_INSTALLED_PATH

__all__ += ["PLUGINS_DIR", "INSTALLED_PLUGINS_PATH", "install_plugin", "uninstall_plugin", "list_installed_plugins"]


def _write_installed_names(names: List[str], installed_path: Optional[Path] = None) -> None:
    """Atomically persist the installed-plugin registry."""
    path = installed_path or INSTALLED_PLUGINS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"installed": names}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def install_plugin(
    name: str, *, plugins_dir: Optional[Path] = None, installed_path: Optional[Path] = None
) -> Dict[str, Any]:
    """Registration-only install: record *name* into the installed registry.

    Raises KeyError if the plugin is not discoverable under PLUGINS_DIR.
    Idempotent: installing an already-installed plugin is a no-op.
    """
    dirp = plugins_dir or PLUGINS_DIR
    path = installed_path or INSTALLED_PLUGINS_PATH

    known = {m.name for m in discover_plugins(dirp)}
    if name not in known:
        raise KeyError(name)

    installed = read_installed_names(path)
    already = name in installed
    if not already:
        _write_installed_names(installed + [name], path)
    return {"installed": True, "already_installed": already}


def list_installed_plugins(*, installed_path: Optional[Path] = None) -> List[str]:
    """Return installed plugin *names* (marketplace facade contract)."""
    return read_installed_names(installed_path or INSTALLED_PLUGINS_PATH)


def uninstall_plugin(name: str, *, installed_path: Optional[Path] = None) -> Dict[str, Any]:
    """Remove *name* from the installed registry (idempotent)."""
    path = installed_path or INSTALLED_PLUGINS_PATH
    installed = read_installed_names(path)
    if name in installed:
        _write_installed_names([n for n in installed if n != name], path)
        return {"removed": True}
    return {"removed": False}

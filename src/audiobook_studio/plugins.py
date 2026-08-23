"""Plugin ecosystem — S3.5 (plugin marketplace + one-click install).

Scans the repo ``plugins/`` directory for plugin manifests and exposes
discovery + idempotent installation. Installation is **registration-only**
(writes ``config/installed_plugins.json``); it never triggers network
downloads, honouring the "free resources only" constraint. TTS model weights
themselves are loaded on demand by the local engines (Kokoro / Edge).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List

# plugins/ lives at the repository root, two levels above this file.
PLUGINS_DIR = Path(__file__).resolve().parents[2] / "plugins"
INSTALLED_PLUGINS_PATH = Path(__file__).resolve().parents[2] / "config" / "installed_plugins.json"


@dataclass(frozen=True)
class PluginManifest:
    """Parsed plugin manifest (see ``plugins/README.md``)."""

    name: str
    version: str
    type: str
    description: str = ""
    models: List[str] = field(default_factory=list)
    entry: str = ""


def _parse_manifest(path: Path) -> PluginManifest:
    raw: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return PluginManifest(
        name=str(raw.get("name", path.parent.name)),
        version=str(raw.get("version", "0.0.0")),
        type=str(raw.get("type", "unknown")),
        description=str(raw.get("description", "")),
        models=list(raw.get("models", [])),
        entry=str(raw.get("entry", "")),
    )


def discover_plugins(plugins_dir: Path | None = None) -> List[PluginManifest]:
    """Scan ``plugins/<name>/manifest.json`` and return all valid manifests.

    Missing/invalid manifests are skipped (logged) rather than raising, so a
    single broken plugin cannot break the whole marketplace.
    """
    root = plugins_dir or PLUGINS_DIR
    if not root.exists():
        return []
    found: List[PluginManifest] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            found.append(_parse_manifest(manifest_path))
        except (json.JSONDecodeError, OSError):
            # Skip malformed plugin, keep the marketplace healthy.
            continue
    return found


def _read_installed() -> Dict[str, Any]:
    if not INSTALLED_PLUGINS_PATH.exists():
        return {"installed": []}
    try:
        data = json.loads(INSTALLED_PLUGINS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "installed" not in data:
            return {"installed": []}
        return data
    except (json.JSONDecodeError, OSError):
        return {"installed": []}


def _write_installed(data: Dict[str, Any]) -> None:
    INSTALLED_PLUGINS_PATH.parent.mkdir(parents=True, exist_ok=True)
    INSTALLED_PLUGINS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def list_installed_plugins() -> List[str]:
    """Return the names of currently installed plugins."""
    return list(_read_installed().get("installed", []))


def install_plugin(name: str, plugins_dir: Path | None = None) -> Dict[str, Any]:
    """One-click install of a plugin by name (registration-only, idempotent).

    Returns a status dict: ``{"name", "installed": bool, "already_installed": bool}``.
    Raises ``KeyError`` (caller maps to 404) if the plugin is not discoverable.
    """
    manifest = next(
        (p for p in discover_plugins(plugins_dir) if p.name == name), None
    )
    if manifest is None:
        raise KeyError(f"Plugin not found: {name}")

    data = _read_installed()
    installed = set(data.get("installed", []))
    already = name in installed
    installed.add(name)
    data["installed"] = sorted(installed)
    _write_installed(data)
    return {"name": name, "installed": True, "already_installed": already}


def uninstall_plugin(name: str) -> Dict[str, Any]:
    """Remove a plugin from the installed registry (registration only)."""
    data = _read_installed()
    installed = set(data.get("installed", []))
    removed = name in installed
    installed.discard(name)
    data["installed"] = sorted(installed)
    _write_installed(data)
    return {"name": name, "removed": removed}


def plugin_manifest_to_dict(manifest: PluginManifest) -> Dict[str, Any]:
    return asdict(manifest)

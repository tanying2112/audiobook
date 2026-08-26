"""Plugin manifest definitions for Audiobook Studio plugin ecosystem."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)

# plugins/ lives at the repository root, three levels above this file (src/audiobook_studio/plugins -> src -> repo_root).
DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parents[3] / "plugins"
#: Registry of installed plugin names (written by the marketplace API).
DEFAULT_INSTALLED_PATH = (
    Path(__file__).resolve().parents[3] / "config" / "installed_plugins.json"
)


class PluginType(str, Enum):
    """Type of plugin functionality."""
    TTS_ENGINE = "tts_engine"
    LLM_PROVIDER = "llm_provider"
    PIPELINE_STAGE = "pipeline_stage"
    VOICE_CLONER = "voice_cloner"
    AUDIO_PROCESSOR = "audio_processor"
    EXPORTER = "exporter"
    
    # Aliases for backward compatibility
    TTS_VOICE = "tts_voice"
    LLM_MODEL = "llm_model"
    
    @property
    def is_loadable(self) -> bool:
        """True if this plugin type has a runtime entrypoint we can load."""
        return self in {PluginType.TTS_ENGINE, PluginType.LLM_PROVIDER, PluginType.PIPELINE_STAGE}


class PluginManifest(BaseModel):
    """Manifest describing a plugin's metadata and capabilities."""
    
    model_config = ConfigDict(use_enum_values=True)
    
    name: str = Field(..., description="Unique plugin identifier (e.g., 'xtts-v2')")
    version: str = Field(..., description="Semantic version (e.g., '1.0.0')")
    type: PluginType = Field(..., description="Plugin type")
    description: str = Field(default="", description="Human-readable description")
    author: str = Field(default="", description="Plugin author")
    license: str = Field(default="MIT", description="License identifier")
    homepage: Optional[str] = Field(default=None, description="Project homepage URL")
    repository: Optional[str] = Field(default=None, description="Source repository URL")
    
    # Models/voices this plugin provides
    models: List[str] = Field(default_factory=list, description="Models or voices provided")
    
    # Dependencies
    requires: List[str] = Field(default_factory=list, description="Required plugin names")
    python_requires: str = Field(default=">=3.10", description="Python version requirement")
    extra_dependencies: List[str] = Field(default_factory=list, description="Extra pip packages")
    
    # Capabilities
    capabilities: Dict[str, Any] = Field(default_factory=dict, description="Plugin-specific capabilities")
    config_schema: Optional[Dict[str, Any]] = Field(default=None, description="JSON schema for plugin config")
    
    # Entry point
    entry_point: str = Field(default="", description="Module:function to call for registration")
    entry: str = Field(default="", description="Entry module (legacy)")
    directory: Optional[str] = Field(default=None, description="Plugin directory path")
    
    @property
    def is_loadable(self) -> bool:
        """True if this plugin has a runtime entrypoint we can load."""
        return bool(self.entry_point) and self.type in {
            PluginType.TTS_ENGINE,
            PluginType.LLM_PROVIDER,
            PluginType.PIPELINE_STAGE,
        }

    @property
    def entry_module(self) -> str:
        """Dotted module path for the entry module (importlib-friendly)."""
        if not self.entry_point:
            return ""
        return self.entry_point.split(":")[0] if ":" in self.entry_point else self.entry_point


class PluginInfo(BaseModel):
    """Runtime information about an installed plugin."""
    manifest: PluginManifest
    installed_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)


def parse_manifest(path: Path) -> Optional[PluginManifest]:
    """Parse a manifest.json into a PluginManifest.

    Returns None (logged) for malformed manifests so a single broken plugin
    cannot break the whole ecosystem.
    """
    try:
        raw: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Skipping malformed plugin manifest %s: %s", path, exc)
        return None

    name = str(raw.get("name") or path.parent.name)
    return PluginManifest(
        name=name,
        version=str(raw.get("version", "0.0.0")),
        type=PluginType(str(raw.get("type", "unknown"))),
        description=str(raw.get("description", "")),
        author=str(raw.get("author", "")),
        license=str(raw.get("license", "MIT")),
        homepage=raw.get("homepage"),
        repository=raw.get("repository"),
        models=[str(m) for m in raw.get("models", [])],
        entry_point=str(raw.get("entry_point", "")),
        entry=str(raw.get("entry", "")),
        directory=str(path.parent),
    )


def discover_plugins(
    plugins_dir: Optional[Path] = None,
) -> List[PluginManifest]:
    """Scan ``<plugins_dir>/<name>/manifest.json`` for valid manifests.

    Plugins are returned sorted by name for deterministic load order.
    """
    root = plugins_dir or DEFAULT_PLUGINS_DIR
    if not root.exists():
        return []
    found: List[PluginManifest] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        manifest_path = child / "manifest.json"
        if not manifest_path.exists():
            continue
        parsed = parse_manifest(manifest_path)
        if parsed is not None:
            found.append(parsed)
    return found


def read_installed_names(installed_path: Optional[Path] = None) -> List[str]:
    """Return plugin names recorded as installed (idempotent, tolerant)."""
    path = installed_path or DEFAULT_INSTALLED_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        names = data.get("installed", [])
        if isinstance(names, list):
            return [str(n) for n in names]
        return []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read installed plugins %s: %s", path, exc)
        return []


def list_installed_plugins(installed_path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Return detailed info for installed plugins."""
    path = installed_path or DEFAULT_INSTALLED_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        installed = data.get("installed", [])
        if isinstance(installed, list):
            return installed
        return []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Could not read installed plugins %s: %s", path, exc)
        return []

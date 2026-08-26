"""Model marketplace catalog — S3.5 (GET /api/v1/models).

Builds an aggregated, free-resource catalog of installable models:
- TTS engines (Edge / Kokoro) with their per-language voices.
- Discovered plugins (see ``plugins.py``) and their provided models.

LLM provider models are listed separately under the provider-management API
(``GET /api/v1/providers/{id}/models/``) because they depend on the user's
configured providers. This catalog is DB-free so it is deterministic and easy
to test.
"""

from __future__ import annotations

from typing import Any, Dict, List

from . import plugins
from .languages import SUPPORTED_LANGUAGES, tts_engine_for


def _tts_engine_catalog() -> List[Dict[str, Any]]:
    """Static TTS engine + voice catalog (free, local engines)."""
    engines: List[Dict[str, Any]] = []
    edge_voices: List[Dict[str, str]] = []
    kokoro_voices: List[Dict[str, str]] = []
    for iso, info in SUPPORTED_LANGUAGES.items():
        edge_voices.append(
            {
                "model_id": f"edge-{info.bcp47}",
                "language": iso,
                "voice": info.default_edge_voice,
                "engine": "edge",
            }
        )
        # Kokoro is a free local engine; map each language to its Kokoro tag.
        kokoro_tag = {"zh": "zh", "en": "en", "ja": "jp", "ko": "ko"}.get(iso)
        if kokoro_tag:
            kokoro_voices.append(
                {
                    "model_id": f"kokoro-{info.bcp47}",
                    "language": iso,
                    "voice": f"af_heart ({kokoro_tag})",
                    "engine": "kokoro",
                }
            )
    engines.append(
        {"engine": "edge", "free": True, "voices": edge_voices}
    )
    engines.append(
        {"engine": "kokoro", "free": True, "voices": kokoro_voices}
    )
    return engines


def build_model_catalog() -> Dict[str, Any]:
    """Return the aggregated model marketplace catalog (S3.5)."""
    discovered = plugins.discover_plugins()
    installed = set(plugins.read_installed_names())
    plugin_entries: List[Dict[str, Any]] = []
    for m in discovered:
        plugin_entries.append(
            {
                "name": m.name,
                "version": m.version,
                "type": m.type,
                "description": m.description,
                "models": list(m.models),
                "installed": m.name in installed,
            }
        )
    return {
        "tts_engines": _tts_engine_catalog(),
        "plugins": plugin_entries,
        "total_models": (
            sum(len(e["voices"]) for e in _tts_engine_catalog())
            + sum(len(p["models"]) for p in plugin_entries)
        ),
    }

"""Load the TTS provider registry from ``config/tts_providers.yaml`` (S2-4).

Provides a single source of truth for engine *priority*, *enablement*, and (P0)
*capabilities* / *license*, so the API voice enumeration, the ``EngineRegistry``,
and the capability-aware ``select_engine`` agree on ordering and on what each
engine can actually do. Falls back to built-in defaults when the file is absent.

P0 (capability-aware provider model)
------------------------------------
The single numeric ``priority`` cannot express "only pick F5 when cloning + zh +
GPU is available". We therefore parse, per provider:

  - ``capabilities``: ``{cloning, emotion, languages:[zh,en], min_compute: cpu|gpu}``
  - ``license``:      ``{commercial_use, name, verified_at}`` (P2.11 honesty)

and expose ``capability_matrix()`` + ``select_engine(...) -> (engine, mode)`` where
``mode ∈ {clone, preset, standard}``. ``select_engine`` degrades gracefully: when
cloning is requested but no GPU clone backend is available (free + no-GPU reality),
it returns a CPU *preset* engine with ``mode="preset"`` instead of selecting an
engine it cannot run or pretending to clone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = __import__("logging").getLogger(__name__)

DEFAULT_CONFIG_PATH = (
    Path(__file__).parent.parent.parent / "config" / "tts_providers.yaml"
)

#: Fallback ordering if the YAML file is missing.
FALLBACK_PROVIDERS: List[Dict[str, object]] = [
    {"name": "piper", "engine": "piper", "priority": 0, "enabled": True,
     "capabilities": {"cloning": False, "emotion": False, "languages": ["zh", "en"], "min_compute": "cpu"},
     "license": {"commercial_use": True, "name": "Piper (MIT/Apache)", "verified_at": None}},
    {"name": "kokoro", "engine": "kokoro", "priority": 1, "enabled": True,
     "capabilities": {"cloning": False, "emotion": False, "languages": ["zh", "en"], "min_compute": "cpu"},
     "license": {"commercial_use": True, "name": "Kokoro-82M Apache-2.0", "verified_at": None}},
    {"name": "edge_tts", "engine": "edge_tts", "priority": 2, "enabled": True,
     "capabilities": {"cloning": False, "emotion": False, "languages": ["zh", "en"], "min_compute": "cpu"},
     "license": {"commercial_use": None, "name": "Edge-TTS (Microsoft cloud, ToS-restricted)", "verified_at": None}},
]


# ---------------------------------------------------------------------------
# Capability / license dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EngineCapability:
    """What an engine can actually do (P0 capability matrix)."""

    cloning: bool = False
    emotion: bool = False
    languages: Tuple[str, ...] = ("zh", "en")
    min_compute: str = "cpu"  # "cpu" | "gpu"


@dataclass(frozen=True)
class EngineLicense:
    """TTS engine commercial-license metadata (P2.11 honesty).

    ``commercial_use=None`` = unverified (warn, never fake a claim).
    ``True`` only when the official license explicitly permits commercial use.
    ``False`` blocks registration under the commercial profile.
    """

    commercial_use: Optional[bool] = None
    name: Optional[str] = None
    verified_at: Optional[str] = None


#: Env var that turns on GPU-only engines (F5/CosyVoice2/Dia). Default OFF so
#: no-GPU hosts (sandbox / CI / CPU prod) never select an engine they can't run.
GPU_BACKENDS_ENV = "ENABLE_GPU_BACKENDS"


def gpu_backends_enabled() -> bool:
    """Whether GPU-only TTS backends are allowed to be selected/instantiated."""
    return os.environ.get(GPU_BACKENDS_ENV, "false").lower() in ("1", "true", "yes", "on")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_tts_provider_config(path: Optional[str] = None) -> List[Dict[str, object]]:
    """Load and validate the TTS provider list, sorted by ascending priority.

    Returns a list of dicts with at least ``name``, ``engine``, ``priority``,
    ``enabled``, ``capabilities`` (``EngineCapability``-shaped dict) and
    ``license`` (``EngineLicense``-shaped dict). Falls back to
    :data:`FALLBACK_PROVIDERS` on any error.
    """
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        return [dict(p) for p in FALLBACK_PROVIDERS]

    try:
        import yaml

        with open(cfg_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        providers = data.get("providers") or []
        if not isinstance(providers, list):
            raise ValueError("config/tts_providers.yaml: 'providers' must be a list")

        normalized: List[Dict[str, object]] = []
        for idx, p in enumerate(providers):
            cap = p.get("capabilities") or {}
            lic = p.get("license") or {}
            normalized.append(
                {
                    "name": p.get("name", f"provider_{idx}"),
                    "engine": p.get("engine", p.get("name")),
                    "priority": int(p.get("priority", idx)),
                    "enabled": bool(p.get("enabled", True)),
                    "default_voice": p.get("default_voice"),
                    "auto_download": bool(p.get("auto_download", False)),
                    "model_dir": p.get("model_dir"),
                    "capabilities": {
                        "cloning": bool(cap.get("cloning", False)),
                        "emotion": bool(cap.get("emotion", False)),
                        "languages": list(cap.get("languages", ["zh", "en"])),
                        "min_compute": str(cap.get("min_compute", "cpu")).lower(),
                    },
                    "license": {
                        "commercial_use": lic.get("commercial_use"),
                        "name": lic.get("name"),
                        "verified_at": lic.get("verified_at"),
                    },
                }
            )
        normalized.sort(key=lambda x: x["priority"])
        return normalized
    except Exception as e:  # noqa: BLE001 — degrade to defaults, never crash the API
        logger.warning(f"Failed to load TTS provider config ({cfg_path}): {e}; using defaults")
        return [dict(p) for p in FALLBACK_PROVIDERS]


def provider_priority_map(path: Optional[str] = None) -> Dict[str, int]:
    """Return ``{engine_name: priority}`` for enabled providers."""
    return {
        p["engine"]: int(p["priority"])
        for p in load_tts_provider_config(path)
        if p.get("enabled", True)
    }


# ---------------------------------------------------------------------------
# P0 capability matrix + capability-aware selector
# ---------------------------------------------------------------------------


def capability_matrix(path: Optional[str] = None) -> Dict[str, EngineCapability]:
    """Build ``{engine_name: EngineCapability}`` from the provider config."""
    matrix: Dict[str, EngineCapability] = {}
    for p in load_tts_provider_config(path):
        cap = p.get("capabilities") or {}
        matrix[p["engine"]] = EngineCapability(
            cloning=bool(cap.get("cloning", False)),
            emotion=bool(cap.get("emotion", False)),
            languages=tuple(str(l) for l in cap.get("languages", ["zh", "en"])),
            min_compute=str(cap.get("min_compute", "cpu")).lower(),
        )
    return matrix


def license_matrix(path: Optional[str] = None) -> Dict[str, EngineLicense]:
    """Build ``{engine_name: EngineLicense}`` from the provider config (P2.11)."""
    matrix: Dict[str, EngineLicense] = {}
    for p in load_tts_provider_config(path):
        lic = p.get("license") or {}
        matrix[p["engine"]] = EngineLicense(
            commercial_use=lic.get("commercial_use"),
            name=lic.get("name"),
            verified_at=lic.get("verified_at"),
        )
    return matrix


def select_engine(
    language: str = "zh-CN",
    need_clone: bool = False,
    need_emotion: bool = False,
    gpu_available: Optional[bool] = None,
    path: Optional[str] = None,
) -> Tuple[str, str]:
    """Capability- and resource-aware engine selection.

    Returns ``(engine_name, mode)`` where ``mode`` is one of:

      - ``"clone"``    — a real zero-shot clone engine was selected (requires GPU).
      - ``"preset"``   — cloning was requested but no GPU clone backend exists;
                         a CPU preset engine is returned for *voice differentiation*
                         (the free + no-GPU substitute for cloning).
      - ``"standard"`` — normal narration/voice synthesis.

    Under free + no-GPU (``gpu_available`` defaults to ``gpu_backends_enabled()``
    which is ``False``), GPU-only engines are skipped and cloning degrades to
    ``"preset"`` — the selector never returns an engine it cannot run, and never
    pretends to clone.
    """
    if gpu_available is None:
        gpu_available = gpu_backends_enabled()

    providers = load_tts_provider_config(path)
    caps = capability_matrix(path)
    lang_prefix = (language or "zh").split("-")[0].lower()

    # Feasible = enabled + (cpu, or gpu when available).
    feasible = []
    for p in providers:
        if not p.get("enabled", True):
            continue
        cap = caps.get(p["engine"])
        if cap is not None and cap.min_compute == "gpu" and not gpu_available:
            continue  # no-GPU safety: skip engines we cannot run
        feasible.append(p)

    def _lang_match(engine: str) -> bool:
        cap = caps.get(engine)
        if cap is None:
            return True  # unknown engine: don't filter on language
        return lang_prefix in [str(l).split("-")[0].lower() for l in cap.languages]

    # 1) Clone requested -> prefer a real clone engine (needs GPU), else preset.
    if need_clone:
        for p in feasible:
            cap = caps.get(p["engine"])
            if cap and cap.cloning and _lang_match(p["engine"]):
                return (p["engine"], "clone")
        for p in feasible:
            if _lang_match(p["engine"]):
                return (p["engine"], "preset")
        if feasible:
            return (feasible[0]["engine"], "preset")
        return ("kokoro", "preset")

    # 2) Emotion requested -> prefer an emotion-capable engine.
    if need_emotion:
        for p in feasible:
            cap = caps.get(p["engine"])
            if cap and cap.emotion and _lang_match(p["engine"]):
                return (p["engine"], "standard")

    # 3) Default: highest-priority feasible engine.
    if feasible:
        return (feasible[0]["engine"], "standard")
    return ("kokoro", "standard")


if __name__ == "__main__":
    import json

    print(json.dumps(load_tts_provider_config(), indent=2, ensure_ascii=False))

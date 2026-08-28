"""Character → preset-voice assignment (no-GPU clone substitute, Track A).

Under free + no-GPU, true zero-shot voice cloning is infeasible: both Kokoro and
Piper silently discard ``reference_audio`` (see ``kokoro_backend.py`` /
``piper_backend.py``), and the GPU neural clone models (F5-TTS / CosyVoice2 / Dia)
cannot run on CPU at audible speed. Multi-character audiobooks therefore achieve
*voice differentiation* by assigning **distinct pre-trained preset voices** to
distinct characters — which is exactly what this module does, deterministically.

This is the honest, deployable fallback. When a GPU clone backend (F5/CosyVoice2,
Track B) later registers, callers should prefer that path for true cloning; this
assignment remains the graceful degradation when no GPU is present.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional

from .engine import VoiceInfo

# Curated no-GPU preset pool: real, already-available voices (no separate GPU
# download required for Kokoro's bundled zh presets or Edge's free cloud voices;
# Piper zh voices download on first use via model_downloader).
_DEFAULT_POOL: List[VoiceInfo] = [
    VoiceInfo(voice_id="zf_xiaoxiao", name="晓晓(女)", language="zh", gender="female",
              description="Kokoro 中文女声", engine="kokoro", supports_reference_audio=False),
    VoiceInfo(voice_id="zf_xiaobei", name="小贝(女)", language="zh", gender="female",
              description="Kokoro 中文女声", engine="kokoro", supports_reference_audio=False),
    VoiceInfo(voice_id="zf_xiaoni", name="小妮(女)", language="zh", gender="female",
              description="Kokoro 中文女声", engine="kokoro", supports_reference_audio=False),
    VoiceInfo(voice_id="zf_xiaoxuan", name="小萱(女)", language="zh", gender="female",
              description="Kokoro 中文女声", engine="kokoro", supports_reference_audio=False),
    VoiceInfo(voice_id="zm_yunjian", name="云健(男)", language="zh", gender="male",
              description="Kokoro 中文男声", engine="kokoro", supports_reference_audio=False),
    VoiceInfo(voice_id="zm_yunxi", name="云希(男)", language="zh", gender="male",
              description="Kokoro 中文男声", engine="kokoro", supports_reference_audio=False),
    VoiceInfo(voice_id="zh_CN-huayan-medium", name="华婉(女)", language="zh-CN", gender="female",
              description="Piper 中文女声 (默认旁白)", engine="piper", supports_reference_audio=False),
    VoiceInfo(voice_id="zh_CN-shaoer-medium", name="少儿", language="zh-CN", gender="neutral",
              description="Piper 中文少儿/活泼声线", engine="piper", supports_reference_audio=False),
    VoiceInfo(voice_id="zh-CN-XiaoxiaoNeural", name="晓晓(Edge)", language="zh-CN", gender="female",
              description="Edge 中文女声 (免费云)", engine="edge_tts", supports_reference_audio=False),
    VoiceInfo(voice_id="zh-CN-YunxiNeural", name="云希(Edge)", language="zh-CN", gender="male",
              description="Edge 中文男声 (免费云)", engine="edge_tts", supports_reference_audio=False),
]

#: Voice used for the narrator role when present in the character list.
NARRATOR_DEFAULT = "zh_CN-huayan-medium"
_NARRATOR_ROLES = {"", "narrator", "旁白", " narration"}


def _voice_by_id(voice_id: str, pool: List[VoiceInfo]) -> Optional[VoiceInfo]:
    for v in pool:
        if v.voice_id == voice_id:
            return v
    return None


def _stable_index(key: str, modulus: int) -> int:
    """Deterministic, stable hash of a character name → index in [0, modulus)."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % modulus


def character_voice_plan(
    characters: List[str],
    *,
    language: str = "zh-CN",
    pool: Optional[List[VoiceInfo]] = None,
    override: Optional[Dict[str, str]] = None,
    narrator: str = NARRATOR_DEFAULT,
) -> Dict[str, VoiceInfo]:
    """Assign a distinct preset voice to each character (no-GPU differentiation).

    Args:
        characters: ordered list of character/role names (may include a narrator).
        language: target language filter (prefix-matched, e.g. ``zh-CN`` -> ``zh``).
        pool: optional custom voice pool; defaults to :data:`_DEFAULT_POOL`.
        override: explicit ``{character: voice_id}`` overrides (e.g. from config).
        narrator: voice_id reserved for the narrator role.

    Returns:
        ``{character: VoiceInfo}`` — deterministic and distinct per character
        (unless the filtered pool is smaller than the number of characters, in
        which case voices wrap around).
    """
    pool = pool or list(_DEFAULT_POOL)
    override = override or {}
    lang_prefix = (language or "zh").split("-")[0].lower()

    candidates = [v for v in pool if v.language.split("-")[0].lower() == lang_prefix]
    if not candidates:
        candidates = list(pool)  # fall back to whatever is available

    narrator_voice = _voice_by_id(narrator, pool) or (candidates[0] if candidates else None)

    plan: Dict[str, VoiceInfo] = {}
    used: set = set()

    for ch in characters:
        if ch in _NARRATOR_ROLES:
            plan[ch] = narrator_voice
            if narrator_voice is not None:
                used.add(narrator_voice.voice_id)
            continue
        if ch in override:
            voice = _voice_by_id(override[ch], pool) or (candidates[0] if candidates else None)
            plan[ch] = voice
            if voice is not None:
                used.add(voice.voice_id)
            continue
        if not candidates:
            plan[ch] = None
            continue
        # Deterministic starting point, then walk to the next free voice.
        idx = _stable_index(ch, len(candidates))
        chosen = candidates[idx]
        if chosen.voice_id in used:
            chosen = next((v for v in candidates if v.voice_id not in used), chosen)
        used.add(chosen.voice_id)
        plan[ch] = chosen

    return plan


def all_distinct(plan: Dict[str, VoiceInfo]) -> bool:
    """True when non-narrator characters map to distinct voices (no collision)."""
    seen = set()
    for ch, voice in plan.items():
        if ch in _NARRATOR_ROLES or voice is None:
            continue
        if voice.voice_id in seen:
            return False
        seen.add(voice.voice_id)
    return True

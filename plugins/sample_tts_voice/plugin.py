"""Sample TTS voice-pack plugin.

Declares a set of high-quality Chinese/Japanese voices for Kokoro/Edge engines.
Voice packs carry metadata only; availability is probed by the engine layer.
"""

from __future__ import annotations

import logging

from audiobook_studio.plugins import PluginContext

logger = logging.getLogger(__name__)

VOICES = [
    {"engine": "kokoro", "voice_id": "zh-CN-XiaoyiNeural", "lang": "zh-CN"},
    {"engine": "kokoro", "voice_id": "ja-JP-NanamiNeural", "lang": "ja-JP"},
    {"engine": "edge", "voice_id": "zh-CN-YunxiNeural", "lang": "zh-CN"},
]


def register(ctx: PluginContext) -> None:
    """Register the voice pack (metadata-only; no engine factory)."""
    logger.info("sample_tts_voice pack registered: %d voices", len(VOICES))
    # Voice metadata is consumed via the manifest models list; nothing to
    # register in the engine registry for a pure voice pack.

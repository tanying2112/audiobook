# Audiobook Studio - Translation Module
"""Multi-language translation with semantic coherence preservation."""

from .multilingual_dubbing import (
    CharacterVoice,
    EmotionMapping,
    EmotionType,
    MultilingualDubbingManager,
    Segment,
)

__all__ = [
    "MultilingualDubbingManager",
    "CharacterVoice",
    "EmotionMapping",
    "Segment",
    "EmotionType",
]

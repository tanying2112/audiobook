# Audiobook Studio - Translation Module
"""Multi-language translation with semantic coherence preservation."""

from .multilingual_dubbing import (
    MultilingualDubbingManager,
    CharacterVoice,
    EmotionMapping,
    Segment,
    EmotionType,
)

__all__ = [
    "MultilingualDubbingManager",
    "CharacterVoice",
    "EmotionMapping",
    "Segment",
    "EmotionType",
]
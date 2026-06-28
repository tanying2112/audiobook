"""Tests for translation package initialization."""


def test_translation_imports():
    """Test that translation package exports are available."""
    from src.audiobook_studio.translation import (
        CharacterVoice,
        EmotionMapping,
        EmotionType,
        MultilingualDubbingManager,
        Segment,
    )

    assert MultilingualDubbingManager is not None
    assert CharacterVoice is not None
    assert EmotionMapping is not None
    assert Segment is not None
    assert EmotionType is not None

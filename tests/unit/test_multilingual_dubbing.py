"""Tests for multilingual_dubbing module."""


def test_multilingual_dubbing_import():
    """Test that we can import the module."""
    from src.audiobook_studio.translation.multilingual_dubbing import (
        MultilingualDubbingManager,
    )

    assert MultilingualDubbingManager is not None

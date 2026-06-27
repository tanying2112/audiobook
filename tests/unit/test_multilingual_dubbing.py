"""Tests for multilingual_dubbing module."""

import pytest
from unittest.mock import MagicMock

from src.audiobook_studio.translation.multilingual_dubbing import (
    EmotionType,
    CharacterVoice,
    EmotionMapping,
    Segment,
    MultilingualDubbingManager,
)


class TestEmotionType:
    """Tests for EmotionType enum."""

    def test_emotion_type_values(self):
        """Test EmotionType enum values."""
        assert EmotionType.NEUTRAL.value == "neutral"
        assert EmotionType.HAPPY.value == "happy"
        assert EmotionType.SAD.value == "sad"
        assert EmotionType.ANGRY.value == "angry"
        assert EmotionType.FEARFUL.value == "fearful"
        assert EmotionType.SURPRISED.value == "surprised"
        assert EmotionType.DISGUSTED.value == "disgusted"
        assert EmotionType.OTHER.value == "other"

    def test_emotion_type_membership(self):
        """Test EmotionType membership."""
        assert EmotionType.NEUTRAL in EmotionType
        assert EmotionType.HAPPY in EmotionType
        assert EmotionType.SAD in EmotionType
        assert EmotionType.ANGRY in EmotionType
        assert EmotionType.FEARFUL in EmotionType
        assert EmotionType.SURPRISED in EmotionType
        assert EmotionType.DISGUSTED in EmotionType
        assert EmotionType.OTHER in EmotionType


class TestCharacterVoice:
    """Tests for CharacterVoice dataclass."""

    def test_character_voice_creation(self):
        """Test creating a CharacterVoice with all fields."""
        voice = CharacterVoice(
            name="测试角色",
            language="zh-CN",
            voice_id="test_voice_001",
            style="friendly",
            pitch_shift=1.5,
            speed_rate=1.2,
            volume=1.1,
        )
        assert voice.name == "测试角色"
        assert voice.language == "zh-CN"
        assert voice.voice_id == "test_voice_001"
        assert voice.style == "friendly"
        assert voice.pitch_shift == 1.5
        assert voice.speed_rate == 1.2
        assert voice.volume == 1.1

    def test_character_voice_defaults(self):
        """Test CharacterVoice with default values."""
        voice = CharacterVoice(
            name="测试角色",
            language="zh-CN",
            voice_id="test_voice_001",
        )
        assert voice.name == "测试角色"
        assert voice.language == "zh-CN"
        assert voice.voice_id == "test_voice_001"
        assert voice.style == "neutral"
        assert voice.pitch_shift == 0.0
        assert voice_speed_rate == 1.0
        assert voice_volume == 1.0
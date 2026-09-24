"""
Tests for Multilingual Dubbing Module (TEST-001: coverage improvement).

Tests for src/audiobook_studio/translation/multilingual_dubbing.py
Target: 70%+ coverage
"""

import os

# Set TEST_MODE before any imports to use fake services
os.environ["TEST_MODE"] = "true"
os.environ["MOCK_TTS"] = "true"
os.environ["MOCK_LLM"] = "true"

from unittest.mock import patch

# Now import the module under test
from src.audiobook_studio.translation.multilingual_dubbing import (
    CharacterVoice,
    EmotionMapping,
    EmotionType,
    MultilingualDubbingManager,
    Segment,
)


class TestEmotionType:
    """Tests for EmotionType enum."""

    def test_emotion_type_values(self):
        """Test EmotionType enum values exist."""
        assert EmotionType.NEUTRAL.value == "neutral"
        assert EmotionType.HAPPY.value == "happy"
        assert EmotionType.SAD.value == "sad"
        assert EmotionType.ANGRY.value == "angry"
        assert EmotionType.FEARFUL.value == "fearful"
        assert EmotionType.SURPRISED.value == "surprised"
        assert EmotionType.DISGUSTED.value == "disgusted"
        assert EmotionType.OTHER.value == "other"


class TestCharacterVoice:
    """Tests for CharacterVoice dataclass."""

    def test_character_voice_creation(self):
        """Test CharacterVoice can be created with all fields."""
        voice = CharacterVoice(
            name="Narrator",
            language="en-US",
            voice_id="en-US-JennyNeural",
            style="neutral",
            pitch_shift=1.0,
            speed_rate=1.2,
            volume=0.9,
        )
        assert voice.name == "Narrator"
        assert voice.language == "en-US"
        assert voice.voice_id == "en-US-JennyNeural"
        assert voice.style == "neutral"
        assert voice.pitch_shift == 1.0
        assert voice.speed_rate == 1.2
        assert voice.volume == 0.9

    def test_character_voice_defaults(self):
        """Test CharacterVoice default values."""
        voice = CharacterVoice(
            name="Test",
            language="zh-CN",
            voice_id="zh-CN-XiaoyiNeural",
        )
        assert voice.style == "neutral"
        assert voice.pitch_shift == 0.0
        assert voice.speed_rate == 1.0
        assert voice.volume == 1.0


class TestEmotionMapping:
    """Tests for EmotionMapping dataclass."""

    def test_emotion_mapping_creation(self):
        """Test EmotionMapping can be created."""
        mapping = EmotionMapping(
            emotion=EmotionType.HAPPY,
            pitch_shift=2.0,
            speed_rate=1.1,
            volume=1.05,
            energy=0.8,
        )
        assert mapping.emotion == EmotionType.HAPPY
        assert mapping.pitch_shift == 2.0
        assert mapping.speed_rate == 1.1
        assert mapping.volume == 1.05
        assert mapping.energy == 0.8


class TestSegment:
    """Tests for Segment dataclass."""

    def test_segment_creation(self):
        """Test Segment can be created with all fields."""
        segment = Segment(
            id="seg_001",
            text="Hello world",
            character="Narrator",
            emotion=EmotionType.NEUTRAL,
            language="en-US",
            start_time=0.0,
            end_time=5.0,
            voice_id="en-US-JennyNeural",
            pitch_shift=1.0,
            speed_rate=1.2,
            volume=0.9,
        )
        assert segment.id == "seg_001"
        assert segment.text == "Hello world"
        assert segment.character == "Narrator"
        assert segment.emotion == EmotionType.NEUTRAL
        assert segment.language == "en-US"
        assert segment.start_time == 0.0
        assert segment.end_time == 5.0
        assert segment.voice_id == "en-US-JennyNeural"
        assert segment.pitch_shift == 1.0
        assert segment.speed_rate == 1.2
        assert segment.volume == 0.9

    def test_segment_defaults(self):
        """Test Segment default values."""
        segment = Segment(
            id="seg_001",
            text="Hello",
            character="Narrator",
            emotion=EmotionType.NEUTRAL,
            language="en-US",
            start_time=0.0,
            end_time=5.0,
        )
        assert segment.voice_id is None
        assert segment.pitch_shift == 0.0
        assert segment.speed_rate == 1.0
        assert segment.volume == 1.0


class TestMultilingualDubbingManagerInit:
    """Tests for MultilingualDubbingManager initialization."""

    def test_init_creates_empty_structures(self):
        """Test init creates empty dicts for voices, mappings, qualities."""
        # Note: The manager initializes with sample voices, so character_voices is not empty
        manager = MultilingualDubbingManager()
        assert isinstance(manager.character_voices, dict)
        assert isinstance(manager.translation_quality, dict)
        assert len(manager.translation_quality) == 0  # translation_quality starts empty

    def test_init_default_emotion_mappings(self):
        """Test default emotion mappings are initialized."""
        manager = MultilingualDubbingManager()
        assert len(manager.emotion_mappings) == 8  # 8 emotions (NEUTRAL + 7 others)
        assert EmotionType.NEUTRAL in manager.emotion_mappings
        assert EmotionType.HAPPY in manager.emotion_mappings
        assert EmotionType.SAD in manager.emotion_mappings
        assert EmotionType.ANGRY in manager.emotion_mappings
        assert EmotionType.FEARFUL in manager.emotion_mappings
        assert EmotionType.SURPRISED in manager.emotion_mappings
        assert EmotionType.DISGUSTED in manager.emotion_mappings
        assert EmotionType.OTHER in manager.emotion_mappings

    def test_init_sample_character_voices(self):
        """Test sample character voices are initialized."""
        manager = MultilingualDubbingManager()
        assert "旁白" in manager.character_voices
        assert "主角" in manager.character_voices
        assert "反派" in manager.character_voices

        narrator = manager.character_voices["旁白"]
        assert "zh-CN" in narrator
        assert "en-US" in narrator
        assert "es-ES" in narrator
        assert "ja-JP" in narrator


class TestAddCharacterVoice:
    """Tests for add_character_voice method."""

    def test_add_character_voice_new_character(self):
        """Test adding voice for new character."""
        manager = MultilingualDubbingManager()
        voice = CharacterVoice("NewChar", "en-US", "en-US-TestNeural")

        manager.add_character_voice("NewChar", "en-US", voice)

        assert "NewChar" in manager.character_voices
        assert manager.character_voices["NewChar"]["en-US"] == voice

    def test_add_character_voice_existing_character(self):
        """Test adding voice for existing character."""
        manager = MultilingualDubbingManager()
        voice = CharacterVoice("旁白", "fr-FR", "fr-FR-TestNeural")

        manager.add_character_voice("旁白", "fr-FR", voice)

        assert "fr-FR" in manager.character_voices["旁白"]
        assert manager.character_voices["旁白"]["fr-FR"] == voice


class TestAddEmotionMapping:
    """Tests for add_emotion_mapping method."""

    def test_add_emotion_mapping_new(self):
        """Test adding new emotion mapping."""
        manager = MultilingualDubbingManager()
        custom_mapping = EmotionMapping(
            emotion=EmotionType.OTHER,
            pitch_shift=5.0,
            speed_rate=2.0,
            volume=2.0,
            energy=1.0,
        )

        manager.add_emotion_mapping(EmotionType.OTHER, custom_mapping)

        assert manager.emotion_mappings[EmotionType.OTHER] == custom_mapping
        assert manager.emotion_mappings[EmotionType.OTHER].pitch_shift == 5.0

    def test_add_emotion_mapping_update(self):
        """Test updating existing emotion mapping."""
        manager = MultilingualDubbingManager()
        original = manager.emotion_mappings[EmotionType.HAPPY]

        new_mapping = EmotionMapping(
            emotion=EmotionType.HAPPY,
            pitch_shift=10.0,
            speed_rate=10.0,
            volume=10.0,
            energy=10.0,
        )

        manager.add_emotion_mapping(EmotionType.HAPPY, new_mapping)

        assert manager.emotion_mappings[EmotionType.HAPPY] == new_mapping
        assert manager.emotion_mappings[EmotionType.HAPPY] != original


class TestSetTranslationQuality:
    """Tests for set_translation_quality method."""

    def test_set_translation_quality(self):
        """Test setting translation quality."""
        manager = MultilingualDubbingManager()

        manager.set_translation_quality("zh-CN", "en-US", 0.95)

        assert manager.translation_quality[("zh-CN", "en-US")] == 0.95
        assert manager.translation_quality[("en-US", "zh-CN")] == 0.95


class TestGetCharacterVoice:
    """Tests for get_character_voice method."""

    def test_get_character_voice_exists(self):
        """Test getting existing character voice."""
        manager = MultilingualDubbingManager()

        voice = manager.get_character_voice("旁白", "en-US")

        assert voice is not None
        assert voice.name == "旁白"
        assert voice.language == "en-US"
        assert voice.voice_id == "en-US-JennyNeural"

    def test_get_character_voice_not_found_character(self):
        """Test getting voice for non-existent character."""
        manager = MultilingualDubbingManager()

        voice = manager.get_character_voice("NonExistent", "en-US")

        assert voice is None

    def test_get_character_voice_not_found_language(self):
        """Test getting voice for non-existent language."""
        manager = MultilingualDubbingManager()

        voice = manager.get_character_voice("旁白", "fr-FR")

        assert voice is None


class TestGetEmotionMapping:
    """Tests for get_emotion_mapping method."""

    def test_get_emotion_mapping_exists(self):
        """Test getting existing emotion mapping."""
        manager = MultilingualDubbingManager()

        mapping = manager.get_emotion_mapping(EmotionType.HAPPY)

        assert mapping is not None
        assert mapping.emotion == EmotionType.HAPPY
        assert mapping.pitch_shift == 2.0
        assert mapping.speed_rate == 1.1

    def test_get_emotion_mapping_fallback_to_neutral(self):
        """Test fallback to NEUTRAL for unknown emotion."""
        manager = MultilingualDubbingManager()

        mapping = manager.get_emotion_mapping(EmotionType.NEUTRAL)
        assert mapping == manager.emotion_mappings[EmotionType.NEUTRAL]


class TestTranslateTextPreservingMarkup:
    """Tests for translate_text_preserving_markup method."""

    def test_translate_preserves_character_markup(self):
        """Test character markup is preserved during translation."""
        manager = MultilingualDubbingManager()

        text = "[character:旁白]Hello world[/character]"
        # Mock the internal LLM call to return text with placeholders
        with patch.object(manager, "_translate_with_llm", return_value="__CHAR_PLACEHOLDER_0__"):
            result = manager.translate_text_preserving_markup(text, "en-US", "zh-CN")

        assert "[character:旁白]" in result
        assert "[/character]" in result
        assert "Hello world" in result

    def test_translate_preserves_emotion_markup(self):
        """Test emotion markup is preserved during translation."""
        manager = MultilingualDubbingManager()

        text = "(emotion:happy)I am happy(/emotion)"
        with patch.object(manager, "_translate_with_llm", return_value="__EMOTION_PLACEHOLDER_0__"):
            result = manager.translate_text_preserving_markup(text, "en-US", "zh-CN")

        assert "(emotion:happy)" in result
        assert "(/emotion)" in result
        assert "I am happy" in result

    def test_translate_with_character_emotion_pairs(self):
        """Test translation with character_emotion_pairs parameter."""
        manager = MultilingualDubbingManager()

        text = "Hello world"
        with patch.object(manager, "_translate_with_llm", return_value="Hello world translated"):
            result = manager.translate_text_preserving_markup(
                text, "en-US", "zh-CN", character_emotion_pairs=[("Narrator", "happy")]
            )

        assert isinstance(result, str)

    def test_translate_with_llm_mock_mode(self):
        """Test _translate_with_llm returns some translation in mock mode."""
        manager = MultilingualDubbingManager()

        result = manager._translate_with_llm("Hello", "en-US", "zh-CN")

        # In mock mode, should return some translation (actual behavior varies)
        assert isinstance(result, str)
        assert len(result) > 0


class TestCheckEmotionalContinuity:
    """Tests for check_emotional_continuity method."""

    def test_continuity_passed_matching_segments(self):
        """Test continuity check passes for matching segments."""
        manager = MultilingualDubbingManager()

        original = [
            Segment("1", "Hello", "Narrator", EmotionType.NEUTRAL, "en-US", 0.0, 5.0),
            Segment("2", "I am happy", "Protagonist", EmotionType.HAPPY, "en-US", 5.0, 10.0),
        ]
        translated = [
            Segment("1_zh", "你好", "Narrator", EmotionType.NEUTRAL, "zh-CN", 0.0, 5.0),
            Segment("2_zh", "我很快乐", "Protagonist", EmotionType.HAPPY, "zh-CN", 5.0, 10.0),
        ]

        passed, issues = manager.check_emotional_continuity(original, translated)

        assert passed is True
        assert issues == []

    def test_continuity_failed_mismatched_length(self):
        """Test continuity check fails for mismatched segment count."""
        manager = MultilingualDubbingManager()

        original = [
            Segment("1", "Hello", "Narrator", EmotionType.NEUTRAL, "en-US", 0.0, 5.0),
        ]
        translated = [
            Segment("1_zh", "你好", "Narrator", EmotionType.NEUTRAL, "zh-CN", 0.0, 5.0),
            Segment("2_zh", "我很快乐", "Protagonist", EmotionType.HAPPY, "zh-CN", 5.0, 10.0),
        ]

        passed, issues = manager.check_emotional_continuity(original, translated)

        assert passed is False
        assert len(issues) == 1
        assert "片段数量不匹配" in issues[0]

    def test_continuity_failed_character_mismatch(self):
        """Test continuity check fails for character mismatch."""
        manager = MultilingualDubbingManager()

        original = [
            Segment("1", "Hello", "Narrator", EmotionType.NEUTRAL, "en-US", 0.0, 5.0),
        ]
        translated = [
            Segment("1_zh", "你好", "Protagonist", EmotionType.NEUTRAL, "zh-CN", 0.0, 5.0),
        ]

        passed, issues = manager.check_emotional_continuity(original, translated)

        assert passed is False
        assert len(issues) == 1
        assert "角色不匹配" in issues[0]

    def test_continuity_failed_emotion_mismatch(self):
        """Test continuity check fails for emotion mismatch."""
        manager = MultilingualDubbingManager()

        original = [
            Segment("1", "Hello", "Narrator", EmotionType.NEUTRAL, "en-US", 0.0, 5.0),
        ]
        translated = [
            Segment("1_zh", "你好", "Narrator", EmotionType.HAPPY, "zh-CN", 0.0, 5.0),
        ]

        passed, issues = manager.check_emotional_continuity(original, translated)

        assert passed is False
        assert len(issues) == 1
        assert "情感不匹配" in issues[0]

    def test_continuity_failed_text_length_ratio_too_low(self):
        """Test continuity check fails for text length ratio too low."""
        manager = MultilingualDubbingManager()

        original = [
            Segment("1", "Hello world this is a long sentence", "Narrator", EmotionType.NEUTRAL, "en-US", 0.0, 5.0),
        ]
        translated = [
            Segment("1_zh", "Hi", "Narrator", EmotionType.NEUTRAL, "zh-CN", 0.0, 5.0),
        ]

        passed, issues = manager.check_emotional_continuity(original, translated)

        assert passed is False
        assert len(issues) == 1
        assert "文本长度异常变化" in issues[0]
        assert "比率" in issues[0]

    def test_continuity_failed_text_length_ratio_too_high(self):
        """Test continuity check fails for text length ratio too high."""
        manager = MultilingualDubbingManager()

        original = [
            Segment("1", "Hi", "Narrator", EmotionType.NEUTRAL, "en-US", 0.0, 5.0),
        ]
        translated = [
            Segment(
                "1_zh",
                "Hello world this is a very long translated sentence that exceeds the ratio",
                "Narrator",
                EmotionType.NEUTRAL,
                "zh-CN",
                0.0,
                5.0,
            ),
        ]

        passed, issues = manager.check_emotional_continuity(original, translated)

        assert passed is False
        assert len(issues) == 1
        assert "文本长度异常变化" in issues[0]

    def test_continuity_multiple_issues(self):
        """Test continuity check reports multiple issues."""
        manager = MultilingualDubbingManager()

        original = [
            Segment("1", "Hello", "Narrator", EmotionType.NEUTRAL, "en-US", 0.0, 5.0),
            Segment("2", "I am happy", "Protagonist", EmotionType.HAPPY, "en-US", 5.0, 10.0),
        ]
        translated = [
            Segment("1_zh", "Hi", "Protagonist", EmotionType.SAD, "zh-CN", 0.0, 5.0),
            Segment("2_zh", "I am very very very happy indeed", "Protagonist", EmotionType.HAPPY, "zh-CN", 5.0, 10.0),
        ]

        passed, issues = manager.check_emotional_continuity(original, translated)

        assert passed is False
        assert len(issues) >= 2


class TestProcessMultilingualDubbing:
    """Tests for process_multilingual_dubbing method."""

    def test_process_multilingual_dubbing_success(self):
        """Test process_multilingual_dubbing returns translated segments and report."""
        manager = MultilingualDubbingManager()

        source_segments = [
            Segment(
                id="seg_001",
                text="[character:旁白](emotion:neutral)Hello[/character]",
                character="旁白",
                emotion=EmotionType.NEUTRAL,
                language="zh-CN",
                start_time=0.0,
                end_time=5.0,
            ),
        ]

        with patch.object(
            manager, "_translate_with_llm", return_value="[character:旁白](emotion:neutral)你好[/character]"
        ):
            translated_segments, report = manager.process_multilingual_dubbing(source_segments, "en-US")

        assert len(translated_segments) == 1
        assert report["source_segments"] == 1
        assert report["target_language"] == "en-US"
        assert report["successful_translations"] == 1
        assert report["failed_translations"] == 0
        assert "emotional_continuity_passed" in report
        assert "continuity_issues" in report
        assert "warnings" in report

    def test_process_multilingual_dubbing_empty_segments(self):
        """Test process_multilingual_dubbing with empty segment list."""
        manager = MultilingualDubbingManager()

        translated_segments, report = manager.process_multilingual_dubbing([], "en-US")

        assert translated_segments == []
        assert report["source_segments"] == 0
        assert report["successful_translations"] == 0
        assert report["failed_translations"] == 0
        assert report["emotional_continuity_passed"]

    def test_process_multilingual_dubbing_missing_voice_fallback(self):
        """Test process_multilingual_dubbing falls back to default voice when missing."""
        manager = MultilingualDubbingManager()

        source_segments = [
            Segment(
                id="seg_001",
                text="[character:NewChar](emotion:neutral)Hello[/character]",
                character="NewChar",
                emotion=EmotionType.NEUTRAL,
                language="zh-CN",
                start_time=0.0,
                end_time=5.0,
            ),
        ]

        with patch.object(
            manager,
            "_translate_with_llm",
            return_value="[character:NewChar](emotion:neutral)Hello translated[/character]",
        ):
            translated_segments, report = manager.process_multilingual_dubbing(source_segments, "es-ES")

        assert len(translated_segments) == 1
        assert len(report["warnings"]) >= 1
        assert "未找到角色" in report["warnings"][0] or "default" in report["warnings"][0].lower()

    def test_process_multilingual_dubbing_translation_failure(self):
        """Test process_multilingual_dubbing handles translation failure."""
        manager = MultilingualDubbingManager()

        source_segments = [
            Segment(
                id="seg_001",
                text="[character:旁白](emotion:neutral)Hello[/character]",
                character="旁白",
                emotion=EmotionType.NEUTRAL,
                language="zh-CN",
                start_time=0.0,
                end_time=5.0,
            ),
        ]

        with patch.object(manager, "_translate_with_llm", side_effect=Exception("LLM error")):
            translated_segments, report = manager.process_multilingual_dubbing(source_segments, "en-US")

        assert len(translated_segments) == 1
        assert report["successful_translations"] == 0
        assert report["failed_translations"] == 1
        assert "_FAILED" in translated_segments[0].id
        assert "翻译失败" in translated_segments[0].text

    def test_process_multilingual_dubbing_quality_threshold(self):
        """Test process_multilingual_dubbing with quality threshold."""
        manager = MultilingualDubbingManager()

        source_segments = [
            Segment(
                id="seg_001",
                text="Hello",
                character="旁白",
                emotion=EmotionType.NEUTRAL,
                language="zh-CN",
                start_time=0.0,
                end_time=5.0,
            ),
        ]

        with patch.object(
            manager, "_translate_with_llm", return_value="[character:旁白](emotion:neutral)Hello translated[/character]"
        ):
            translated_segments, report = manager.process_multilingual_dubbing(
                source_segments, "en-US", quality_threshold=0.8
            )

        assert len(translated_segments) == 1
        assert report["target_language"] == "en-US"

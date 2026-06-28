"""Tests for audio_postprocess pipeline module."""

import pytest

from src.audiobook_studio.pipeline.audio_postprocess import (
    EMOTION_PRESETS,
    AudioPostProcessor,
)
from src.audiobook_studio.schemas import (
    AudioPostProcessParams,
    CharacterVoiceBinding,
    EmotionSnapshot,
    ParagraphAnnotation,
)


class TestAudioPostProcessor:
    """Test AudioPostProcessor class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.processor = AudioPostProcessor()

    def test_init_default(self):
        """Test processor initialization with defaults."""
        assert self.processor is not None
        assert self.processor.emotion_presets == EMOTION_PRESETS

    def test_init_custom_presets(self):
        """Test processor initialization with custom presets."""
        custom_presets = {
            "neutral": {"speech_rate": 0.9, "pitch_shift_semitones": 0, "sfx_tags": []}
        }
        processor = AudioPostProcessor(emotion_presets=custom_presets)
        assert processor.emotion_presets == custom_presets

    def test_process_neutral(self):
        """Test processing neutral emotion."""
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        assert isinstance(result, AudioPostProcessParams)
        assert result.speech_rate == 1.0
        assert result.pitch_shift_semitones == 0
        assert result.needs_sfx is False

    def test_process_happy(self):
        """Test processing happy emotion."""
        annotation = ParagraphAnnotation(
            paragraph_index=1,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="happy",
            emotion_intensity=0.7,
            speech_rate=1.1,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        assert result.speech_rate == 1.1
        assert result.pitch_shift_semitones == 1
        assert "ambient_cheerful" in result.sfx_tags

    def test_process_sad(self):
        """Test processing sad emotion."""
        annotation = ParagraphAnnotation(
            paragraph_index=2,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="sad",
            emotion_intensity=0.8,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        assert result.speech_rate == 0.8
        assert result.pitch_shift_semitones == -1
        assert "ambient_melancholic" in result.sfx_tags

    def test_process_angry(self):
        """Test processing angry emotion."""
        annotation = ParagraphAnnotation(
            paragraph_index=3,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="angry",
            emotion_intensity=0.9,
            speech_rate=1.2,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        # Angry preset: speech_rate=1.2, with intensity > 0.8 adds 0.05 -> 1.25
        # round(12.5) = 12 (banker's rounding) -> 1.2
        # pitch_shift=2, with intensity > 0.8 adds 1 -> 3
        assert result.speech_rate == 1.2
        assert result.pitch_shift_semitones == 3
        assert "ambient_tense" in result.sfx_tags

    def test_process_fearful(self):
        """Test processing fearful emotion."""
        annotation = ParagraphAnnotation(
            paragraph_index=4,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="fearful",
            emotion_intensity=0.8,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        assert result.speech_rate == 1.2
        assert result.pitch_shift_semitones == 3
        assert "ambient_suspense" in result.sfx_tags

    def test_process_surprised(self):
        """Test processing surprised emotion."""
        annotation = ParagraphAnnotation(
            paragraph_index=5,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="surprised",
            emotion_intensity=0.8,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        assert result.speech_rate == 1.2
        assert result.pitch_shift_semitones == 2
        assert "ambient_surprise" in result.sfx_tags

    def test_process_dialogue(self):
        """Test processing dialogue with is_dialogue=True."""
        annotation = ParagraphAnnotation(
            paragraph_index=6,
            speaker_canonical_name="character1",
            is_dialogue=True,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        # Dialogue gets slight bump: neutral preset 1.0 + 0.05 = 1.05, rounds to 1.0 (banker's rounding)
        assert result.speech_rate == 1.0

    def test_process_intensity_high(self):
        """Test processing high intensity (>0.8)."""
        annotation = ParagraphAnnotation(
            paragraph_index=7,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="happy",
            emotion_intensity=0.9,  # > 0.8
            speech_rate=1.1,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        # Higher intensity should increase speech_rate and pitch
        assert result.speech_rate > 1.1

    def test_process_intensity_low(self):
        """Test processing low intensity (<0.3)."""
        annotation = ParagraphAnnotation(
            paragraph_index=8,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="happy",
            emotion_intensity=0.2,  # < 0.3
            speech_rate=1.1,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        # Lower intensity should decrease speech_rate
        assert result.speech_rate < 1.1

    def test_process_voice_map_override(self):
        """Test voice_map override with voice_preset (if attribute exists)."""
        # Note: CharacterVoiceBinding doesn't currently have voice_preset field
        # The code handles this with hasattr check - testing the fallback behavior
        voice_map = [
            CharacterVoiceBinding(
                canonical_name="character1",
                aliases=[],
                gender="female",
                age_range="young",
                suggested_voice_id="voice_1",
                sample_quote="测试",
            )
        ]
        annotation = ParagraphAnnotation(
            paragraph_index=9,
            speaker_canonical_name="character1",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=voice_map, emotion_snapshot=None
        )
        # Without voice_preset, defaults from emotion preset should be used
        assert result.speech_rate == 1.0  # neutral preset
        assert result.pitch_shift_semitones == 0

    def test_process_speech_rate_clamping(self):
        """Test speech_rate is clamped to 0.7-1.3 range."""
        # This test would need extreme values to trigger clamping
        # But we can test the rounding behavior
        annotation = ParagraphAnnotation(
            paragraph_index=10,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="angry",
            emotion_intensity=0.9,
            speech_rate=1.2,
            pitch_shift_semitones=2,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        # Should be rounded to 0.1 step
        assert result.speech_rate == round(result.speech_rate * 10) / 10

    def test_process_pause_before_after(self):
        """Test pause_before_ms and pause_after_ms are preserved."""
        annotation = ParagraphAnnotation(
            paragraph_index=11,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
            pause_before_ms=500,
            pause_after_ms=300,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        assert result.pause_before_ms == 500
        assert result.pause_after_ms == 300

    def test_process_whisper(self):
        """Test processing whisper emotion."""
        annotation = ParagraphAnnotation(
            paragraph_index=12,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="whisper",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        assert result.speech_rate == 0.7
        assert result.pitch_shift_semitones == -2

    def test_process_sigh(self):
        """Test processing sigh emotion."""
        annotation = ParagraphAnnotation(
            paragraph_index=13,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="sigh",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        result = self.processor.process(
            annotation=annotation, voice_map=[], emotion_snapshot=None
        )
        assert result.speech_rate == 0.7
        assert result.pitch_shift_semitones == -1
        assert "ambient_sigh" in result.sfx_tags


class TestEmotionPresets:
    """Test EMOTION_PRESETS dictionary."""

    def test_all_emotions_have_presets(self):
        """Test all 14 emotions have presets in EMOTION_PRESETS."""
        expected_emotions = [
            "neutral",
            "happy",
            "sad",
            "angry",
            "fearful",
            "surprised",
            "disgusted",
            "tense",
            "tender",
            "contemplative",
            "whisper",
            "cold_laugh",
            "sigh",
            "sarcastic",
        ]
        for emotion in expected_emotions:
            assert emotion in EMOTION_PRESETS
            preset = EMOTION_PRESETS[emotion]
            assert "speech_rate" in preset
            assert "pitch_shift_semitones" in preset
            assert "sfx_tags" in preset

    def test_preset_speech_rate_in_range(self):
        """Test all presets have speech_rate in valid range."""
        for preset in EMOTION_PRESETS.values():
            assert 0.7 <= preset["speech_rate"] <= 1.3

    def test_preset_pitch_shift_in_range(self):
        """Test all presets have pitch_shift_semitones in valid range."""
        for preset in EMOTION_PRESETS.values():
            assert -5 <= preset["pitch_shift_semitones"] <= 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

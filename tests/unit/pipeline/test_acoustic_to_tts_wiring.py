"""Tests for AudioPostProcessor → TTS Synthesis acoustic parameter wiring.

Verifies that acoustic parameters computed by AudioPostProcessor
(volume_db, speed, pitch_hz, pause_after_ms) are properly propagated
to the SynthesizePipeline._make_routing_decision() output.
"""
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("MOCK_LLM", "true")

from src.audiobook_studio.pipeline.audio_postprocess import (
    AudioPostProcessor,
    PhysicalAudioSegment,
)
from src.audiobook_studio.pipeline.stage_registry import SynthesizeStage
from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline
from src.audiobook_studio.schemas.tts_routing import TtsRoutingInput
from src.audiobook_studio.schemas.paragraph import ParagraphAnnotation
from src.audiobook_studio.schemas.book import CharacterVoiceBinding, BookMeta


class TestPhysicalAudioSegmentToProsody:
    """Test PhysicalAudioSegment → TTS prosody parameter conversion."""

    def test_to_tts_prosody_returns_correct_format(self):
        segment = PhysicalAudioSegment(
            text="测试文本",
            speaker="_narrator_",
            speed=1.15,
            volume_db=1.5,
            pitch_hz=20,
            pause_after_ms=450,
            emotion="angry",
            paragraph_type="dialogue",
        )
        prosody = segment.to_tts_prosody()
        assert prosody["rate"] == "1.15"
        assert prosody["volume"] == "+1.5dB"
        assert prosody["pitch"] == "+20Hz"

    def test_to_tts_prosody_with_negative_values(self):
        segment = PhysicalAudioSegment(
            text="悲伤",
            speaker="_narrator_",
            speed=0.85,
            volume_db=-2.0,
            pitch_hz=-10,
            pause_after_ms=800,
            emotion="sad",
            paragraph_type="narration",
        )
        prosody = segment.to_tts_prosody()
        assert prosody["rate"] == "0.85"
        assert prosody["volume"] == "-2.0dB"
        assert prosody["pitch"] == "-10Hz"

    def test_to_dict_is_complete(self):
        segment = PhysicalAudioSegment(
            text="完整测试",
            speaker="角色A",
            speed=1.05,
            volume_db=0.0,
            pitch_hz=0,
            pause_after_ms=300,
            emotion="neutral",
            paragraph_type="narration",
        )
        d = segment.to_dict()
        assert d["text"] == "完整测试"
        assert d["speaker"] == "角色A"
        assert d["speed"] == 1.05
        assert d["volume_db"] == 0.0
        assert d["pitch_hz"] == 0
        assert d["pause_after_ms"] == 300
        assert d["emotion"] == "neutral"
        assert d["paragraph_type"] == "narration"
        assert d["audio_format"] == "wav"


class TestAudioPostProcessorEmotionToAcoustic:
    """Test emotion → acoustic parameter computation is deterministic."""

    def test_neutral_emotion_defaults(self):
        processor = AudioPostProcessor()
        result = processor.process_single({
            "text": "中性测试",
            "speaker": "_narrator_",
            "emotion": "neutral",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
        })
        assert result.speed == 1.0
        assert result.volume_db == 0.0
        assert result.pitch_hz == 0.0

    def test_angry_produces_faster_louder_higher(self):
        processor = AudioPostProcessor()
        result = processor.process_single({
            "text": "愤怒测试",
            "speaker": "_narrator_",
            "emotion": "angry",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
        })
        assert result.speed > 1.0
        assert result.volume_db > 0.0
        assert result.pitch_hz > 0.0

    def test_sad_produces_slower_quieter_lower(self):
        processor = AudioPostProcessor()
        result = processor.process_single({
            "text": "悲伤测试",
            "speaker": "_narrator_",
            "emotion": "sad",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
        })
        assert result.speed < 1.0
        assert result.volume_db < 0.0
        assert result.pitch_hz < 0.0

    def test_whisper_is_minimal(self):
        processor = AudioPostProcessor()
        result = processor.process_single({
            "text": "耳语测试",
            "speaker": "_narrator_",
            "emotion": "whisper",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
        })
        assert result.speed == 0.7  # SPEED_MIN clamped
        assert result.volume_db == -6.0  # VOLUME_DB_MIN clamped

    def test_high_intensity_amplifies(self):
        processor = AudioPostProcessor()
        neutral = processor.process_single({
            "text": "基准",
            "speaker": "_narrator_",
            "emotion": "neutral",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
        })
        intense = processor.process_single({
            "text": "高强度",
            "speaker": "_narrator_",
            "emotion": "neutral",
            "is_dialogue": False,
            "emotion_intensity": 0.9,
        })
        assert intense.speed > neutral.speed
        assert intense.volume_db > neutral.volume_db

    def test_low_intensity_dampens(self):
        processor = AudioPostProcessor()
        neutral = processor.process_single({
            "text": "基准",
            "speaker": "_narrator_",
            "emotion": "neutral",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
        })
        low = processor.process_single({
            "text": "低强度",
            "speaker": "_narrator_",
            "emotion": "neutral",
            "is_dialogue": False,
            "emotion_intensity": 0.2,
        })
        assert low.volume_db < neutral.volume_db

    def test_dialogue_boosts_speed(self):
        processor = AudioPostProcessor()
        narration = processor.process_single({
            "text": "旁白测试",
            "speaker": "_narrator_",
            "emotion": "neutral",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
        })
        dialogue = processor.process_single({
            "text": "对话测试",
            "speaker": "角色A",
            "emotion": "neutral",
            "is_dialogue": True,
            "emotion_intensity": 0.5,
        })
        assert dialogue.speed > narration.speed

    def test_pause_calculation_includes_punctuation(self):
        processor = AudioPostProcessor()
        no_period = processor.process_single({
            "text": "没有句号",
            "speaker": "_narrator_",
            "emotion": "neutral",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
        })
        with_period = processor.process_single({
            "text": "有句号。",
            "speaker": "_narrator_",
            "emotion": "neutral",
            "is_dialogue": False,
            "emotion_intensity": 0.5,
        })
        # Period (。) adds punctuation delay per acoustic_mapping config
        assert with_period.pause_after_ms >= no_period.pause_after_ms

    def test_output_fields_all_present(self):
        processor = AudioPostProcessor()
        result = processor.process_single({
            "text": "验证字段完整性",
            "speaker": "角色B",
            "emotion": "happy",
            "is_dialogue": True,
            "emotion_intensity": 0.7,
        })
        assert result.speaker == "角色B"
        assert result.text == "验证字段完整性"
        assert result.emotion == "happy"
        assert result.paragraph_type == "dialogue"
        assert isinstance(result.pause_after_ms, int)
        assert result.audio_format == "wav"

    def test_speed_clamped_to_range(self):
        processor = AudioPostProcessor()
        result = processor.process_single({
            "text": "速度测试",
            "speaker": "_narrator_",
            "emotion": "fearful",
            "is_dialogue": True,
            "emotion_intensity": 1.0,
        })
        assert 0.7 <= result.speed <= 1.3

    def test_volume_clamped_to_range(self):
        processor = AudioPostProcessor()
        result = processor.process_single({
            "text": "音量测试",
            "speaker": "_narrator_",
            "emotion": "whisper",
            "is_dialogue": False,
            "emotion_intensity": 1.0,
        })
        assert -6.0 <= result.volume_db <= 6.0

    def test_pitch_clamped_to_range(self):
        processor = AudioPostProcessor()
        result = processor.process_single({
            "text": "音高测试",
            "speaker": "_narrator_",
            "emotion": "fearful",
            "is_dialogue": False,
            "emotion_intensity": 1.0,
        })
        assert -50.0 <= result.pitch_hz <= 50.0


class TestSynthesizeRoutingUsesAcousticParams:
    """Verify that SynthesizeStage._make_routing_decision uses emotion-based volume."""

    def test_prosody_overrides_include_volume_from_emotion(self):
        pipeline = SynthesizePipeline(mock_mode=True, output_dir="/tmp")
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="_narrator_",
            is_dialogue=False,
            emotion="angry",
            emotion_intensity=0.5,
            speech_rate=1.15,
            pitch_shift_semitones=3,
            pause_after_ms=450,
            confidence=0.9,
        )
        voice_map = [
            CharacterVoiceBinding(
                canonical_name="_narrator_",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="test-voice",
                sample_quote="",
            )
        ]
        inp = TtsRoutingInput(
            paragraph_annotation=annotation,
            text="测试文本",
            character_voice_map=voice_map,
            book_id="test",
            chapter_index=1,
            paragraph_index=0,
            prefer_local=True,
        )
        decision = pipeline._make_routing_decision(inp)
        assert "rate" in decision.prosody_overrides
        assert "pitch" in decision.prosody_overrides
        assert "volume" in decision.prosody_overrides
        assert "emotion" in decision.prosody_overrides
        # angry volume should be > 0
        assert decision.prosody_overrides["volume"] > 0.0
        assert decision.prosody_overrides["emotion"] == "angry"

    def test_prosody_overrides_whisper_volume_negative(self):
        pipeline = SynthesizePipeline(mock_mode=True, output_dir="/tmp")
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="_narrator_",
            is_dialogue=False,
            emotion="whisper",
            emotion_intensity=0.5,
            speech_rate=0.7,
            pitch_shift_semitones=-5,
            confidence=0.9,
        )
        voice_map = [
            CharacterVoiceBinding(
                canonical_name="_narrator_",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="test-voice",
                sample_quote="",
            )
        ]
        inp = TtsRoutingInput(
            paragraph_annotation=annotation,
            text="耳语",
            character_voice_map=voice_map,
            book_id="test",
            chapter_index=1,
            paragraph_index=0,
            prefer_local=True,
        )
        decision = pipeline._make_routing_decision(inp)
        assert decision.prosody_overrides["volume"] < 0.0
        assert decision.prosody_overrides["rate"] == 0.7

    def test_neutral_emotion_volume_is_zero(self):
        pipeline = SynthesizePipeline(mock_mode=True, output_dir="/tmp")
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="_narrator_",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        voice_map = [
            CharacterVoiceBinding(
                canonical_name="_narrator_",
                aliases=[],
                gender="neutral",
                age_range="adult",
                suggested_voice_id="test-voice",
                sample_quote="",
            )
        ]
        inp = TtsRoutingInput(
            paragraph_annotation=annotation,
            text="中性",
            character_voice_map=voice_map,
            book_id="test",
            chapter_index=1,
            paragraph_index=0,
            prefer_local=True,
        )
        decision = pipeline._make_routing_decision(inp)
        assert decision.prosody_overrides["volume"] == 0.0

    def test_generate_acoustic_schedule_multi_paragraph(self):
        processor = AudioPostProcessor()
        paragraphs = [
            {
                "text": "第一段旁白。",
                "speaker": "_narrator_",
                "emotion": "neutral",
                "is_dialogue": False,
                "emotion_intensity": 0.5,
            },
            {
                "text": "第二段对话！",
                "speaker": "张三",
                "emotion": "happy",
                "is_dialogue": True,
                "emotion_intensity": 0.8,
            },
            {
                "text": "第三段悲伤...",
                "speaker": "_narrator_",
                "emotion": "sad",
                "is_dialogue": False,
                "emotion_intensity": 0.3,
            },
        ]
        schedule = processor.generate_acoustic_schedule(paragraphs)
        assert len(schedule) == 3
        # Dialogue should be faster/more dynamic
        assert schedule[1].speed > schedule[0].speed
        assert schedule[1].volume_db > schedule[0].volume_db
        # Sad should be slower/quieter
        assert schedule[2].speed < schedule[0].speed
        assert schedule[2].volume_db < schedule[0].volume_db
        # Paragraph types should be correct
        assert schedule[0].paragraph_type == "narration"
        assert schedule[1].paragraph_type == "dialogue"
        assert schedule[2].paragraph_type == "narration"
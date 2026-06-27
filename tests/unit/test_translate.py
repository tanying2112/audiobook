"""Tests for Multilingual Translation Dubbing module."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skip(
    reason="Sprint G Placeholder — translate pipeline is mock_mode stub, not real usable code"
)

# Set MOCK_LLM environment variable before importing pipeline
from unittest.mock import MagicMock, patch

import pytest

# Set MOCK_LLM environment variable before importing pipeline
os.environ["MOCK_LLM"] = "true"

from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline
from src.audiobook_studio.schemas import ParagraphAnnotation
from src.audiobook_studio.models.audio_segment import AudioSegment


class TestTranslateAndDubPipeline:
    """Tests for TranslateAndDubPipeline class."""

    @pytest.fixture
    def mock_voice_cloning_manager(self):
        manager = MagicMock()
        return manager

    @pytest.fixture
    def mock_annotate_pipeline(self):
        pipeline = MagicMock()
        return pipeline

    @pytest.fixture
    def pipeline(self, mock_voice_cloning_manager, mock_annotate_pipeline):
        return TranslateAndDubPipeline(
            voice_cloning_manager=mock_voice_cloning_manager,
            annotate_pipeline=mock_annotate_pipeline,
        )

    def test_pipeline_initialization(self, pipeline):
        assert pipeline.mock_mode is True
        assert pipeline.voice_cloning_manager is not None
        assert pipeline.annotate_pipeline is not None

    def test_pipeline_initialization_defaults(self):
        # Test with defaults (no mocks)
        with patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager") as mock_vc, \
             patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline") as mock_ap:
            mock_vc.return_value = MagicMock()
            mock_ap.return_value = MagicMock()

            pipeline = TranslateAndDubPipeline()
            assert pipeline.mock_mode is True
            mock_vc.assert_called_once()
            mock_ap.assert_called_once()

    def test_translate_and_dub_basic(self, pipeline):
        """Test basic translation and dubbing flow."""
        # Create mock segments
        segments = []
        for i in range(3):
            seg = AudioSegment(
                project_id=1,
                chapter_id=1,
                paragraph_id=i + 1,
                file_path=f"/tmp/seg_{i}.wav",
                duration_ms=2000,
                engine="kokoro",
                voice_id="voice_1",
            )
            seg.text = f"这是第 {i+1} 段测试文本。"
            segments.append(seg)

        dubbed_segments, report = pipeline.translate_and_dub(
            segments=segments,
            target_language="en-US",
            book_title="测试书籍",
            author="测试作者",
        )

        assert len(dubbed_segments) == 3
        assert report["source_segments"] == 3
        assert report["target_language"] == "en-US"
        assert report["book_title"] == "测试书籍"
        assert report["author"] == "测试作者"
        assert report["successful_translations"] == 3
        assert report["failed_translations"] == 0

    def test_translate_and_dub_with_annotations(self, pipeline):
        """Test translation with existing annotations."""
        segments = []
        for i in range(2):
            seg = AudioSegment(
                project_id=1,
                chapter_id=1,
                paragraph_id=i + 1,
                file_path=f"/tmp/seg_{i}.wav",
                duration_ms=2000,
                engine="kokoro",
                voice_id="voice_1",
            )
            seg.text = f"对话内容 {i+1}。"
            seg.annotation = ParagraphAnnotation(
                paragraph_index=i,
                speaker_canonical_name="角色A" if i == 0 else "角色B",
                is_dialogue=True,
                emotion="happy" if i == 0 else "sad",
                emotion_intensity=0.8,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                pause_before_ms=300,
                pause_after_ms=500,
                confidence=0.9,
                needs_sfx=False,
                sfx_tags=[],
            )
            segments.append(seg)

        dubbed_segments, report = pipeline.translate_and_dub(
            segments=segments,
            target_language="es-ES",
        )

        assert len(dubbed_segments) == 2
        assert report["successful_translations"] == 2
        # Check that annotations were preserved/used
        for seg in dubbed_segments:
            assert hasattr(seg, "text")

    def test_translate_and_dub_partial_failure(self, pipeline):
        """Test handling of partial translation failures."""
        # Create a segment that will cause an error
        segments = []

        # Valid segment
        seg1 = AudioSegment(
            project_id=1,
            chapter_id=1,
            paragraph_id=1,
            file_path="/tmp/seg1.wav",
            duration_ms=2000,
            engine="kokoro",
            voice_id="voice_1",
        )
        seg1.text = "正常文本"
        segments.append(seg1)

        # Segment that will cause an error (no text attribute)
        seg2 = AudioSegment(
            project_id=1,
            chapter_id=1,
            paragraph_id=2,
            file_path="/tmp/seg2.wav",
            duration_ms=2000,
            engine="kokoro",
            voice_id="voice_1",
        )
        # Don't set text attribute - will use default
        segments.append(seg2)

        dubbed_segments, report = pipeline.translate_and_dub(
            segments=segments,
            target_language="en-US",
        )

        # Should still process both segments (second one uses fallback text)
        assert len(dubbed_segments) == 2
        assert report["successful_translations"] >= 1

    def test_get_target_voice(self, pipeline):
        """Test getting target voice configuration."""
        voice = pipeline._get_target_voice("旁白", "en-US", "neutral")

        assert "voice_id" in voice
        assert "language" in voice
        assert voice["language"] == "en-US"
        assert "base_pitch_shift" in voice
        assert "base_speed_rate" in voice
        assert "base_volume" in voice

    def test_translate_text(self, pipeline):
        """Test text translation."""
        # Same language - should return original
        result = pipeline._translate_text("测试文本", "zh-CN", "zh-CN", "旁白", "neutral")
        assert result == "测试文本"

        # Different language - should translate
        result = pipeline._translate_text("测试文本", "zh-CN", "en-US", "旁白", "neutral")
        assert "[English translation of:" in result
        assert "测试文本" in result

        # Other target languages
        result = pipeline._translate_text("测试文本", "zh-CN", "es-ES", "旁白", "neutral")
        assert "[Español translation of:" in result

        result = pipeline._translate_text("测试文本", "zh-CN", "ja-JP", "旁白", "neutral")
        assert "[日本語 translation of:" in result

    def test_apply_voice_characteristics(self, pipeline):
        """Test applying voice characteristics based on emotion."""
        voice_config = {
            "base_pitch_shift": 0.0,
            "base_speed_rate": 1.0,
            "base_volume": 1.0,
        }

        # Test various emotions
        emotions_expected = {
            "neutral": {"pitch_shift": 0.0, "speed_rate": 1.0, "volume": 1.0},
            "happy": {"pitch_shift": 2.0, "speed_rate": 1.1, "volume": 1.05},
            "sad": {"pitch_shift": -3.0, "speed_rate": 0.9, "volume": 0.9},
            "angry": {"pitch_shift": 1.0, "speed_rate": 1.2, "volume": 1.3},
            "fearful": {"pitch_shift": -1.0, "speed_rate": 1.1, "volume": 0.8},
            "surprised": {"pitch_shift": 3.0, "speed_rate": 1.15, "volume": 1.1},
            "disgusted": {"pitch_shift": -2.0, "speed_rate": 0.95, "volume": 0.9},
        }

        for emotion, expected in emotions_expected.items():
            annotation = ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="旁白",
                is_dialogue=False,
                emotion=emotion,
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                pause_before_ms=300,
                pause_after_ms=500,
                confidence=0.9,
                needs_sfx=False,
                sfx_tags=[],
            )
            params = pipeline._apply_voice_characteristics(annotation, voice_config)

            assert params["pitch_shift"] == expected["pitch_shift"]
            assert params["speed_rate"] == expected["speed_rate"]
            assert params["volume"] == expected["volume"]

    def test_synthesize_dubbed_segment(self, pipeline):
        """Test synthesizing a dubbed segment."""
        original = AudioSegment(
            project_id=1,
            chapter_id=1,
            paragraph_id=1,
            file_path="/tmp/orig.wav",
            duration_ms=2000,
            engine="kokoro",
            voice_id="voice_1",
        )

        voice_params = {
            "voice_id": "dubbed_voice_en",
            "pitch_shift": 0.0,
            "speed_rate": 1.0,
            "volume": 1.0,
        }

        dubbed = pipeline._synthesize_dubbed_segment(
            original_segment=original,
            translated_text="This is translated text.",
            target_language="en-US",
            voice_params=voice_params,
        )

        assert dubbed.project_id == 1
        assert dubbed.chapter_id == 1
        assert dubbed.paragraph_id == 10001  # offset by 10000
        assert "dubbed" in dubbed.file_path
        assert "en-US" in dubbed.file_path
        assert dubbed.duration_ms >= 1000
        assert dubbed.engine == "kokoro"
        assert dubbed.voice_id == "dubbed_voice_en"
        assert hasattr(dubbed, "text")
        assert dubbed.text == "This is translated text."

    def test_synthesize_dubbed_segment_duration_calculation(self, pipeline):
        """Test duration calculation in synthesis."""
        original = AudioSegment(
            project_id=1,
            chapter_id=1,
            paragraph_id=1,
            file_path="/tmp/orig.wav",
            duration_ms=2000,
            engine="kokoro",
            voice_id="voice_1",
        )

        voice_params = {
            "voice_id": "voice",
            "pitch_shift": 0.0,
            "speed_rate": 1.0,
            "volume": 1.0,
        }

        # Longer text should produce longer duration
        dubbed_short = pipeline._synthesize_dubbed_segment(
            original, "Short.", "en-US", voice_params
        )
        dubbed_long = pipeline._synthesize_dubbed_segment(
            original, "This is a much longer text that should take more time to speak.", "en-US", voice_params
        )

        assert dubbed_long.duration_ms > dubbed_short.duration_ms

    def test_synthesize_dubbed_segment_min_duration(self, pipeline):
        """Test minimum duration enforcement."""
        original = AudioSegment(
            project_id=1,
            chapter_id=1,
            paragraph_id=1,
            file_path="/tmp/orig.wav",
            duration_ms=2000,
            engine="kokoro",
            voice_id="voice_1",
        )

        voice_params = {
            "voice_id": "voice",
            "pitch_shift": 0.0,
            "speed_rate": 10.0,  # Very fast - would make duration very short
            "volume": 1.0,
        }

        dubbed = pipeline._synthesize_dubbed_segment(
            original, "A", "en-US", voice_params
        )

        # Minimum duration should be 1000ms
        assert dubbed.duration_ms >= 1000


class TestTranslateAndDubPipelineEdgeCases:
    """Test edge cases for TranslateAndDubPipeline."""

    @pytest.fixture
    def pipeline(self):
        with patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager") as mock_vc, \
             patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline") as mock_ap:
            mock_vc.return_value = MagicMock()
            mock_ap.return_value = MagicMock()
            return TranslateAndDubPipeline()

    def test_empty_segments(self, pipeline):
        """Test with empty segment list."""
        dubbed_segments, report = pipeline.translate_and_dub(
            segments=[],
            target_language="en-US",
        )
        assert dubbed_segments == []
        assert report["source_segments"] == 0
        assert report["successful_translations"] == 0

    def test_unknown_emotion_fallback(self, pipeline):
        """Test fallback for unknown emotion (uses valid emotion not in adjustment dict)."""
        voice_config = {"base_pitch_shift": 0.0, "base_speed_rate": 1.0, "base_volume": 1.0}

        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion="tense",  # Valid emotion but not in adjustment dict
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=300,
            pause_after_ms=500,
            confidence=0.9,
            needs_sfx=False,
            sfx_tags=[],
        )
        params = pipeline._apply_voice_characteristics(annotation, voice_config)

        # Should fall back to neutral (tense not in adjustment dict)
        assert params["pitch_shift"] == 0.0
        assert params["speed_rate"] == 1.0
        assert params["volume"] == 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
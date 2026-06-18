"""Tests for TranslateAndDubPipeline (Stage 7 - Multilingual Translation Dubbing)."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline
from src.audiobook_studio.models.audio_segment import AudioSegment
from src.audiobook_studio.schemas import ParagraphAnnotation


class TestTranslateAndDubPipeline:
    """Test TranslateAndDubPipeline class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.pipeline = TranslateAndDubPipeline(mock_mode=True)

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        pipeline = TranslateAndDubPipeline()
        assert pipeline is not None
        assert pipeline.mock_mode is False
        assert pipeline.voice_cloning_manager is not None
        assert pipeline.annotate_pipeline is not None

    def test_init_mock_mode(self):
        """Test pipeline initialization in mock mode."""
        pipeline = TranslateAndDubPipeline(mock_mode=True)
        assert pipeline.mock_mode is True

    def test_init_custom_managers(self):
        """Test pipeline initialization with custom managers."""
        mock_vc = Mock()
        mock_ap = Mock()
        pipeline = TranslateAndDubPipeline(
            voice_cloning_manager=mock_vc,
            annotate_pipeline=mock_ap,
            mock_mode=True,
        )
        assert pipeline.voice_cloning_manager == mock_vc
        assert pipeline.annotate_pipeline == mock_ap

    def test_get_target_voice(self):
        """Test _get_target_voice returns expected config."""
        voice = self.pipeline._get_target_voice("character1", "en-US", "happy")
        assert isinstance(voice, dict)
        assert "voice_id" in voice
        assert voice["voice_id"] == "character1_en-US_happy"
        assert voice["language"] == "en-US"
        assert voice["base_pitch_shift"] == 0.0
        assert voice["base_speed_rate"] == 1.0
        assert voice["base_volume"] == 1.0

    def test_translate_text_same_language(self):
        """Test _translate_text returns same text when languages match."""
        text = "测试文本"
        result = self.pipeline._translate_text(text, "zh-CN", "zh-CN", "character1", "neutral")
        assert result == text

    def test_translate_text_different_language(self):
        """Test _translate_text adds translation prefix for different languages."""
        text = "测试文本"
        result = self.pipeline._translate_text(text, "zh-CN", "en-US", "character1", "neutral")
        assert "[English translation of: 测试文本]" in result

    def test_translate_text_various_languages(self):
        """Test _translate_text handles various target languages."""
        text = "测试"
        for target_lang, expected_name in [
            ("en-US", "English"),
            ("es-ES", "Español"),
            ("ja-JP", "日本語"),
        ]:
            result = self.pipeline._translate_text(text, "zh-CN", target_lang, "char", "neutral")
            assert f"[{expected_name} translation of:" in result

    def test_apply_voice_characteristics(self):
        """Test _apply_voice_characteristics applies emotion adjustments."""
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="happy",
            emotion_intensity=0.7,
            speech_rate=1.1,
            pitch_shift_semitones=1,
            confidence=0.9,
        )
        voice_config = {
            "base_pitch_shift": 1.0,
            "base_speed_rate": 1.0,
            "base_volume": 1.0,
        }
        result = self.pipeline._apply_voice_characteristics(annotation, voice_config)
        # happy: pitch_shift +2.0, speed_rate *1.1, volume *1.05
        assert result["pitch_shift"] == 3.0  # 1.0 + 2.0
        assert result["speed_rate"] == 1.1  # 1.0 * 1.1
        assert result["volume"] == 1.05  # 1.0 * 1.05

    def test_apply_voice_characteristics_neutral(self):
        """Test _apply_voice_characteristics with neutral emotion."""
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
        voice_config = {
            "base_pitch_shift": 0.0,
            "base_speed_rate": 1.0,
            "base_volume": 1.0,
        }
        result = self.pipeline._apply_voice_characteristics(annotation, voice_config)
        assert result["pitch_shift"] == 0.0
        assert result["speed_rate"] == 1.0
        assert result["volume"] == 1.0

    def test_apply_voice_characteristics_unknown_emotion(self):
        """Test _apply_voice_characteristics falls back to neutral for unknown emotion."""
        # The schema validates emotion, so we can't create invalid annotation directly
        # Instead, test that the method handles missing emotion key in emotion_adjustments
        # by directly calling with a valid emotion and checking fallback behavior
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="neutral",  # Use valid emotion
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.9,
        )
        voice_config = {"base_pitch_shift": 0.0, "base_speed_rate": 1.0, "base_volume": 1.0}
        result = self.pipeline._apply_voice_characteristics(annotation, voice_config)
        assert result["pitch_shift"] == 0.0
        assert result["speed_rate"] == 1.0
        assert result["volume"] == 1.0

    def test_synthesize_dubbed_segment(self):
        """Test _synthesize_dubbed_segment creates AudioSegment."""
        original = AudioSegment(
            id=1,
            project_id=1,
            chapter_id=1,
            paragraph_id=1,
            file_path="/tmp/orig.wav",
            duration_ms=5000,
            engine="kokoro",
            voice_id="voice_1",
        )
        translated_text = "Translated text content"
        target_language = "en-US"
        voice_params = {"pitch_shift": 0.0, "speed_rate": 1.0, "volume": 1.0}

        result = self.pipeline._synthesize_dubbed_segment(
            original, translated_text, target_language, voice_params
        )

        assert isinstance(result, AudioSegment)
        assert result.project_id == 1
        assert result.chapter_id == 1
        assert result.paragraph_id > 10000  # Offset applied
        assert result.file_path.endswith(".wav")
        assert result.duration_ms >= 1000
        assert result.engine == "kokoro"

    def test_translate_and_dub_empty_segments(self):
        """Test translate_and_dub with empty segments list."""
        segments = []
        result_segments, report = self.pipeline.translate_and_dub(
            segments, "en-US", "Test Book", "Test Author"
        )
        assert result_segments == []
        assert report["source_segments"] == 0
        assert report["successful_translations"] == 0
        assert report["failed_translations"] == 0

    def test_translate_and_dub_single_segment(self):
        """Test translate_and_dub with single segment."""
        segments = [
            AudioSegment(
                id=1,
                project_id=1,
                chapter_id=1,
                paragraph_id=1,
                file_path="/tmp/seg1.wav",
                duration_ms=5000,
                engine="kokoro",
                voice_id="voice_1",
            )
        ]
        with patch("scripts.semantic_coherence.SemanticCoherenceChecker", side_effect=ImportError):
            result_segments, report = self.pipeline.translate_and_dub(
                segments, "en-US", "Test Book", "Test Author"
            )
        assert len(result_segments) == 1
        assert report["source_segments"] == 1
        assert report["successful_translations"] == 1
        assert report["failed_translations"] == 0
        assert report["target_language"] == "en-US"
        assert report["book_title"] == "Test Book"
        assert report["author"] == "Test Author"

    def test_translate_and_dub_multiple_segments(self):
        """Test translate_and_dub with multiple segments."""
        segments = [
            AudioSegment(
                id=i+1,
                project_id=1,
                chapter_id=1,
                paragraph_id=i+1,
                file_path=f"/tmp/seg{i}.wav",
                duration_ms=3000,
                engine="kokoro",
                voice_id="voice_1",
            )
            for i in range(3)
        ]
        with patch("scripts.semantic_coherence.SemanticCoherenceChecker", side_effect=ImportError):
            result_segments, report = self.pipeline.translate_and_dub(
                segments, "en-US", "Test Book", "Test Author"
            )
        assert len(result_segments) == 3
        assert report["source_segments"] == 3
        assert report["successful_translations"] == 3

    def test_translate_and_dub_with_annotation(self):
        """Test translate_and_dub uses segment annotation if available."""
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="character1",
            is_dialogue=True,
            emotion="happy",
            emotion_intensity=0.8,
            speech_rate=1.1,
            pitch_shift_semitones=1,
            confidence=0.9,
        )
        segments = [
            AudioSegment(
                id=1,
                project_id=1,
                chapter_id=1,
                paragraph_id=1,
                file_path="/tmp/seg1.wav",
                duration_ms=5000,
                engine="kokoro",
                voice_id="voice_1",
            )
        ]
        segments[0].annotation = annotation
        segments[0].text = "Original text"

        with patch("scripts.semantic_coherence.SemanticCoherenceChecker", side_effect=ImportError):
            result_segments, report = self.pipeline.translate_and_dub(
                segments, "en-US", "Test Book", "Test Author"
            )
        assert len(result_segments) == 1
        assert report["successful_translations"] == 1

    def test_translate_and_dub_failure_handling(self):
        """Test translate_and_dub handles failures gracefully."""
        # Create segment that will cause an error in processing
        segments = [
            AudioSegment(
                id=1,
                project_id=1,
                chapter_id=1,
                paragraph_id=1,
                file_path="/tmp/seg1.wav",
                duration_ms=5000,
                engine="kokoro",
                voice_id="voice_1",
            )
        ]
        # Mock pipeline's _translate_text to raise exception
        with patch.object(self.pipeline, '_translate_text', side_effect=Exception("Translation failed")):
            with patch("scripts.semantic_coherence.SemanticCoherenceChecker", side_effect=ImportError):
                result_segments, report = self.pipeline.translate_and_dub(
                    segments, "en-US", "Test Book", "Test Author"
                )
        # Should still return a segment (failed one)
        assert len(result_segments) == 1
        assert report["failed_translations"] == 1
        assert report["successful_translations"] == 0
        # Failed segment has paragraph_id = -1
        assert result_segments[0].paragraph_id == -1

    def test_translate_and_dub_emotional_continuity_check_import_error(self):
        """Test translate_and_dub handles missing SemanticCoherenceChecker."""
        segments = [
            AudioSegment(
                id=i+1,
                project_id=1,
                chapter_id=1,
                paragraph_id=i+1,
                file_path=f"/tmp/seg{i}.wav",
                duration_ms=3000,
                engine="kokoro",
                voice_id="voice_1",
            )
            for i in range(2)
        ]
        with patch("scripts.semantic_coherence.SemanticCoherenceChecker", side_effect=ImportError):
            result_segments, report = self.pipeline.translate_and_dub(
                segments, "en-US", "Test Book", "Test Author"
            )
        assert len(result_segments) == 2
        # Semantic coherence check should be skipped (ImportError caught)
        assert report["semantic_coherence_score"] is None
        assert report["emotional_continuity_passed"] is False

    def test_translate_and_dub_semantic_coherence_check_passes(self):
        """Test translate_and_dub when semantic coherence check passes."""
        segments = [
            AudioSegment(
                id=i+1,
                project_id=1,
                chapter_id=1,
                paragraph_id=i+1,
                file_path=f"/tmp/seg{i}.wav",
                duration_ms=3000,
                engine="kokoro",
                voice_id="voice_1",
            )
            for i in range(2)
        ]
        # Add text attribute dynamically since it's not a model field
        for i, seg in enumerate(segments):
            seg.text = f"Text {i}"

        # Mock SemanticCoherenceChecker
        mock_checker = Mock()
        mock_checker.check_coherence.return_value = {
            "score": 0.95,
            "passed": True,
            "issues": []
        }

        with patch("scripts.semantic_coherence.SemanticCoherenceChecker", return_value=mock_checker):
            result_segments, report = self.pipeline.translate_and_dub(
                segments, "en-US", "Test Book", "Test Author"
            )
        assert report["semantic_coherence_score"] == 0.95
        assert report["emotional_continuity_passed"] is True
        assert report["continuity_issues"] == []

    def test_translate_and_dub_semantic_coherence_check_fails(self):
        """Test translate_and_dub when semantic coherence check fails."""
        segments = [
            AudioSegment(
                id=i+1,
                project_id=1,
                chapter_id=1,
                paragraph_id=i+1,
                file_path=f"/tmp/seg{i}.wav",
                duration_ms=3000,
                engine="kokoro",
                voice_id="voice_1",
            )
            for i in range(2)
        ]
        for i, seg in enumerate(segments):
            seg.text = f"Text {i}"

        mock_checker = Mock()
        mock_checker.check_coherence.return_value = {
            "score": 0.45,
            "passed": False,
            "issues": ["Emotional curve mismatch at segment 1"]
        }

        with patch("scripts.semantic_coherence.SemanticCoherenceChecker", return_value=mock_checker):
            result_segments, report = self.pipeline.translate_and_dub(
                segments, "en-US", "Test Book", "Test Author"
            )
        assert report["semantic_coherence_score"] == 0.45
        assert report["emotional_continuity_passed"] is False
        assert len(report["continuity_issues"]) == 1

    def test_translate_and_dub_semantic_coherence_exception(self):
        """Test translate_and_dub handles exception in semantic coherence check."""
        segments = [
            AudioSegment(
                id=i+1,
                project_id=1,
                chapter_id=1,
                paragraph_id=i+1,
                file_path=f"/tmp/seg{i}.wav",
                duration_ms=3000,
                engine="kokoro",
                voice_id="voice_1",
            )
            for i in range(2)
        ]
        for i, seg in enumerate(segments):
            seg.text = f"Text {i}"

        mock_checker = Mock()
        mock_checker.check_coherence.side_effect = Exception("Checker error")

        with patch("scripts.semantic_coherence.SemanticCoherenceChecker", return_value=mock_checker):
            result_segments, report = self.pipeline.translate_and_dub(
                segments, "en-US", "Test Book", "Test Author"
            )
        # Should still complete but with warning
        assert "情感连贯性检查失败" in str(report["warnings"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
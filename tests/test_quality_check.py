"""Unit tests for audio quality check pipeline."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest

from src.audiobook_studio.monitoring import record_stage_performance
from src.audiobook_studio.pipeline.quality_check import AudioAnalysisResult, QualityCheckPipeline, quality_check
from src.audiobook_studio.schemas import ParagraphAnnotation, QualityJudgment, TtsRoutingDecision


class TestQualityCheckPipeline:
    """Test audio quality check pipeline functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.mock_router = Mock()
        self.mock_judge = Mock()
        self.pipeline = QualityCheckPipeline(router=self.mock_router, judge=self.mock_judge, mock_mode=True)

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        old_value = os.environ.get("MOCK_LLM")
        try:
            os.environ["MOCK_LLM"] = "false"
            pipeline = QualityCheckPipeline()
            assert not pipeline.mock_mode
            assert pipeline.router is not None
            assert pipeline.judge is not None
        finally:
            if old_value is None:
                os.environ.pop("MOCK_LLM", None)
            else:
                os.environ["MOCK_LLM"] = old_value

    def test_init_custom_params(self):
        """Test pipeline initialization with custom parameters."""
        pipeline = QualityCheckPipeline(router=self.mock_router, judge=self.mock_judge, mock_mode=False)
        assert pipeline.router == self.mock_router
        assert pipeline.judge == self.mock_judge
        assert not pipeline.mock_mode

    def test_init_mock_mode(self):
        """Test pipeline initialization in mock mode."""
        old_value = os.environ.get("MOCK_LLM")
        try:
            os.environ["MOCK_LLM"] = "true"
            pipeline = QualityCheckPipeline()
            assert pipeline.mock_mode
        finally:
            if old_value is None:
                os.environ.pop("MOCK_LLM", None)
            else:
                os.environ["MOCK_LLM"] = old_value

    def test_analyze_audio_rules_mock(self):
        """Test rule-based audio analysis in mock mode."""
        self.pipeline.mock_mode = True

        # Create a dummy audio path
        audio_path = "/fake/path.mp3"
        expected_duration_ms = 3000

        result = self.pipeline._analyze_audio_rules(Path(audio_path), expected_duration_ms)

        assert isinstance(result, AudioAnalysisResult)
        assert result.duration_ms == expected_duration_ms
        assert not result.has_silence
        assert result.silence_regions == []
        assert not result.has_clipping
        assert result.rms_db == -20.0
        assert result.peak_db == -3.0
        assert result.duration_match
        assert result.issues == []

    def test_build_audio_description(self):
        """Test building audio description for LLM judge."""
        analysis = AudioAnalysisResult(
            duration_ms=3500,
            has_silence=True,
            silence_regions=[(500, 1500), (2000, 2500)],
            has_clipping=False,
            rms_db=-18.5,
            peak_db=-2.0,
            duration_match=False,
            issues=["minor_issue"],
        )

        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="happy",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.95,
            needs_sfx=False,
            sfx_tags=[],
        )

        description = self.pipeline._build_audio_description(analysis, annotation)

        assert "音频时长 3500ms" in description
        assert "检测到 2 处静音段" in description
        assert "RMS -18.5dB" in description
        assert "峰值 -2.0dB" in description
        assert "时长与预期不符(预期3500ms)" in description

    def test_build_audio_description_no_issues(self):
        """Test building audio description when no issues."""
        analysis = AudioAnalysisResult(
            duration_ms=3000,
            has_silence=False,
            silence_regions=[],
            has_clipping=False,
            rms_db=-20.0,
            peak_db=-3.0,
            duration_match=True,
            issues=[],
        )

        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.95,
            needs_sfx=False,
            sfx_tags=[],
        )

        description = self.pipeline._build_audio_description(analysis, annotation)

        assert "音频时长 3000ms" in description
        assert "静音段" not in description  # No silence
        assert "削波失真" not in description  # No clipping
        assert "RMS -20.0dB" in description
        assert "峰值 -3.0dB" in description

    def test_run_empty_inputs(self):
        """Test running quality check with empty inputs."""
        judgments = self.pipeline.run([])
        assert judgments == []

    def test_run_mock_mode(self):
        """Test quality check in mock mode."""
        self.pipeline.mock_mode = True

        # Mock the judge response
        mock_judgment = QualityJudgment(
            segment_id="test_seg",
            overall_score=0.85,
            speaker_clarity=0.9,
            emotion_match=0.8,
            prosody_naturalness=0.8,
            text_audio_alignment=0.85,
            issues=[],
            needs_regeneration=False,
            fix_suggestions=[],
        )
        self.mock_judge.judge_quality.return_value = mock_judgment

        # Create test inputs
        audio_path = "/fake/path.mp3"
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.95,
            needs_sfx=False,
            sfx_tags=[],
        )

        routing = TtsRoutingDecision(
            segment_id="test_seg",
            engine_choice="kokoro",
            voice_id="test_voice",
            prosody_overrides={},
            fallback_engine="edge",
            reasoning="Test",
            estimated_cost_usd=0.0,
            estimated_duration_ms=3000,
        )

        reference_text = "This is a test reference text."

        inputs = [(audio_path, annotation, routing, reference_text)]

        judgments = self.pipeline.run(inputs)

        assert len(judgments) == 1
        judgment = judgments[0]
        assert judgment.segment_id == "test_seg"
        assert judgment.overall_score == 0.85
        assert judgment.speaker_clarity == 0.9
        assert judgment.emotion_match == 0.8
        assert judgment.prosody_naturalness == 0.8
        assert judgment.text_audio_alignment == 0.85

        # Verify the judge was called
        self.mock_judge.judge_quality.assert_called_once()

    def test_run_with_rule_based_issues_triggers_regeneration(self):
        """Test that rule-based issues can trigger regeneration."""
        self.pipeline.mock_mode = True

        # Mock the judge response
        mock_judgment = QualityJudgment(
            segment_id="test_seg",
            overall_score=0.75,
            speaker_clarity=0.8,
            emotion_match=0.7,
            prosody_naturalness=0.7,
            text_audio_alignment=0.75,
            issues=[],
            needs_regeneration=False,
            fix_suggestions=[],
        )
        self.mock_judge.judge_quality.return_value = mock_judgment

        # Create analysis with clipping issue
        analysis_with_clipping = AudioAnalysisResult(
            duration_ms=3000,
            has_silence=False,
            silence_regions=[],
            has_clipping=True,  # This should trigger regeneration
            rms_db=-3.0,  # High RMS indicates potential clipping
            peak_db=-1.0,  # High peak near 0dB
            duration_match=True,
            issues=["audio_clipping_detected"],
        )

        # Patch the _analyze_audio_rules method to return our analysis with clipping
        with patch.object(self.pipeline, "_analyze_audio_rules", return_value=analysis_with_clipping):
            # Create test inputs
            audio_path = "/fake/path.mp3"
            annotation = ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="narrator",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                confidence=0.95,
            )

            routing = TtsRoutingDecision(
                segment_id="test_seg",
                engine_choice="kokoro",
                voice_id="test_voice",
                prosody_overrides={},
                fallback_engine="edge",
                reasoning="Test",
                estimated_cost_usd=0.0,
                estimated_duration_ms=3000,
            )

            reference_text = "This is a test reference text."

            inputs = [(audio_path, annotation, routing, reference_text)]

            judgments = self.pipeline.run(inputs)

            assert len(judgments) == 1
            judgment = judgments[0]

            # The rule-based issue should be added to judgment.issues
            assert "audio_clipping_detected" in judgment.issues

            # Because clipping was detected, needs_regeneration should be True
            assert judgment.needs_regeneration

            # Should have fix suggestions
            assert len(judgment.fix_suggestions) > 0
            assert any("重新合成以修复音频质量问题" in s.suggested_value for s in judgment.fix_suggestions)

    def test_run_with_silence_issue_triggers_regeneration(self):
        """Test that silence issues can trigger regeneration."""
        self.pipeline.mock_mode = True

        # Mock the judge response
        mock_judgment = QualityJudgment(
            segment_id="test_seg",
            overall_score=0.75,
            speaker_clarity=0.8,
            emotion_match=0.7,
            prosody_naturalness=0.7,
            text_audio_alignment=0.75,
            issues=[],
            needs_regeneration=False,
            fix_suggestions=[],
        )
        self.mock_judge.judge_quality.return_value = mock_judgment

        # Create analysis with silence issue
        analysis_with_silence = AudioAnalysisResult(
            duration_ms=3000,
            has_silence=True,  # This should trigger regeneration
            silence_regions=[(0, 1000), (2000, 3000)],  # Significant silence
            has_clipping=False,
            rms_db=-20.0,
            peak_db=-3.0,
            duration_match=True,
            issues=["excessive_silence_detected"],
        )

        # Patch the _analyze_audio_rules method
        with patch.object(self.pipeline, "_analyze_audio_rules", return_value=analysis_with_silence):
            # Create test inputs
            audio_path = "/fake/path.mp3"
            annotation = ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="narrator",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                confidence=0.95,
            )

            routing = TtsRoutingDecision(
                segment_id="test_seg",
                engine_choice="kokoro",
                voice_id="test_voice",
                prosody_overrides={},
                fallback_engine="edge",
                reasoning="Test",
                estimated_cost_usd=0.0,
                estimated_duration_ms=3000,
            )

            reference_text = "This is a test reference text."

            inputs = [(audio_path, annotation, routing, reference_text)]

            judgments = self.pipeline.run(inputs)

            assert len(judgments) == 1
            judgment = judgments[0]

            # The rule-based issue should be added to judgment.issues
            assert "excessive_silence_detected" in judgment.issues

            # Because silence was detected, needs_regeneration should be True
            assert judgment.needs_regeneration

    def test_quality_check_convenience_function(self):
        """Test the convenience quality_check function."""
        # Mock the judge
        mock_judge = Mock()
        mock_judgment = QualityJudgment(
            segment_id="test_seg",
            overall_score=0.8,
            speaker_clarity=0.85,
            emotion_match=0.75,
            prosody_naturalness=0.8,
            text_audio_alignment=0.8,
            issues=[],
            needs_regeneration=False,
            fix_suggestions=[],
        )
        mock_judge.judge_quality.return_value = mock_judgment

        # Create test inputs
        audio_path = "/fake/path.mp3"
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.95,
            needs_sfx=False,
            sfx_tags=[],
        )

        routing = TtsRoutingDecision(
            segment_id="test_seg",
            engine_choice="kokoro",
            voice_id="test_voice",
            prosody_overrides={},
            fallback_engine="edge",
            reasoning="Test",
            estimated_cost_usd=0.0,
            estimated_duration_ms=3000,
        )

        reference_text = "Test reference text."

        inputs = [(audio_path, annotation, routing, reference_text)]

        # Test with mock_mode=True to avoid needing real judge/router
        judgments = quality_check(inputs=inputs)

        assert len(judgments) == 1
        # In mock_mode=True, it should create its own mock judge and return mock judgments

    def test_audio_analysis_result_dataclass(self):
        """Test AudioAnalysisResult dataclass."""
        result = AudioAnalysisResult(
            duration_ms=2500,
            has_silence=True,
            silence_regions=[(100, 500)],
            has_clipping=False,
            rms_db=-18.0,
            peak_db=-2.5,
            duration_match=False,
            issues=["test_issue"],
        )

        assert result.duration_ms == 2500
        assert result.has_silence
        assert result.silence_regions == [(100, 500)]
        assert not result.has_clipping
        assert result.rms_db == -18.0
        assert result.peak_db == -2.5
        assert not result.duration_match
        assert result.issues == ["test_issue"]


class TestQualityCheckNonMockPaths:
    """Test non-mock audio analysis paths for coverage."""

    def setup_method(self):
        """Setup test fixtures with real (non-mock) pipeline."""
        self.mock_router = Mock()
        self.mock_judge = Mock()
        self.pipeline = QualityCheckPipeline(router=self.mock_router, judge=self.mock_judge, mock_mode=False)

    def test_analyze_audio_rules_mock_mode(self):
        """Test _analyze_audio_rules in mock mode."""
        self.pipeline.mock_mode = True
        result = self.pipeline._analyze_audio_rules(Path("/fake/audio.mp3"), 3000)
        assert isinstance(result, AudioAnalysisResult)
        assert result.duration_ms == 3000
        assert result.issues == []

    def test_analyze_audio_rules_ffprobe_failure(self):
        """Test ffprobe fails - returns error result."""
        with patch(
            "src.audiobook_studio.pipeline.quality_check.get_duration_sync",
            side_effect=FileNotFoundError,
        ):
            result = self.pipeline._analyze_audio_rules(Path("/fake/audio.mp3"), 3000)
            assert result.issues == ["ffprobe_not_found"]
            assert result.rms_db == -60.0

    def test_analyze_audio_rules_generic_exception(self):
        """Test generic exception in analysis - returns error result."""
        with patch(
            "src.audiobook_studio.pipeline.quality_check.get_duration_sync",
            side_effect=Exception("analysis error"),
        ):
            result = self.pipeline._analyze_audio_rules(Path("/fake/audio.mp3"), 3000)
            assert "analysis_error" in result.issues[0]
            assert result.rms_db == -60.0

    def test_get_threshold_none_config(self):
        """Test _get_threshold with None config."""
        self.pipeline.quality_thresholds = None
        assert self.pipeline._get_threshold("audio", "silence_threshold_db", default=-40.0) == -40.0

    def test_get_threshold_non_dict_value(self):
        """Test _get_threshold when intermediate value is not a dict."""
        self.pipeline.quality_thresholds = {"audio": "not_a_dict"}
        assert self.pipeline._get_threshold("audio", "silence_threshold_db", default=-40.0) == -40.0

    def test_get_threshold_missing_key(self):
        """Test _get_threshold when key is missing."""
        self.pipeline.quality_thresholds = {"audio": {"other_key": 123}}
        assert self.pipeline._get_threshold("audio", "silence_threshold_db", default=-40.0) == -40.0

    def test_get_threshold_valid(self):
        """Test _get_threshold with valid nested path."""
        self.pipeline.quality_thresholds = {"audio": {"silence_threshold_db": -35.0}}
        assert self.pipeline._get_threshold("audio", "silence_threshold_db", default=-40.0) == -35.0

    def test_reload_config_if_changed(self):
        """Test hot-reload config."""
        with patch("src.audiobook_studio.config.loader.reload_config_if_changed") as mock_reload:
            mock_reload.return_value = (
                {"audio": {"silence_threshold_db": -35.0}},
                123456.0,
            )
            self.pipeline._reload_config_if_changed()
            assert self.pipeline.quality_thresholds["audio"]["silence_threshold_db"] == -35.0
            assert self.pipeline._last_config_modified == 123456.0

    @patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.detect_silence_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.read_pcm_samples_sync")
    def test_analyze_with_ffprobe_success(self, mock_read_pcm, mock_get_rms, mock_detect_silence, mock_get_duration):
        """Test successful ffprobe audio analysis path using utility functions."""
        # Mock utility function returns
        mock_get_duration.return_value = 4000
        mock_detect_silence.return_value = [(500.0, 1500.0), (2000.0, 2500.0)]
        mock_get_rms.return_value = (-20.0, -3.0)
        # Create mock PCM samples with enough clipping (> 10% threshold from config)
        mock_samples = np.zeros(10000, dtype=np.float32)
        mock_samples[:1100] = 1.0  # 1100 clipped samples = 11% > 10% threshold
        mock_read_pcm.return_value = mock_samples

        result = self.pipeline._analyze_with_ffprobe(Path("/fake/audio.mp3"), 3000)

        assert result.duration_ms == 4000
        assert result.has_silence is True
        assert len(result.silence_regions) == 2
        assert result.rms_db == -20.0
        assert result.peak_db == -3.0
        assert result.has_clipping is True
        assert not result.duration_match  # 4000 vs 3000 exceeds 30% threshold

    @patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.detect_silence_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.read_pcm_samples_sync")
    def test_analyze_with_ffprobe_zero_duration(
        self, mock_read_pcm, mock_get_rms, mock_detect_silence, mock_get_duration
    ):
        """Test ffprobe analysis with zero duration."""
        mock_get_duration.return_value = 0
        mock_detect_silence.return_value = []
        mock_get_rms.return_value = (-60.0, -60.0)
        mock_read_pcm.return_value = np.array([], dtype=np.float32)

        result = self.pipeline._analyze_with_ffprobe(Path("/fake/audio.mp3"), 3000)

        assert result.duration_ms == 3000  # Falls back to expected
        assert result.issues == ["no_audio_data"]

    @patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.detect_silence_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.read_pcm_samples_sync")
    def test_analyze_with_ffprobe_no_audio_stream(
        self, mock_read_pcm, mock_get_rms, mock_detect_silence, mock_get_duration
    ):
        """Test ffprobe analysis with no audio stream (falls back to default sample rate)."""
        mock_get_duration.return_value = 3000
        mock_detect_silence.return_value = []
        mock_get_rms.return_value = (-20.0, -3.0)
        mock_read_pcm.return_value = np.ones(100, dtype=np.float32) * 0.1

        result = self.pipeline._analyze_with_ffprobe(Path("/fake/audio.mp3"), 3000)

        assert result.duration_ms == 3000
        assert result.duration_match is True
        assert result.has_silence is False

    @patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync")
    def test_analyze_with_ffprobe_file_not_found(self, mock_get_duration):
        """Test ffprobe FileNotFoundError propagation."""
        mock_get_duration.side_effect = FileNotFoundError("ffprobe not found")

        with pytest.raises(FileNotFoundError):
            self.pipeline._analyze_with_ffprobe(Path("/fake/audio.mp3"), 3000)

    @patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.detect_silence_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.read_pcm_samples_sync")
    def test_analyze_with_ffprobe_no_audio_data(
        self, mock_read_pcm, mock_get_rms, mock_detect_silence, mock_get_duration
    ):
        """Test ffprobe analysis with empty audio data and zero duration."""
        # When duration is 0, "no_audio_data" issue is added
        mock_get_duration.return_value = 0
        mock_detect_silence.return_value = []
        mock_get_rms.return_value = (-60.0, -60.0)
        mock_read_pcm.return_value = np.array([], dtype=np.float32)

        result = self.pipeline._analyze_with_ffprobe(Path("/fake/audio.mp3"), 3000)

        assert result.duration_ms == 3000  # Falls back to expected
        assert result.issues == ["no_audio_data"]

    def test_analyze_with_ffprobe_clipping_detection(self):
        """Test clipping detection with enough clipped samples."""
        with patch(
            "src.audiobook_studio.pipeline.quality_check.get_duration_sync",
            return_value=3000,
        ):
            with patch(
                "src.audiobook_studio.pipeline.quality_check.detect_silence_sync",
                return_value=[],
            ):
                with patch(
                    "src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync",
                    return_value=(-20.0, -3.0),
                ):
                    with patch("src.audiobook_studio.pipeline.quality_check.read_pcm_samples_sync") as mock_read_pcm:
                        # Create mock PCM samples with enough clipping (> 10% threshold from config)
                        mock_samples = np.zeros(10000, dtype=np.float32)
                        mock_samples[:1100] = 1.0  # 1100 clipped samples = 11% > 10% threshold
                        mock_read_pcm.return_value = mock_samples

                        result = self.pipeline._analyze_with_ffprobe(Path("/fake/audio.mp3"), 3000)

                        assert result.has_clipping is True
                        assert "clipping" in " ".join(result.issues)

    def test_run_exception_handling(self):
        """Test exception handling in run method records failure."""
        self.pipeline.mock_mode = False

        mock_judge = Mock()
        mock_judge.judge_quality.side_effect = Exception("LLM failed")
        self.pipeline.judge = mock_judge

        # Also mock analyze to return a valid result
        with patch.object(
            self.pipeline,
            "_analyze_audio_rules",
            return_value=AudioAnalysisResult(
                duration_ms=3000,
                has_silence=False,
                silence_regions=[],
                has_clipping=False,
                rms_db=-20.0,
                peak_db=-3.0,
                duration_match=True,
                issues=[],
            ),
        ):
            audio_path = "/fake/path.mp3"
            annotation = ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="narrator",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                confidence=0.95,
            )
            routing = TtsRoutingDecision(
                segment_id="test_seg",
                engine_choice="kokoro",
                voice_id="test",
                prosody_overrides={},
                fallback_engine="edge",
                reasoning="test",
                estimated_cost_usd=0.0,
                estimated_duration_ms=3000,
            )
            reference_text = "Test text"
            inputs = [(audio_path, annotation, routing, reference_text)]

            with pytest.raises(Exception, match="LLM failed"):
                self.pipeline.run(inputs)

    def test_run_success_records_performance(self):
        """Test successful run records performance metrics."""
        recorded = {}

        def capture_record(*args, **kwargs):
            # The function is called with keyword arguments
            recorded.update(kwargs)

        # Set mock_mode=False to test non-mock path that records performance
        self.pipeline.mock_mode = False
        mock_judgment = QualityJudgment(
            segment_id="test_seg",
            overall_score=0.85,
            speaker_clarity=0.9,
            emotion_match=0.8,
            prosody_naturalness=0.8,
            text_audio_alignment=0.85,
            issues=[],
            needs_regeneration=False,
            fix_suggestions=[],
        )
        self.mock_judge.judge_quality.return_value = mock_judgment

        # Patch where it's used in quality_check module (local binding from monitoring import)
        with patch(
            "src.audiobook_studio.pipeline.quality_check.record_stage_performance",
            side_effect=capture_record,
        ):
            audio_path = "/fake/path.mp3"
            annotation = ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="narrator",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                confidence=0.95,
            )
            routing = TtsRoutingDecision(
                segment_id="test_seg",
                engine_choice="kokoro",
                voice_id="test",
                prosody_overrides={},
                fallback_engine="edge",
                reasoning="test",
                estimated_cost_usd=0.0,
                estimated_duration_ms=3000,
            )
            reference_text = "Test text"
            inputs = [(audio_path, annotation, routing, reference_text)]

            self.pipeline.run(inputs)

            # Verify record_stage_performance was called with correct params
            assert recorded.get("stage") == "quality_check"
            assert recorded.get("success") is True
            assert recorded.get("quality_score") == 0.85
            assert recorded.get("schema_compliance") is True


if __name__ == "__main__":
    pytest.main([__file__])

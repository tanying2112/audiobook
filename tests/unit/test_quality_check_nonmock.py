import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Add the src directory to the path so we can import the module as a package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

from src.audiobook_studio.pipeline.quality_check import AudioAnalysisResult, QualityCheckPipeline, quality_check
from src.audiobook_studio.schemas import ParagraphAnnotation, QualityJudgment
from src.audiobook_studio.schemas.quality import FixSuggestion
from src.audiobook_studio.schemas.tts_routing import TtsRoutingDecision as TtsRoutingDecisionSchema


class TestQualityCheckPipelineNonMock:
    """Test QualityCheckPipeline class in non-mock mode."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        # Test with mock_mode=False to test non-mock paths
        self.pipeline = QualityCheckPipeline(mock_mode=False)

        # Create a mock audio file
        self.mock_audio_path = Path(self.temp_dir) / "test_segment.wav"
        self.mock_audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)  # Minimal WAV header

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_mock_annotation(self, **overrides):
        """Create a minimal ParagraphAnnotation for testing."""
        defaults = {
            "paragraph_index": 0,
            "speaker_canonical_name": "旁白",
            "is_dialogue": False,
            "emotion": "neutral",
            "emotion_intensity": 0.5,
            "speech_rate": 1.0,
            "pitch_shift_semitones": 0,
            "pause_before_ms": 300,
            "pause_after_ms": 500,
            "confidence": 0.9,
            "difficulty": "B",
            "needs_sfx": False,
            "sfx_tags": [],
        }
        defaults.update(overrides)
        return ParagraphAnnotation(**defaults)

    def create_mock_routing_decision(self, **overrides):
        """Create a minimal TtsRoutingDecision for testing."""
        defaults = {
            "segment_id": "book_001_ch1_p0",
            "engine_choice": "kokoro",
            "voice_id": "kokoro_narrator",
            "prosody_overrides": None,
            "fallback_engine": "edge",
            "reasoning": "Mock routing decision",
            "estimated_cost_usd": 0.001,
            "estimated_duration_ms": 5000,
        }
        defaults.update(overrides)
        return TtsRoutingDecisionSchema(**defaults)

    def test_init_non_mock(self):
        """Test pipeline initialization with mock_mode=False."""
        assert self.pipeline.mock_mode is False
        assert self.pipeline.router is not None
        assert self.pipeline.judge is not None

    def test_analyze_audio_rules_non_mock_success(self):
        """Test _analyze_audio_rules in non-mock mode with successful ffprobe analysis."""
        # Mock the ffprobe analysis to return specific values
        with patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync", return_value=5000):
            with patch("src.audiobook_studio.pipeline.quality_check.detect_silence_sync", return_value=[(1000, 1500)]):
                with patch("src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync", return_value=(-20.0, -3.0)):
                    with patch(
                        "src.audiobook_studio.pipeline.quality_check.read_pcm_samples_sync",
                        return_value=np.array([0.1, 0.2, 0.3]),
                    ):
                        analysis = self.pipeline._analyze_audio_rules(self.mock_audio_path, 5000)

                        assert isinstance(analysis, AudioAnalysisResult)
                        assert analysis.duration_ms == 5000
                        assert analysis.has_silence is True
                        assert analysis.silence_regions == [(1000, 1500)]
                        assert analysis.has_clipping is False  # Low values in test array
                        assert analysis.rms_db == -20.0
                        assert analysis.peak_db == -3.0
                        assert analysis.duration_match is True  # 5000 == 5000
                        # Silence is reported as an issue
                        assert len(analysis.issues) == 1
                        assert "silence" in analysis.issues[0]

    def test_analyze_audio_rules_non_mock_with_issues(self):
        """Test _analyze_audio_rules in non-mock mode with various issues detected."""
        # Mock the ffprobe analysis to return values that trigger issues
        with patch(
            "src.audiobook_studio.pipeline.quality_check.get_duration_sync", return_value=3000
        ):  # Duration mismatch
            with patch(
                "src.audiobook_studio.pipeline.quality_check.detect_silence_sync",
                return_value=[(500, 1000), (2000, 2500)],
            ):  # Silence detected
                with patch(
                    "src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync", return_value=(1.0, -1.0)
                ):  # High volume
                    with patch(
                        "src.audiobook_studio.pipeline.quality_check.read_pcm_samples_sync",
                        return_value=np.array([1.0] * 15 + [0.5] * 5),
                    ):  # Clipping
                        analysis = self.pipeline._analyze_audio_rules(self.mock_audio_path, 5000)

                        assert isinstance(analysis, AudioAnalysisResult)
                        assert analysis.duration_ms == 3000
                        assert analysis.has_silence is True
                        assert len(analysis.silence_regions) == 2
                        assert analysis.has_clipping is True
                        assert analysis.rms_db == 1.0
                        assert analysis.peak_db == -1.0
                        assert analysis.duration_match is False  # 3000 != 5000
                        assert len(analysis.issues) > 0

                        # Check that issues contain expected problem types
                        issues_text = " ".join(analysis.issues)
                        assert "duration_mismatch" in issues_text
                        assert "silence" in issues_text
                        assert "high_volume" in issues_text

    def test_analyze_audio_rules_non_mock_ffprobe_not_found(self):
        """Test _analyze_audio_rules when ffprobe is not found."""
        with patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync", side_effect=FileNotFoundError()):
            analysis = self.pipeline._analyze_audio_rules(self.mock_audio_path, 5000)

            assert isinstance(analysis, AudioAnalysisResult)
            assert analysis.duration_ms == 5000  # Falls back to expected duration
            assert analysis.has_silence is False
            assert analysis.has_clipping is False
            assert analysis.rms_db == -60.0  # Error values
            assert analysis.peak_db == -60.0
            assert analysis.duration_match is False
            assert "ffprobe_not_found" in analysis.issues

    def test_analyze_audio_rules_non_mock_analysis_error(self):
        """Test _analyze_audio_rules when analysis encounters an error."""
        with patch(
            "src.audiobook_studio.pipeline.quality_check.get_duration_sync", side_effect=Exception("Analysis failed")
        ):
            analysis = self.pipeline._analyze_audio_rules(self.mock_audio_path, 5000)

            assert isinstance(analysis, AudioAnalysisResult)
            assert analysis.duration_ms == 5000  # Falls back to expected duration
            assert analysis.has_silence is False
            assert analysis.has_clipping is False
            assert analysis.rms_db == -60.0  # Error values
            assert analysis.peak_db == -60.0
            assert analysis.duration_match is False
            assert any("analysis_error" in issue for issue in analysis.issues)

    def test_build_audio_description_normal(self):
        """Test _build_audio_description with normal analysis."""
        annotation = self.create_mock_annotation()
        analysis = AudioAnalysisResult(
            duration_ms=5000,
            has_silence=True,
            silence_regions=[(1000, 1500)],
            has_clipping=False,
            rms_db=-20.0,
            peak_db=-3.0,
            duration_match=True,
            issues=[],
        )

        desc = self.pipeline._build_audio_description(analysis, annotation)

        assert "音频时长 5000ms" in desc
        assert "检测到 1 处静音段" in desc
        assert "RMS -20.0dB" in desc
        assert "峰值 -3.0dB" in desc

    def test_build_audio_description_with_issues(self):
        """Test _build_audio_description with various issues."""
        annotation = self.create_mock_annotation()
        analysis = AudioAnalysisResult(
            duration_ms=3000,
            has_silence=True,
            silence_regions=[(500, 1000), (2000, 2500)],
            has_clipping=True,
            rms_db=-10.0,
            peak_db=-1.0,
            duration_match=False,
            issues=[
                "duration_mismatch: expected 5000ms, got 3000ms",
                "clipping: 2/3 samples clipped",
                "silence: 2 silent regions detected (500-1000ms; 2000-2500ms)",
            ],
        )

        desc = self.pipeline._build_audio_description(analysis, annotation)

        assert "音频时长 3000ms" in desc
        assert "检测到 2 处静音段" in desc
        assert "存在削波失真" in desc  # Chinese for clipping
        assert "时长与预期不符" in desc  # Chinese for duration mismatch
        assert "RMS -10.0dB" in desc
        assert "峰值 -1.0dB" in desc

    def test_run_non_mock_mode_calls_jududge(self):
        """Test run() in non-mock mode calls LLM judge."""
        mock_judge = MagicMock()
        mock_judgment = QualityJudgment(
            segment_id="book_001_ch1_p0",
            speaker_clarity=0.9,
            emotion_match=0.85,
            prosody_naturalness=0.9,
            text_audio_alignment=0.95,
            overall_score=0.9,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
        )
        mock_judge.judge_quality.return_value = mock_judgment

        pipeline = QualityCheckPipeline(judge=mock_judge, mock_mode=False)
        annotation = self.create_mock_annotation()
        routing = self.create_mock_routing_decision()

        inputs = [(str(self.mock_audio_path), annotation, routing, "测试文本")]

        results = pipeline.run(inputs)

        assert results[0] == mock_judgment
        mock_judge.judge_quality.assert_called_once()

    def test_run_non_mock_mode_combines_rule_issues(self):
        """Test run() combines rule-based issues with LLM judgment in non-mock mode."""
        # Setup mock judge
        mock_judge = MagicMock()
        mock_judgment = QualityJudgment(
            segment_id="book_001_ch1_p0",
            speaker_clarity=0.9,
            emotion_match=0.85,
            prosody_naturalness=0.9,
            text_audio_alignment=0.95,
            overall_score=0.9,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
        )
        mock_judge.judge_quality.return_value = mock_judgment

        pipeline = QualityCheckPipeline(judge=mock_judge, mock_mode=False)
        annotation = self.create_mock_annotation()
        routing = self.create_mock_routing_decision()

        # Create audio that will have issues when analyzed
        with patch(
            "src.audiobook_studio.pipeline.quality_check.get_duration_sync", return_value=3000
        ):  # Duration mismatch
            with patch(
                "src.audiobook_studio.pipeline.quality_check.detect_silence_sync", return_value=[(500, 1000)]
            ):  # Silence
                with patch(
                    "src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync", return_value=(-10.0, -1.0)
                ):  # High volume
                    with patch(
                        "src.audiobook_studio.pipeline.quality_check.read_pcm_samples_sync",
                        return_value=np.array([0.1, 0.2, 0.3]),
                    ):  # No clipping

                        inputs = [(str(self.mock_audio_path), annotation, routing, "测试文本")]

                        results = pipeline.run(inputs)

                        assert isinstance(results[0], QualityJudgment)
                        # Should have rule-based issues incorporated
                        assert len(results[0].issues) > 0
                        # Check that duration mismatch issue is present
                        issues_text = " ".join(results[0].issues)
                        assert "duration_mismatch" in issues_text or "时长与预期不符" in issues_text

    def test_quality_check_convenience_function_non_mock(self):
        """Test quality_check convenience function with mock_mode=False."""
        annotation = self.create_mock_annotation()
        routing = self.create_mock_routing_decision()

        # Mock the judge to avoid actual LLM calls
        with patch("src.audiobook_studio.pipeline.quality_check.create_judge") as mock_create_judge:
            mock_judge = MagicMock()
            mock_judgment = QualityJudgment(
                segment_id="test_seg",
                speaker_clarity=0.8,
                emotion_match=0.7,
                prosody_naturalness=0.75,
                text_audio_alignment=0.8,
                overall_score=0.75,
                issues=[],
                fix_suggestions=[],
                needs_regeneration=False,
            )
            mock_judge.judge_quality.return_value = mock_judgment
            mock_create_judge.return_value = mock_judge

            inputs = [(str(self.mock_audio_path), annotation, routing, "测试文本")]

            results = quality_check(inputs, mock_mode=False)

            assert isinstance(results, list)
            assert len(results) == 1
            assert isinstance(results[0], QualityJudgment)
            assert results[0].overall_score == 0.75


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

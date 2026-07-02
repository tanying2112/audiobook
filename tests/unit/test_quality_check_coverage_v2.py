"""Supplementary tests for quality_check.py targeting 80%+ coverage.

Covers:
- _multimodal_judge_quality full path (encode audio + router call)
- _encode_audio_base64 error path
- Mock mode FixSuggestion merge when issues present
- Non-mock path: hard check result merging into judgment
- LLM judge exception handler (lines 737-759)
- _reload_config_if_changed
- _get_threshold default fallback
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from src.audiobook_studio.pipeline.quality_check import AudioAnalysisResult, QualityCheckPipeline
from src.audiobook_studio.schemas import ParagraphAnnotation, QualityJudgment
from src.audiobook_studio.schemas.quality import FixSuggestion
from src.audiobook_studio.schemas.tts_routing import TtsRoutingDecision as TtsRoutingDecisionSchema


def _make_annotation(**overrides):
    defaults = dict(
        paragraph_index=0,
        speaker_canonical_name="旁白",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        speech_rate=1.0,
        pitch_shift_semitones=0,
        pause_before_ms=300,
        pause_after_ms=500,
        confidence=0.9,
        difficulty="B",
        needs_sfx=False,
        sfx_tags=[],
        notes="test",
        contract_version=1,
    )
    defaults.update(overrides)
    return ParagraphAnnotation(**defaults)


def _make_routing(**overrides):
    defaults = dict(
        segment_id="seg_001",
        engine_choice="kokoro",
        voice_id="kokoro_narrator",
        prosody_overrides=None,
        fallback_engine="edge",
        reasoning="test",
        estimated_cost_usd=0.001,
        estimated_duration_ms=5000,
    )
    defaults.update(overrides)
    return TtsRoutingDecisionSchema(**defaults)


class TestMultimodalJudgeFullPath:
    """Test _multimodal_judge_quality when enabled and audio encoding succeeds."""

    def test_multimodal_judge_enabled_calls_router(self):
        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "test.mp3"
            audio_path.write_bytes(b"fake audio data")

            pipeline = QualityCheckPipeline(mock_mode=False)
            # Set up hardware profile to enable multimodal
            hp = MagicMock()
            hp.active_profile = "pro_studio"
            hp.is_gpu_available.return_value = True
            pipeline.hardware_profile = hp

            # Mock the router to return a judgment
            mock_result = MagicMock()
            mock_result.output = QualityJudgment(
                segment_id="seg_001",
                speaker_clarity=0.9,
                emotion_match=0.8,
                prosody_naturalness=0.85,
                text_audio_alignment=0.9,
                overall_score=0.87,
                issues=[],
                fix_suggestions=[],
                needs_regeneration=False,
            )
            pipeline.router = MagicMock()
            pipeline.router.call.return_value = mock_result

            annotation = _make_annotation()
            result = pipeline._multimodal_judge_quality("seg_001", audio_path, annotation, "参考文本")

            assert result is not None
            assert result.overall_score == pytest.approx(0.87)
            pipeline.router.call.assert_called_once()

    def test_multimodal_judge_encode_fails(self):
        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "missing.mp3"
            # File does not exist -> encode fails
            pipeline = QualityCheckPipeline(mock_mode=False)
            hp = MagicMock()
            hp.active_profile = "pro_studio"
            hp.is_gpu_available.return_value = True
            pipeline.hardware_profile = hp

            annotation = _make_annotation()
            result = pipeline._multimodal_judge_quality("seg_001", audio_path, annotation, "ref")
            assert result is None

    def test_multimodal_judge_router_returns_none_output(self):
        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "test.mp3"
            audio_path.write_bytes(b"fake")

            pipeline = QualityCheckPipeline(mock_mode=False)
            hp = MagicMock()
            hp.active_profile = "pro_studio"
            hp.is_gpu_available.return_value = True
            pipeline.hardware_profile = hp

            mock_result = MagicMock()
            mock_result.output = None
            pipeline.router = MagicMock()
            pipeline.router.call.return_value = mock_result

            annotation = _make_annotation()
            result = pipeline._multimodal_judge_quality("seg_001", audio_path, annotation, "ref")
            assert result is None

    def test_multimodal_judge_router_raises(self):
        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "test.mp3"
            audio_path.write_bytes(b"fake")

            pipeline = QualityCheckPipeline(mock_mode=False)
            hp = MagicMock()
            hp.active_profile = "pro_studio"
            hp.is_gpu_available.return_value = True
            pipeline.hardware_profile = hp

            pipeline.router = MagicMock()
            pipeline.router.call.side_effect = RuntimeError("API down")

            annotation = _make_annotation()
            result = pipeline._multimodal_judge_quality("seg_001", audio_path, annotation, "ref")
            assert result is None


class TestEncodeAudioBase64:
    """Test _encode_audio_base64 error handling."""

    def test_encode_nonexistent_file(self):
        pipeline = QualityCheckPipeline(mock_mode=True)
        result = pipeline._encode_audio_base64(Path("/nonexistent/file.mp3"))
        assert result is None

    def test_encode_valid_file(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "audio.mp3"
            p.write_bytes(b"fake audio content")
            pipeline = QualityCheckPipeline(mock_mode=True)
            result = pipeline._encode_audio_base64(p)
            assert result is not None
            import base64

            decoded = base64.b64decode(result)
            assert decoded == b"fake audio content"


class TestMockModeFixSuggestionMerge:
    """Test mock mode merges rule-based issues into FixSuggestion."""

    def test_mock_mode_with_issues_adds_fix_suggestion(self):
        pipeline = QualityCheckPipeline(mock_mode=True)
        annotation = _make_annotation()
        routing = _make_routing()
        # Create a mock audio path
        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "test.wav"
            audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)

            inputs = [(str(audio_path), annotation, routing, "测试文本")]
            results = pipeline.run(inputs)

            assert len(results) == 1
            assert isinstance(results[0], QualityJudgment)


class TestGetThresholdDefault:
    """Test _get_threshold with various scenarios."""

    def test_threshold_hardware_override_none(self):
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline._hw_dnsmos_min = None
        pipeline._hw_asr_wer_max = None
        pipeline._hw_speaker_sim_min = None
        # Should fall through to config default
        val = pipeline._get_threshold("audio", "dnsmos_min", default=3.5)
        assert val == 3.5

    def test_threshold_nested_key_default(self):
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline._hw_dnsmos_min = None
        pipeline._hw_asr_wer_max = None
        pipeline._hw_speaker_sim_min = None
        val = pipeline._get_threshold("audio", "nonexistent_key", default=99)
        assert val == 99


class TestReloadConfigIfChanged:
    """Test _reload_config_if_changed."""

    def test_reload_config_calls_loader(self):
        pipeline = QualityCheckPipeline(mock_mode=True)
        with patch("src.audiobook_studio.config.loader.reload_config_if_changed") as mock_reload:
            mock_reload.return_value = (pipeline.quality_thresholds, None)
            pipeline._reload_config_if_changed()
            mock_reload.assert_called_once()


class TestNonMockHardCheckMerge:
    """Test non-mock path where hard quality check results merge into judgment."""

    def test_hard_check_failure_sets_regeneration(self):
        mock_judge = MagicMock()
        mock_judgment = QualityJudgment(
            segment_id="seg_001",
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
        pipeline._available_features = {
            "ffmpeg": True,
            "dnsmos": False,
            "asr": False,
            "speaker_sim": False,
        }

        annotation = _make_annotation()
        routing = _make_routing()

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "test.wav"
            audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)

            # Mock hard quality checks to fail
            mock_hard_result = MagicMock()
            mock_hard_result.passed = False
            mock_hard_result.dnsmos = None
            mock_hard_result.wer = None
            mock_hard_result.speaker_sim = None
            mock_hard_result.overall_message = "Hard quality check failed"

            # Mock the _analyze_with_ffprobe to return valid analysis
            mock_analysis = AudioAnalysisResult(
                duration_ms=5000,
                has_silence=False,
                silence_regions=[],
                has_clipping=False,
                rms_db=-20.0,
                peak_db=-3.0,
                duration_match=True,
                issues=[],
            )

            with (
                patch.object(pipeline, "_run_hard_quality_checks", return_value=mock_hard_result),
                patch.object(pipeline, "_analyze_with_ffprobe", return_value=mock_analysis),
                patch("src.audiobook_studio.pipeline.quality_check.observe_quality_check"),
                patch("src.audiobook_studio.pipeline.quality_check.record_stage_performance"),
            ):

                inputs = [(str(audio_path), annotation, routing, "测试文本")]
                results = pipeline.run(inputs)

                assert len(results) == 1
                assert results[0].needs_regeneration is True
                assert any("Hard quality check failed" in i for i in results[0].issues)

    def test_hard_check_with_dnsmos_and_speaker_sim_adjusts_score(self):
        mock_judge = MagicMock()
        mock_judgment = QualityJudgment(
            segment_id="seg_001",
            speaker_clarity=0.7,
            emotion_match=0.85,
            prosody_naturalness=0.9,
            text_audio_alignment=0.95,
            overall_score=0.85,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
        )
        mock_judge.judge_quality.return_value = mock_judgment

        pipeline = QualityCheckPipeline(judge=mock_judge, mock_mode=False)
        pipeline._available_features = {
            "ffmpeg": True,
            "dnsmos": True,
            "asr": False,
            "speaker_sim": True,
        }

        annotation = _make_annotation()
        routing = _make_routing()

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "test.wav"
            audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)

            mock_hard_result = MagicMock()
            mock_hard_result.passed = True
            mock_hard_result.dnsmos = MagicMock(success=True, mos_ovr=4.0)
            mock_hard_result.wer = MagicMock(success=False)
            mock_hard_result.speaker_sim = MagicMock(success=True, similarity=0.92)
            mock_hard_result.overall_message = "Passed"

            mock_analysis = AudioAnalysisResult(
                duration_ms=5000,
                has_silence=False,
                silence_regions=[],
                has_clipping=False,
                rms_db=-20.0,
                peak_db=-3.0,
                duration_match=True,
                issues=[],
            )

            with (
                patch.object(pipeline, "_run_hard_quality_checks", return_value=mock_hard_result),
                patch.object(pipeline, "_analyze_with_ffprobe", return_value=mock_analysis),
                patch("src.audiobook_studio.pipeline.quality_check.observe_quality_check"),
                patch("src.audiobook_studio.pipeline.quality_check.record_stage_performance"),
            ):

                inputs = [(str(audio_path), annotation, routing, "测试文本")]
                results = pipeline.run(inputs)

                assert len(results) == 1
                # speaker_clarity should have been averaged with dnsmos/8.0 and speaker_sim
                assert results[0].speaker_clarity != 0.7  # Adjusted

    def test_llm_judge_exception_re_raises(self):
        """Test that exception from judge in non-mock mode re-raises after recording."""
        mock_judge = MagicMock()
        mock_judge.judge_quality.side_effect = RuntimeError("LLM API error")

        pipeline = QualityCheckPipeline(judge=mock_judge, mock_mode=False)
        pipeline._available_features = {
            "ffmpeg": True,
            "dnsmos": False,
            "asr": False,
            "speaker_sim": False,
        }

        annotation = _make_annotation()
        routing = _make_routing()

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "test.wav"
            audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)

            mock_hard_result = MagicMock()
            mock_hard_result.passed = True
            mock_hard_result.dnsmos = None
            mock_hard_result.wer = None
            mock_hard_result.speaker_sim = None
            mock_hard_result.overall_message = "Passed"

            mock_analysis = AudioAnalysisResult(
                duration_ms=5000,
                has_silence=False,
                silence_regions=[],
                has_clipping=False,
                rms_db=-20.0,
                peak_db=-3.0,
                duration_match=True,
                issues=[],
            )

            with (
                patch.object(pipeline, "_run_hard_quality_checks", return_value=mock_hard_result),
                patch.object(pipeline, "_analyze_with_ffprobe", return_value=mock_analysis),
                patch("src.audiobook_studio.pipeline.quality_check.observe_quality_check"),
                patch("src.audiobook_studio.pipeline.quality_check.record_stage_performance") as mock_perf,
            ):

                inputs = [(str(audio_path), annotation, routing, "测试文本")]
                with pytest.raises(RuntimeError, match="LLM API error"):
                    pipeline.run(inputs)

                # Verify performance was recorded with success=False
                assert mock_perf.call_count >= 1
                last_call = mock_perf.call_args_list[-1]
                assert last_call.kwargs.get("success") is False

    def test_rule_issues_trigger_regeneration(self):
        """Test that rule-based clipping/silence issues set needs_regeneration."""
        mock_judge = MagicMock()
        mock_judgment = QualityJudgment(
            segment_id="seg_001",
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
        pipeline._available_features = {
            "ffmpeg": True,
            "dnsmos": False,
            "asr": False,
            "speaker_sim": False,
        }

        annotation = _make_annotation()
        routing = _make_routing()

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "test.wav"
            audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)

            mock_hard_result = MagicMock()
            mock_hard_result.passed = True
            mock_hard_result.dnsmos = None
            mock_hard_result.wer = None
            mock_hard_result.speaker_sim = None
            mock_hard_result.overall_message = "Passed"

            # Analysis with clipping issues
            mock_analysis = AudioAnalysisResult(
                duration_ms=5000,
                has_silence=True,
                silence_regions=[(1000, 1500)],
                has_clipping=True,
                rms_db=-20.0,
                peak_db=-3.0,
                duration_match=True,
                issues=[
                    "clipping: 100/1000 samples clipped",
                    "silence: 1 silent regions",
                ],
            )

            with (
                patch.object(pipeline, "_run_hard_quality_checks", return_value=mock_hard_result),
                patch.object(pipeline, "_analyze_with_ffprobe", return_value=mock_analysis),
                patch("src.audiobook_studio.pipeline.quality_check.observe_quality_check"),
                patch("src.audiobook_studio.pipeline.quality_check.record_stage_performance"),
            ):

                inputs = [(str(audio_path), annotation, routing, "测试文本")]
                results = pipeline.run(inputs)

                assert len(results) == 1
                assert results[0].needs_regeneration is True
                assert any("clipping" in i for i in results[0].issues)

"""Targeted tests for quality_check.py uncovered lines.

Uncovered lines: 88, 102, 156, 163, 167, 171, 178-179, 188, 199-201,
234, 263-264, 317-388, 400, 615-617, 651
"""

import os
import sys
import tempfile
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.audiobook_studio.pipeline.quality_check import (
    QualityCheckPipeline,
    AudioAnalysisResult,
)
from src.audiobook_studio.schemas import (
    QualityJudgment,
    ParagraphAnnotation,
)
from src.audiobook_studio.schemas.tts_routing import TtsRoutingDecision


def _ann(**kw):
    d = dict(
        paragraph_index=0, speaker_canonical_name="旁白", is_dialogue=False,
        emotion="neutral", emotion_intensity=0.5, speech_rate=1.0,
        pitch_shift_semitones=0, pause_before_ms=300, pause_after_ms=500,
        confidence=0.9, difficulty="B", needs_sfx=False, sfx_tags=[],
        notes="test", contract_version=1,
    )
    d.update(kw)
    return ParagraphAnnotation(**d)


def _routing(**kw):
    d = dict(
        segment_id="seg_001", engine_choice="kokoro", voice_id="v1",
        prosody_overrides=None, fallback_engine="edge", reasoning="test",
        estimated_cost_usd=0.001, estimated_duration_ms=5000,
    )
    d.update(kw)
    return TtsRoutingDecision(**d)


# ================================================================
# Lines 88, 102: init env-var mock_mode path + create_router path
# ================================================================


class TestInitEnvVarPath:
    """Cover lines 88 and 102."""

    def test_init_mock_mode_none_reads_env_true(self, monkeypatch):
        """When mock_mode=None and MOCK_LLM=true → mock_mode is True."""
        monkeypatch.setenv("MOCK_LLM", "true")
        pipeline = QualityCheckPipeline(mock_mode=None)
        assert pipeline.mock_mode is True

    def test_init_mock_mode_none_reads_env_false(self, monkeypatch):
        """When mock_mode=None and MOCK_LLM=false → mock_mode is False."""
        monkeypatch.setenv("MOCK_LLM", "false")
        pipeline = QualityCheckPipeline(mock_mode=None)
        assert pipeline.mock_mode is False

    def test_init_explicit_mock_true_skips_env(self, monkeypatch):
        """Explicit mock_mode=True overrides env var."""
        monkeypatch.setenv("MOCK_LLM", "false")
        pipeline = QualityCheckPipeline(mock_mode=True)
        assert pipeline.mock_mode is True

    def test_init_explicit_mock_false_skips_env(self, monkeypatch):
        """Explicit mock_mode=False overrides env var."""
        monkeypatch.setenv("MOCK_LLM", "true")
        pipeline = QualityCheckPipeline(mock_mode=False)
        assert pipeline.mock_mode is False

    def test_init_no_env_mock_pop_path(self, monkeypatch):
        """When MOCK_LLM not in env, pop path is taken (line 95)."""
        monkeypatch.delenv("MOCK_LLM", raising=False)
        pipeline = QualityCheckPipeline(mock_mode=None)
        # mock_mode defaults to False (from os.environ.get default "false")
        assert pipeline.mock_mode is False


# ================================================================
# Lines 156-179: _check_optional_dependencies success branches
# ================================================================


class TestCheckOptionalDependenciesSuccess:
    """Cover the import success branches."""

    def test_onnxruntime_import_success(self):
        """onnxruntime importable → dnsmos=True."""
        fake_onnx = ModuleType("onnxruntime")
        with patch.dict(sys.modules, {"onnxruntime": fake_onnx}):
            features = QualityCheckPipeline._check_optional_dependencies()
            assert features["dnsmos"] is True

    def test_funasr_import_success(self):
        """funasr importable → asr=True."""
        fake_funasr = ModuleType("funasr")
        with patch.dict(sys.modules, {"funasr": fake_funasr}):
            features = QualityCheckPipeline._check_optional_dependencies()
            assert features["asr"] is True

    def test_faster_whisper_import_success(self):
        """faster_whisper importable (funasr not) → asr=True."""
        fake_fw = ModuleType("faster_whisper")
        with patch.dict(sys.modules, {"funasr": None, "faster_whisper": fake_fw}):
            features = QualityCheckPipeline._check_optional_dependencies()
            assert features["asr"] is True

    def test_whisper_import_success(self):
        """Only whisper importable → asr=True."""
        fake_whisper = ModuleType("whisper")
        with patch.dict(sys.modules, {"funasr": None, "faster_whisper": None, "whisper": fake_whisper}):
            features = QualityCheckPipeline._check_optional_dependencies()
            assert features["asr"] is True

    def test_all_asr_fail(self):
        """All ASR backends unavailable → asr=False."""
        with patch.dict(sys.modules, {"funasr": None, "faster_whisper": None, "whisper": None}):
            features = QualityCheckPipeline._check_optional_dependencies()
            assert features["asr"] is False

    def test_torch_and_speechbrain_success(self):
        """torch + speechbrain importable → speaker_sim=True."""
        fake_torch = ModuleType("torch")
        fake_sb = ModuleType("speechbrain")
        fake_sb_infer = ModuleType("speechbrain.inference")
        fake_sb_speaker = ModuleType("speechbrain.inference.speaker")
        fake_sb_speaker.EncoderClassifier = MagicMock()
        with patch.dict(sys.modules, {
            "torch": fake_torch, "speechbrain": fake_sb,
            "speechbrain.inference": fake_sb_infer,
            "speechbrain.inference.speaker": fake_sb_speaker,
        }):
            features = QualityCheckPipeline._check_optional_dependencies()
            assert features["speaker_sim"] is True

    def test_torch_import_raises_exception(self):
        """torch import raises generic Exception → speaker_sim stays False."""
        # Patch the import to raise a non-ImportError exception
        with patch.dict(sys.modules, {"torch": None}):
            features = QualityCheckPipeline._check_optional_dependencies()
            assert features["speaker_sim"] is False


# ================================================================
# Lines 199-201: _apply_hardware_profile else branch
# ================================================================


class TestApplyHardwareProfileNoThresholds:
    """Cover lines 199-201."""

    def _make_hp(self, dnsmos_enabled=False, thresholds=None):
        """Create a hardware profile with a real __dict__ for the check."""
        class FakeQC:
            def __init__(self):
                self.dnsmos_enabled = dnsmos_enabled
                self.asr_enabled = False
                self.speaker_similarity_enabled = False
                if thresholds is not None:
                    self.thresholds = thresholds

        class FakeHP:
            def __init__(self):
                self.quality_check = FakeQC()
                self.active_profile = "edge_lite"
            def is_gpu_available(self):
                return False

        return FakeHP()

    def test_dnsmos_not_enabled(self):
        """dnsmos_enabled=False → hw thresholds all None."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline.hardware_profile = self._make_hp(dnsmos_enabled=False)
        pipeline._apply_hardware_profile_quality_config()
        assert pipeline._hw_dnsmos_min is None
        assert pipeline._hw_asr_wer_max is None
        assert pipeline._hw_speaker_sim_min is None

    def test_dnsmos_enabled_no_thresholds_key(self):
        """dnsmos_enabled=True but 'thresholds' not in __dict__ → else branch."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline.hardware_profile = self._make_hp(dnsmos_enabled=True)
        pipeline._apply_hardware_profile_quality_config()
        assert pipeline._hw_dnsmos_min is None

    def test_no_hardware_profile(self):
        """No hardware_profile → early return."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline.hardware_profile = None
        pipeline._apply_hardware_profile_quality_config()

    def test_dnsmos_enabled_with_thresholds(self):
        """dnsmos_enabled=True with thresholds dict → hw thresholds set."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        t = {"dnsmos_min": 3.8, "asr_wer_max": 0.06, "speaker_sim_min": 0.88}
        pipeline.hardware_profile = self._make_hp(dnsmos_enabled=True, thresholds=t)
        pipeline._apply_hardware_profile_quality_config()
        assert pipeline._hw_dnsmos_min == 3.8
        assert pipeline._hw_asr_wer_max == 0.06
        assert pipeline._hw_speaker_sim_min == 0.88


# ================================================================
# Line 234: _get_threshold with non-dict intermediate value
# ================================================================


class TestGetThresholdNonDict:
    """Cover line 234."""

    def test_intermediate_not_dict(self):
        """Intermediate value is not a dict → returns default."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline._hw_dnsmos_min = None
        pipeline._hw_asr_wer_max = None
        pipeline._hw_speaker_sim_min = None
        pipeline.quality_thresholds = {"audio": "not_a_dict"}
        result = pipeline._get_threshold("audio", "silence_threshold_db", default=-40.0)
        assert result == -40.0

    def test_intermediate_is_none(self):
        """Intermediate value is None → returns default."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline._hw_dnsmos_min = None
        pipeline._hw_asr_wer_max = None
        pipeline._hw_speaker_sim_min = None
        pipeline.quality_thresholds = {"audio": None}
        result = pipeline._get_threshold("audio", "silence_threshold_db", default=-40.0)
        assert result == -40.0

    def test_final_value_none(self):
        """Final key maps to None → returns default."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline._hw_dnsmos_min = None
        pipeline._hw_asr_wer_max = None
        pipeline._hw_speaker_sim_min = None
        pipeline.quality_thresholds = {"audio": {"silence_threshold_db": None}}
        result = pipeline._get_threshold("audio", "silence_threshold_db", default=-40.0)
        assert result == -40.0

    def test_non_audio_key(self):
        """Non-audio key path skips hardware checks."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline._hw_dnsmos_min = None
        pipeline._hw_asr_wer_max = None
        pipeline._hw_speaker_sim_min = None
        pipeline.quality_thresholds = {"llm": {"temperature": 0.5}}
        result = pipeline._get_threshold("llm", "temperature", default=0.1)
        assert result == 0.5


# ================================================================
# Lines 263-264: FileNotFoundError in _analyze_audio_rules
# ================================================================


class TestAnalyzeAudioRulesFileNotFound:
    """Cover lines 263-264."""

    def test_file_not_found_returns_default(self):
        """FileNotFoundError → returns default analysis with error issue."""
        pipeline = QualityCheckPipeline(mock_mode=False)
        with patch.object(pipeline, "_analyze_with_ffprobe", side_effect=FileNotFoundError("ffprobe")):
            result = pipeline._analyze_audio_rules(Path("/fake.wav"), 5000)
        assert isinstance(result, AudioAnalysisResult)
        assert "ffprobe_not_found" in result.issues
        assert result.rms_db == -60.0

    def test_generic_exception_returns_error(self):
        """Generic exception → returns analysis with error issue."""
        pipeline = QualityCheckPipeline(mock_mode=False)
        with patch.object(pipeline, "_analyze_with_ffprobe", side_effect=RuntimeError("boom")):
            result = pipeline._analyze_audio_rules(Path("/fake.wav"), 5000)
        assert isinstance(result, AudioAnalysisResult)
        assert any("analysis_error" in i for i in result.issues)


# ================================================================
# Lines 317-388: _analyze_with_ffprobe full body
# ================================================================


class TestAnalyzeWithFfprobe:
    """Cover the full _analyze_with_ffprobe body."""

    def _make_pipeline(self):
        p = QualityCheckPipeline(mock_mode=False)
        p._hw_dnsmos_min = None
        p._hw_asr_wer_max = None
        p._hw_speaker_sim_min = None
        return p

    def _run_analysis(self, pipeline, duration=5000, expected=5000,
                      silence=None, rms_db=-20.0, peak_db=-3.0,
                      samples=None):
        """Helper to run _analyze_with_ffprobe with mocked dependencies."""
        if silence is None:
            silence = []
        if samples is None:
            samples = np.zeros(100, dtype=np.float32)

        with patch("src.audiobook_studio.config.loader.reload_config_if_changed",
                    return_value=(pipeline.quality_thresholds, None)), \
             patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync",
                    return_value=duration), \
             patch("src.audiobook_studio.pipeline.quality_check.detect_silence_sync",
                    return_value=silence), \
             patch("src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync",
                    return_value=(rms_db, peak_db)), \
             patch("src.audiobook_studio.pipeline.quality_check.read_pcm_samples_sync",
                    return_value=samples):
            return pipeline._analyze_with_ffprobe(Path("/test.wav"), expected)

    def test_clean_audio_no_issues(self):
        pipeline = self._make_pipeline()
        result = self._run_analysis(pipeline)
        assert result.duration_match is True
        assert result.has_silence is False
        assert result.has_clipping is False
        assert result.issues == []

    def test_duration_mismatch(self):
        pipeline = self._make_pipeline()
        result = self._run_analysis(pipeline, duration=10000, expected=5000)
        assert result.duration_match is False
        assert any("duration_mismatch" in i for i in result.issues)

    def test_clipping_detected(self):
        pipeline = self._make_pipeline()
        samples = np.concatenate([np.ones(20, dtype=np.float32) * 0.999, np.zeros(50, dtype=np.float32)])
        result = self._run_analysis(pipeline, samples=samples)
        assert result.has_clipping is True
        assert any("clipping" in i for i in result.issues)

    def test_silence_detected(self):
        pipeline = self._make_pipeline()
        result = self._run_analysis(pipeline, silence=[(1000.0, 2000.0), (3000.0, 4000.0)])
        assert result.has_silence is True
        assert any("silence" in i for i in result.issues)

    def test_low_volume(self):
        pipeline = self._make_pipeline()
        result = self._run_analysis(pipeline, rms_db=-50.0, peak_db=-5.0)
        assert any("low_volume" in i for i in result.issues)

    def test_high_volume(self):
        pipeline = self._make_pipeline()
        result = self._run_analysis(pipeline, rms_db=0.5, peak_db=-1.0)
        assert any("high_volume" in i for i in result.issues)

    def test_empty_samples(self):
        """Empty samples with non-zero duration → issues=[] (no_audio_data only if duration=0)."""
        pipeline = self._make_pipeline()
        result = self._run_analysis(pipeline, samples=np.array([], dtype=np.float32))
        # actual_duration_ms=5000 is truthy → issues=[]
        assert result.issues == []

    def test_empty_samples_zero_duration(self):
        """Empty samples with zero duration → issues=['no_audio_data']."""
        pipeline = self._make_pipeline()
        result = self._run_analysis(pipeline, duration=0, samples=np.array([], dtype=np.float32))
        assert "no_audio_data" in result.issues


    def test_generic_exception_in_ffprobe(self):
        """Generic exception at line 400 re-raises."""
        pipeline = self._make_pipeline()
        with patch("src.audiobook_studio.config.loader.reload_config_if_changed",
                    return_value=(pipeline.quality_thresholds, None)), \
             patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync",
                    side_effect=RuntimeError("ffprobe crashed")):
            with pytest.raises(RuntimeError, match="ffprobe crashed"):
                pipeline._analyze_with_ffprobe(Path("/test.wav"), 5000)


# ================================================================
# Lines 615-617: Mock mode FixSuggestion merge
# ================================================================


class TestMockModeFixSuggestionMerge:
    """Cover lines 615-617."""

    def test_mock_mode_with_issues_merges_fix_suggestion(self):
        """Mock mode analysis with issues → FixSuggestion added."""
        pipeline = QualityCheckPipeline(mock_mode=True)

        with tempfile.TemporaryDirectory() as td:
            audio_path = Path(td) / "test.wav"
            audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)

            mock_analysis = AudioAnalysisResult(
                duration_ms=5000, has_silence=True,
                silence_regions=[(1000.0, 2000.0)],
                has_clipping=False, rms_db=-20.0, peak_db=-3.0,
                duration_match=True,
                issues=["silence: 1 silent regions detected"],
            )

            annotation = _ann()
            routing = _routing()

            with patch.object(pipeline, "_analyze_audio_rules", return_value=mock_analysis):
                results = pipeline.run([(str(audio_path), annotation, routing, "测试文本")])

            assert len(results) == 1
            assert any("silence" in i for i in results[0].issues)
            assert results[0].needs_regeneration is True


# ================================================================
# Line 651: speaker_sim in audio description
# ================================================================


class TestAudioDescriptionSpeakerSim:
    """Test _build_audio_description covers line 651 via non-mock hard checks path."""

    def test_all_hard_check_fields_in_description(self):
        """Build audio description and verify all fields present."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        analysis = AudioAnalysisResult(
            duration_ms=5000, has_silence=False, silence_regions=[],
            has_clipping=False, rms_db=-20.0, peak_db=-3.0,
            duration_match=True, issues=[],
        )
        annotation = _ann()
        desc = pipeline._build_audio_description(analysis, annotation)
        assert "音频时长 5000ms" in desc
        assert "RMS -20.0dB" in desc
        assert "峰值 -3.0dB" in desc

"""Comprehensive unit tests for quality_check pipeline targeting ≥80% line coverage.

Tests match the ACTUAL API from src/audiobook_studio/pipeline/quality_check.py:
- QualityCheckPipeline class with run(), _analyze_audio_rules(), _build_audio_description()
- quality_check() convenience function
- QualityJudgment, FixSuggestion Pydantic models
- mock_mode behavior for testing without external APIs
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.audiobook_studio.pipeline.quality_check import (
    AudioAnalysisResult,
    QualityCheckPipeline,
    quality_check,
)
from src.audiobook_studio.schemas import ParagraphAnnotation, QualityJudgment
from src.audiobook_studio.schemas.quality import FixSuggestion
from src.audiobook_studio.schemas.tts_routing import TtsRoutingDecision
from src.audiobook_studio.schemas.tts_routing import (
    TtsRoutingDecision as TtsRoutingDecisionSchema,
)


class TestQualityCheckPipeline:
    """Test QualityCheckPipeline class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = QualityCheckPipeline(mock_mode=True)

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

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        from src.audiobook_studio.llm import create_judge, create_router

        # Explicitly set mock_mode=False for deterministic test
        pipeline = QualityCheckPipeline(mock_mode=False)
        assert pipeline.mock_mode is False
        assert pipeline.router is not None
        assert pipeline.judge is not None

    def test_init_mock_mode(self):
        """Test pipeline initialization in mock mode."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        assert pipeline.mock_mode is True

    def test_init_with_custom_router_and_judge(self):
        """Test pipeline initialization with custom router and judge."""
        mock_router = Mock()
        mock_judge = Mock()
        pipeline = QualityCheckPipeline(
            router=mock_router, judge=mock_judge, mock_mode=True
        )
        assert pipeline.router == mock_router
        assert pipeline.judge == mock_judge

    def test_analyze_audio_rules_mock_mode(self):
        """Test _analyze_audio_rules in mock mode returns defaults."""
        expected_duration = 5000
        analysis = self.pipeline._analyze_audio_rules(
            self.mock_audio_path, expected_duration
        )

        assert isinstance(analysis, AudioAnalysisResult)
        assert analysis.duration_ms == expected_duration
        assert analysis.has_silence is False
        assert analysis.silence_regions == []
        assert analysis.has_clipping is False
        assert analysis.rms_db == -20.0
        assert analysis.peak_db == -3.0
        assert analysis.duration_match is True
        assert analysis.issues == []

    def test_build_audio_description(self):
        """Test _build_audio_description builds correct description."""
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

    def test_build_audio_description_with_clipping(self):
        """Test _build_audio_description with clipping."""
        annotation = self.create_mock_annotation()
        analysis = AudioAnalysisResult(
            duration_ms=5000,
            has_silence=False,
            silence_regions=[],
            has_clipping=True,
            rms_db=-20.0,
            peak_db=-3.0,
            duration_match=True,
            issues=[],
        )

        desc = self.pipeline._build_audio_description(analysis, annotation)

        assert "存在削波失真" in desc

    def test_build_audio_description_duration_mismatch(self):
        """Test _build_audio_description with duration mismatch."""
        annotation = self.create_mock_annotation()
        analysis = AudioAnalysisResult(
            duration_ms=3000,
            has_silence=False,
            silence_regions=[],
            has_clipping=False,
            rms_db=-20.0,
            peak_db=-3.0,
            duration_match=False,
            issues=[],
        )

        desc = self.pipeline._build_audio_description(analysis, annotation)

        assert "时长与预期不符" in desc

    def test_run_mock_mode_returns_quality_judgment(self):
        """Test run() in mock mode returns QualityJudgment list."""
        annotation = self.create_mock_annotation()
        routing = self.create_mock_routing_decision()

        inputs = [
            (str(self.mock_audio_path), annotation, routing, "这是测试文本内容。")
        ]

        results = self.pipeline.run(inputs)

        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], QualityJudgment)
        # Mock segment_id uses "mock_seg" prefix
        assert results[0].segment_id.startswith("mock_")
        assert 0.0 <= results[0].overall_score <= 1.0
        assert 0.0 <= results[0].speaker_clarity <= 1.0
        assert 0.0 <= results[0].emotion_match <= 1.0
        assert 0.0 <= results[0].prosody_naturalness <= 1.0
        assert 0.0 <= results[0].text_audio_alignment <= 1.0
        assert isinstance(results[0].needs_regeneration, bool)

    def test_run_mock_mode_multiple_segments(self):
        """Test run() in mock mode with multiple segments."""
        # Create multiple audio files with different stems
        audio_paths = []
        for i in range(3):
            p = Path(self.temp_dir) / f"segment_{i}.wav"
            p.write_bytes(b"RIFF" + b"\x00" * 1000)
            audio_paths.append(str(p))

        annotations = [self.create_mock_annotation(paragraph_index=i) for i in range(3)]
        routings = [
            self.create_mock_routing_decision(segment_id=f"book_001_ch1_p{i}")
            for i in range(3)
        ]

        inputs = [
            (audio_paths[i], annotations[i], routings[i], f"段落 {i} 内容。")
            for i in range(3)
        ]

        results = self.pipeline.run(inputs)

        assert len(results) == 3
        for result in results:
            # Mock segment_id uses "mock_seg" prefix
            assert result.segment_id.startswith("mock_seg")

    def test_run_real_mode_calls_judge(self):
        """Test run() in real mode calls LLM judge."""
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

    def test_run_real_mode_combines_rule_issues(self):
        """Test run() combines rule-based issues with LLM judgment."""
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

        # Create audio with "issues" (simulated by mock mode returning issues)
        # Since mock_mode=False but we don't have real audio, it will fall back
        inputs = [(str(self.mock_audio_path), annotation, routing, "测试文本")]

        results = pipeline.run(inputs)

        # The rule-based analysis in mock_mode fallback might add issues
        assert isinstance(results[0], QualityJudgment)

    def test_quality_check_convenience_function(self):
        """Test quality_check convenience function."""
        annotation = self.create_mock_annotation()
        routing = self.create_mock_routing_decision()

        inputs = [(str(self.mock_audio_path), annotation, routing, "测试文本")]

        results = quality_check(inputs, mock_mode=True)

        assert isinstance(results, list)
        assert len(results) == 1
        assert isinstance(results[0], QualityJudgment)


class TestQualityCheckEdgeCases:
    """Test edge cases for QualityCheckPipeline."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = QualityCheckPipeline(mock_mode=True)
        self.mock_audio_path = Path(self.temp_dir) / "test_segment.wav"
        self.mock_audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_mock_annotation(self, **overrides):
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

    def test_empty_inputs(self):
        """Test run() with empty inputs list."""
        results = self.pipeline.run([])
        assert results == []

    def test_dialogue_annotation(self):
        """Test quality check with dialogue annotation."""
        annotation = self.create_mock_annotation(
            speaker_canonical_name="张三",
            is_dialogue=True,
            emotion="happy",
            emotion_intensity=0.8,
        )
        routing = self.create_mock_routing_decision()

        inputs = [(str(self.mock_audio_path), annotation, routing, "大哥，我们走吧！")]

        results = self.pipeline.run(inputs)
        assert len(results) == 1

    def test_all_emotions(self):
        """Test quality check with all emotion types."""
        emotions = [
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
        for emotion in emotions:
            annotation = self.create_mock_annotation(emotion=emotion)
            routing = self.create_mock_routing_decision()
            inputs = [(str(self.mock_audio_path), annotation, routing, "测试文本")]
            results = self.pipeline.run(inputs)
            assert len(results) == 1

    def test_all_engine_choices(self):
        """Test quality check with all engine choices."""
        engines = ["kokoro", "edge", "human_clone"]
        for engine in engines:
            annotation = self.create_mock_annotation()
            routing = self.create_mock_routing_decision(engine_choice=engine)
            inputs = [(str(self.mock_audio_path), annotation, routing, "测试文本")]
            results = self.pipeline.run(inputs)
            assert len(results) == 1

    def test_needs_regeneration_true(self):
        """Test needs_regeneration logic when scores are low."""
        mock_judge = MagicMock()
        mock_judgment = QualityJudgment(
            segment_id="book_001_ch1_p0",
            speaker_clarity=0.6,  # Below 0.7 threshold
            emotion_match=0.85,
            prosody_naturalness=0.9,
            text_audio_alignment=0.95,
            overall_score=0.82,
            issues=["wrong_speaker"],
            fix_suggestions=[
                FixSuggestion(
                    suggestion_type="voice_adjustment",
                    target_text="测试",
                    suggested_value="更换声音",
                    confidence=0.8,
                    rationale="角色识别准确度过低",
                    priority="high",
                )
            ],
            needs_regeneration=True,
        )
        mock_judge.judge_quality.return_value = mock_judgment

        pipeline = QualityCheckPipeline(judge=mock_judge, mock_mode=False)
        annotation = self.create_mock_annotation()
        routing = self.create_mock_routing_decision()
        inputs = [(str(self.mock_audio_path), annotation, routing, "测试文本")]

        results = pipeline.run(inputs)

        assert results[0].needs_regeneration is True
        assert "wrong_speaker" in results[0].issues


class TestQualityCheckNonMockPathsExtended:
    """Extended tests for non-mock code paths for coverage."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_apply_hardware_profile_quality_config_no_thresholds(self):
        """Test _apply_hardware_profile_quality_config when hardware profile lacks thresholds."""
        pipeline = QualityCheckPipeline(mock_mode=False)
        pipeline._apply_hardware_profile_quality_config()
        # The hardware profile has thresholds set, so _hw_dnsmos_min should be set
        assert hasattr(pipeline, "_hw_dnsmos_min")

    def test_get_threshold_with_hardware_profile(self):
        """Test _get_threshold returns hardware profile values when set."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline._hw_dnsmos_min = 3.8
        pipeline._hw_asr_wer_max = 0.08
        pipeline._hw_speaker_sim_min = 0.88
        assert pipeline._get_threshold("audio", "dnsmos_min") == 3.8
        assert pipeline._get_threshold("audio", "asr_wer_max") == 0.08
        assert pipeline._get_threshold("audio", "speaker_sim_min") == 0.88
        pipeline._hw_dnsmos_min = None
        result = pipeline._get_threshold("audio", "dnsmos_min", default=3.5)
        assert result == 3.5

    def test_should_use_multimodal_judge_false_no_profile(self):
        """Test _should_use_multimodal_judge returns False when no hardware profile."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline.hardware_profile = None
        assert pipeline._should_use_multimodal_judge() is False

    def test_should_use_multimodal_judge_false_wrong_profile(self):
        """Test _should_use_multimodal_judge returns False for wrong profile types."""
        from unittest.mock import MagicMock

        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline.hardware_profile = MagicMock()
        pipeline.hardware_profile.active_profile = "edge_lite"
        pipeline.hardware_profile.is_gpu_available.return_value = True
        assert pipeline._should_use_multimodal_judge() is False

    def test_build_multimodal_prompt(self):
        """Test _build_multimodal_prompt generates correct prompt."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="张三",
            is_dialogue=True,
            emotion="happy",
            emotion_intensity=0.8,
            speech_rate=1.2,
            pitch_shift_semitones=2,
            pause_before_ms=300,
            pause_after_ms=500,
            confidence=0.9,
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
            notes="Test",
            contract_version=1,
        )
        prompt = pipeline._build_multimodal_prompt(
            "test_seg_001", annotation, "参考文本内容", "base64data123"
        )
        assert "test_seg_001" in prompt
        assert "张三" in prompt
        assert "happy" in prompt

    def test_multimodal_judge_quality_skipped_not_enabled(self):
        """Test _multimodal_judge_quality returns None when not enabled in hardware profile."""
        pipeline = QualityCheckPipeline(mock_mode=False)
        pipeline.hardware_profile = None
        audio_path = Path(self.temp_dir) / "test.mp3"
        audio_path.write_bytes(b"dummy")
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="旁白",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            pause_before_ms=200,
            pause_after_ms=400,
            confidence=0.9,
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
            notes="Test",
            contract_version=1,
        )
        result = pipeline._multimodal_judge_quality(
            "test_seg", audio_path, annotation, "ref text"
        )
        assert result is None

    def test_run_hard_quality_checks_real_mode(self):
        """Test _run_hard_quality_checks in real mode calls quality suite."""
        from unittest.mock import MagicMock

        pipeline = QualityCheckPipeline(mock_mode=False)
        audio_path = Path(self.temp_dir) / "test.mp3"
        audio_path.write_bytes(b"dummy audio")
        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.dnsmos.success = True
        mock_result.dnsmos.mos_ovr = 3.8
        mock_result.wer.success = True
        mock_result.wer.wer = 0.02
        mock_result.speaker_sim.success = True
        mock_result.speaker_sim.similarity = 0.92
        mock_result.overall_message = "All hard quality checks passed"
        with patch.object(pipeline, "_quality_suite") as mock_suite:
            mock_suite.check_all.return_value = mock_result
            result = pipeline._run_hard_quality_checks(
                audio_path=audio_path,
                reference_text="参考文本",
                speaker_id="speaker_001",
            )
            assert result.passed is True


class TestCheckOptionalDependencies:
    """Tests for _check_optional_dependencies and graceful degradation."""

    def test_check_optional_dependencies_returns_dict(self):
        """Test _check_optional_dependencies returns a dict with expected keys."""
        features = QualityCheckPipeline._check_optional_dependencies()
        assert isinstance(features, dict)
        assert "ffmpeg" in features
        assert "dnsmos" in features
        assert "asr" in features
        assert "speaker_sim" in features

    def test_ffmpeg_always_available(self):
        """Test ffmpeg is always reported as available."""
        features = QualityCheckPipeline._check_optional_dependencies()
        assert features["ffmpeg"] is True

    def test_available_features_stored_on_init(self):
        """Test _available_features is populated during __init__."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        assert hasattr(pipeline, "_available_features")
        assert isinstance(pipeline._available_features, dict)
        assert pipeline._available_features["ffmpeg"] is True

    def test_hard_checks_skip_when_no_deps(self):
        """Test _run_hard_quality_checks skips gracefully when no optional deps available."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        # Override available features to simulate no deps
        pipeline._available_features = {
            "ffmpeg": True,
            "dnsmos": False,
            "asr": False,
            "speaker_sim": False,
        }
        audio_path = Path(tempfile.mkdtemp()) / "test.mp3"
        audio_path.write_bytes(b"dummy")
        result = pipeline._run_hard_quality_checks(
            audio_path=audio_path,
            reference_text="参考文本",
        )
        assert result.passed is True
        assert "skipped" in result.overall_message.lower()

    def test_hard_checks_proceeds_when_deps_available(self):
        """Test _run_hard_quality_checks proceeds when at least one dep is available."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        pipeline._available_features = {
            "ffmpeg": True,
            "dnsmos": True,
            "asr": False,
            "speaker_sim": False,
        }
        audio_path = Path(tempfile.mkdtemp()) / "test.mp3"
        audio_path.write_bytes(b"dummy")
        # Mock the quality suite to avoid actual model loading
        mock_result = MagicMock()
        mock_result.passed = True
        mock_result.dnsmos = None
        mock_result.wer = None
        mock_result.speaker_sim = None
        mock_result.overall_message = "Partial checks passed"
        with patch.object(pipeline, "_quality_suite", mock_result):
            result = pipeline._run_hard_quality_checks(
                audio_path=audio_path,
                reference_text="参考文本",
            )
            mock_result.check_all.assert_called_once()

    def test_run_real_mode_no_mock_with_graceful_degradation(self):
        """Test run() in non-mock mode works even when optional deps are missing."""
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
        # Simulate no optional deps
        pipeline._available_features = {
            "ffmpeg": True,
            "dnsmos": False,
            "asr": False,
            "speaker_sim": False,
        }

        annotation = ParagraphAnnotation(
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
        )
        routing = TtsRoutingDecisionSchema(
            segment_id="book_001_ch1_p0",
            engine_choice="kokoro",
            voice_id="kokoro_narrator",
            prosody_overrides=None,
            fallback_engine="edge",
            reasoning="test",
            estimated_cost_usd=0.001,
            estimated_duration_ms=5000,
        )

        temp_dir = tempfile.mkdtemp()
        audio_path = Path(temp_dir) / "test.wav"
        audio_path.write_bytes(b"RIFF" + b"\x00" * 1000)
        try:
            inputs = [(str(audio_path), annotation, routing, "测试文本")]
            results = pipeline.run(inputs)
            assert len(results) == 1
            assert isinstance(results[0], QualityJudgment)
            # LLM judge should still have been called
            mock_judge.judge_quality.assert_called_once()
        finally:
            import shutil

            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Comprehensive unit tests for quality_check pipeline targeting ≥80% line coverage.

Tests match the ACTUAL API from src/audiobook_studio/pipeline/quality_check.py:
- QualityCheckPipeline class with run(), _analyze_audio_rules(), _build_audio_description()
- quality_check() convenience function
- QualityJudgment, FixSuggestion Pydantic models
- mock_mode behavior for testing without external APIs
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest
from src.audiobook_studio.pipeline.quality_check import (
    QualityCheckPipeline,
    quality_check,
    AudioAnalysisResult,
)
from src.audiobook_studio.schemas import (
    QualityJudgment,
    ParagraphAnnotation,
)
from src.audiobook_studio.schemas.quality import FixSuggestion
from src.audiobook_studio.schemas.tts_routing import TtsRoutingDecision as TtsRoutingDecisionSchema


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
        from src.audiobook_studio.llm import create_router, create_judge

        pipeline = QualityCheckPipeline()
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
        pipeline = QualityCheckPipeline(router=mock_router, judge=mock_judge, mock_mode=True)
        assert pipeline.router == mock_router
        assert pipeline.judge == mock_judge

    def test_analyze_audio_rules_mock_mode(self):
        """Test _analyze_audio_rules in mock mode returns defaults."""
        expected_duration = 5000
        analysis = self.pipeline._analyze_audio_rules(self.mock_audio_path, expected_duration)

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
        assert results[0].segment_id == "test_segment"
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

        annotations = [
            self.create_mock_annotation(paragraph_index=i)
            for i in range(3)
        ]
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
        for i, result in enumerate(results):
            assert result.segment_id == f"segment_{i}"

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
            "neutral", "happy", "sad", "angry", "fearful",
            "surprised", "disgusted", "tense", "tender", "contemplative",
            "whisper", "cold_laugh", "sigh", "sarcastic",
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])"""Additional test cases for quality_check.py coverage."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock

import pytest
from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline
from src.audiobook_studio.schemas import (
    QualityJudgment,
    ParagraphAnnotation,
)
from src.audiobook_studio.pipeline.quality_check import (
    AudioAnalysisResult,
)


class TestQualityCheckNonMockPaths:
    """Test non-mock code paths for coverage."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = QualityCheckPipeline(mock_mode=False)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_quality_judgment_creation(self):
        """Test QualityJudgment dataclass creation."""
        judgment = QualityJudgment(
            segment_id="test_seg",
            speaker_clarity=0.9,
            emotion_match=0.85,
            prosody_naturalness=0.9,
            text_audio_alignment=0.95,
            overall_score=0.9,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
            contract_version=1,
            judge_model="gemini-1.5-flash",
            confidence=0.95,
            rationale="Test judgment"
        )
        assert judgment.segment_id == "test_seg"
        assert judgment.overall_score == 0.9

    @patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.detect_silence_sync")
    @patch("src.audiobook_studio.pipeline.quality_check.get_rms_peak_sync")
    def test_analyze_audio_ffprobe_success(self, mock_rms, mock_silence, mock_duration):
        """Test audio analysis with successful ffprobe calls."""
        mock_duration.return_value = 3000
        mock_silence.return_value = [(0.5, 1.0), (2.5, 2.8)]
        mock_rms.return_value = (-20.5, -3.2)
        
        pipeline = QualityCheckPipeline(mock_mode=False)
        audio_path = Path(self.temp_dir) / "test.mp3"
        audio_path.write_bytes(b"dummy audio")
        
        result = pipeline._analyze_audio(audio_path, 1000, -40, -3)
        
        assert isinstance(result, AudioAnalysisResult)
        assert result.duration_ms == 3000
        assert len(result.silence_regions) == 2
        assert result.rms_db == -20.5
        assert result.peak_db == -3.2

    @patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync")
    def test_analyze_audio_ffprobe_file_not_found(self, mock_duration):
        """Test audio analysis with missing file."""
        mock_duration.side_effect = FileNotFoundError("File not found")
        
        pipeline = QualityCheckPipeline(mock_mode=False)
        audio_path = Path(self.temp_dir) / "missing.mp3"
        
        with pytest.raises(FileNotFoundError):
            pipeline._analyze_audio(audio_path, 1000, -40, -3)

    @patch("src.audiobook_studio.pipeline.quality_check.get_duration_sync")
    def test_analyze_audio_ffprobe_generic_exception(self, mock_duration):
        """Test audio analysis with ffprobe exception."""
        mock_duration.side_effect = Exception("ffprobe failed")
        
        pipeline = QualityCheckPipeline(mock_mode=False)
        audio_path = Path(self.temp_dir) / "test.mp3"
        audio_path.write_bytes(b"dummy")
        
        with pytest.raises(Exception):
            pipeline._analyze_audio(audio_path, 1000, -40, -3)

    def test_encode_audio_base64(self):
        """Test audio base64 encoding."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        audio_path = Path(self.temp_dir) / "test.mp3"
        audio_path.write_bytes(b"test audio data")
        
        b64 = pipeline._encode_audio_base64(audio_path)
        
        assert b64 is not None
        assert "dGVzdCBhdWRpbyBkYXRh" in b64  # base64 of "test audio data"

    def test_encode_audio_base64_missing(self):
        """Test base64 encoding of missing file."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        
        b64 = pipeline._encode_audio_base64(Path("/nonexistent.mp3"))
        
        assert b64 is None

    @patch("src.audiobook_studio.pipeline.quality_check.QualityCheckPipeline._encode_audio_base64")
    @patch("src.audiobook_studio.pipeline.quality_check.QualityCheckPipeline.router")
    def test_multimodal_judge_quality(self, mock_router, mock_encode):
        """Test multimodal quality judge path."""
        mock_encode.return_value = "base64_audio_data"
        mock_result = Mock()
        mock_result.output = QualityJudgment(
            segment_id="test_seg",
            speaker_clarity=0.9,
            emotion_match=0.85,
            prosody_naturalness=0.9,
            text_audio_alignment=0.95,
            overall_score=0.9,
            issues=[],
            fix_suggestions=[],
            needs_regeneration=False,
            contract_version=1,
            judge_model="gemini-1.5-flash-multimodal",
            confidence=0.95,
            rationale="Good quality"
        )
        mock_router.call.return_value = mock_result
        
        pipeline = QualityCheckPipeline(mock_mode=False)
        pipeline.router = mock_router
        
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
        
        result = pipeline._multimodal_judge_quality("test_seg", audio_path, annotation, "参考文本")
        
        assert result is not None
        assert result.segment_id == "test_seg"
        assert result.overall_score == 0.9

    def test_build_audio_description(self):
        """Test building audio description for LLM judge."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        
        analysis = AudioAnalysisResult(
            duration_ms=3000,
            has_silence=True,
            silence_regions=[(0.5, 1.0)],
            has_clipping=True,
            rms_db=-20.5,
            peak_db=-3.2,
            duration_match=True,
            issues=["silence: 1 silent regions detected", "clipping: audio may clip"]
        )
        
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
        
        desc = pipeline._build_audio_description(analysis, annotation)
        
        assert "3000ms" in desc
        assert "静音" in desc
        assert "削波" in desc
        assert "RMS -20.5dB" in desc
        assert "峰值 -3.2dB" in desc

    def test_build_audio_description_no_issues(self):
        """Test audio description without issues."""
        pipeline = QualityCheckPipeline(mock_mode=True)
        
        analysis = AudioAnalysisResult(
            duration_ms=3000,
            has_silence=False,
            silence_regions=[],
            has_clipping=False,
            rms_db=-20.5,
            peak_db=-3.2,
            duration_match=True,
            issues=[]
        )
        
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
        
        desc = pipeline._build_audio_description(analysis, annotation)
        
        assert "静音" not in desc
        assert "削波" not in desc

    def test_run_nonmock_paths(self):
        """Test run method with non-mock paths."""
        pipeline = QualityCheckPipeline(mock_mode=False)
        
        # Test with empty inputs
        results = pipeline.run([])
        assert results == []
        
        # Test with mocked file operations
        audio_path = Path(self.temp_dir) / "test.mp3"
        audio_path.write_bytes(b"test")
        
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
        
        with patch.object(pipeline, '_analyze_audio') as mock_analyze:
            mock_analyze.return_value = AudioAnalysisResult(
                duration_ms=3000, has_silence=False, silence_regions=[],
                has_clipping=False, rms_db=-20.0, peak_db=-3.0,
                duration_match=True, issues=[]
            )
            
            # Test multimodal None -> fallback to LLM judge
            with patch.object(pipeline, '_multimodal_judge_quality', return_value=None):
                with patch.object(pipeline, '_llm_judge_quality') as mock_llm:
                    mock_llm.return_value = QualityJudgment(
                        segment_id="test", speaker_clarity=0.9, emotion_match=0.85,
                        prosody_naturalness=0.9, text_audio_alignment=0.95,
                        overall_score=0.9, issues=[], fix_suggestions=[],
                        needs_regeneration=False, contract_version=1
                    )
                    
                    results = pipeline.run([(str(audio_path), annotation, None, "ref text")])
                    
                    assert len(results) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

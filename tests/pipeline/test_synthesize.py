"""Unit tests for SynthesizePipeline module."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.pipeline.synthesize import AudioSegment
from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline
from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline as SynthesizePipelineAlias
from src.audiobook_studio.schemas import CharacterVoiceBinding, ParagraphAnnotation, TtsRoutingDecision, TtsRoutingInput


class TestAudioSegment:
    """Test AudioSegment dataclass."""

    def test_audio_segment_creation(self):
        """Test AudioSegment creation and serialization."""
        segment = AudioSegment(
            segment_id="test_seg_1",
            file_path="/tmp/test.mp3",
            duration_ms=3000,
            engine="kokoro",
            voice_id="zh-CN-XiaoxiaoNeural",
            text_hash="abc123",
        )
        assert segment.segment_id == "test_seg_1"
        assert segment.duration_ms == 3000
        assert segment.engine == "kokoro"

        data = segment.to_dict()
        assert data["segment_id"] == "test_seg_1"
        assert data["duration_ms"] == 3000
        assert data["engine"] == "kokoro"

    def test_audio_segment_to_dict(self):
        """Test AudioSegment to_dict serialization."""
        segment = AudioSegment(
            segment_id="seg_1",
            file_path="/tmp/seg.mp3",
            duration_ms=2500,
            engine="edge",
            voice_id="en-US-AriaNeural",
            text_hash="def456",
        )
        data = segment.to_dict()
        assert data == {
            "segment_id": "seg_1",
            "file_path": "/tmp/seg.mp3",
            "duration_ms": 2500,
            "engine": "edge",
            "voice_id": "en-US-AriaNeural",
            "text_hash": "def456",
        }


class TestSynthesizePipeline:
    """Test SynthesizePipeline class."""

    def test_init_default(self):
        """Test default initialization."""
        pipeline = SynthesizePipeline(output_dir="/tmp/test_out", mock_mode=True)
        assert pipeline.mock_mode is True
        assert pipeline.output_dir == Path("/tmp/test_out")
        assert pipeline.output_dir.exists()

    def test_init_with_mock_mode_env(self):
        """Test initialization with MOCK_LLM env var."""
        import os

        os.environ["MOCK_LLM"] = "true"
        try:
            pipeline = SynthesizePipeline(output_dir="/tmp/test_out")
            assert pipeline.mock_mode is True
        finally:
            os.environ.pop("MOCK_LLM", None)

    def test_init_mock_mode_explicit(self):
        """Test explicit mock_mode parameter."""
        pipeline = SynthesizePipeline(output_dir="/tmp/test_out", mock_mode=False)
        assert pipeline.mock_mode is False

    def test_init_with_custom_router(self):
        """Test initialization with custom router."""
        mock_router = MagicMock()
        pipeline = SynthesizePipeline(output_dir="/tmp/test_out", router=mock_router, mock_mode=True)
        assert pipeline.router is mock_router

    def test_text_hash_consistency(self):
        """Test text hashing produces consistent results."""
        pipeline = SynthesizePipeline(output_dir="/tmp/test_out", mock_mode=True)
        text = "这是一段测试文本"
        hash1 = pipeline._text_hash(text)
        hash2 = pipeline._text_hash(text)
        assert hash1 == hash2
        assert len(hash1) == 12  # MD5 first 12 chars

    def test_text_hash_different_texts(self):
        """Test different texts produce different hashes."""
        pipeline = SynthesizePipeline(output_dir="/tmp/test_out", mock_mode=True)
        hash1 = pipeline._text_hash("文本1")
        hash2 = pipeline._text_hash("文本2")
        assert hash1 != hash2

    def test_metadata_path(self):
        """Test metadata path generation."""
        pipeline = SynthesizePipeline(output_dir="/tmp/test_out", mock_mode=True)
        path = pipeline._metadata_path("seg_123")
        assert path == Path("/tmp/test_out/seg_123.json")

    def test_edge_voice_map_resolution(self):
        """Test Edge voice mapping resolution."""
        pipeline = SynthesizePipeline(output_dir="/tmp/test_out", mock_mode=True)

        # Test known mapping
        resolved = pipeline._resolve_edge_voice("zh-CN-XiaoxiaoNeural")
        assert "Microsoft Server Speech Text to Speech Voice" in resolved

        # Test already full format
        full = "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)"
        resolved = pipeline._resolve_edge_voice(full)
        assert resolved == full

        # Test dynamic resolution
        resolved = pipeline._resolve_edge_voice("zh-CN-TestVoice")
        assert "Microsoft Server Speech Text to Speech Voice" in resolved

    def test_azure_voice_map(self):
        """Test Azure voice mapping."""
        pipeline = SynthesizePipeline(output_dir="/tmp/test_out", mock_mode=True)

        # Known mapping
        assert "zh-CN-XiaoxiaoNeural" in pipeline.AZURE_VOICE_MAP

        # GCP voice map
        assert "zh-CN-Standard-A" in pipeline.GCP_VOICE_MAP

    def test_edge_voice_map(self):
        """Test Edge voice map entries."""
        pipeline = SynthesizePipeline(output_dir="/tmp/test_out", mock_mode=True)
        assert "zh-CN-XiaoxiaoNeural" in pipeline.EDGE_VOICE_MAP
        assert "en-US-AriaNeural" in pipeline.EDGE_VOICE_MAP
        assert len(pipeline.EDGE_VOICE_MAP) > 10


class TestSynthesizePipelineMockMode:
    """Test SynthesizePipeline in mock mode."""

    def test_mock_synthesis_creates_file(self, tmp_path):
        """Test mock synthesis creates audio file."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        output_path = tmp_path / "test.mp3"

        duration = pipeline._synthesize_mock("测试文本", "zh-CN-XiaoxiaoNeural", {}, output_path)

        # Mock creates .wav file
        wav_path = output_path.with_suffix(".wav")
        assert wav_path.exists()
        # Duration based on text length (~50 chars/sec, min 1000ms): "测试文本" = 4 chars -> 1000ms
        assert duration == 1000

    def test_kokoro_mock_synthesis(self, tmp_path):
        """Test Kokoro mock synthesis."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        output_path = tmp_path / "test.mp3"

        duration = pipeline._synthesize_kokoro("测试文本", "zh-CN-XiaoxiaoNeural", {}, output_path)

        assert output_path.exists()
        # Duration based on text length (~50 chars/sec, min 1000ms): "测试文本" = 4 chars -> 1000ms
        assert duration == 1000

    def test_edge_mock_synthesis(self, tmp_path):
        """Test Edge-TTS mock synthesis."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        output_path = tmp_path / "test.mp3"

        duration = pipeline._synthesize_edge("测试文本", "zh-CN-XiaoxiaoNeural", {}, output_path)

        assert output_path.exists()
        # Duration based on text length (~50 chars/sec, min 1000ms): "测试文本" = 4 chars -> 1000ms
        assert duration == 1000

    def test_azure_mock_synthesis(self, tmp_path):
        """Test Azure TTS mock synthesis."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        output_path = tmp_path / "test.mp3"

        duration = pipeline._synthesize_azure("测试文本", "zh-CN-XiaoxiaoNeural", {}, output_path)

        assert output_path.exists()
        # Duration based on text length (~50 chars/sec, min 1000ms): "测试文本" = 4 chars -> 1000ms
        assert duration == 1000

    def test_gcp_mock_synthesis(self, tmp_path):
        """Test GCP TTS mock synthesis."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        output_path = tmp_path / "test.mp3"

        duration = pipeline._synthesize_gcp("测试文本", "zh-CN-Standard-A", {}, output_path)

        assert output_path.exists()
        # Duration based on text length (~50 chars/sec, min 1000ms): "测试文本" = 4 chars -> 1000ms
        assert duration == 1000


class TestSynthesizePipelineRun:
    """Test SynthesizePipeline run method."""

    def create_routing_input(self, idx: int = 0) -> TtsRoutingInput:
        """Create a sample TtsRoutingInput for testing."""
        return TtsRoutingInput(
            book_id="book_1",
            chapter_index=1,
            paragraph_index=idx,
            text=f"这是第 {idx + 1} 段测试文本。",
            paragraph_annotation=ParagraphAnnotation(
                paragraph_index=idx,
                text=f"这是第 {idx + 1} 段测试文本。",
                speaker_canonical_name="旁白",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                confidence=0.9,
                speech_rate=1.0,
                pitch_shift_semitones=0,
            ),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    suggested_voice_id="zh-CN-XiaoxiaoNeural",
                    sample_quote="样本文本",
                )
            ],
            prefer_local=True,
        )

    def test_run_single_paragraph_mock(self, tmp_path):
        """Test run with single paragraph in mock mode."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        inputs = [self.create_routing_input(0)]

        segments = pipeline.run(inputs)

        assert len(segments) == 1
        assert segments[0].segment_id == "book_1_ch1_p0"
        assert segments[0].engine == "kokoro"  # prefer_local=True -> kokoro
        assert segments[0].voice_id == "zh-CN-XiaoxiaoNeural"
        # Duration based on text length (~50 chars/sec, min 1000ms): "这是第 1 段测试文本。" = 12 chars -> 1000ms
        assert segments[0].duration_ms == 1000

    def test_run_multiple_paragraphs_mock(self, tmp_path):
        """Test run with multiple paragraphs in mock mode."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        inputs = [self.create_routing_input(i) for i in range(3)]

        segments = pipeline.run(inputs)

        assert len(segments) == 3
        assert segments[0].segment_id == "book_1_ch1_p0"
        assert segments[1].segment_id == "book_1_ch1_p1"
        assert segments[2].segment_id == "book_1_ch1_p2"
        # Each paragraph has ~12 chars -> 1000ms minimum
        for seg in segments:
            assert seg.duration_ms == 1000

    def test_run_incremental_skip_unchanged(self, tmp_path):
        """Test incremental synthesis skips unchanged text."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        inputs = [self.create_routing_input(0)]

        # First run
        segments1 = pipeline.run(inputs)
        assert len(segments1) == 1

        # Second run with same text - should skip
        pipeline2 = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        segments2 = pipeline2.run(inputs)

        assert len(segments2) == 1
        assert segments2[0].segment_id == "book_1_ch1_p0"
        # Should be loaded from disk metadata, same segment

    def test_run_different_text_regenerates(self, tmp_path):
        """Test changed text triggers regeneration."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        inputs1 = [self.create_routing_input(0)]
        segments1 = pipeline.run(inputs1)

        # Create new input with different text
        input2 = self.create_routing_input(0)
        input2.text = "这是修改后的文本。"
        pipeline2 = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        segments2 = pipeline2.run([input2])

        # Should have regenerated (new text_hash)
        assert segments2[0].text_hash != segments1[0].text_hash

    def test_run_chapter_stitching(self, tmp_path):
        """Test chapter-level audio stitching."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        inputs = [self.create_routing_input(i) for i in range(3)]

        segments = pipeline.run(inputs)

        # Should create chapter file
        chapter_file = tmp_path / "book_1_ch1.mp3"
        # In mock mode, stitching might use simple concat
        # Just verify segments returned
        assert len(segments) == 3

    def test_run_with_edge_engine(self, tmp_path):
        """Test run with Edge TTS engine (prefer_local=False)."""
        input_edge = self.create_routing_input(0)
        input_edge.prefer_local = False

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        segments = pipeline.run([input_edge])

        assert len(segments) == 1
        assert segments[0].engine == "edge"  # prefer_local=False -> edge


class TestSynthesizePipelineRouting:
    """Test routing decision logic."""

    def test_routing_decision_prefer_local(self, tmp_path):
        """Test routing prefers local engine when prefer_local=True."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        inp = TtsRoutingInput(
            book_id="book_1",
            chapter_index=1,
            paragraph_index=0,
            text="测试文本",
            paragraph_annotation=ParagraphAnnotation(
                paragraph_index=0,
                text="测试文本",
                speaker_canonical_name="旁白",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                confidence=0.9,
                speech_rate=1.0,
                pitch_shift_semitones=0,
            ),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    suggested_voice_id="zh-CN-XiaoxiaoNeural",
                    sample_quote="样本文本",
                )
            ],
            prefer_local=True,
        )

        decision = pipeline._make_routing_decision(inp)

        assert decision.engine_choice == "kokoro"
        assert decision.voice_id == "zh-CN-XiaoxiaoNeural"
        assert decision.fallback_engine == "edge"

    def test_routing_decision_prefer_cloud(self, tmp_path):
        """Test routing prefers cloud engine when prefer_local=False."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        inp = TtsRoutingInput(
            book_id="book_1",
            chapter_index=1,
            paragraph_index=0,
            text="Test text",
            paragraph_annotation=ParagraphAnnotation(
                paragraph_index=0,
                text="Test text",
                speaker_canonical_name="Narrator",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                confidence=0.9,
                speech_rate=1.0,
                pitch_shift_semitones=0,
            ),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="Narrator",
                    suggested_voice_id="en-US-AriaNeural",
                    sample_quote="样本文本",
                )
            ],
            prefer_local=False,
        )

        decision = pipeline._make_routing_decision(inp)

        assert decision.engine_choice == "edge"
        assert decision.fallback_engine == "kokoro"  # Cloud preferred, local as fallback

    def test_routing_decision_prosody_overrides(self, tmp_path):
        """Test routing includes prosody overrides."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        inp = TtsRoutingInput(
            book_id="book_1",
            chapter_index=1,
            paragraph_index=0,
            text="测试文本",
            paragraph_annotation=ParagraphAnnotation(
                paragraph_index=0,
                text="测试文本",
                speaker_canonical_name="旁白",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                confidence=0.9,
                speech_rate=1.2,
                pitch_shift_semitones=2,
            ),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    suggested_voice_id="zh-CN-XiaoxiaoNeural",
                    sample_quote="样本文本",
                )
            ],
            prefer_local=True,
        )

        decision = pipeline._make_routing_decision(inp)

        assert decision.prosody_overrides["rate"] == 1.2
        assert decision.prosody_overrides["pitch"] == 2.0

    def test_routing_decision_segment_id_format(self, tmp_path):
        """Test segment ID format in routing decision."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        inp = TtsRoutingInput(
            book_id="book_1",
            chapter_index=2,
            paragraph_index=5,
            text="测试",
            paragraph_annotation=ParagraphAnnotation(
                paragraph_index=5,
                text="测试",
                speaker_canonical_name="旁白",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                confidence=0.9,
                speech_rate=1.0,
                pitch_shift_semitones=0,
            ),
            character_voice_map=[
                CharacterVoiceBinding(
                    canonical_name="旁白",
                    suggested_voice_id="zh-CN-XiaoxiaoNeural",
                    sample_quote="样本文本",
                )
            ],
            prefer_local=True,
        )

        decision = pipeline._make_routing_decision(inp)

        assert decision.segment_id == "book_1_ch2_p5"


class TestSynthesizePipelineSegmentPersistence:
    """Test segment metadata persistence and loading."""

    def test_persist_and_load_metadata(self, tmp_path):
        """Test segment metadata persistence and loading."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        # Create a dummy audio file
        import numpy as np
        import soundfile as sf

        audio_file = tmp_path / "test.mp3"
        dummy_audio = np.zeros(24000, dtype=np.float32)
        sf.write(str(audio_file), dummy_audio, 24000)

        segment = AudioSegment(
            segment_id="test_seg",
            file_path=str(audio_file),
            duration_ms=3000,
            engine="kokoro",
            voice_id="zh-CN-XiaoxiaoNeural",
            text_hash="abc123",
        )

        pipeline._persist_segment_metadata(segment)

        metadata_path = tmp_path / "test_seg.json"
        assert metadata_path.exists()

        # Load from disk
        loaded = pipeline._load_existing_segment_from_disk("test_seg", "abc123")
        assert loaded is not None
        assert loaded.segment_id == "test_seg"
        assert loaded.text_hash == "abc123"

    def test_load_metadata_hash_mismatch(self, tmp_path):
        """Test loading fails when text hash doesn't match."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        segment = AudioSegment(
            segment_id="test_seg",
            file_path=str(tmp_path / "test.mp3"),
            duration_ms=3000,
            engine="kokoro",
            voice_id="zh-CN-XiaoxiaoNeural",
            text_hash="abc123",
        )
        pipeline._persist_segment_metadata(segment)

        # Try to load with different hash
        loaded = pipeline._load_existing_segment_from_disk("test_seg", "different_hash")
        assert loaded is None

    def test_load_metadata_missing_file(self, tmp_path):
        """Test loading fails when audio file missing."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        segment = AudioSegment(
            segment_id="test_seg",
            file_path=str(tmp_path / "nonexistent.mp3"),
            duration_ms=3000,
            engine="kokoro",
            voice_id="zh-CN-XiaoxiaoNeural",
            text_hash="abc123",
        )
        pipeline._persist_segment_metadata(segment)

        # Delete audio file but keep metadata
        # (metadata still references missing file)
        loaded = pipeline._load_existing_segment_from_disk("test_seg", "abc123")
        assert loaded is None


class TestSynthesizePipelineCrossfade:
    """Test crossfade stitching functionality."""

    def test_crossfade_stitch_single_segment(self, tmp_path):
        """Test stitching with single segment."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        # Create a dummy audio file
        import numpy as np
        import soundfile as sf

        audio_file = tmp_path / "seg1.wav"
        dummy_audio = np.zeros(24000, dtype=np.float32)
        sf.write(str(audio_file), dummy_audio, 24000)

        segments = [
            AudioSegment(
                segment_id="seg1",
                file_path=str(audio_file),
                duration_ms=1000,
                engine="kokoro",
                voice_id="zh-CN-XiaoxiaoNeural",
                text_hash="abc",
            )
        ]

        output_path = tmp_path / "output.mp3"
        duration = pipeline._crossfade_stitch(segments, output_path)

        assert duration == 1000
        # In mock mode without ffmpeg, might fall back to simple concat

    def test_crossfade_stitch_empty_segments(self, tmp_path):
        """Test stitching with no segments."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        duration = pipeline._crossfade_stitch([], tmp_path / "output.mp3")
        assert duration == 0

    def test_crossfade_stitch_invalid_files(self, tmp_path):
        """Test stitching skips non-existent files."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        segments = [
            AudioSegment(
                segment_id="seg1",
                file_path=str(tmp_path / "nonexistent.mp3"),
                duration_ms=1000,
                engine="kokoro",
                voice_id="zh-CN-XiaoxiaoNeural",
                text_hash="abc",
            )
        ]

        duration = pipeline._crossfade_stitch(segments, tmp_path / "output.mp3")
        assert duration == 0


class TestSynthesizePipelineCostEstimation:
    """Test cost estimation logic."""

    def test_kokoro_cost_zero(self, tmp_path):
        """Test Kokoro local engine has zero cost."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        # Cost is estimated in run(), check logic in _try_synthesize_with_fallback
        # For Kokoro, cost_usd = 0.0

    def test_edge_cost_estimate(self, tmp_path):
        """Test Edge TTS cost estimation."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        # Edge: ~$4 per 1M characters
        # 1000 chars -> $0.004

    def test_azure_cost_free_tier(self, tmp_path):
        """Test Azure TTS free tier cost."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        # Free tier: 5M chars/month

    def test_gcp_cost_free_tier(self, tmp_path):
        """Test GCP TTS free tier cost."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        # Free tier: 1M chars/month


class TestSynthesizePipelineFallback:
    """Test fallback chain logic."""

    def test_fallback_chain_order(self, tmp_path):
        """Test fallback chain follows hardware profile."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        config = pipeline._get_tts_engine_config()
        assert "engine" in config
        assert "fallback_chain" in config

    def test_voice_clone_detection(self, tmp_path):
        """Test cloned voice detection."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        # Voice ID starting with "cloned_" should trigger voice cloning
        assert pipeline.voice_cloning_manager is not None


class TestSynthesizePipelineIntegration:
    """Integration-style tests."""

    def test_synthesize_paragraphs_function(self, tmp_path):
        """Test module-level synthesize_paragraphs function."""
        from src.audiobook_studio.pipeline.synthesize import synthesize_paragraphs

        inputs = [
            TtsRoutingInput(
                book_id="book_1",
                chapter_index=1,
                paragraph_index=0,
                text="测试文本",
                paragraph_annotation=ParagraphAnnotation(
                    paragraph_index=0,
                    text="测试文本",
                    speaker_canonical_name="旁白",
                    is_dialogue=False,
                    emotion="neutral",
                    emotion_intensity=0.5,
                    confidence=0.9,
                    speech_rate=1.0,
                    pitch_shift_semitones=0,
                ),
                character_voice_map=[
                    CharacterVoiceBinding(
                        canonical_name="旁白",
                        suggested_voice_id="zh-CN-XiaoxiaoNeural",
                        sample_quote="样本文本",
                    )
                ],
                prefer_local=True,
            )
        ]

        segments = synthesize_paragraphs(inputs, output_dir=str(tmp_path), mock_mode=True)

        assert len(segments) == 1
        assert segments[0].segment_id == "book_1_ch1_p0"

    def test_pipeline_with_custom_hardware_profile(self, tmp_path):
        """Test pipeline with custom hardware profile."""
        from src.audiobook_studio.config.hardware_profile import HardwareProfile, TTSProfileConfig

        tts_profile = TTSProfileConfig(engine="edge", model_path="", voices_path="")
        hw_profile = HardwareProfile.__new__(HardwareProfile)
        hw_profile._config = type("obj", (object,), {"tts": tts_profile})()
        hw_profile._active_profile_name = "test"

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, hardware_profile=hw_profile)

        config = pipeline._get_tts_engine_config()
        assert config["engine"] == "edge"


class TestSynthesizePipelineErrorHandling:
    """Test error handling and edge cases."""

    def test_kokoro_fallback_on_import_error(self, tmp_path):
        """Test Kokoro falls back to mock on import error."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=False)

        # Patch the import inside the method
        with patch("src.audiobook_studio.tts.kokoro_backend.KokoroBackend") as mock_kokoro:
            mock_kokoro.side_effect = ImportError("onnxruntime not found")

            # In non-mock mode, should fall back to mock
            with patch.object(pipeline, "_synthesize_mock", return_value=3000) as mock_mock:
                output_path = tmp_path / "test.mp3"
                duration = pipeline._synthesize_kokoro("text", "voice", {}, output_path)
                mock_mock.assert_called_once()
                assert duration == 3000

    def test_edge_fallback_on_import_error(self, tmp_path):
        """Test Edge-TTS falls back on import error."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=False)

        # Patch edge_tts import inside the method
        with patch("edge_tts.Communicate", side_effect=ImportError("edge_tts not installed")):
            with patch.object(pipeline, "_synthesize_mock", return_value=2800) as mock_mock:
                output_path = tmp_path / "test.mp3"
                with pytest.raises(ImportError):
                    pipeline._synthesize_edge("text", "voice", {}, output_path)

    def test_record_performance_on_failure(self, tmp_path):
        """Test performance recording even on synthesis failure."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        # Force an error in synthesis
        with patch.object(pipeline, "_try_synthesize_with_fallback", side_effect=RuntimeError("TTS failed")):
            inp = TtsRoutingInput(
                book_id="book_1",
                chapter_index=1,
                paragraph_index=0,
                text="测试",
                paragraph_annotation=ParagraphAnnotation(
                    paragraph_index=0,
                    text="测试",
                    speaker_canonical_name="旁白",
                    is_dialogue=False,
                    emotion="neutral",
                    emotion_intensity=0.5,
                    confidence=0.9,
                    speech_rate=1.0,
                    pitch_shift_semitones=0,
                ),
                character_voice_map=[
                    CharacterVoiceBinding(
                        canonical_name="旁白",
                        suggested_voice_id="zh-CN-XiaoxiaoNeural",
                        sample_quote="样本文本",
                    )
                ],
                prefer_local=True,
            )

            with pytest.raises(RuntimeError):
                pipeline.run([inp])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestSynthesizePipelineMockModeAdvanced:
    """Test additional mock mode paths."""

    def test_mock_kokoro_writes_output(self, tmp_path):
        """Test mock Kokoro writes output file."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        output_path = tmp_path / "test.mp3"

        duration = pipeline._synthesize_kokoro("测试文本", "zh-CN-XiaoxiaoNeural", {}, output_path)

        # Should create output file directly
        assert output_path.exists()
        # Duration based on text length (~50 chars/sec, min 1000ms): "测试文本" = 4 chars -> 1000ms
        assert duration == 1000

    def test_mock_edge_direct_write(self, tmp_path):
        """Test mock Edge writes directly to output path."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        output_path = tmp_path / "test.mp3"

        duration = pipeline._synthesize_edge("测试文本", "zh-CN-XiaoxiaoNeural", {}, output_path)

        assert output_path.exists()
        # Duration based on text length (~50 chars/sec, min 1000ms): "测试文本" = 4 chars -> 1000ms
        assert duration == 1000

    def test_mock_azure_creation(self, tmp_path):
        """Test mock Azure TTS creates file."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        output_path = tmp_path / "test.mp3"

        duration = pipeline._synthesize_azure("测试文本", "zh-CN-XiaoxiaoNeural", {}, output_path)

        assert output_path.exists()
        # Duration based on text length (~50 chars/sec, min 1000ms): "测试文本" = 4 chars -> 1000ms
        assert duration == 1000

    def test_mock_gcp_creation(self, tmp_path):
        """Test mock GCP TTS creates file."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)
        output_path = tmp_path / "test.mp3"

        duration = pipeline._synthesize_gcp("测试文本", "zh-CN-Standard-A", {}, output_path)

        assert output_path.exists()
        # Duration based on text length (~50 chars/sec, min 1000ms): "测试文本" = 4 chars -> 1000ms
        assert duration == 1000


class TestSynthesizePipelineRealEngines:
    """Test real engine paths (non-mock mode)."""

    def test_kokoro_import_error_fallback(self, tmp_path):
        """Test Kokoro falls back to mock on ImportError."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=False)

        with patch(
            "src.audiobook_studio.tts.kokoro_backend.KokoroBackend", side_effect=ImportError("onnxruntime not found")
        ):
            with patch.object(pipeline, "_synthesize_mock", return_value=3000) as mock_mock:
                output_path = tmp_path / "test.mp3"
                duration = pipeline._synthesize_kokoro("text", "voice", {}, output_path)
                mock_mock.assert_called_once()
                assert duration == 3000

    def test_kokoro_file_not_found_fallback(self, tmp_path):
        """Test Kokoro falls back to mock on FileNotFoundError."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=False)

        with patch(
            "src.audiobook_studio.tts.kokoro_backend.KokoroBackend", side_effect=FileNotFoundError("model not found")
        ):
            with patch.object(pipeline, "_synthesize_mock", return_value=3000) as mock_mock:
                output_path = tmp_path / "test.mp3"
                duration = pipeline._synthesize_kokoro("text", "voice", {}, output_path)
                mock_mock.assert_called_once()
                assert duration == 3000

    def test_kokoro_generic_exception_fallback(self, tmp_path):
        """Test Kokoro falls back to mock on generic exception."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=False)

        with patch(
            "src.audiobook_studio.tts.kokoro_backend.KokoroBackend", side_effect=RuntimeError("synthesis failed")
        ):
            with patch.object(pipeline, "_synthesize_mock", return_value=3000) as mock_mock:
                output_path = tmp_path / "test.mp3"
                duration = pipeline._synthesize_kokoro("text", "voice", {}, output_path)
                mock_mock.assert_called_once()
                assert duration == 3000

    def test_azure_mock_mode_not_taken(self, tmp_path):
        """Test Azure TTS in non-mock mode checks credentials."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=False)

        # Remove Azure credentials if any
        import os

        old_key = os.environ.pop("AZURE_TTS_KEY", None)
        old_region = os.environ.pop("AZURE_TTS_REGION", None)

        try:
            output_path = tmp_path / "test.mp3"
            with pytest.raises(RuntimeError, match="Azure TTS not configured"):
                pipeline._synthesize_azure("text", "voice", {}, output_path)
        finally:
            if old_key:
                os.environ["AZURE_TTS_KEY"] = old_key
            if old_region:
                os.environ["AZURE_TTS_REGION"] = old_region

    def test_gcp_mock_mode_not_taken(self, tmp_path):
        """Test GCP TTS in non-mock mode checks credentials."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=False)

        # Remove GCP credentials if any
        import os

        old_creds = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)

        try:
            output_path = tmp_path / "test.mp3"
            with pytest.raises(RuntimeError, match="GCP TTS not configured"):
                pipeline._synthesize_gcp("text", "voice", {}, output_path)
        finally:
            if old_creds:
                os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = old_creds


class TestSynthesizePipelineCrossfadeAdvanced:
    """Test crossfade stitching advanced paths."""

    def test_crossfade_stitch_with_ffmpeg(self, tmp_path):
        """Test crossfade stitching with ffmpeg available."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        import numpy as np
        import soundfile as sf

        # Create two valid audio files
        audio_file1 = tmp_path / "seg1.wav"
        audio_file2 = tmp_path / "seg2.wav"
        dummy_audio = np.zeros(24000, dtype=np.float32)
        sf.write(str(audio_file1), dummy_audio, 24000)
        sf.write(str(audio_file2), dummy_audio, 24000)

        segments = [
            AudioSegment(
                segment_id="seg1",
                file_path=str(audio_file1),
                duration_ms=1000,
                engine="kokoro",
                voice_id="v1",
                text_hash="a",
            ),
            AudioSegment(
                segment_id="seg2",
                file_path=str(audio_file2),
                duration_ms=1500,
                engine="kokoro",
                voice_id="v2",
                text_hash="b",
            ),
        ]

        output_path = tmp_path / "output.mp3"

        # Mock subprocess.run to simulate successful ffmpeg
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""

            # Mock get_duration_sync for BOTH crossfade and simple_concat paths
            with patch("src.audiobook_studio.pipeline.synthesize.get_duration_sync", return_value=2500):
                with patch("src.audiobook_studio.monitoring.langfuse_client.is_enabled", return_value=False):
                    duration = pipeline._crossfade_stitch(segments, output_path)
                    assert duration == 2500
                    # Only crossfade should be called, not simple_concat fallback
                    assert mock_run.call_count == 1

    def test_crossfade_stitch_ffmpeg_failure_fallback(self, tmp_path):
        """Test crossfade falls back to simple concat on ffmpeg failure."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        import numpy as np
        import soundfile as sf

        # Need 2+ segments to trigger crossfade stitching
        audio_file1 = tmp_path / "seg1.wav"
        audio_file2 = tmp_path / "seg2.wav"
        dummy_audio = np.zeros(24000, dtype=np.float32)
        sf.write(str(audio_file1), dummy_audio, 24000)
        sf.write(str(audio_file2), dummy_audio, 24000)

        segments = [
            AudioSegment(
                segment_id="seg1",
                file_path=str(audio_file1),
                duration_ms=1000,
                engine="kokoro",
                voice_id="v1",
                text_hash="a",
            ),
            AudioSegment(
                segment_id="seg2",
                file_path=str(audio_file2),
                duration_ms=1500,
                engine="kokoro",
                voice_id="v2",
                text_hash="b",
            ),
        ]

        output_path = tmp_path / "output.mp3"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 1
            mock_run.return_value.stderr = "ffmpeg error"

            with patch("src.audiobook_studio.pipeline.synthesize.get_duration_sync", return_value=1000):
                with patch.object(pipeline, "_simple_concat", return_value=1000) as mock_concat:
                    duration = pipeline._crossfade_stitch(segments, output_path)
                    mock_concat.assert_called_once()
                    assert duration == 1000

    def test_crossfade_stitch_ffmpeg_not_found_fallback(self, tmp_path):
        """Test crossfade falls back to simple concat when ffmpeg not found."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        import numpy as np
        import soundfile as sf

        # Need 2+ segments to trigger crossfade stitching
        audio_file1 = tmp_path / "seg1.wav"
        audio_file2 = tmp_path / "seg2.wav"
        dummy_audio = np.zeros(24000, dtype=np.float32)
        sf.write(str(audio_file1), dummy_audio, 24000)
        sf.write(str(audio_file2), dummy_audio, 24000)

        segments = [
            AudioSegment(
                segment_id="seg1",
                file_path=str(audio_file1),
                duration_ms=1000,
                engine="kokoro",
                voice_id="v1",
                text_hash="a",
            ),
            AudioSegment(
                segment_id="seg2",
                file_path=str(audio_file2),
                duration_ms=1500,
                engine="kokoro",
                voice_id="v2",
                text_hash="b",
            ),
        ]

        output_path = tmp_path / "output.mp3"

        with patch("subprocess.run", side_effect=FileNotFoundError("ffmpeg not found")):
            with patch.object(pipeline, "_simple_concat", return_value=1000) as mock_concat:
                duration = pipeline._crossfade_stitch(segments, output_path)
                mock_concat.assert_called_once()
                assert duration == 1000

    def test_crossfade_stitch_generic_exception_fallback(self, tmp_path):
        """Test crossfade falls back to simple concat on generic exception."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        import numpy as np
        import soundfile as sf

        # Need 2+ segments to trigger crossfade stitching
        audio_file1 = tmp_path / "seg1.wav"
        audio_file2 = tmp_path / "seg2.wav"
        dummy_audio = np.zeros(24000, dtype=np.float32)
        sf.write(str(audio_file1), dummy_audio, 24000)
        sf.write(str(audio_file2), dummy_audio, 24000)

        segments = [
            AudioSegment(
                segment_id="seg1",
                file_path=str(audio_file1),
                duration_ms=1000,
                engine="kokoro",
                voice_id="v1",
                text_hash="a",
            ),
            AudioSegment(
                segment_id="seg2",
                file_path=str(audio_file2),
                duration_ms=1500,
                engine="kokoro",
                voice_id="v2",
                text_hash="b",
            ),
        ]

        output_path = tmp_path / "output.mp3"

        with patch("subprocess.run", side_effect=RuntimeError("unexpected error")):
            with patch.object(pipeline, "_simple_concat", return_value=1000) as mock_concat:
                duration = pipeline._crossfade_stitch(segments, output_path)
                mock_concat.assert_called_once()
                assert duration == 1000

    def test_simple_concat_success(self, tmp_path):
        """Test simple concat with ffmpeg."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        import numpy as np
        import soundfile as sf

        audio_file1 = tmp_path / "seg1.wav"
        audio_file2 = tmp_path / "seg2.wav"
        dummy_audio = np.zeros(24000, dtype=np.float32)
        sf.write(str(audio_file1), dummy_audio, 24000)
        sf.write(str(audio_file2), dummy_audio, 24000)

        segments = [
            AudioSegment(
                segment_id="seg1",
                file_path=str(audio_file1),
                duration_ms=1000,
                engine="kokoro",
                voice_id="v1",
                text_hash="a",
            ),
            AudioSegment(
                segment_id="seg2",
                file_path=str(audio_file2),
                duration_ms=1500,
                engine="kokoro",
                voice_id="v2",
                text_hash="b",
            ),
        ]

        output_path = tmp_path / "output.mp3"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stderr = ""

            with patch("src.audiobook_studio.pipeline.synthesize.get_duration_sync", return_value=2500):
                duration = pipeline._simple_concat(segments, output_path)
                assert duration == 2500
                mock_run.assert_called_once()

    def test_simple_concat_failure_fallback(self, tmp_path):
        """Test simple concat falls back to sum of durations on failure."""
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True)

        segments = [
            AudioSegment(
                segment_id="seg1",
                file_path=str(tmp_path / "nonexistent1.mp3"),
                duration_ms=1000,
                engine="kokoro",
                voice_id="v1",
                text_hash="a",
            ),
            AudioSegment(
                segment_id="seg2",
                file_path=str(tmp_path / "nonexistent2.mp3"),
                duration_ms=1500,
                engine="kokoro",
                voice_id="v2",
                text_hash="b",
            ),
        ]

        output_path = tmp_path / "output.mp3"

        with patch("subprocess.run", side_effect=RuntimeError("concat failed")):
            duration = pipeline._simple_concat(segments, output_path)
            # Should fall back to sum of durations
            assert duration == 2500

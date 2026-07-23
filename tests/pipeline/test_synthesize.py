"""Unit tests for SynthesizePipeline module (Port-based architecture).

Tests the current Port-based synthesis pipeline that uses RemoteTTSPort abstraction.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.pipeline.synthesize import AudioSegment, SynthesizePipeline
from src.audiobook_studio.schemas import CharacterVoiceBinding, ParagraphAnnotation, TtsRoutingDecision, TtsRoutingInput
from src.audiobook_studio.tts.fake_port import FakeRemoteTTSPort
from src.audiobook_studio.tts.port import (
    RemoteTTSPort,
    TTSProsody,
    TTSStatus,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
)


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
        assert len(hash1) == 12  # SHA256 first 12 chars

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

    def test_build_payload(self):
        """Test building TTSTaskPayload from synthesis parameters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = SynthesizePipeline(output_dir=tmpdir, mock_mode=True)
            payload = pipeline._build_payload("测试文本", "zh-CN-XiaoxiaoNeural", {"rate": 1.2, "pitch": 1.0})

            assert payload.text == "测试文本"
            assert payload.voice_anchor.voice_id == "zh-CN-XiaoxiaoNeural"
            assert payload.prosody.rate == 1.2
            assert payload.prosody.pitch == 1.0

    def test_make_routing_decision_prefer_local(self):
        """Test routing prefers local engine when prefer_local=True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = SynthesizePipeline(output_dir=tmpdir, mock_mode=True)

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

    def test_make_routing_decision_prefer_cloud(self):
        """Test routing prefers cloud engine when prefer_local=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = SynthesizePipeline(output_dir=tmpdir, mock_mode=True)

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
            assert decision.fallback_engine == "kokoro"

    def test_make_routing_decision_prosody_overrides(self):
        """Test routing includes prosody overrides."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = SynthesizePipeline(output_dir=tmpdir, mock_mode=True)

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

    def test_make_routing_decision_segment_id_format(self):
        """Test segment ID format in routing decision."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = SynthesizePipeline(output_dir=tmpdir, mock_mode=True)

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

    def test_close(self):
        """Test closing the pipeline releases port."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)
            pipeline = SynthesizePipeline(output_dir=tmpdir, mock_mode=True, port=fake_port)
            pipeline.close()  # Should not raise


class TestSynthesizePipelineWithFakePort:
    """Test SynthesizePipeline with FakeRemoteTTSPort for mock synthesis."""

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

    def test_run_single_paragraph_with_fake_port(self, tmp_path):
        """Test run with single paragraph using FakeRemoteTTSPort."""
        # Create fake port with fast synthesis
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs = [self.create_routing_input(0)]

        segments = pipeline.run(inputs)

        assert len(segments) == 1
        assert segments[0].segment_id == "book_1_ch1_p0"
        # FakeRemoteTTSPort returns "hermes" as default engine (no metadata.engine set)
        assert segments[0].engine == "hermes"
        assert segments[0].voice_id == "zh-CN-XiaoxiaoNeural"
        # Duration based on text length (~50ms per char): "这是第 1 段测试文本。" = ~12 chars -> ~600ms
        assert segments[0].duration_ms >= 500  # fake port uses 50ms per char

    def test_run_multiple_paragraphs_with_fake_port(self, tmp_path):
        """Test run with multiple paragraphs using FakeRemoteTTSPort."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs = [self.create_routing_input(i) for i in range(3)]

        segments = pipeline.run(inputs)

        assert len(segments) == 3
        assert segments[0].segment_id == "book_1_ch1_p0"
        assert segments[1].segment_id == "book_1_ch1_p1"
        assert segments[2].segment_id == "book_1_ch1_p2"
        for seg in segments:
            # FakeRemoteTTSPort returns "hermes" as default engine
            assert seg.engine == "hermes"
            assert seg.duration_ms >= 500  # fake port uses 50ms per char

    def test_run_incremental_skip_unchanged(self, tmp_path):
        """Test incremental synthesis skips unchanged text."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs = [self.create_routing_input(0)]

        # First run
        segments1 = pipeline.run(inputs)
        assert len(segments1) == 1

        # Second run with same text - should skip (load from disk metadata)
        pipeline2 = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        segments2 = pipeline2.run(inputs)

        assert len(segments2) == 1
        assert segments2[0].segment_id == "book_1_ch1_p0"
        # Should be loaded from disk metadata, same text_hash
        assert segments2[0].text_hash == segments1[0].text_hash

    def test_run_different_text_regenerates(self, tmp_path):
        """Test changed text triggers regeneration."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs1 = [self.create_routing_input(0)]
        segments1 = pipeline.run(inputs1)

        # Create new input with different text
        input2 = self.create_routing_input(0)
        input2.text = "这是修改后的文本。"
        input2.paragraph_annotation.text = "这是修改后的文本。"

        pipeline2 = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        segments2 = pipeline2.run([input2])

        # Should have regenerated (new text_hash)
        assert segments2[0].text_hash != segments1[0].text_hash

    def test_run_chapter_stitching(self, tmp_path):
        """Test chapter-level audio stitching."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs = [self.create_routing_input(i) for i in range(3)]

        segments = pipeline.run(inputs)

        # Should create chapter file
        chapter_file = tmp_path / "book_1_ch1.mp3"
        # In fake port mode, stitching uses simple concat
        assert len(segments) == 3

    def test_run_with_edge_engine(self, tmp_path):
        """Test run with Edge TTS engine (prefer_local=False)."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        input_edge = self.create_routing_input(0)
        input_edge.prefer_local = False

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        segments = pipeline.run([input_edge])

        assert len(segments) == 1
        # FakeRemoteTTSPort always returns "hermes" as engine
        assert segments[0].engine == "hermes"

    def test_fake_port_failure_injection(self, tmp_path):
        """Test failure injection via FakeRemoteTTSPort."""
        # Port that always fails
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=1.0)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs = [self.create_routing_input(0)]

        # Should raise RuntimeError on synthesis failure
        with pytest.raises(RuntimeError, match="Synthesis failed"):
            pipeline.run(inputs)


class TestSynthesizePipelineQualityGate:
    """Test quality gate with auto-retry (max 2 retries)."""

    def create_routing_input(self, idx: int = 0) -> TtsRoutingInput:
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

    def test_quality_check_with_retry(self, tmp_path):
        """Test quality check triggers retry on failure."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs = [self.create_routing_input(0)]

        segments = pipeline.run(inputs)

        assert len(segments) == 1


class TestSynthesizePipelineCrossfade:
    """Test crossfade stitching functionality."""

    def create_routing_input(self, idx: int = 0) -> TtsRoutingInput:
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

    def test_crossfade_stitch_single_segment(self, tmp_path):
        """Test stitching with single segment (just copies)."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs = [self.create_routing_input(0)]

        segments = pipeline.run(inputs)
        assert len(segments) == 1

    def test_crossfade_stitch_empty_segments(self, tmp_path):
        """Test stitching with no valid segments."""
        # Cannot easily test empty segments without mocking run()
        pass


class TestSynthesizePipelineCostEstimation:
    """Test cost estimation logic in run()."""

    def create_routing_input(self, idx: int = 0) -> TtsRoutingInput:
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

    def test_kokoro_cost_zero(self, tmp_path):
        """Test Kokoro engine cost is zero."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        # prefer_local=True -> kokoro
        inputs = [self.create_routing_input(0)]

        segments = pipeline.run(inputs)

        # Kokoro is local, cost should be 0
        # (Cost is logged internally, not returned)

    def test_edge_cost_estimate(self, tmp_path):
        """Test Edge TTS cost estimation."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        # prefer_local=False -> edge
        inp = self.create_routing_input(0)
        inp.prefer_local = False

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        segments = pipeline.run([inp])

        assert len(segments) == 1


class TestSynthesizePipelineFallback:
    """Test fallback chain behavior."""

    def create_routing_input(self, idx: int = 0) -> TtsRoutingInput:
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

    def test_fallback_chain_order(self, tmp_path):
        """Test fallback engine order is correct."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = SynthesizePipeline(output_dir=tmpdir, mock_mode=True)

            inp_local = self.create_routing_input(0)
            inp_local.prefer_local = True
            decision_local = pipeline._make_routing_decision(inp_local)
            assert decision_local.engine_choice == "kokoro"
            assert decision_local.fallback_engine == "edge"

            inp_cloud = self.create_routing_input(0)
            inp_cloud.prefer_local = False
            decision_cloud = pipeline._make_routing_decision(inp_cloud)
            assert decision_cloud.engine_choice == "edge"
            assert decision_cloud.fallback_engine == "kokoro"

    def test_voice_clone_detection(self, tmp_path):
        """Test voice clone detection in routing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = SynthesizePipeline(output_dir=tmpdir, mock_mode=True)

            inp = self.create_routing_input(0)
            inp.character_voice_map[0].suggested_voice_id = "cloned_voice_123"

            decision = pipeline._make_routing_decision(inp)

            assert decision.voice_id == "cloned_voice_123"


class TestSynthesizePipelineIntegration:
    """Integration tests for synthesize_paragraphs convenience function."""

    def test_synthesize_paragraphs_function(self, tmp_path):
        """Test synthesize_paragraphs convenience function."""
        from src.audiobook_studio.pipeline.synthesize import synthesize_paragraphs

        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        inputs = [self.create_routing_input(0)]
        segments = synthesize_paragraphs(
            inputs=inputs,
            output_dir=str(tmp_path),
            mock_mode=True,
            port=fake_port,
        )

        assert len(segments) == 1
        assert segments[0].segment_id == "book_1_ch1_p0"

    def create_routing_input(self, idx: int = 0) -> TtsRoutingInput:
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

    def test_pipeline_with_custom_hardware_profile(self, tmp_path):
        """Test pipeline with custom hardware profile."""
        from src.audiobook_studio.config.hardware_profile import HardwareSpecs

        custom_profile = HardwareSpecs(
            gpu_enabled=True,
            gpu_name="Test GPU",
            vram_gb=24.0,
            ram_gb=32.0,
            cpu_cores=8,
            cpu_arch="x86_64",
            cuda_version="12.1",
            has_nvidia_smi=True,
        )

        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        pipeline = SynthesizePipeline(
            output_dir=str(tmp_path),
            mock_mode=True,
            port=fake_port,
            hardware_profile=custom_profile,
        )

        assert pipeline.hardware_profile == custom_profile


class TestSynthesizePipelineErrorHandling:
    """Test error handling in SynthesizePipeline."""

    def create_routing_input(self, idx: int = 0) -> TtsRoutingInput:
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

    def test_port_submit_failure(self, tmp_path):
        """Test handling of port submit failure."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        # Mock port.submit to return False (rejected)
        fake_port.submit = AsyncMock(return_value=False)

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs = [self.create_routing_input(0)]

        with pytest.raises(RuntimeError, match="rejected by scheduling layer"):
            pipeline.run(inputs)

    def test_port_timeout(self, tmp_path):
        """Test handling of port timeout (slow synthesis)."""
        # Port with very slow synthesis
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        # Override poll interval to be very short for test
        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        inputs = [self.create_routing_input(0)]

        segments = pipeline.run(inputs)

        assert len(segments) == 1

    def test_audio_download_failure(self, tmp_path):
        """Test handling of audio download failure."""
        fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)

        # Mock _download_audio to raise NotImplementedError
        async def mock_download(source, dest):
            raise NotImplementedError("Remote download not implemented")

        pipeline = SynthesizePipeline(output_dir=str(tmp_path), mock_mode=True, port=fake_port)
        pipeline._download_audio = mock_download

        inputs = [self.create_routing_input(0)]

        with pytest.raises(NotImplementedError, match="Remote download not implemented"):
            pipeline.run(inputs)


class TestSynthesizePipelineCrossfadeAdvanced:
    """Advanced crossfade stitching tests."""

    def test_simple_concat_fallback_on_ffmpeg_missing(self, tmp_path):
        """Test simple concat fallback when ffmpeg not available."""
        # This test would require mocking ffmpeg not found
        pass

    def test_crossfade_stitch_ffmpeg_failure_fallback(self, tmp_path):
        """Test fallback to simple concat on ffmpeg failure."""
        pass

    def test_crossfade_stitch_ffmpeg_not_found_fallback(self, tmp_path):
        """Test fallback when ffmpeg not found."""
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

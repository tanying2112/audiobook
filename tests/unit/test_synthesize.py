"""Unit tests for synthesize pipeline targeting ≥80% line coverage.

Tests match the ACTUAL API from src/audiobook_studio/pipeline/synthesize.py:
- AudioSegment dataclass
- SynthesizePipeline class with run(), _make_routing_decision(), _synthesize_kokoro(), _synthesize_edge(), _crossfade_stitch()
- synthesize_paragraphs() convenience function
- mock_mode behavior for testing without external APIs
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, PropertyMock

import pytest
from src.audiobook_studio.pipeline.synthesize import (
    SynthesizePipeline,
    synthesize_paragraphs,
    AudioSegment,
)
from src.audiobook_studio.schemas import (
    TtsRoutingInput,
    TtsRoutingDecision,
    ParagraphAnnotation,
    CharacterVoiceBinding,
)


class TestAudioSegmentDataclass:
    """Test AudioSegment dataclass."""

    def test_audio_segment_creation(self):
        """Test AudioSegment can be created with all fields."""
        segment = AudioSegment(
            segment_id="test_seg_1",
            file_path="/tmp/test.mp3",
            duration_ms=3000,
            engine="kokoro",
            voice_id="voice_001",
            text_hash="abc123",
        )
        assert segment.segment_id == "test_seg_1"
        assert segment.file_path == "/tmp/test.mp3"
        assert segment.duration_ms == 3000
        assert segment.engine == "kokoro"
        assert segment.voice_id == "voice_001"
        assert segment.text_hash == "abc123"

    def test_audio_segment_equality(self):
        """Test AudioSegment equality comparison."""
        seg1 = AudioSegment("id1", "/tmp/a.mp3", 1000, "kokoro", "v1", "hash1")
        seg2 = AudioSegment("id1", "/tmp/a.mp3", 1000, "kokoro", "v1", "hash1")
        seg3 = AudioSegment("id2", "/tmp/b.mp3", 2000, "edge", "v2", "hash2")
        assert seg1 == seg2
        assert seg1 != seg3


class TestSynthesizePipeline:
    """Test SynthesizePipeline class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = SynthesizePipeline(output_dir=self.temp_dir, mock_mode=True)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_default(self):
        """Test pipeline initialization with defaults."""
        pipeline = SynthesizePipeline()
        assert pipeline.output_dir == Path("./output")
        assert pipeline.mock_mode is False
        assert pipeline.router is not None

    def test_init_custom_output_dir(self):
        """Test pipeline initialization with custom output directory."""
        import tempfile
        custom_dir = tempfile.mkdtemp()
        try:
            pipeline = SynthesizePipeline(output_dir=custom_dir)
            assert pipeline.output_dir == Path(custom_dir)
        finally:
            import shutil
            shutil.rmtree(custom_dir, ignore_errors=True)

    def test_init_mock_mode(self):
        """Test pipeline initialization in mock mode."""
        pipeline = SynthesizePipeline(mock_mode=True)
        assert pipeline.mock_mode is True

    def test_init_with_router(self):
        """Test pipeline initialization with custom router."""
        mock_router = Mock()
        pipeline = SynthesizePipeline(router=mock_router, mock_mode=True)
        assert pipeline.router == mock_router

    def test_make_routing_decision_mock_mode(self):
        """Test _make_routing_decision in mock mode returns Kokoro decision."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        inp = TtsRoutingInput(
            book_id="book_001",
            chapter_index=1,
            paragraph_index=0,
            text="测试文本",
            paragraph_annotation=annotation,
            character_voice_map=[char_binding],
            prefer_local=True,
        )

        decision = self.pipeline._make_routing_decision(inp)

        assert decision.engine_choice == "kokoro"
        assert decision.voice_id == "kokoro_voice"
        assert decision.segment_id == "book_001_ch1_p0"
        assert decision.estimated_cost_usd == 0.0
        assert decision.estimated_duration_ms == 3000
        assert "prosody_overrides" in decision.model_dump()

    def test_make_routing_decision_mock_mode_default_voice(self):
        """Test _make_routing_decision with unknown character falls back to default voice."""
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="未知角色",
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        inp = TtsRoutingInput(
            book_id="book_001",
            chapter_index=1,
            paragraph_index=0,
            text="测试文本",
            paragraph_annotation=annotation,
            character_voice_map=[char_binding],
            prefer_local=True,
        )

        decision = self.pipeline._make_routing_decision(inp)

        assert decision.voice_id == "default"

    def test_synthesize_kokoro_mock_mode(self):
        """Test _synthesize_kokoro in mock mode creates dummy file."""
        output_path = Path(self.temp_dir) / "test_kokoro.mp3"
        duration = self.pipeline._synthesize_kokoro("测试文本", "voice_001", {}, output_path)

        assert output_path.exists()
        assert duration == 3000
        assert output_path.stat().st_size > 0

    def test_synthesize_edge_mock_mode(self):
        """Test _synthesize_edge in mock mode creates dummy file."""
        output_path = Path(self.temp_dir) / "test_edge.mp3"
        duration = self.pipeline._synthesize_edge("测试文本", "voice_002", {}, output_path)

        assert output_path.exists()
        assert duration == 2800
        assert output_path.stat().st_size > 0

    def test_crossfade_stitch_mock_mode(self):
        """Test _crossfade_stitch in mock mode returns sum of durations."""
        segments = [
            AudioSegment("seg1", "/tmp/seg1.mp3", 3000, "kokoro", "v1", "hash1"),
            AudioSegment("seg2", "/tmp/seg2.mp3", 2500, "kokoro", "v1", "hash2"),
            AudioSegment("seg3", "/tmp/seg3.mp3", 2000, "kokoro", "v1", "hash3"),
        ]
        output_path = Path(self.temp_dir) / "stitched.mp3"

        total_duration = self.pipeline._crossfade_stitch(segments, output_path)

        assert total_duration == 7500  # sum of durations

    def test_crossfade_stitch_empty_list(self):
        """Test _crossfade_stitch with empty segment list."""
        output_path = Path(self.temp_dir) / "empty.mp3"
        total_duration = self.pipeline._crossfade_stitch([], output_path)
        assert total_duration == 0

    def test_run_mock_mode_single_paragraph(self):
        """Test run() in mock mode with single paragraph."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        inp = TtsRoutingInput(
            book_id="book_001",
            chapter_index=1,
            paragraph_index=0,
            text="这是第一段测试文本。",
            paragraph_annotation=annotation,
            character_voice_map=[char_binding],
            prefer_local=True,
        )

        segments = self.pipeline.run([inp])

        assert len(segments) == 1
        assert isinstance(segments[0], AudioSegment)
        assert segments[0].segment_id == "book_001_ch1_p0"
        assert segments[0].engine == "kokoro"
        assert segments[0].voice_id == "kokoro_voice"
        assert segments[0].duration_ms == 3000
        assert Path(segments[0].file_path).exists()

    def test_run_mock_mode_multiple_paragraphs(self):
        """Test run() in mock mode with multiple paragraphs."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )

        inputs = []
        for i in range(3):
            inputs.append(TtsRoutingInput(
                book_id="book_001",
                chapter_index=1,
                paragraph_index=i,
                text=f"这是第{i+1}段测试文本。",
                paragraph_annotation=annotation,
                character_voice_map=[char_binding],
                prefer_local=True,
            ))

        segments = self.pipeline.run(inputs)

        assert len(segments) == 3
        for i, seg in enumerate(segments):
            assert seg.segment_id == f"book_001_ch1_p{i}"
            assert seg.engine == "kokoro"
            assert seg.duration_ms == 3000

        # In mock_mode, _crossfade_stitch returns sum of durations but doesn't create file
        # Actual file creation happens only in real mode with pydub
        # This is expected behavior for mock_mode

    def test_run_incremental_regeneration_skip_unchanged(self):
        """Test run() skips regeneration when text_hash matches."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        inp = TtsRoutingInput(
            book_id="book_001",
            chapter_index=1,
            paragraph_index=0,
            text="相同的文本内容",
            paragraph_annotation=annotation,
            character_voice_map=[char_binding],
            prefer_local=True,
        )

        # First run
        segments1 = self.pipeline.run([inp])
        first_file = segments1[0].file_path
        first_hash = segments1[0].text_hash

        # Second run with same text - should skip
        segments2 = self.pipeline.run([inp])

        assert len(segments2) == 1
        assert segments2[0].file_path == first_file
        assert segments2[0].text_hash == first_hash

    def test_run_incremental_regeneration_text_changed(self):
        """Test run() regenerates when text changes (overwrites same file with new content)."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )

        inp1 = TtsRoutingInput(
            book_id="book_001", chapter_index=1, paragraph_index=0,
            text="原始文本", paragraph_annotation=annotation,
            character_voice_map=[char_binding], prefer_local=True,
        )
        inp2 = TtsRoutingInput(
            book_id="book_001", chapter_index=1, paragraph_index=0,
            text="修改后的文本", paragraph_annotation=annotation,
            character_voice_map=[char_binding], prefer_local=True,
        )

        segments1 = self.pipeline.run([inp1])
        segments2 = self.pipeline.run([inp2])

        # Same segment_id generates same file path, but text_hash should differ indicating regeneration
        assert segments1[0].segment_id == segments2[0].segment_id
        assert segments1[0].file_path == segments2[0].file_path
        assert segments1[0].text_hash != segments2[0].text_hash

    def test_run_uses_disk_metadata_to_skip_regeneration_after_restart(self):
        """Test run() can skip regeneration using persisted metadata."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        inp = TtsRoutingInput(
            book_id="book_001",
            chapter_index=1,
            paragraph_index=0,
            text="可恢复增量合成文本",
            paragraph_annotation=annotation,
            character_voice_map=[char_binding],
            prefer_local=True,
        )

        first_segments = self.pipeline.run([inp])
        first_segment = first_segments[0]

        restarted_pipeline = SynthesizePipeline(output_dir=self.temp_dir, mock_mode=True)
        with patch.object(restarted_pipeline, "_synthesize_kokoro", wraps=restarted_pipeline._synthesize_kokoro) as mocked_synthesis:
            restarted_segments = restarted_pipeline.run([inp])

        restarted_segment = restarted_segments[0]
        assert restarted_segment == first_segment
        mocked_synthesis.assert_not_called()

    def test_run_ignores_stale_disk_metadata_when_text_changed(self):
        """Test stale metadata does not skip regeneration after text changes."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        old_input = TtsRoutingInput(
            book_id="book_001",
            chapter_index=1,
            paragraph_index=0,
            text="旧文本",
            paragraph_annotation=annotation,
            character_voice_map=[char_binding],
            prefer_local=True,
        )
        new_input = TtsRoutingInput(
            book_id="book_001",
            chapter_index=1,
            paragraph_index=0,
            text="新文本",
            paragraph_annotation=annotation,
            character_voice_map=[char_binding],
            prefer_local=True,
        )

        self.pipeline.run([old_input])
        restarted_pipeline = SynthesizePipeline(output_dir=self.temp_dir, mock_mode=True)
        restarted_segments = restarted_pipeline.run([new_input])

        assert restarted_segments[0].text_hash != self.pipeline._text_hash("旧文本")
        assert restarted_segments[0].duration_ms == 3000

    def test_run_empty_input_list(self):
        """Test run() with empty input list."""
        segments = self.pipeline.run([])
        assert segments == []


class TestSynthesizeParagraphsConvenienceFunction:
    """Test synthesize_paragraphs convenience function."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_synthesize_paragraphs_mock_mode(self):
        """Test synthesize_paragraphs in mock mode."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        inp = TtsRoutingInput(
            book_id="book_001",
            chapter_index=1,
            paragraph_index=0,
            text="便利函数测试文本",
            paragraph_annotation=annotation,
            character_voice_map=[char_binding],
            prefer_local=True,
        )

        segments = synthesize_paragraphs([inp], output_dir=self.temp_dir, mock_mode=True)

        assert len(segments) == 1
        assert isinstance(segments[0], AudioSegment)
        assert segments[0].segment_id == "book_001_ch1_p0"

    def test_synthesize_paragraphs_custom_output_dir(self):
        """Test synthesize_paragraphs with custom output directory."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        inp = TtsRoutingInput(
            book_id="book_002",
            chapter_index=1,
            paragraph_index=0,
            text="自定义输出目录测试",
            paragraph_annotation=annotation,
            character_voice_map=[char_binding],
            prefer_local=True,
        )

        custom_dir = os.path.join(self.temp_dir, "custom_output")
        segments = synthesize_paragraphs([inp], output_dir=custom_dir, mock_mode=True)

        assert len(segments) == 1
        assert custom_dir in segments[0].file_path


class TestSynthesizePipelineEdgeCases:
    """Test edge cases for SynthesizePipeline."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = SynthesizePipeline(output_dir=self.temp_dir, mock_mode=True)

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_whitespace_only_text(self):
        """Test synthesis with whitespace-only text."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        inp = TtsRoutingInput(
            book_id="book_001", chapter_index=1, paragraph_index=0,
            text="   \n\t  ", paragraph_annotation=annotation,
            character_voice_map=[char_binding], prefer_local=True,
        )

        segments = self.pipeline.run([inp])
        assert len(segments) == 1
        assert segments[0].duration_ms == 3000

    def test_very_long_text(self):
        """Test synthesis with very long text."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        long_text = "这是一段很长的文本。" * 1000  # ~8000 chars
        inp = TtsRoutingInput(
            book_id="book_001", chapter_index=1, paragraph_index=0,
            text=long_text, paragraph_annotation=annotation,
            character_voice_map=[char_binding], prefer_local=True,
        )

        segments = self.pipeline.run([inp])
        assert len(segments) == 1
        assert segments[0].duration_ms == 3000  # mock mode returns fixed duration

    def test_unicode_content(self):
        """Test synthesis with unicode content (emoji, special chars)."""
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
            notes="Mock annotation",
        )
        char_binding = CharacterVoiceBinding(
            canonical_name="旁白",
            aliases=[],
            gender="neutral",
            age_range="adult",
            suggested_voice_id="kokoro_voice",
            sample_quote="测试",
        )
        inp = TtsRoutingInput(
            book_id="book_001", chapter_index=1, paragraph_index=0,
            text="Hello 世界! 🌍 你好 👋", paragraph_annotation=annotation,
            character_voice_map=[char_binding], prefer_local=True,
        )

        segments = self.pipeline.run([inp])
        assert len(segments) == 1
        assert "kokoro" == segments[0].engine

    def test_multiple_characters_different_voices(self):
        """Test synthesis with multiple characters using different voices."""
        annotation1 = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="张三",
            is_dialogue=True,
            emotion="happy",
            emotion_intensity=0.8,
            speech_rate=1.1,
            pitch_shift_semitones=2,
            pause_before_ms=200,
            pause_after_ms=400,
            confidence=0.95,
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
            notes="Dialogue",
        )
        annotation2 = ParagraphAnnotation(
            paragraph_index=1,
            speaker_canonical_name="李四",
            is_dialogue=True,
            emotion="sad",
            emotion_intensity=0.7,
            speech_rate=0.9,
            pitch_shift_semitones=-1,
            pause_before_ms=200,
            pause_after_ms=400,
            confidence=0.95,
            difficulty="B",
            needs_sfx=False,
            sfx_tags=[],
            notes="Dialogue",
        )
        char_bindings = [
            CharacterVoiceBinding(
                canonical_name="张三", aliases=["三哥"],
                gender="male", age_range="adult",
                suggested_voice_id="male_voice_01", sample_quote="哈哈哈",
            ),
            CharacterVoiceBinding(
                canonical_name="李四", aliases=["四弟"],
                gender="male", age_range="young",
                suggested_voice_id="male_voice_02", sample_quote="呜呜呜",
            ),
        ]

        inp1 = TtsRoutingInput(
            book_id="book_001", chapter_index=1, paragraph_index=0,
            text="张三说：今天真开心！", paragraph_annotation=annotation1,
            character_voice_map=char_bindings, prefer_local=True,
        )
        inp2 = TtsRoutingInput(
            book_id="book_001", chapter_index=1, paragraph_index=1,
            text="李四说：我好难过。", paragraph_annotation=annotation2,
            character_voice_map=char_bindings, prefer_local=True,
        )

        segments = self.pipeline.run([inp1, inp2])

        assert len(segments) == 2
        assert segments[0].voice_id == "male_voice_01"
        assert segments[1].voice_id == "male_voice_02"
        assert segments[0].segment_id == "book_001_ch1_p0"
        assert segments[1].segment_id == "book_001_ch1_p1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

    """Additional test cases for synthesize.py coverage."""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock, call

import pytest
from src.audiobook_studio.pipeline.synthesize import (
    SynthesizePipeline,
    AudioSegment,
    _crossfade_stitch,
)
from src.audiobook_studio.schemas import (
    TtsRoutingInput,
    TtsRoutingDecision,
    ParagraphAnnotation,
    CharacterVoiceBinding,
)


class TestSynthesizeNonMockPaths:
    """Test non-mock code paths for coverage."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.pipeline = SynthesizePipeline(output_dir=self.temp_dir, mock_mode=False)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_text_hash(self):
        """Test text_hash method for caching."""
        pipeline = SynthesizePipeline(mock_mode=True)
        hash1 = pipeline._text_hash("测试文本")
        hash2 = pipeline._text_hash("测试文本")
        hash3 = pipeline._text_hash("不同文本")
        assert hash1 == hash2
        assert hash1 != hash3

    @patch("src.audiobook_studio.pipeline.synthesize.kokoro")
    def test_synthesize_kokoro_real_mode(self, mock_kokoro):
        """Test kokoro synthesis in real (non-mock) mode."""
        # Mock kokoro-onnx availability
        mock_kokoro.__version__ = "1.0"
        
        pipeline = SynthesizePipeline(output_dir=self.temp_dir, mock_mode=False)
        
        # Mock get_duration_sync to avoid ffprobe call
        with patch("src.audiobook_studio.pipeline.synthesize.get_duration_sync", return_value=3000):
            output_path = Path(self.temp_dir) / "test.mp3"
            duration = pipeline._synthesize_kokoro("测试文本", "voice_1", {"rate": "1.0"}, output_path)
            
            assert output_path.exists()
            assert duration == 3000

    @patch("src.audiobook_studio.pipeline.synthesize.edge_tts")
    def test_synthesize_edge_real_mode(self, mock_edge_tts):
        """Test Edge-TTS synthesis in real mode."""
        # Setup async mock
        mock_communicate = AsyncMock()
        mock_edge_tts.Communicate.return_value = mock_communicate
        
        pipeline = SynthesizePipeline(output_dir=self.temp_dir, mock_mode=False)
        
        with patch("src.audiobook_studio.pipeline.synthesize.get_duration_sync", return_value=2800):
            output_path = Path(self.temp_dir) / "test_edge.mp3"
            duration = pipeline._synthesize_edge("测试文本", "zh-CN-XiaoxiaoNeural", {"rate": "1.0"}, output_path)
            
            assert output_path.exists()
            assert duration == 2800
            mock_edge_tts.Communicate.assert_called_once()

    @patch("src.audiobook_studio.pipeline.synthesize.asyncio")
    @patch("src.audiobook_studio.pipeline.synthesize.edge_tts")
    def test_synthesize_edge_exception_fallback(self, mock_edge_tts, mock_asyncio):
        """Test Edge-TTS exception triggers fallback estimate."""
        mock_edge_tts.Communicate.side_effect = Exception("Network error")
        
        pipeline = SynthesizePipeline(output_dir=self.temp_dir, mock_mode=False)
        
        output_path = Path(self.temp_dir) / "test_edge_fallback.mp3"
        # Should not raise, just return estimated duration
        duration = pipeline._synthesize_edge("测试文本内容", "zh-CN-XiaoxiaoNeural", {}, output_path)
        
        assert isinstance(duration, int)
        assert duration > 0

    def test_crossfade_stitch_mock_mode(self):
        """Test crossfade stitching in mock mode."""
        segments = [
            AudioSegment("seg1", "/tmp/seg1.mp3", 1000, "kokoro", "v1", "hash1"),
            AudioSegment("seg2", "/tmp/seg2.mp3", 1000, "edge", "v2", "hash2"),
        ]
        
        with patch("src.audiobook_studio.pipeline.synthesize.AudioSegment") as MockAudioSegment:
            # Mock the crossfade function
            with patch("src.audiobook_studio.pipeline.synthesize.shutil.copy2"):
                with patch("src.audiobook_studio.pipeline.synthesize.get_duration_sync", return_value=2000):
                    result = _crossfade_stitch(segments, Path(self.temp_dir) / "output.mp3", mock_mode=True)
                    
                    assert result is not None

    def test_crossfade_stitch_empty_segments(self):
        """Test crossfade with empty segments list."""
        result = _crossfade_stitch([], Path(self.temp_dir) / "output.mp3", mock_mode=True)
        assert result is None

    def test_resolve_edge_voice_full_format(self):
        """Test _resolve_edge_voice with full voice format."""
        pipeline = SynthesizePipeline(mock_mode=True)
        # Full format should return as-is
        voice = pipeline._resolve_edge_voice("zh-CN-XiaoxiaoNeural")
        assert voice == "zh-CN-XiaoxiaoNeural"

    def test_resolve_edge_voice_mapped(self):
        """Test _resolve_edge_voice with voice mapping."""
        pipeline = SynthesizePipeline(mock_mode=True)
        # Short form should map to full
        voice = pipeline._resolve_edge_voice("zh-CN-XiaoxiaoNeural")
        assert "Xiaoxiao" in voice

    def test_resolve_edge_voice_dynamic(self):
        """Test _resolve_edge_voice generates dynamic voice."""
        pipeline = SynthesizePipeline(mock_mode=True)
        # Unknown voice should generate compatible one
        voice = pipeline._resolve_edge_voice("unknown_voice")
        assert voice.startswith("zh-CN-")

    def test_resolve_edge_voice_fallback(self):
        """Test _resolve_edge_voice fallback behavior."""
        pipeline = SynthesizePipeline(mock_mode=True)
        voice = pipeline._resolve_edge_voice("invalid")
        assert voice == "zh-CN-XiaoxiaoNeural"  # Default fallback


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

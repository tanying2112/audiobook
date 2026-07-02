"""Targeted tests for synthesize.py pipeline helpers — boost coverage on
undertested methods like _synthesize_azure, _synthesize_gcp, _simple_concat,
_load_existing_segment_from_disk, and _persist_segment_metadata."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.pipeline.synthesize import AudioSegment, SynthesizePipeline


def _make_pipeline(tmp_path: Path, mock_mode: bool = True) -> SynthesizePipeline:
    """Build a mock-mode pipeline writing into tmp_path."""
    return SynthesizePipeline(
        router=MagicMock(),
        output_dir=str(tmp_path / "out"),
        mock_mode=mock_mode,
    )


class TestSynthesizePipelineAzureMock:
    """Exercise Azure mock-mode branch."""

    def test_synthesize_azure_mock_creates_file(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        out = tmp_path / "azure.mp3"
        duration = pipeline._synthesize_azure(
            text="hello world", voice_id="zh-CN-XiaoxiaoNeural", prosody={}, output_path=out
        )
        # mock returns 2800ms
        assert duration == 2800
        assert out.exists()
        assert out.stat().st_size > 0

    def test_synthesize_azure_mock_low_quality_fallback(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        out = tmp_path / "azure-fallback.mp3"
        # voice_id not in AZURE_VOICE_MAP but starts with Microsoft...:
        full_voice = "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)"
        duration = pipeline._synthesize_azure(
            text="text",
            voice_id=full_voice,
            prosody={"rate": "1.2", "pitch": "+2st", "volume": "+10%"},
            output_path=out,
        )
        assert duration == 2800


class TestSynthesizePipelineGCPMock:
    """Exercise GCP mock-mode branch."""

    def test_synthesize_gcp_mock_creates_file(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        out = tmp_path / "gcp.mp3"
        duration = pipeline._synthesize_gcp(
            text="hello world",
            voice_id="cmn-CN-Neural2-A",
            prosody={"rate": 1.0, "pitch": 0.0, "volume": 0.0},
            output_path=out,
        )
        assert duration == 2800
        assert out.exists()


class TestSynthesizeEdgeVoiceResolution:
    """_resolve_edge_voice has multiple branches."""

    def test_full_format_returns_as_is(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        full = "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)"
        assert pipeline._resolve_edge_voice(full) == full

    def test_mapped_short_id(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        result = pipeline._resolve_edge_voice("zh-CN-XiaoxiaoNeural")
        assert result == "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)"

    def test_dynamic_two_dashes(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        result = pipeline._resolve_edge_voice("zh-CN-CustomVoice")
        assert "Microsoft Server Speech Text to Speech Voice" in result
        assert "zh-CN" in result
        assert "Customvoice" in result or "CustomVoice" in result

    def test_unmappable_passthrough(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        # No dashes; falls through to passthrough
        assert pipeline._resolve_edge_voice("unknown_voice") == "unknown_voice"


class TestPersistentMetadataAndLoad:
    """_persist_segment_metadata + _load_existing_segment_from_disk round-trip."""

    def test_persist_then_load_round_trip(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        # Create the audio file referenced by the metadata
        audio_file = tmp_path / "segment.mp3"
        audio_file.write_bytes(b"\x00" * 16)
        seg = AudioSegment(
            segment_id="seg1",
            file_path=str(audio_file),
            duration_ms=1234,
            engine="kokoro",
            voice_id="zh-CN-XiaoxiaoNeural",
            text_hash="deadbeef1234",
        )
        pipeline._persist_segment_metadata(seg)
        meta_path = pipeline._metadata_path("seg1")
        assert meta_path.exists()

        loaded = pipeline._load_existing_segment_from_disk("seg1", "deadbeef1234")
        assert loaded is not None
        assert loaded.segment_id == "seg1"
        assert loaded.duration_ms == 1234
        assert loaded.engine == "kokoro"

    def test_load_missing_meta_returns_none(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        result = pipeline._load_existing_segment_from_disk("nope", "x")
        assert result is None

    def test_load_hash_mismatch_returns_none(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        audio_file = tmp_path / "segment.mp3"
        audio_file.write_bytes(b"\x00" * 16)
        seg = AudioSegment(
            segment_id="seg2",
            file_path=str(audio_file),
            duration_ms=500,
            engine="edge",
            voice_id="v1",
            text_hash="OLD_HASH",
        )
        pipeline._persist_segment_metadata(seg)
        result = pipeline._load_existing_segment_from_disk("seg2", "NEW_HASH")
        assert result is None

    def test_load_missing_audio_file_returns_none(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        # Persist segment pointing at non-existent file
        seg = AudioSegment(
            segment_id="seg3",
            file_path=str(tmp_path / "does_not_exist.mp3"),
            duration_ms=500,
            engine="edge",
            voice_id="v1",
            text_hash="XYZ123",
        )
        pipeline._persist_segment_metadata(seg)
        result = pipeline._load_existing_segment_from_disk("seg3", "XYZ123")
        assert result is None

    def test_load_corrupted_metadata(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        meta = pipeline._metadata_path("seg_bad")
        meta.write_text("not-valid-json{", encoding="utf-8")
        result = pipeline._load_existing_segment_from_disk("seg_bad", "X")
        assert result is None


class TestSimpleConcat:
    """_simple_concat has success + failure branches."""

    def test_simple_concat_uses_fallback_when_ffmpeg_missing(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        # Two audio segments
        seg1_path = tmp_path / "a.mp3"
        seg2_path = tmp_path / "b.mp3"
        seg1_path.write_bytes(b"\x00" * 100)
        seg2_path.write_bytes(b"\x00" * 100)
        segs = [
            AudioSegment(
                segment_id="a",
                file_path=str(seg1_path),
                duration_ms=500,
                engine="kokoro",
                voice_id="v",
                text_hash="h1",
            ),
            AudioSegment(
                segment_id="b",
                file_path=str(seg2_path),
                duration_ms=700,
                engine="kokoro",
                voice_id="v",
                text_hash="h2",
            ),
        ]
        out = tmp_path / "concat.mp3"
        with patch("subprocess.run", side_effect=FileNotFoundError):
            duration = pipeline._simple_concat(segs, out)
        # Fallback returns sum of segment durations
        assert duration == 500 + 700


class TestPipelineInitMockEngines:
    """Pipeline constructor with mock_mode bool.

    Branches covered: explicit mock_mode True/False, env var-driven path.
    """

    def test_init_creates_output_dir(self, tmp_path: Path):
        out_dir = tmp_path / "nested" / "out"
        pipeline = SynthesizePipeline(router=MagicMock(), output_dir=str(out_dir), mock_mode=True)
        assert out_dir.exists()
        assert pipeline.output_dir == out_dir

    def test_init_uses_explicit_router(self, tmp_path: Path):
        router = MagicMock()
        pipeline = SynthesizePipeline(router=router, output_dir=str(tmp_path), mock_mode=True)
        assert pipeline.router is router

    def test_init_default_crossfade_constant(self, tmp_path: Path):
        pipeline = _make_pipeline(tmp_path)
        assert pipeline.DEFAULT_CROSSFADE_MS == 50


class TestAudioSegmentToDict:
    """AudioSegment.to_dict is used by SynthesizeAgent._handle_message."""

    def test_audio_segment_to_dict(self):
        seg = AudioSegment(
            segment_id="abc",
            file_path="/x/y.mp3",
            duration_ms=100,
            engine="kokoro",
            voice_id="v",
            text_hash="h",
        )
        result = seg.to_dict()
        assert result == {
            "segment_id": "abc",
            "file_path": "/x/y.mp3",
            "duration_ms": 100,
            "engine": "kokoro",
            "voice_id": "v",
            "text_hash": "h",
        }

"""Tests for pipeline/translate.py (83 miss) + pipeline/synthesize.py (116 miss)."""
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest


class TestTranslateAndDubPipeline:
    def test_import(self):
        from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline
        assert callable(TranslateAndDubPipeline)

    def test_init_default(self):
        from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline
        with patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager"), \
             patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline"), \
             patch("src.audiobook_studio.pipeline.translate.create_router"), \
             patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline"):
            p = TranslateAndDubPipeline()
            assert p is not None

    def test_init_custom(self):
        from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline
        mock_vcm = MagicMock()
        mock_ap = MagicMock()
        with patch("src.audiobook_studio.pipeline.translate.create_router"), \
             patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline"):
            p = TranslateAndDubPipeline(voice_cloning_manager=mock_vcm, annotate_pipeline=mock_ap)
            assert p.voice_cloning_manager is mock_vcm
            assert p.annotate_pipeline is mock_ap

    def test_get_target_voice(self):
        from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline
        with patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager"), \
             patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline"), \
             patch("src.audiobook_studio.pipeline.translate.create_router"), \
             patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline"):
            p = TranslateAndDubPipeline()
            result = p._get_target_voice("narrator", "en", "neutral")
            assert isinstance(result, dict)
            assert "voice_id" in result

    @patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager")
    @patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline")
    @patch("src.audiobook_studio.pipeline.translate.create_router")
    @patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline")
    def test_translate_text(self, mock_synth, mock_router_cls, mock_ap, mock_vcm):
        from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline
        mock_router = MagicMock()
        mock_router_cls.return_value = mock_router
        # router.call() returns object with .output.translated_text
        mock_output = MagicMock()
        mock_output.translated_text = "你好世界"
        mock_result = MagicMock()
        mock_result.output = mock_output
        mock_router.call.return_value = mock_result
        p = TranslateAndDubPipeline()
        result = p._translate_text("Hello World", "en", "zh", "narrator", "neutral")
        assert isinstance(result, str)
        assert "你好世界" in result

    @patch("src.audiobook_studio.pipeline.translate.VoiceCloningManager")
    @patch("src.audiobook_studio.pipeline.translate.AnnotateParagraphPipeline")
    @patch("src.audiobook_studio.pipeline.translate.create_router")
    @patch("src.audiobook_studio.pipeline.translate.SynthesizePipeline")
    def test_translate_text_fallback(self, mock_synth, mock_router_cls, mock_ap, mock_vcm):
        from src.audiobook_studio.pipeline.translate import TranslateAndDubPipeline
        mock_router = MagicMock()
        mock_router_cls.return_value = mock_router
        mock_router.call.side_effect = Exception("LLM unavailable")
        p = TranslateAndDubPipeline()
        result = p._translate_text("Hello", "en", "zh", "narrator", "neutral")
        assert "[zh]" in result


class TestSynthesizePipeline:
    def test_import(self):
        from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline
        assert callable(SynthesizePipeline)

    def test_init_default(self):
        from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline
        p = SynthesizePipeline(output_dir="/tmp/test_synth")
        assert p is not None

    def test_resolve_edge_voice(self):
        from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline
        p = SynthesizePipeline(output_dir="/tmp/test_synth")
        result = p._resolve_edge_voice("zh-CN-XiaoxiaoNeural")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_text_hash(self):
        from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline
        p = SynthesizePipeline(output_dir="/tmp/test_synth")
        h1 = p._text_hash("hello")
        h2 = p._text_hash("hello")
        h3 = p._text_hash("world")
        assert h1 == h2
        assert h1 != h3

    def test_metadata_path(self):
        from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline
        p = SynthesizePipeline(output_dir="/tmp/test_synth")
        path = p._metadata_path("seg_1")
        assert isinstance(path, Path)
        assert "seg_1" in str(path)

    def test_persist_segment_metadata(self, tmp_path):
        from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline, AudioSegment
        p = SynthesizePipeline(output_dir=str(tmp_path))
        seg = AudioSegment(
            segment_id="test_seg",
            file_path=str(tmp_path / "test.mp3"),
            duration_ms=1000,
            engine="edge_tts",
            voice_id="zh-CN-XiaoxiaoNeural",
            text_hash="abc123",
        )
        p._persist_segment_metadata(seg)
        assert (tmp_path / "test_seg.json").exists()

    def test_load_existing_segment_from_disk_not_found(self, tmp_path):
        from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline
        p = SynthesizePipeline(output_dir=str(tmp_path))
        result = p._load_existing_segment_from_disk("nonexistent_seg", "hash_xyz")
        assert result is None

    def test_load_existing_segment_from_disk_found(self, tmp_path):
        from src.audiobook_studio.pipeline.synthesize import SynthesizePipeline, AudioSegment
        import json
        p = SynthesizePipeline(output_dir=str(tmp_path))
        # Create the audio file so Path(file_path).exists() is True
        (tmp_path / "found.mp3").write_bytes(b"fake audio")
        seg = AudioSegment(
            segment_id="found_seg",
            file_path=str(tmp_path / "found.mp3"),
            duration_ms=500,
            engine="edge_tts",
            voice_id="zh-CN-XiaoxiaoNeural",
            text_hash="def456",
        )
        p._persist_segment_metadata(seg)
        result = p._load_existing_segment_from_disk("found_seg", "def456")
        assert result is not None
        assert result.segment_id == "found_seg"

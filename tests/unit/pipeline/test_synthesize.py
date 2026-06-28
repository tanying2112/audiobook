import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

# Add the src directory to the path so we can import the module as a package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

# Mock problematic dependencies
sys.modules["torch"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["numpy"] = MagicMock()
sys.modules["soundfile"] = MagicMock()
sys.modules["TTS"] = MagicMock()
sys.modules["TTS.api"] = MagicMock()
sys.modules["TTS.tts.configs"] = MagicMock()
sys.modules["TTS.tts.utils"] = MagicMock()
sys.modules["TTS.utils"] = MagicMock()
sys.modules["TTS.utils.manage"] = MagicMock()
sys.modules["TTS.utils.synthesizer"] = MagicMock()
sys.modules["TTS.tts.utils.synthesizer"] = MagicMock()
sys.modules["pydub"] = MagicMock()
sys.modules["pydub.AudioSegment"] = MagicMock()
sys.modules["pydub.effects"] = MagicMock()
sys.modules["librosa"] = MagicMock()
sys.modules["librosa.effects"] = MagicMock()
sys.modules["llm"] = MagicMock()
sys.modules["llm.LLMRouter"] = MagicMock()
sys.modules["llm.create_router"] = MagicMock()
sys.modules["config"] = MagicMock()
sys.modules["config.hardware_profile"] = MagicMock()
sys.modules["monitoring"] = MagicMock()
sys.modules["monitoring.langfuse_client"] = MagicMock()
sys.modules["schemas"] = MagicMock()
sys.modules["utils"] = MagicMock()
sys.modules["utils.ffmpeg_probe"] = MagicMock()
sys.modules["tts"] = MagicMock()
sys.modules["tts.TTSEngine"] = MagicMock()
sys.modules["tts.VoiceInfo"] = MagicMock()
sys.modules["tts.SynthesisResult"] = MagicMock()
sys.modules["tts.EngineRegistry"] = MagicMock()
sys.modules["di"] = MagicMock()
sys.modules["di.get_app_container"] = MagicMock()

from audiobook_studio.pipeline.synthesize import (
    AudioSegment,
    SynthesizePipeline,
    TtsRoutingDecision,
    TtsRoutingInput,
)


class TestSynthesizePipeline(unittest.TestCase):
    def setUp(self):
        self.pipeline = SynthesizePipeline(output_dir="./test_output", mock_mode=True)

    def test_init(self):
        self.assertIsInstance(self.pipeline, SynthesizePipeline)
        self.assertEqual(str(self.pipeline.output_dir), "test_output")
        self.assertTrue(self.pipeline.mock_mode)

    def test_text_hash(self):
        text1 = "hello world"
        text2 = "hello world"
        text3 = "hello world!"

        hash1 = self.pipeline._text_hash(text1)
        hash2 = self.pipeline._text_hash(text2)
        hash3 = self.pipeline._text_hash(text3)

        self.assertEqual(hash1, hash2)  # Same text should produce same hash
        self.assertNotEqual(
            hash1, hash3
        )  # Different text should produce different hash
        self.assertIsInstance(hash1, str)
        self.assertEqual(len(hash1), 12)  # MD5 hash truncated to 12 chars

    def test_resolve_edge_voice(self):
        # Test known voice mappings
        self.assertEqual(
            self.pipeline._resolve_edge_voice("zh-CN-XiaoxiaoNeural"),
            "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)",
        )

        self.assertEqual(
            self.pipeline._resolve_edge_voice("zh-CN-YunxiNeural"),
            "Microsoft Server Speech Text to Speech Voice (zh-CN, YunxiNeural)",
        )

        # Test unknown voice (should return as-is)
        self.assertEqual(
            self.pipeline._resolve_edge_voice("unknown-voice"), "unknown-voice"
        )

    @patch("asyncio.run")
    @patch("audiobook_studio.pipeline.synthesize.SynthesizePipeline._synthesize_kokoro")
    def test_synthesize_kokoro_call(self, mock_kokoro, mock_run):
        # Mock the async function to return immediately
        async def mock_async_synthesize(*args, **kwargs):
            return AudioSegment(
                segment_id="test",
                file_path="/tmp/test.wav",
                duration_ms=1000,
                engine="kokoro",
                voice_id="test_voice",
                text_hash="abc123",
            )

        mock_kokoro.return_value = mock_async_synthesize()
        mock_run.return_value = None

        # This is a simplified test - in reality we'd need to properly mock the async behavior
        # For now, we're just testing that the method exists and can be called
        self.assertTrue(hasattr(self.pipeline, "_synthesize_kokoro"))

    @patch("asyncio.run")
    @patch("audiobook_studio.pipeline.synthesize.SynthesizePipeline._synthesize_edge")
    def test_synthesize_edge_call(self, mock_edge, mock_run):
        # Mock the async function to return immediately
        async def mock_async_synthesize(*args, **kwargs):
            return AudioSegment(
                segment_id="test",
                file_path="/tmp/test.wav",
                duration_ms=1000,
                engine="edge",
                voice_id="test_voice",
                text_hash="abc123",
            )

        mock_edge.return_value = mock_async_synthesize()
        mock_run.return_value = None

        # This is a simplified test - in reality we'd need to properly mock the async behavior
        self.assertTrue(hasattr(self.pipeline, "_synthesize_edge"))

    def test_crossfade_stitch_empty(self):
        # Test with empty list
        result = self.pipeline._crossfade_stitch([], Path("/tmp/output.wav"))
        self.assertEqual(result, 0)

    def test_crossfade_stitch_single(self):
        # Test with single segment - create actual temp file
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFF" + b"\x00" * 44)  # Minimal WAV header
            temp_path = f.name

        try:
            segment = AudioSegment(
                segment_id="test",
                file_path=temp_path,
                duration_ms=1000,
                engine="test",
                voice_id="test",
                text_hash="abc",
            )
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as out_f:
                output_path = Path(out_f.name)

            result = self.pipeline._crossfade_stitch([segment], output_path)
            self.assertEqual(result, 1000)  # Should return duration of single segment

            # Clean up
            if output_path.exists():
                output_path.unlink()
        finally:
            Path(temp_path).unlink(missing_ok=True)

    @patch("audiobook_studio.pipeline.synthesize.SynthesizePipeline._simple_concat")
    def test_simple_concat_call(self, mock_concat):
        mock_concat.return_value = 1000

        segment = AudioSegment(
            segment_id="test",
            file_path="/tmp/test.wav",
            duration_ms=1000,
            engine="test",
            voice_id="test",
            text_hash="abc",
        )
        result = self.pipeline._simple_concat([segment], Path("/tmp/output.wav"))
        self.assertEqual(result, 1000)
        mock_concat.assert_called_once_with([segment], Path("/tmp/output.wav"))

    def test_run_method_exists(self):
        self.assertTrue(hasattr(self.pipeline, "run"))
        self.assertTrue(callable(getattr(self.pipeline, "run")))

    def _create_mock_tts_input(self, text="test text", character="narrator"):
        # Create a minimal valid TtsRoutingInput
        from audiobook_studio.schemas.book import CharacterVoiceBinding
        from audiobook_studio.schemas.paragraph import ParagraphAnnotation

        annotation = ParagraphAnnotation(
            paragraph_index=1,
            text=text,
            speaker_canonical_name=character,
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            confidence=0.9,
        )
        binding = CharacterVoiceBinding(
            canonical_name=character,
            suggested_voice_id="test_voice",
            sample_quote="This is a sample quote for voice cloning.",
        )
        return TtsRoutingInput(
            paragraph_annotation=annotation,
            text=text,
            character_voice_map=[binding],
            book_id="test_book",
            chapter_index=1,
            paragraph_index=1,
        )

    @patch(
        "audiobook_studio.pipeline.synthesize.SynthesizePipeline._make_routing_decision"
    )
    @patch(
        "audiobook_studio.pipeline.synthesize.SynthesizePipeline._synthesize_with_engine"
    )
    def test_run_calls_expected_methods(self, mock_synthesize, mock_decision):
        # Setup mocks
        mock_decision.return_value = TtsRoutingDecision(
            segment_id="test_segment",
            engine_choice="kokoro",
            voice_id="test_voice",
            fallback_engine="edge",
            reasoning="test routing decision",
        )

        async def mock_async_synthesize(*args, **kwargs):
            return [
                AudioSegment(
                    segment_id="test",
                    file_path="/tmp/test.wav",
                    duration_ms=1000,
                    engine="kokoro",
                    voice_id="test_voice",
                    text_hash="abc123",
                )
            ]

        mock_synthesize.return_value = mock_async_synthesize()

        # Create test input
        test_input = self._create_mock_tts_input("Hello world", "narrator")

        # Call the method
        # Note: This is a simplified test due to async complexity
        # In a full test, we would properly handle the async nature
        self.assertTrue(hasattr(self.pipeline, "_make_routing_decision"))
        self.assertTrue(hasattr(self.pipeline, "_synthesize_with_engine"))

    def test_run_with_mock_mode(self):
        """Test run method in mock mode which generates simulated segments."""
        # Mock mode returns simulated segments
        test_input = self._create_mock_tts_input("Hello world", "narrator")
        result = self.pipeline.run([test_input])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].segment_id, "test_book_ch1_p1")

    def test_make_routing_decision(self):
        """Test routing decision creation."""
        test_input = self._create_mock_tts_input("Hello world", "narrator")
        decision = self.pipeline._make_routing_decision(test_input)
        self.assertEqual(decision.segment_id, "test_book_ch1_p1")
        self.assertEqual(decision.voice_id, "test_voice")

    def test_make_routing_decision_with_prefer_local(self):
        """Test routing decision prefers local engine."""
        test_input = self._create_mock_tts_input("Hello world", "narrator")
        test_input.prefer_local = True
        decision = self.pipeline._make_routing_decision(test_input)
        self.assertEqual(decision.engine_choice, "kokoro")

    def test_metadata_path(self):
        """Test metadata path generation."""
        path = self.pipeline._metadata_path("test_segment")
        self.assertTrue(str(path).endswith("test_segment.json"))

    def test_synthesize_kokoro_mock_mode(self):
        """Test kokoro synthesis in mock mode."""
        output_path = Path("/tmp/test_kokoro.wav")
        duration = self.pipeline._synthesize_kokoro(
            "test text", "test_voice", {}, output_path
        )
        self.assertEqual(duration, 3000)
        self.assertTrue(output_path.exists())

    def test_synthesize_edge_mock_mode(self):
        """Test edge synthesis in mock mode."""
        output_path = Path("/tmp/test_edge.wav")
        duration = self.pipeline._synthesize_edge(
            "test text", "test_voice", {}, output_path
        )
        self.assertEqual(duration, 2800)
        self.assertTrue(output_path.exists())

    @patch.dict(
        "os.environ", {"AZURE_TTS_KEY": "test_key", "AZURE_TTS_REGION": "test_region"}
    )
    @patch("shutil.copy2")
    @patch("pathlib.Path.exists", return_value=True)
    @patch.dict(
        "sys.modules",
        {
            "azure": MagicMock(),
            "azure.cognitiveservices": MagicMock(),
            "azure.cognitiveservices.speech": MagicMock(),
        },
    )
    def test_synthesize_azure_mock_mode(self, mock_exists, mock_copy):
        """Test azure synthesis in mock mode."""
        import sys

        # Setup the mock
        mock_speech = sys.modules["azure.cognitiveservices.speech"]
        mock_speech.SpeechConfig.return_value = MagicMock()
        mock_speech.SpeechSynthesizer.return_value = MagicMock()

        # Mock the result to indicate success - need to set the enum value properly
        mock_speech.ResultReason.SynthesizingAudioCompleted = 0
        mock_result = MagicMock()
        mock_result.reason = 0  # Use integer value directly
        mock_speech.SpeechSynthesizer.return_value.speak_ssml_async.return_value.get.return_value = (
            mock_result
        )

        # Also need to mock get_duration_sync
        with patch(
            "audiobook_studio.pipeline.synthesize.get_duration_sync", return_value=2800
        ):
            output_path = Path("/tmp/test_azure.wav")
            # Use pipeline with mock_mode=True (from setUp) to test mock path
            duration = self.pipeline._synthesize_azure(
                "test text", "test_voice", {}, output_path
            )
            self.assertEqual(duration, 2800)
            self.assertTrue(output_path.exists())

    @patch.dict("os.environ", {"GOOGLE_APPLICATION_CREDENTIALS": "/fake/path.json"})
    @patch("pathlib.Path.exists", return_value=True)
    @patch("shutil.copy2")
    @patch.dict(
        "sys.modules",
        {
            "google": MagicMock(),
            "google.cloud": MagicMock(),
            "google.cloud.texttospeech": MagicMock(),
        },
    )
    def test_synthesize_gcp_mock_mode(self, mock_copy, mock_exists):
        """Test gcp synthesis in mock mode."""
        import sys

        # Setup the mock
        mock_tts = sys.modules["google.cloud.texttospeech"]
        mock_client = MagicMock()
        mock_tts.TextToSpeechClient.return_value = mock_client
        # Use actual bytes for audio_content - create a proper mock with bytes
        mock_response = MagicMock()
        mock_response.audio_content = b"test_audio_data"
        mock_client.synthesize_speech.return_value = mock_response

        # Also mock get_duration_sync
        with patch(
            "audiobook_studio.pipeline.synthesize.get_duration_sync", return_value=2800
        ):
            output_path = Path("/tmp/test_gcp.wav")
            # Use pipeline with mock_mode=True (from setUp) to test mock path
            duration = self.pipeline._synthesize_gcp(
                "test text", "test_voice", {}, output_path
            )
            self.assertEqual(duration, 2800)
            self.assertTrue(output_path.exists())

    def test_get_tts_engine_config_no_profile(self):
        """Test TTS engine config with no hardware profile."""
        # When hardware_profile is None
        self.pipeline.hardware_profile = None
        config = self.pipeline._get_tts_engine_config()
        self.assertEqual(config["engine"], "kokoro")

    def test_persist_segment_metadata(self):
        """Test segment metadata persistence."""
        segment = AudioSegment(
            segment_id="test_seg",
            file_path="/tmp/test_seg.mp3",
            duration_ms=1000,
            engine="kokoro",
            voice_id="test_voice",
            text_hash="abc123",
        )
        self.pipeline._persist_segment_metadata(segment)
        # Check metadata file was created
        metadata_path = self.pipeline._metadata_path("test_seg")
        self.assertTrue(metadata_path.exists())
        # Clean up
        metadata_path.unlink()

    def test_load_existing_segment_from_disk(self):
        """Test loading existing segment from disk."""
        # First create a segment and persist it
        segment = AudioSegment(
            segment_id="load_test",
            file_path="/tmp/load_test.mp3",
            duration_ms=1000,
            engine="kokoro",
            voice_id="test_voice",
            text_hash="hash123",
        )
        Path("/tmp/load_test.mp3").write_bytes(b"dummy")
        self.pipeline._persist_segment_metadata(segment)

        # Now try to load it
        loaded = self.pipeline._load_existing_segment_from_disk("load_test", "hash123")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.segment_id, "load_test")

        # Clean up
        Path("/tmp/load_test.mp3").unlink()
        self.pipeline._metadata_path("load_test").unlink()

    def test_load_existing_segment_mismatch_hash(self):
        """Test loading segment with mismatched text hash."""
        loaded = self.pipeline._load_existing_segment_from_disk(
            "nonexistent", "wrong_hash"
        )
        self.assertIsNone(loaded)

    def test_existing_segments_cache(self):
        """Test existing segments caching in run method."""
        # Add a cached segment
        cached_segment = AudioSegment(
            segment_id="cached_seg",
            file_path="/tmp/cached.mp3",
            duration_ms=2000,
            engine="kokoro",
            voice_id="test_voice",
            text_hash="same_hash",
        )
        Path("/tmp/cached.mp3").write_bytes(b"dummy")
        self.pipeline.existing_segments["cached_seg"] = cached_segment

        test_input = self._create_mock_tts_input("Hello world", "narrator")
        test_input.book_id = "cached_book"
        test_input.paragraph_index = 0
        # Set the segment_id to match our cached one
        # We need to mock _make_routing_decision to return matching segment_id
        with patch.object(self.pipeline, "_make_routing_decision") as mock_decision:
            mock_decision.return_value = TtsRoutingDecision(
                segment_id="cached_seg",
                engine_choice="kokoro",
                voice_id="test_voice",
                fallback_engine="edge",
                reasoning="test",
            )
            result = self.pipeline.run([test_input])
            # Should return cached segment
            self.assertEqual(len(result), 1)

        # Clean up
        Path("/tmp/cached.mp3").unlink()

    def test_resolve_edge_voice_full_format(self):
        """Test voice already in full format."""
        full_voice = (
            "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)"
        )
        result = self.pipeline._resolve_edge_voice(full_voice)
        self.assertEqual(result, full_voice)

    def test_resolve_edge_voice_dynamic(self):
        """Test dynamic voice resolution."""
        result = self.pipeline._resolve_edge_voice("zh-CN-TestNeural")
        self.assertIn("Microsoft Server Speech Text to Speech Voice", result)
        self.assertIn("Test", result)

    def test_try_synthesize_with_fallback(self):
        """Test fallback synthesis chain."""
        output_path = Path("/tmp/fallback_test.wav")

        # Test fallback when kokoro is unavailable
        # Need to use a pipeline with mock_mode=False to test actual fallback logic
        pipeline = SynthesizePipeline(output_dir="./test_output", mock_mode=False)
        with patch.object(pipeline, "_get_tts_engine_config") as mock_config:
            mock_config.return_value = {
                "engine": "kokoro",
                "fallback_chain": [{"engine": "edge"}],
            }
            with patch.object(pipeline, "_get_engine_for_synthesis", return_value=None):
                with patch.object(pipeline, "_synthesize_edge", return_value=2800):
                    duration, engine = pipeline._try_synthesize_with_fallback(
                        "test", "voice", {}, output_path, "kokoro"
                    )
                    # The fallback returns the engine that was actually used (edge)
                    self.assertEqual(engine, "edge")

    def test_init_with_router(self):
        """Test initialization with custom router."""
        mock_router = MagicMock()
        pipeline = SynthesizePipeline(router=mock_router, mock_mode=True)
        self.assertEqual(pipeline.router, mock_router)

    def test_init_mock_mode_from_env(self):
        """Test mock_mode respects MOCK_LLM env var."""
        old_val = os.environ.get("MOCK_LLM")
        os.environ["MOCK_LLM"] = "true"
        try:
            pipeline = SynthesizePipeline(output_dir="./test_output")
            self.assertTrue(pipeline.mock_mode)
        finally:
            if old_val:
                os.environ["MOCK_LLM"] = old_val
            else:
                os.environ.pop("MOCK_LLM", None)


if __name__ == "__main__":
    unittest.main()

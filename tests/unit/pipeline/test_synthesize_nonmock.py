"""Tests for SynthesizePipeline using FakeRemoteTTSPort for non-mock mode testing.

These tests verify the pipeline's integration with the RemoteTTSPort abstraction
without requiring actual TTS engine installations.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np

# Record the original sys.modules entries for third-party modules this suite
# mocks at import time. These are restored in tearDownModule() so the mocks do
# not leak into other test modules (notably instructor -> LLM client tests).
_MODULE_MOCK_TARGETS = [
    "edge_tts",
    "azure",
    "azure.cognitiveservices",
    "azure.cognitiveservices.speech",
    "google",
    "google.cloud",
    "google.cloud.texttospeech",
    "google.cloud.texttospeech_v1",
    "google.protobuf",
    "instructor",
    "opentelemetry",
    "opentelemetry.metrics",
    "opentelemetry.trace",
    "opentelemetry.exporter",
    "opentelemetry.exporter.prometheus",
    "opentelemetry.exporter.otlp",
    "opentelemetry.exporter.otlp.proto",
    "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
    "opentelemetry.sdk",
    "opentelemetry.sdk.metrics",
    "opentelemetry.sdk.metrics.export",
    "opentelemetry.sdk.trace",
    "opentelemetry.sdk.trace.export",
    "opentelemetry.sdk.resources",
    "langfuse",
    "langfuse.decorators",
    "langfuse.client",
]
_RECORD_TO_RESTORE = _MODULE_MOCK_TARGETS
_ORIGINAL_MODULES = {name: sys.modules.get(name) for name in _RECORD_TO_RESTORE}

# Mocks to prevent ModuleNotFoundError for external dependencies only
# DO NOT mock audiobook_studio.tts - we need the real FakeRemoteTTSPort
sys.modules["edge_tts"] = MagicMock()
sys.modules["azure"] = MagicMock()
sys.modules["azure.cognitiveservices"] = MagicMock()
azure_speech_mock = MagicMock()
azure_speech_mock.__path__ = []
sys.modules["azure.cognitiveservices.speech"] = azure_speech_mock
sys.modules["azure"].cognitiveservices.speech = azure_speech_mock
sys.modules["google"] = MagicMock()
sys.modules["google.cloud"] = MagicMock()
sys.modules["google.cloud.texttospeech"] = MagicMock()
sys.modules["google.cloud.texttospeech_v1"] = MagicMock()
sys.modules["instructor"] = MagicMock()

# OpenTelemetry mock with package structure
opentelemetry_mock = MagicMock()
opentelemetry_mock.__path__ = []  # Mark as package
opentelemetry_mock.trace = MagicMock()
opentelemetry_mock.metrics = MagicMock()
opentelemetry_mock.metrics.Counter = MagicMock()
opentelemetry_mock.metrics.Histogram = MagicMock()
opentelemetry_mock.exporter = MagicMock()
opentelemetry_mock.exporter.prometheus = MagicMock()
opentelemetry_mock.exporter.otlp = MagicMock()
opentelemetry_mock.exporter.otlp.proto = MagicMock()
opentelemetry_mock.exporter.otlp.proto.grpc = MagicMock()
opentelemetry_mock.exporter.otlp.proto.grpc.trace_exporter = MagicMock()
opentelemetry_mock.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter = MagicMock()
opentelemetry_mock.sdk = MagicMock()
opentelemetry_mock.sdk.metrics = MagicMock()
opentelemetry_mock.sdk.metrics.MeterProvider = MagicMock()
opentelemetry_mock.sdk.metrics.export = MagicMock()
opentelemetry_mock.sdk.metrics.export.PeriodicExportingMetricReader = MagicMock()
opentelemetry_mock.sdk.trace = MagicMock()
opentelemetry_mock.sdk.trace.TracerProvider = MagicMock()
opentelemetry_mock.sdk.resources = MagicMock()
opentelemetry_mock.sdk.resources.SERVICE_NAME = "test"
opentelemetry_mock.sdk.resources.SERVICE_VERSION = "test"
opentelemetry_mock.sdk.resources.Resource = MagicMock()
sys.modules["opentelemetry"] = opentelemetry_mock
sys.modules["opentelemetry.metrics"] = opentelemetry_mock.metrics
sys.modules["opentelemetry.trace"] = opentelemetry_mock.trace
sys.modules["opentelemetry.exporter"] = opentelemetry_mock.exporter
sys.modules["opentelemetry.exporter.prometheus"] = opentelemetry_mock.exporter.prometheus
sys.modules["opentelemetry.exporter.otlp"] = opentelemetry_mock.exporter.otlp
sys.modules["opentelemetry.exporter.otlp.proto"] = opentelemetry_mock.exporter.otlp.proto
sys.modules["opentelemetry.exporter.otlp.proto.grpc"] = opentelemetry_mock.exporter.otlp.proto.grpc
sys.modules["opentelemetry.exporter.otlp.proto.grpc.trace_exporter"] = (
    opentelemetry_mock.exporter.otlp.proto.grpc.trace_exporter
)
opentelemetry_mock.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter = MagicMock()
sys.modules["opentelemetry.sdk"] = opentelemetry_mock.sdk
sys.modules["opentelemetry.sdk.metrics"] = opentelemetry_mock.sdk.metrics
sys.modules["opentelemetry.sdk.metrics.export"] = opentelemetry_mock.sdk.metrics.export
opentelemetry_mock.sdk.trace.export = MagicMock()
opentelemetry_mock.sdk.trace.export.BatchSpanProcessor = MagicMock()
opentelemetry_mock.sdk.trace.export.ConsoleSpanExporter = MagicMock()
sys.modules["opentelemetry.sdk.trace"] = opentelemetry_mock.sdk.trace
sys.modules["opentelemetry.sdk.trace.export"] = opentelemetry_mock.sdk.trace.export
sys.modules["opentelemetry.sdk.resources"] = opentelemetry_mock.sdk.resources
sys.modules["google.protobuf"] = MagicMock()

sys.modules["langfuse"] = MagicMock()
sys.modules["langfuse.decorators"] = MagicMock()
sys.modules["langfuse.client"] = MagicMock()

# Prevent __spec__ errors
for mod in ["google", "azure", "opentelemetry", "langfuse", "langfuse.decorators", "langfuse.client"]:
    if mod in sys.modules:
        sys.modules[mod].__spec__ = None

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../src"))

from audiobook_studio.pipeline.synthesize import AudioSegment, SynthesizePipeline
from audiobook_studio.schemas import (
    TtsRoutingInput,
    TtsRoutingDecision,
    ParagraphAnnotation,
)
from audiobook_studio.schemas.book import CharacterVoiceBinding
from audiobook_studio.tts import FakeRemoteTTSPort, TTSTaskPayload, TTSVoiceAnchor, TTSProsody, TTSStatus, TTSTaskResult


class DummyObserve:
    def __call__(self, *args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return args[0]

        def decorator(f):
            return f

        return decorator


sys.modules["langfuse.decorators"].observe = DummyObserve()


class TestSynthesizePipelineNonMock(unittest.TestCase):
    """Test SynthesizePipeline with FakeRemoteTTSPort (non-mock mode)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        # Create a fake port with fast synthesis delay for tests
        self.fake_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)
        self.pipeline = SynthesizePipeline(
            output_dir=self.temp_dir,
            mock_mode=False,
            port=self.fake_port,
        )

    def tearDown(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)
        # Clean up fake port background tasks
        # Use the event loop properly
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Schedule close in the running loop
                asyncio.create_task(self.fake_port.close())
            else:
                loop.run_until_complete(self.fake_port.close())
        except RuntimeError:
            # No event loop, create one
            asyncio.run(self.fake_port.close())

    def _create_mock_tts_input(
        self,
        text="test text",
        character="narrator",
        paragraph_index=1,
        book_id="test_book",
        chapter_index=1,
    ):
        """Create a TtsRoutingInput for testing."""
        annotation = ParagraphAnnotation(
            paragraph_index=paragraph_index,
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
            book_id=book_id,
            chapter_index=chapter_index,
            paragraph_index=paragraph_index,
        )

    def test_pipeline_initialization(self):
        """Test pipeline initializes correctly with fake port."""
        self.assertIsInstance(self.pipeline, SynthesizePipeline)
        self.assertFalse(self.pipeline.mock_mode)
        self.assertIsNotNone(self.pipeline._port)
        self.assertIsInstance(self.pipeline._port, FakeRemoteTTSPort)

    def test_synthesize_via_port_success(self):
        """Test _synthesize_via_port succeeds with fake port."""
        async def run_test():
            duration, engine = await self.pipeline._synthesize_via_port(
                text="Hello world",
                voice_id="test_voice",
                prosody={},
                output_path=Path(self.temp_dir) / "test.wav",
                segment_id="seg_001",
            )
            self.assertGreater(duration, 0)
            self.assertEqual(engine, "hermes")  # Default engine from fake port

        asyncio.run(run_test())

    def test_synthesize_via_port_creates_audio_file(self):
        """Test that synthesis creates an audio file at output path."""
        async def run_test():
            output_path = Path(self.temp_dir) / "test_output.wav"
            await self.pipeline._synthesize_via_port(
                text="Test audio generation",
                voice_id="test_voice",
                prosody={},
                output_path=output_path,
                segment_id="seg_002",
            )
            self.assertTrue(output_path.exists())
            self.assertGreater(output_path.stat().st_size, 0)

        asyncio.run(run_test())

    def test_synthesize_via_port_respects_prosody(self):
        """Test that prosody parameters are included in payload."""
        async def run_test():
            prosody = {"rate": 1.2, "pitch": 0.5, "volume": -0.2, "emotion": "happy"}
            await self.pipeline._synthesize_via_port(
                text="Test with prosody",
                voice_id="test_voice",
                prosody=prosody,
                output_path=Path(self.temp_dir) / "prosody.wav",
                segment_id="seg_003",
            )
            # Check the task was submitted with correct prosody
            # Task ID format: seg_003-<timestamp>
            for task_id, state in self.fake_port._tasks.items():
                if task_id.startswith("seg_003-"):
                    self.assertEqual(state.payload.prosody.rate, 1.2)
                    self.assertEqual(state.payload.prosody.pitch, 0.5)
                    self.assertEqual(state.payload.prosody.volume, -0.2)
                    self.assertEqual(state.payload.prosody.emotion, "happy")
                    return
            self.fail("Task not found in fake port")

        asyncio.run(run_test())

    def test_run_single_segment(self):
        """Test run() with a single segment."""
        inputs = [self._create_mock_tts_input(text="Hello world", paragraph_index=1)]
        segments = self.pipeline.run(inputs)

        self.assertEqual(len(segments), 1)
        self.assertIsInstance(segments[0], AudioSegment)
        self.assertEqual(segments[0].segment_id, "test_book_ch1_p1")
        self.assertTrue(Path(segments[0].file_path).exists())
        self.assertGreater(segments[0].duration_ms, 0)

    def test_run_multiple_segments(self):
        """Test run() with multiple segments."""
        inputs = [
            self._create_mock_tts_input(text="First paragraph", paragraph_index=1),
            self._create_mock_tts_input(text="Second paragraph", paragraph_index=2),
            self._create_mock_tts_input(text="Third paragraph", paragraph_index=3),
        ]
        segments = self.pipeline.run(inputs)

        self.assertEqual(len(segments), 3)
        for i, seg in enumerate(segments):
            self.assertEqual(seg.segment_id, f"test_book_ch1_p{i+1}")
            self.assertTrue(Path(seg.file_path).exists())

    def test_run_skips_unchanged_segments(self):
        """Test that unchanged segments are skipped on re-run."""
        inputs = [self._create_mock_tts_input(text="Same text", paragraph_index=1)]

        # First run
        segments1 = self.pipeline.run(inputs)
        self.assertEqual(len(segments1), 1)

        # Second run with same text - should skip
        segments2 = self.pipeline.run(inputs)
        self.assertEqual(len(segments2), 1)
        # Should be the same segment object (from cache)
        self.assertEqual(segments2[0].file_path, segments1[0].file_path)

    def test_run_regenerates_changed_segments(self):
        """Test that changed segments are regenerated (content changes, path stays same)."""
        inputs1 = [self._create_mock_tts_input(text="Original text", paragraph_index=1)]
        segments1 = self.pipeline.run(inputs1)
        original_path = segments1[0].file_path
        original_hash = segments1[0].text_hash

        # Change the text
        inputs2 = [self._create_mock_tts_input(text="Modified text", paragraph_index=1)]
        segments2 = self.pipeline.run(inputs2)

        # Path stays the same (segment_id unchanged), but content hash changes
        self.assertEqual(segments2[0].file_path, original_path)
        self.assertNotEqual(segments2[0].text_hash, original_hash)
        # File should have been overwritten with new content
        self.assertTrue(Path(original_path).exists())

    def test_synthesize_with_failure_rate(self):
        """Test synthesis handles failures from port."""
        # Create a port with 100% failure rate
        failing_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=1.0)
        pipeline = SynthesizePipeline(
            output_dir=self.temp_dir,
            mock_mode=False,
            port=failing_port,
        )

        inputs = [self._create_mock_tts_input(text="Will fail", paragraph_index=1)]

        with self.assertRaises(RuntimeError) as ctx:
            pipeline.run(inputs)
        self.assertIn("Synthesis failed", str(ctx.exception))

        asyncio.run(failing_port.close())

    def test_synthesize_with_custom_failure_mode(self):
        """Test synthesis with custom failure mode function."""
        def fail_on_long_text(payload: TTSTaskPayload) -> bool:
            return len(payload.text) > 10

        failing_port = FakeRemoteTTSPort(
            synthesis_delay=0.01, failure_rate=0.0, failure_mode=fail_on_long_text
        )
        pipeline = SynthesizePipeline(
            output_dir=self.temp_dir,
            mock_mode=False,
            port=failing_port,
        )

        # Short text should succeed
        inputs_short = [self._create_mock_tts_input(text="Short", paragraph_index=1)]
        segments_short = pipeline.run(inputs_short)
        self.assertEqual(len(segments_short), 1)

        # Long text should fail
        inputs_long = [self._create_mock_tts_input(text="This text is very long indeed", paragraph_index=1)]
        with self.assertRaises(RuntimeError):
            pipeline.run(inputs_long)

        asyncio.run(failing_port.close())

    def test_quality_check_integration(self):
        """Test that quality check runs after synthesis."""
        # Use a port with good quality scores
        quality_port = FakeRemoteTTSPort(
            synthesis_delay=0.01,
            failure_rate=0.0,
            quality_scores={"dnsmos": 4.5, "wer": 0.02, "speaker_sim": 0.98},
        )
        pipeline = SynthesizePipeline(
            output_dir=self.temp_dir,
            mock_mode=False,
            port=quality_port,
        )

        inputs = [self._create_mock_tts_input(text="Quality test", paragraph_index=1)]
        segments = pipeline.run(inputs)

        self.assertEqual(len(segments), 1)
        # Quality report should be generated
        report_path = Path(self.temp_dir) / "quality_report.json"
        self.assertTrue(report_path.exists())

        asyncio.run(quality_port.close())

    def test_quality_check_failure_triggers_retry(self):
        """Test that quality failures trigger retry via callback."""
        # Port with poor quality scores that will fail quality check
        poor_quality_port = FakeRemoteTTSPort(
            synthesis_delay=0.01,
            failure_rate=0.0,
            quality_scores={"dnsmos": 2.0, "wer": 0.5, "speaker_sim": 0.3},  # Poor scores
        )
        pipeline = SynthesizePipeline(
            output_dir=self.temp_dir,
            mock_mode=False,
            port=poor_quality_port,
        )

        inputs = [self._create_mock_tts_input(text="Poor quality test", paragraph_index=1)]
        # Should still return segments (retries happen internally)
        segments = pipeline.run(inputs)
        self.assertEqual(len(segments), 1)

        asyncio.run(poor_quality_port.close())

    def test_synthesize_via_port_cancellation(self):
        """Test that cancellation works during synthesis."""
        async def run_test():
            # Start synthesis
            task_id = "cancel_test"
            payload = TTSTaskPayload(
                text="Long text to synthesize",
                voice_anchor=TTSVoiceAnchor(voice_id="test", speaker_name=None, language="zh-CN"),
                prosody=TTSProsody(rate=1.0, pitch=0.0, volume=0.0),
            )
            await self.fake_port.submit(task_id, payload)

            # Immediately cancel
            cancelled = await self.fake_port.cancel(task_id)
            self.assertTrue(cancelled)

            # Wait a bit and check status
            await asyncio.sleep(0.05)
            status = await self.fake_port.get_status(task_id)
            self.assertEqual(status.status, TTSStatus.FAILED)
            self.assertIn("Cancelled", status.error_message or "")

        asyncio.run(run_test())

    def test_port_health_check(self):
        """Test port health check returns expected stats."""
        async def run_test():
            health = await self.fake_port.health_check()
            self.assertTrue(health["healthy"])
            self.assertEqual(health["pending_count"], 0)
            self.assertEqual(health["running_count"], 0)
            self.assertEqual(health["done_count"], 0)
            self.assertEqual(health["failed_count"], 0)

            # Submit a task
            payload = TTSTaskPayload(
                text="Health check test",
                voice_anchor=TTSVoiceAnchor(voice_id="test", speaker_name=None, language="zh-CN"),
                prosody=TTSProsody(rate=1.0, pitch=0.0, volume=0.0),
            )
            await self.fake_port.submit("health_test", payload)

            # Check health again
            health = await self.fake_port.health_check()
            self.assertEqual(health["pending_count"] + health["running_count"], 1)

        asyncio.run(run_test())

    def test_persist_and_load_segment_metadata(self):
        """Test that segment metadata is persisted and loaded correctly."""
        inputs = [self._create_mock_tts_input(text="Persist test", paragraph_index=1)]
        segments = self.pipeline.run(inputs)

        self.assertEqual(len(segments), 1)
        segment = segments[0]
        original_path = segment.file_path
        original_hash = segment.text_hash

        # Create new pipeline instance with same output dir
        new_port = FakeRemoteTTSPort(synthesis_delay=0.01, failure_rate=0.0)
        new_pipeline = SynthesizePipeline(
            output_dir=self.temp_dir,
            mock_mode=False,
            port=new_port,
        )

        # Run with same inputs - should load from disk
        segments2 = new_pipeline.run(inputs)
        self.assertEqual(len(segments2), 1)
        self.assertEqual(segments2[0].file_path, original_path)
        self.assertEqual(segments2[0].text_hash, original_hash)

        asyncio.run(new_port.close())

    def test_crossfade_stitching_multiple_segments(self):
        """Test that crossfade stitching is attempted for multiple segments."""
        inputs = [
            self._create_mock_tts_input(text="First segment", paragraph_index=1),
            self._create_mock_tts_input(text="Second segment", paragraph_index=2),
        ]
        segments = self.pipeline.run(inputs)

        self.assertEqual(len(segments), 2)
        # Chapter output should exist (stitched) - may fail if ffmpeg not available
        for seg in segments:
            self.assertTrue(Path(seg.file_path).exists())

    def test_synthesize_via_port_empty_text_raises(self):
        """Test that empty text raises ValueError."""
        async def run_test():
            with self.assertRaises(ValueError) as ctx:
                await self.pipeline._synthesize_via_port(
                    text="",  # Empty text
                    voice_id="test_voice",
                    prosody={},
                    output_path=Path(self.temp_dir) / "empty.wav",
                    segment_id="seg_empty",
                )
            self.assertIn("non-empty", str(ctx.exception))

        asyncio.run(run_test())

    def test_pipeline_with_different_voices(self):
        """Test pipeline handles different voices per segment."""
        inputs = [
            self._create_mock_tts_input(text="Narrator speaks", character="narrator", paragraph_index=1),
            self._create_mock_tts_input(text="Character speaks", character="hero", paragraph_index=2),
        ]
        segments = self.pipeline.run(inputs)

        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].voice_id, "test_voice")
        self.assertEqual(segments[1].voice_id, "test_voice")  # Same binding in test

    def test_synthesize_via_port_duration_calculation(self):
        """Test that duration is calculated from audio file."""
        async def run_test():
            output_path = Path(self.temp_dir) / "duration_test.wav"
            duration, engine = await self.pipeline._synthesize_via_port(
                text="A" * 100,  # 100 chars
                voice_id="test_voice",
                prosody={},
                output_path=output_path,
                segment_id="seg_duration",
            )
            # Duration should be proportional to text length (~50ms per char in fake port)
            expected_approx = 100 * 50
            self.assertAlmostEqual(duration, expected_approx, delta=1000)

        asyncio.run(run_test())


def tearDownModule():
    """Restore third-party sys.modules entries mocked by this suite.

    Prevents cross-module pollution (e.g. LLM client tests failing because
    ``instructor`` was replaced with a MagicMock).
    """
    for name in _RECORD_TO_RESTORE:
        original = _ORIGINAL_MODULES.get(name)
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


if __name__ == "__main__":
    unittest.main()
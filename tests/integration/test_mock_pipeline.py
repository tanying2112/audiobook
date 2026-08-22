#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration test for Mock Pipeline (P0-1).

Tests that the full pipeline runs in mock mode without "硬质检门禁" (hard quality check) errors.
Verifies:
1. Pipeline completes successfully in mock mode
2. No hard quality check failures (DNSMOS/ASR/SpeakerSim)
3. Quality judgments are generated for all segments
"""

import os
import sys
import pytest
import asyncio
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from src.audiobook_studio.database import AsyncSessionLocal, init_async_db
from src.audiobook_studio.models import Project, Chapter, Paragraph
from src.audiobook_studio.pipeline.orchestrator import run_pipeline
from src.audiobook_studio.pipeline.checkpoint import CheckpointManager
from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline
from src.audiobook_studio.schemas import ParagraphAnnotation, TtsRoutingDecision, QualityJudgment


@pytest.fixture(scope="module")
async def db_session():
    """Create a database session for testing."""
    # Use a test database
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_mock_pipeline.db"
    await init_async_db()
    async with AsyncSessionLocal() as session:
        yield session
    # Cleanup
    if Path("./test_mock_pipeline.db").exists():
        Path("./test_mock_pipeline.db").unlink()


@pytest.fixture
def mock_pipeline():
    """Create a QualityCheckPipeline in mock mode."""
    return QualityCheckPipeline(mock_mode=True)


class TestMockPipeline:
    """Test mock mode pipeline execution."""

    @pytest.mark.asyncio
    async def test_quality_check_mock_mode_no_hard_checks(self, mock_pipeline):
        """Test that mock mode skips hard quality checks (DNSMOS/ASR/SpeakerSim)."""
        # Create test inputs
        annotation = ParagraphAnnotation(
            paragraph_index=0,
            speaker_canonical_name="narrator",
            is_dialogue=False,
            emotion="neutral",
            emotion_intensity=0.5,
            speech_rate=1.0,
            pitch_shift_semitones=0,
            confidence=0.95,
            needs_sfx=False,
            sfx_tags=[],
        )

        routing = TtsRoutingDecision(
            segment_id="test_ch1_p1",
            engine_choice="kokoro",
            voice_id="zf_xiaoxiao",
            prosody_overrides={},
            fallback_engine="edge",
            reasoning="Test routing",
            estimated_cost_usd=0.0,
            estimated_duration_ms=3000,
        )

        reference_text = "这是一个测试文本。"
        audio_path = "/fake/audio.wav"

        inputs = [(audio_path, annotation, routing, reference_text)]

        # Run quality check in mock mode
        judgments = mock_pipeline.run(inputs)

        # Verify we get a judgment
        assert len(judgments) == 1
        judgment = judgments[0]

        # Verify no hard quality check failures (should not contain "Hard quality check failed")
        assert not any("Hard quality check failed" in str(issue) for issue in judgment.issues)

        # Verify mock_mode is reflected in judgment (no DNSMOS/ASR/SpeakerSim mentions)
        # The mock judgment should only have rule-based issues if any
        assert judgment.segment_id == "test_ch1_p1"

    @pytest.mark.asyncio
    async def test_quality_check_mock_mode_with_silence_issue(self, mock_pipeline):
        """Test that rule-based issues (silence) still trigger regeneration in mock mode."""
        from unittest.mock import patch
        from src.audiobook_studio.pipeline.quality_check import AudioAnalysisResult

        # Create analysis with silence issue
        analysis_with_silence = AudioAnalysisResult(
            duration_ms=3000,
            has_silence=True,
            silence_regions=[(0, 1000)],
            has_clipping=False,
            rms_db=-20.0,
            peak_db=-3.0,
            duration_match=True,
            issues=["excessive_silence_detected"],
        )

        # Patch _analyze_audio_rules to return our analysis
        with patch.object(mock_pipeline, "_analyze_audio_rules", return_value=analysis_with_silence):
            annotation = ParagraphAnnotation(
                paragraph_index=0,
                speaker_canonical_name="narrator",
                is_dialogue=False,
                emotion="neutral",
                emotion_intensity=0.5,
                speech_rate=1.0,
                pitch_shift_semitones=0,
                confidence=0.95,
            )

            routing = TtsRoutingDecision(
                segment_id="test_ch1_p1",
                engine_choice="kokoro",
                voice_id="zf_xiaoxiao",
                prosody_overrides={},
                fallback_engine="edge",
                reasoning="Test routing",
                estimated_cost_usd=0.0,
                estimated_duration_ms=3000,
            )

            reference_text = "测试文本。"
            audio_path = "/fake/audio.wav"

            inputs = [(audio_path, annotation, routing, reference_text)]
            judgments = mock_pipeline.run(inputs)

            assert len(judgments) == 1
            judgment = judgments[0]

            # Should have the silence issue
            assert "excessive_silence_detected" in judgment.issues

            # Should need regeneration due to silence
            assert judgment.needs_regeneration

            # Should have fix suggestions
            assert len(judgment.fix_suggestions) > 0


class TestFakeRemoteTTSPortSineWave:
    """Test that FakeRemoteTTSPort generates sine wave audio."""

    @pytest.mark.asyncio
    async def test_fake_port_generates_sine_wave(self):
        """Verify FakeRemoteTTSPort generates valid WAV with sine wave (not silence)."""
        from src.audiobook_studio.tts.fake_port import FakeRemoteTTSPort
        from src.audiobook_studio.tts.port import TTSTaskPayload, TTSVoiceAnchor, TTSProsody
        import tempfile
        import wave
        import struct

        port = FakeRemoteTTSPort(synthesis_delay=0.01)

        # Create a payload
        payload = TTSTaskPayload(
            text="这是一段测试文本用于验证正弦波生成",
            voice_anchor=TTSVoiceAnchor(voice_id="test_voice", speaker_name="narrator", language="zh-CN"),
            prosody=TTSProsody(rate=1.0, pitch=0.0, volume=0.0),
        )

        # Submit and wait for completion
        await port.submit("test_task_1", payload)

        # Poll for result
        import asyncio
        for _ in range(50):
            status = await port.get_status("test_task_1")
            if status.status.value == "DONE":
                break
            await asyncio.sleep(0.01)

        result = await port.get_result("test_task_1")

        # Verify audio file exists and is valid
        assert result.audio_path is not None
        assert Path(result.audio_path).exists()

        # Verify it's a valid WAV file with actual audio data (not silence)
        with wave.open(result.audio_path, "rb") as wav_file:
            assert wav_file.getnchannels() == 1
            assert wav_file.getsampwidth() == 2
            assert wav_file.getframerate() == 16000

            # Read all frames
            frames = wav_file.readframes(wav_file.getnframes())
            samples = struct.unpack(f"<{len(frames)//2}h", frames)

            # Verify not all samples are zero (not silence)
            non_zero_samples = sum(1 for s in samples if s != 0)
            assert non_zero_samples > len(samples) * 0.5, "Audio should not be mostly silence"

            # Verify it has variation (sine wave should have both positive and negative values)
            max_val = max(samples)
            min_val = min(samples)
            assert max_val > 0, "Should have positive values"
            assert min_val < 0, "Should have negative values"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

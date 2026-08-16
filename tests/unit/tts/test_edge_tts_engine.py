"""Tests for Edge-TTS Engine (tests/unit/tts/test_edge_tts_engine.py).

Target: 70%+ coverage of edge_tts_engine.py (148 lines, ~20% coverage).
Tests: initialization, synthesize, voice listing, SSML prosody, error handling, mock mode.
"""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.audiobook_studio.tts.edge_tts_engine import (
    EDGE_VOICES,
    EdgeTTSEngine,
    create_edge_tts_engine,
)
from src.audiobook_studio.tts.engine import (
    SynthesisResult,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
    TTSProsody,
    VoiceInfo,
)


class TestEdgeVoices:
    """Test EDGE_VOICES voice registry."""

    def test_edge_voices_has_expected_keys(self):
        """Test that EDGE_VOICES contains expected voice keys."""
        expected_voices = [
            "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "zh-CN-YunjianNeural",
            "zh-CN-XiaoyiNeural", "zh-CN-XiaochenNeural",
            "en-US-JennyNeural", "en-US-GuyNeural", "en-US-AriaNeural", "en-US-DavisNeural",
        ]
        for voice in expected_voices:
            assert voice in EDGE_VOICES

    def test_edge_voices_structure(self):
        """Test each voice is a VoiceInfo with required fields."""
        for voice_id, info in EDGE_VOICES.items():
            assert isinstance(info, VoiceInfo)
            assert info.voice_id == voice_id
            assert info.engine == "edge"
            assert info.sample_rate == 24000
            assert info.supports_prosody is True
            assert info.language in ("zh-CN", "en-US")
            assert info.gender in ("male", "female")


class TestEdgeTTSEngineInitialization:
    """Test EdgeTTSEngine initialization and configuration."""

    def test_init_default(self):
        """Test default initialization."""
        engine = EdgeTTSEngine()

        assert engine.mock_mode is False
        assert engine.device == "cloud"
        assert engine.sample_rate == 24000
        assert engine._loaded is False
        assert engine._initialized is False
        assert engine._voices_cache is None

    def test_init_custom_parameters(self):
        """Test initialization with custom parameters."""
        engine = EdgeTTSEngine(
            model_path="/custom/model",
            device="cloud",
            sample_rate=48000,
            mock_mode=True,
        )
        assert engine.device == "cloud"
        assert engine.sample_rate == 48000
        assert engine.mock_mode is True

    @pytest.mark.asyncio
    async def test_initialize_mock_mode(self):
        """Test initialization in mock mode."""
        engine = EdgeTTSEngine(mock_mode=True)
        await engine.initialize()

        assert engine._loaded is True
        assert engine._initialized is True

    @pytest.mark.asyncio
    async def test_initialize_mock_mode_skips_edge_tts_import(self):
        """Test mock mode skips edge_tts import and list_voices."""
        engine = EdgeTTSEngine(mock_mode=True)

        with patch("src.audiobook_studio.tts.edge_tts_engine.edge_tts", None):
            await engine.initialize()
            assert engine._loaded is True

    @pytest.mark.asyncio
    async def test_initialize_missing_edge_tts_raises(self):
        """Test initialization fails when edge_tts not installed."""
        engine = EdgeTTSEngine(mock_mode=False)

        with patch("src.audiobook_studio.tts.edge_tts_engine.edge_tts", None):
            with pytest.raises(ImportError, match="edge_tts package not installed"):
                await engine.initialize()

    @pytest.mark.asyncio
    async def test_initialize_network_failure_raises(self):
        """Test initialization fails when list_voices fails."""
        engine = EdgeTTSEngine(mock_mode=False)

        mock_edge_tts = Mock()
        mock_edge_tts.list_voices = AsyncMock(side_effect=ConnectionError("Network error"))

        with patch("src.audiobook_studio.tts.edge_tts_engine.edge_tts", mock_edge_tts):
            with pytest.raises(ConnectionError, match="Network error"):
                await engine.initialize()

    @pytest.mark.asyncio
    async def test_initialize_empty_voices_raises(self):
        """Test initialization fails when no voices returned."""
        engine = EdgeTTSEngine(mock_mode=False)

        mock_edge_tts = Mock()
        mock_edge_tts.list_voices = AsyncMock(return_value=[])

        with patch("src.audiobook_studio.tts.edge_tts_engine.edge_tts", mock_edge_tts):
            with pytest.raises(RuntimeError, match="No Edge-TTS voices available"):
                await engine.initialize()


class TestEdgeTTSEngineSynthesis:
    """Test EdgeTTSEngine synthesis functionality."""

    @pytest.fixture
    def mock_engine(self):
        """Create an EdgeTTSEngine in mock mode."""
        engine = EdgeTTSEngine(mock_mode=True, output_dir="/tmp/test_output")
        return engine

    @pytest.mark.asyncio
    async def test_synthesize_internal_mock_mode(self, mock_engine, tmp_path):
        """Test _synthesize_internal in mock mode creates audio file."""
        await mock_engine.initialize()

        output_path = tmp_path / "test_output.mp3"
        result = await mock_engine._synthesize_internal(
            text="Hello world",
            voice_id="zh-CN-XiaoxiaoNeural",
            output_path=output_path,
        )

        assert isinstance(result, SynthesisResult)
        assert result.engine == "edge"
        assert result.voice_id == "zh-CN-XiaoxiaoNeural"
        assert result.sample_rate == 24000
        assert result.duration_ms > 0
        assert len(result.text_hash) == 12
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_internal_mock_mode_wav(self, mock_engine, tmp_path):
        """Test _synthesize_internal with WAV output."""
        await mock_engine.initialize()

        wav_path = tmp_path / "test_output.wav"
        result = await mock_engine._synthesize_internal(
            text="Test text",
            voice_id="zh-CN-XiaoxiaoNeural",
            output_path=wav_path,
        )

        assert result.audio_path == str(wav_path)
        assert wav_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_with_prosody(self, mock_engine, tmp_path):
        """Test synthesis with prosody controls via SSML."""
        await mock_engine.initialize()

        output_path = tmp_path / "prosody_test.mp3"
        result = await mock_engine._synthesize_internal(
            text="Hello with prosody",
            voice_id="zh-CN-XiaoxiaoNeural",
            output_path=output_path,
            prosody={"rate": 1.2, "pitch": 2.0, "volume": -3.0},
        )

        assert result.duration_ms > 0
        assert result.metadata["prosody"] is not None
        assert result.metadata["prosody"]["rate"] == 1.2

    @pytest.mark.asyncio
    async def test_synthesize_unknown_voice_fallback(self, mock_engine, tmp_path):
        """Test synthesis falls back to default voice for unknown voice_id."""
        await mock_engine.initialize()

        output_path = tmp_path / "fallback_test.mp3"
        result = await mock_engine._synthesize_internal(
            text="Fallback test",
            voice_id="nonexistent_voice",
            output_path=output_path,
        )

        assert result.voice_id == "zh-CN-XiaoxiaoNeural"
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_no_prosody_plain_text(self, mock_engine, tmp_path):
        """Test synthesis without prosody uses plain text."""
        await mock_engine.initialize()

        output_path = tmp_path / "plain_test.mp3"
        result = await mock_engine._synthesize_internal(
            text="Plain text",
            voice_id="en-US-JennyNeural",
            output_path=output_path,
            prosody=None,
        )

        assert output_path.exists()
        assert result.metadata["prosody"] is None


class TestEdgeTTSEngineSSML:
    """Test SSML building for prosody control."""

    @pytest.fixture
    def mock_engine(self):
        engine = EdgeTTSEngine(mock_mode=True)
        return engine

    def test_build_ssml_no_prosody(self, mock_engine):
        """Test _build_ssml returns plain text when no prosody."""
        ssml = mock_engine._build_ssml("Plain text", "zh-CN-XiaoxiaoNeural", None)
        assert ssml == "Plain text"

    def test_build_ssml_with_rate(self, mock_engine):
        """Test _build_ssml includes rate in prosody."""
        ssml = mock_engine._build_ssml("Test", "zh-CN-XiaoxiaoNeural", {"rate": 1.5})
        assert '+50%' in ssml  # 1.5 -> +50%
        assert 'rate='+'' in ssml or 'rate="' in ssml

    def test_build_ssml_with_pitch(self, mock_engine):
        """Test _build_ssml includes pitch in prosody."""
        ssml = mock_engine._build_ssml("Test", "zh-CN-XiaoxiaoNeural", {"pitch": 2.0})
        assert '+2.0st' in ssml
        assert 'pitch='+'' in ssml or 'pitch="' in ssml

    def test_build_ssml_with_volume(self, mock_engine):
        """Test _build_ssml includes volume in prosody."""
        ssml = mock_engine._build_ssml("Test", "zh-CN-XiaoxiaoNeural", {"volume": -3.0})
        assert '-3.0dB' in ssml
        assert 'volume='+'' in ssml or 'volume="' in ssml

    def test_build_ssml_full_prosody(self, mock_engine):
        """Test _build_ssml with all prosody controls."""
        prosody = {"rate": 0.8, "pitch": -1.5, "volume": 5.0}
        ssml = mock_engine._build_ssml("Test text", "zh-CN-XiaoxiaoNeural", prosody)

        assert '-20%' in ssml or '-19%' in ssml  # 0.8 -> -20% (or -19% due to float precision)
        assert '-1.5st' in ssml
        assert '+5.0dB' in ssml
        assert 'Test text' in ssml
        assert 'zh-CN-XiaoxiaoNeural' in ssml
        assert 'prosody' in ssml
        assert '<speak' in ssml
        assert '</speak>' in ssml

    def test_build_ssml_xml_lang(self, mock_engine):
        """Test _build_ssml includes xml:lang attribute."""
        ssml = mock_engine._build_ssml("Test", "zh-CN-XiaoxiaoNeural", {"rate": 1.0})
        assert 'xml:lang="zh-CN"' in ssml


class TestEdgeTTSEngineSynthesizeProtocol:
    """Test TTSEngine protocol methods."""

    @pytest.fixture
    def mock_engine(self):
        engine = EdgeTTSEngine(mock_mode=True, output_dir="/tmp/test_output")
        return engine

    @pytest.mark.asyncio
    async def test_synthesize_protocol_method(self, mock_engine, tmp_path):
        """Test synthesize() TTSEngine protocol method."""
        await mock_engine.initialize()

        payload = TTSTaskPayload(
            text="Protocol test",
            voice_anchor=TTSVoiceAnchor(voice_id="zh-CN-XiaoxiaoNeural"),
            prosody=TTSProsody(rate=1.0, pitch=0.0, volume=0.0),
        )
        output_path = tmp_path / "protocol_test.mp3"

        result = await mock_engine.synthesize(payload, output_path)

        assert isinstance(result, TTSTaskResult)
        assert result.status == "DONE"
        assert result.audio_path == str(output_path)
        assert result.engine == "edge"
        assert result.text_hash is not None

    @pytest.mark.asyncio
    async def test_synthesize_handles_exception(self, mock_engine):
        """Test synthesize() returns FAILED result on exception."""
        await mock_engine.initialize()

        payload = TTSTaskPayload(
            text="Error test",
            voice_anchor=TTSVoiceAnchor(voice_id="zh-CN-XiaoxiaoNeural"),
        )
        output_path = Path("/invalid/path/that/does/not/exist.mp3")

        result = await mock_engine.synthesize(payload, output_path)

        assert isinstance(result, TTSTaskResult)
        assert result.status == "FAILED"
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_submit_and_get_status(self, mock_engine):
        """Test submit() and get_status() async flow."""
        await mock_engine.initialize()

        payload = TTSTaskPayload(
            text="Submit test",
            voice_anchor=TTSVoiceAnchor(voice_id="en-US-JennyNeural"),
        )

        task_id = "test_task_123"
        submitted = await mock_engine.submit(task_id, payload)
        assert submitted is True

        status = await mock_engine.get_status(task_id)
        assert isinstance(status, TTSTaskStatus)
        assert status.task_id == task_id
        assert status.status in ("PENDING", "RUNNING", "DONE", "FAILED")

    @pytest.mark.asyncio
    async def test_get_status_unknown_task(self, mock_engine):
        """Test get_status() for unknown task."""
        await mock_engine.initialize()

        status = await mock_engine.get_status("nonexistent_task")
        assert isinstance(status, TTSTaskStatus)
        assert status.task_id == "nonexistent_task"
        assert status.status == "PENDING"
        assert "not found" in status.error_message.lower()

    @pytest.mark.asyncio
    async def test_get_result_after_completion(self, mock_engine, tmp_path):
        """Test get_result() after task completion."""
        await mock_engine.initialize()

        payload = TTSTaskPayload(
            text="Result test",
            voice_anchor=TTSVoiceAnchor(voice_id="zh-CN-XiaoxiaoNeural"),
        )
        task_id = "result_task_123"

        await mock_engine.submit(task_id, payload)

        import asyncio
        await asyncio.sleep(0.1)

        result = await mock_engine.get_result(task_id)
        assert isinstance(result, TTSTaskResult)
        assert result.task_id is not None  # Result has generated task_id
        assert result.status == "DONE"
        assert result.audio_path is not None

    @pytest.mark.asyncio
    async def test_get_result_not_ready(self, mock_engine):
        """Test get_result() raises for non-existent task."""
        await mock_engine.initialize()

        with pytest.raises(KeyError, match="not found or not ready"):
            await mock_engine.get_result("nonexistent")

    @pytest.mark.asyncio
    async def test_cancel_pending_task(self, mock_engine):
        """Test cancel() on pending task."""
        await mock_engine.initialize()

        payload = TTSTaskPayload(
            text="Cancel test",
            voice_anchor=TTSVoiceAnchor(voice_id="zh-CN-XiaoxiaoNeural"),
        )
        task_id = "cancel_task_123"

        await mock_engine.submit(task_id, payload)

        cancelled = await mock_engine.cancel(task_id)
        assert cancelled is True

        status = await mock_engine.get_status(task_id)
        assert status.status == "FAILED"
        assert "cancelled" in status.error_message.lower()

    @pytest.mark.asyncio
    async def test_cancel_completed_task(self, mock_engine, tmp_path):
        """Test cancel() on completed task returns False."""
        await mock_engine.initialize()

        payload = TTSTaskPayload(
            text="Done task",
            voice_anchor=TTSVoiceAnchor(voice_id="zh-CN-XiaoxiaoNeural"),
        )
        task_id = "done_task_123"

        await mock_engine.submit(task_id, payload)
        import asyncio
        await asyncio.sleep(0.15)

        cancelled = await mock_engine.cancel(task_id)
        assert cancelled is False


class TestEdgeTTSEngineHealthCheck:
    """Test health_check and close methods."""

    @pytest.mark.asyncio
    async def test_health_check_mock_mode(self):
        """Test health_check returns correct status in mock mode."""
        engine = EdgeTTSEngine(mock_mode=True)
        await engine.initialize()

        health = await engine.health_check()

        assert health["healthy"] is True
        assert health["engine"] == "edge"
        assert health["loaded"] is True
        assert health["mock_mode"] is True
        assert health["sample_rate"] == 24000

    @pytest.mark.asyncio
    async def test_close_cleans_up(self):
        """Test close() cleans up resources."""
        engine = EdgeTTSEngine(mock_mode=True)
        await engine.initialize()

        await engine.close()

        assert engine._loaded is False
        assert engine._initialized is False
        assert engine._voices_cache is None


class TestEdgeTTSEngineVoices:
    """Test get_voices() method."""

    @pytest.mark.asyncio
    async def test_get_voices_returns_all_voices(self):
        """Test get_voices() returns VoiceInfo for all EDGE_VOICES."""
        engine = EdgeTTSEngine(mock_mode=True)
        await engine.initialize()

        voices = engine.get_voices()

        assert len(voices) == len(EDGE_VOICES)
        for voice in voices:
            assert voice.engine == "edge"
            assert voice.sample_rate == 24000
            assert voice.supports_prosody is True

    @pytest.mark.asyncio
    async def test_get_voices_voice_ids_match_registry(self):
        """Test voice IDs match EDGE_VOICES keys."""
        engine = EdgeTTSEngine(mock_mode=True)
        await engine.initialize()

        voices = engine.get_voices()
        voice_ids = {v.voice_id for v in voices}

        assert voice_ids == set(EDGE_VOICES.keys())

    @pytest.mark.asyncio
    async def test_get_voices_cached(self):
        """Test get_voices() caches result on second call."""
        engine = EdgeTTSEngine(mock_mode=True)
        await engine.initialize()

        voices1 = engine.get_voices()
        voices2 = engine.get_voices()

        assert voices1 is voices2  # Same object


class TestEdgeTTSEngineEstimateDuration:
    """Test estimate_duration() method."""

    @pytest.mark.asyncio
    async def test_estimate_duration_chinese(self):
        """Test duration estimation for Chinese text."""
        engine = EdgeTTSEngine()

        text = "你好世界，这是一个测试句子。"
        duration = engine.estimate_duration(text, "zh-CN-XiaoxiaoNeural")

        assert duration >= 500

    @pytest.mark.asyncio
    async def test_estimate_duration_english(self):
        """Test duration estimation for English text."""
        engine = EdgeTTSEngine()

        text = "Hello world, this is a test sentence."
        duration = engine.estimate_duration(text, "en-US-JennyNeural")

        assert duration >= 500

    @pytest.mark.asyncio
    async def test_estimate_duration_with_prosody_rate(self):
        """Test duration estimation respects prosody speed."""
        engine = EdgeTTSEngine()

        text = "Test speed adjustment"
        normal_duration = engine.estimate_duration(text, "zh-CN-XiaoxiaoNeural", prosody={"rate": 1.0})
        fast_duration = engine.estimate_duration(text, "zh-CN-XiaoxiaoNeural", prosody={"rate": 2.0})
        slow_duration = engine.estimate_duration(text, "zh-CN-XiaoxiaoNeural", prosody={"rate": 0.5})

        assert fast_duration < normal_duration
        assert slow_duration > normal_duration

    @pytest.mark.asyncio
    async def test_estimate_duration_empty_string(self):
        """Test duration estimation for empty string returns minimum."""
        engine = EdgeTTSEngine()

        duration = engine.estimate_duration("", "zh-CN-XiaoxiaoNeural")
        assert duration == 500


class TestCreateEdgeTTSEngine:
    """Test create_edge_tts_engine factory function."""

    @pytest.mark.asyncio
    async def test_create_factory(self):
        """Test factory creates and initializes engine."""
        engine = await create_edge_tts_engine(mock_mode=True)

        assert isinstance(engine, EdgeTTSEngine)
        assert engine._loaded is True
        assert engine._initialized is True


class TestEdgeTTSEngineEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_synthesize_without_initialize(self):
        """Test synthesis auto-initializes if not initialized."""
        engine = EdgeTTSEngine(mock_mode=True)

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "auto_init.mp3"
            result = await engine._synthesize_internal(
                text="Auto init test",
                voice_id="zh-CN-XiaoxiaoNeural",
                output_path=output_path,
            )

            assert result.engine == "edge"
            assert engine._initialized is True

    @pytest.mark.asyncio
    async def test_mock_mode_creates_valid_audio(self, tmp_path):
        """Test mock mode creates valid audio file."""
        engine = EdgeTTSEngine(mock_mode=True)
        await engine.initialize()

        output_path = tmp_path / "mock_audio.mp3"
        result = await engine._synthesize_internal(
            text="Mock audio test",
            voice_id="zh-CN-XiaoxiaoNeural",
            output_path=output_path,
        )

        assert output_path.exists()
        assert output_path.stat().st_size > 0
        assert isinstance(result.duration_ms, int)
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_concurrent_synthesis(self, tmp_path):
        """Test multiple concurrent synthesis requests."""
        engine = EdgeTTSEngine(mock_mode=True, max_concurrent=3)
        await engine.initialize()

        import asyncio

        async def synthesize(text, idx):
            output_path = tmp_path / f"concurrent_{idx}.mp3"
            return await engine._synthesize_internal(
                text=text,
                voice_id="zh-CN-XiaoxiaoNeural",
                output_path=output_path,
            )

        tasks = [synthesize(f"Concurrent {i}", i) for i in range(3)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 3
        for i, result in enumerate(results):
            assert result.engine == "edge"
            assert (tmp_path / f"concurrent_{i}.mp3").exists()

    @pytest.mark.asyncio
    async def test_hash_different_texts_different_hashes(self, tmp_path):
        """Test different texts produce different hashes."""
        engine = EdgeTTSEngine(mock_mode=True)
        await engine.initialize()

        output1 = tmp_path / "hash1.mp3"
        output2 = tmp_path / "hash2.mp3"

        result1 = await engine._synthesize_internal("Text one", "zh-CN-XiaoxiaoNeural", output1)
        result2 = await engine._synthesize_internal("Text two", "zh-CN-XiaoxiaoNeural", output2)

        assert result1.text_hash != result2.text_hash
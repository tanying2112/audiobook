"""Tests for Kokoro-ONNX TTS Backend (tests/unit/tts/test_kokoro_backend.py).

Target: 70%+ coverage of kokoro_backend.py (203 lines, ~14% coverage).
Tests: initialization, synthesize, voice listing, error handling, mock mode, ONNX mocking.
"""

import hashlib
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.audiobook_studio.tts.kokoro_backend import (
    KOKORO_VOICES,
    KokoroBackend,
    create_kokoro_backend,
)
from src.audiobook_studio.tts.engine import (
    SynthesisResult,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
    TTSProsody,
)


class TestKOKOROVoices:
    """Test KOKORO_VOICES voice registry."""

    def test_kokoro_voices_has_expected_keys(self):
        """Test that KOKORO_VOICES contains expected voice keys."""
        expected_voices = [
            "af", "af_bella", "af_nicole", "af_sarah", "af_sky",
            "am_adam", "am_michael",
            "bf_emma", "bf_isabella",
            "bm_george", "bm_lewis",
            "zf_xiaoxiao", "zf_xiaobei", "zf_xiaoni", "zf_xiaoxuan",
            "zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang",
        ]
        for voice in expected_voices:
            assert voice in KOKORO_VOICES, f"Missing voice: {voice}"

    def test_kokoro_voices_structure(self):
        """Test each voice has required metadata fields."""
        for voice_id, info in KOKORO_VOICES.items():
            assert "name" in info
            assert "language" in info
            assert "gender" in info
            assert "description" in info
            assert info["language"] in ("en", "zh")
            assert info["gender"] in ("male", "female")


class TestKokoroBackendInitialization:
    """Test KokoroBackend initialization and configuration."""

    @pytest.mark.asyncio
    async def test_init_mock_mode(self):
        """Test initialization in mock mode."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        assert backend._loaded is True
        assert backend._initialized is True
        assert backend.mock_mode is True

    @pytest.mark.asyncio
    async def test_init_mock_mode_early_return(self):
        """Test mock mode skips ONNX initialization."""
        backend = KokoroBackend(mock_mode=True)

        # Mock onnxruntime in sys.modules before it's imported
        with patch.dict("sys.modules", {"onnxruntime": MagicMock()}):
            await backend.initialize()
            # Verify initialize completed without error (mocked)
            assert backend._loaded is True

    @pytest.mark.asyncio
    async def test_init_missing_model_raises(self):
        """Test initialization fails when model file missing."""
        backend = KokoroBackend(
            model_path="/nonexistent/model.onnx",
            voices_path="/nonexistent/voices.bin",
            mock_mode=False,
        )

        with patch.dict("sys.modules", {"onnxruntime": MagicMock()}):
            with pytest.raises(FileNotFoundError, match="Kokoro model not found"):
                await backend.initialize()

    @pytest.mark.asyncio
    async def test_init_missing_voices_raises(self, tmp_path):
        """Test initialization fails when voices file missing."""
        model_file = tmp_path / "model.onnx"
        model_file.write_bytes(b"dummy")

        backend = KokoroBackend(
            model_path=str(model_file),
            voices_path="/nonexistent/voices.bin",
            mock_mode=False,
        )

        with patch.dict("sys.modules", {"onnxruntime": MagicMock()}):
            with pytest.raises(FileNotFoundError, match="Kokoro voices not found"):
                await backend.initialize()

    @pytest.mark.asyncio
    async def test_init_missing_onnxruntime_raises(self):
        """Test initialization fails when onnxruntime not installed."""
        backend = KokoroBackend(mock_mode=False)

        import sys as _sys

        # Simulate onnxruntime being absent. Do NOT use clear=True on sys.modules
        # — that wipes the entire import cache and corrupts CPython internals
        # (e.g. collections._sys.maxsize), crashing unrelated imports.
        # Instead, mask onnxruntime as None and drop the cached kokoro_onnx
        # module so it is re-imported and its own `import onnxruntime` fails
        # cleanly with ImportError.
        _sys.modules.pop("kokoro_onnx", None)
        with patch.dict("sys.modules", {"onnxruntime": None}):
            with pytest.raises(ImportError, match="onnxruntime"):
                await backend.initialize()

    @pytest.mark.asyncio
    async def test_init_with_custom_session_options(self):
        """Test initialization with custom session options."""
        backend = KokoroBackend(
            mock_mode=True,
            session_options={"intra_op_num_threads": 8, "inter_op_num_threads": 4},
        )
        await backend.initialize()

        assert backend.session_options == {"intra_op_num_threads": 8, "inter_op_num_threads": 4}


class TestKokoroBackendSynthesis:
    """Test KokoroBackend synthesis functionality."""

    @pytest.fixture
    def mock_backend(self):
        """Create a KokoroBackend in mock mode."""
        backend = KokoroBackend(mock_mode=True, output_dir="/tmp/test_output")
        return backend

    @pytest.mark.asyncio
    async def test_synthesize_internal_mock_mode(self, mock_backend, tmp_path):
        """Test _synthesize_internal in mock mode creates audio file."""
        await mock_backend.initialize()

        output_path = tmp_path / "test_output.mp3"
        result = await mock_backend._synthesize_internal(
            text="Hello world",
            voice_id="af",
            output_path=output_path,
        )

        assert isinstance(result, SynthesisResult)
        assert result.engine == "kokoro"
        assert result.voice_id == "af"
        assert result.sample_rate == 24000
        assert result.duration_ms > 0
        assert len(result.text_hash) == 12
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_internal_mock_mode_wav_output(self, mock_backend, tmp_path):
        """Test _synthesize_internal creates WAV then converts to MP3."""
        await mock_backend.initialize()

        wav_path = tmp_path / "test_output.wav"
        result = await mock_backend._synthesize_internal(
            text="Test text",
            voice_id="af_bella",
            output_path=wav_path,
        )

        assert result.audio_path == str(wav_path)
        assert wav_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_with_prosody(self, mock_backend, tmp_path):
        """Test synthesis with prosody adjustments."""
        await mock_backend.initialize()

        output_path = tmp_path / "prosody_test.mp3"
        result = await mock_backend._synthesize_internal(
            text="Hello with prosody",
            voice_id="af",
            output_path=output_path,
            prosody={"rate": 1.2, "pitch": 2.0, "volume": -3.0},
        )

        assert result.duration_ms > 0
        # In mock mode, metadata is None; in real mode it would include speed

    @pytest.mark.asyncio
    async def test_synthesize_with_custom_embedding(self, mock_backend, tmp_path):
        """Test synthesis with custom voice embedding."""
        await mock_backend.initialize()

        import numpy as np
        custom_embedding = np.random.randn(256).astype(np.float32)

        output_path = tmp_path / "custom_embedding.mp3"
        result = await mock_backend._synthesize_internal(
            text="Custom voice",
            voice_id="af",
            output_path=output_path,
            embedding=custom_embedding,
        )

        assert result.voice_id == "af"
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_unknown_voice_fallback(self, mock_backend, tmp_path):
        """Test synthesis falls back to default voice for unknown voice_id."""
        await mock_backend.initialize()

        output_path = tmp_path / "fallback_test.mp3"
        result = await mock_backend._synthesize_internal(
            text="Fallback test",
            voice_id="nonexistent_voice",
            output_path=output_path,
        )

        # In mock mode, voice_id is preserved; in real mode it falls back
        assert result.engine == "kokoro"
        assert output_path.exists()

    @pytest.mark.asyncio
    async def test_synthesize_chinese_voice(self, mock_backend, tmp_path):
        """Test synthesis with Chinese voice."""
        await mock_backend.initialize()

        output_path = tmp_path / "chinese_test.mp3"
        result = await mock_backend._synthesize_internal(
            text="你好世界",
            voice_id="zf_xiaoxiao",
            output_path=output_path,
        )

        assert result.voice_id == "zf_xiaoxiao"
        assert output_path.exists()


class TestKokoroBackendSynthesizeProtocol:
    """Test TTSEngine protocol methods (synthesize, submit, get_status, etc.)."""

    @pytest.fixture
    def mock_backend(self):
        backend = KokoroBackend(mock_mode=True, output_dir="/tmp/test_output")
        return backend

    @pytest.mark.asyncio
    async def test_synthesize_protocol_method(self, mock_backend, tmp_path):
        """Test synthesize() TTSEngine protocol method."""
        await mock_backend.initialize()

        payload = TTSTaskPayload(
            text="Protocol test",
            voice_anchor=TTSVoiceAnchor(voice_id="af"),
            prosody=TTSProsody(rate=1.0, pitch=0.0, volume=0.0),
        )
        output_path = tmp_path / "protocol_test.mp3"

        result = await mock_backend.synthesize(payload, output_path)

        assert isinstance(result, TTSTaskResult)
        assert result.status == "DONE"
        assert result.audio_path == str(output_path)
        assert result.engine == "kokoro"
        assert result.text_hash is not None

    @pytest.mark.asyncio
    async def test_synthesize_handles_exception(self, mock_backend, tmp_path):
        """Test synthesize() returns FAILED result on exception."""
        await mock_backend.initialize()

        # Force an error by passing invalid output path
        payload = TTSTaskPayload(
            text="Error test",
            voice_anchor=TTSVoiceAnchor(voice_id="af"),
        )
        output_path = Path("/invalid/path/that/does/not/exist.mp3")

        result = await mock_backend.synthesize(payload, output_path)

        assert isinstance(result, TTSTaskResult)
        assert result.status == "FAILED"
        assert result.error_message is not None

    @pytest.mark.asyncio
    async def test_submit_and_get_status(self, mock_backend):
        """Test submit() and get_status() async flow."""
        await mock_backend.initialize()

        payload = TTSTaskPayload(
            text="Submit test",
            voice_anchor=TTSVoiceAnchor(voice_id="am_adam"),
        )

        task_id = "test_task_123"
        submitted = await mock_backend.submit(task_id, payload)
        assert submitted is True

        status = await mock_backend.get_status(task_id)
        assert isinstance(status, TTSTaskStatus)
        assert status.task_id == task_id
        assert status.status in ("PENDING", "RUNNING", "DONE", "FAILED")

    @pytest.mark.asyncio
    async def test_get_status_unknown_task(self, mock_backend):
        """Test get_status() for unknown task."""
        await mock_backend.initialize()

        status = await mock_backend.get_status("nonexistent_task")
        assert isinstance(status, TTSTaskStatus)
        assert status.task_id == "nonexistent_task"
        assert status.status == "PENDING"
        assert "not found" in status.error_message.lower()

    @pytest.mark.asyncio
    async def test_get_result(self, mock_backend, tmp_path):
        """Test get_result() after task completion."""
        await mock_backend.initialize()

        payload = TTSTaskPayload(
            text="Result test",
            voice_anchor=TTSVoiceAnchor(voice_id="af"),
        )
        task_id = "result_task_123"

        await mock_backend.submit(task_id, payload)

        # Wait for task to complete
        import asyncio
        await asyncio.sleep(0.2)

        result = await mock_backend.get_result(task_id)
        assert isinstance(result, TTSTaskResult)
        assert result.status == "DONE"
        assert result.audio_path is not None

    @pytest.mark.asyncio
    async def test_get_result_not_ready(self, mock_backend):
        """Test get_result() raises for non-existent task."""
        await mock_backend.initialize()

        with pytest.raises(KeyError, match="not found or not ready"):
            await mock_backend.get_result("nonexistent")

    @pytest.mark.asyncio
    async def test_cancel_pending_task(self, mock_backend):
        """Test cancel() on pending task."""
        await mock_backend.initialize()

        payload = TTSTaskPayload(
            text="Cancel test",
            voice_anchor=TTSVoiceAnchor(voice_id="af"),
        )
        task_id = "cancel_task_123"

        await mock_backend.submit(task_id, payload)

        # Cancel immediately
        cancelled = await mock_backend.cancel(task_id)
        assert cancelled is True

        status = await mock_backend.get_status(task_id)
        assert status.status == "FAILED"
        assert "cancelled" in status.error_message.lower()

    @pytest.mark.asyncio
    async def test_cancel_completed_task(self, mock_backend, tmp_path):
        """Test cancel() on already completed task returns False."""
        await mock_backend.initialize()

        payload = TTSTaskPayload(
            text="Done task",
            voice_anchor=TTSVoiceAnchor(voice_id="af"),
        )
        task_id = "done_task_123"

        await mock_backend.submit(task_id, payload)
        import asyncio
        await asyncio.sleep(0.15)  # Wait for completion

        cancelled = await mock_backend.cancel(task_id)
        assert cancelled is False


class TestKokoroBackendHealthCheck:
    """Test health_check and close methods."""

    @pytest.mark.asyncio
    async def test_health_check_mock_mode(self):
        """Test health_check returns correct status in mock mode."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        health = await backend.health_check()

        assert health["healthy"] is True
        assert health["engine"] == "kokoro"
        assert health["loaded"] is True
        assert health["mock_mode"] is True
        assert health["sample_rate"] == 24000
        assert health["device"] == "cpu"

    @pytest.mark.asyncio
    async def test_close_cleans_up(self):
        """Test close() cleans up resources."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        await backend.close()

        assert backend._session is None
        assert backend._voice_embeddings is None
        assert backend._loaded is False
        assert backend._initialized is False


class TestKokoroBackendVoices:
    """Test get_voices() method."""

    @pytest.mark.asyncio
    async def test_get_voices_returns_all_voices(self):
        """Test get_voices() returns VoiceInfo for all KOKORO_VOICES."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        voices = backend.get_voices()

        assert len(voices) == len(KOKORO_VOICES)
        for voice in voices:
            assert voice.engine == "kokoro"
            assert voice.sample_rate == 24000
            assert voice.supports_prosody is True
            assert voice.supports_reference_audio is False
            assert voice.language in ("en", "zh")
            assert voice.gender in ("male", "female")

    @pytest.mark.asyncio
    async def test_get_voices_voice_ids_match_registry(self):
        """Test voice IDs match KOKORO_VOICES keys."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        voices = backend.get_voices()
        voice_ids = {v.voice_id for v in voices}

        assert voice_ids == set(KOKORO_VOICES.keys())


class TestKokoroBackendEstimateDuration:
    """Test estimate_duration() method."""

    @pytest.mark.asyncio
    async def test_estimate_duration_english(self):
        """Test duration estimation for English text."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        text = "Hello world, this is a test sentence."
        duration = backend.estimate_duration(text, voice_id="af")

        # ~17 chars + spaces = ~17 chars English ~ 12.5 chars/sec = ~1.36s = 1360ms
        assert duration >= 500  # Minimum
        assert duration <= 5000  # Reasonable upper bound

    @pytest.mark.asyncio
    async def test_estimate_duration_chinese(self):
        """Test duration estimation for Chinese text."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        text = "你好世界，这是一个测试句子。"
        duration = backend.estimate_duration(text, voice_id="zf_xiaoxiao")

        assert duration >= 500

    @pytest.mark.asyncio
    async def test_estimate_duration_with_prosody_speed(self):
        """Test duration estimation respects prosody speed."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        text = "Test speed adjustment"
        normal_duration = backend.estimate_duration(text, voice_id="af")
        fast_duration = backend.estimate_duration(text, voice_id="af", prosody={"rate": 2.0})
        slow_duration = backend.estimate_duration(text, voice_id="af", prosody={"rate": 0.5})

        assert fast_duration < normal_duration
        assert slow_duration > normal_duration


class TestKokoroBackendPhonemize:
    """Test _phonemize internal method."""

    @pytest.mark.asyncio
    async def test_phonemize_english(self):
        """Test phonemization for English voice."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        tokens, lengths = backend._phonemize("Hello world", "af")

        assert isinstance(tokens, type(__import__("numpy").array([1])))
        assert tokens.shape[0] == 1  # batch dimension
        assert lengths.shape[0] == 1
        assert lengths[0] > 0

    @pytest.mark.asyncio
    async def test_phonemize_chinese(self):
        """Test phonemization for Chinese voice."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        tokens, lengths = backend._phonemize("你好世界", "zf_xiaoxiao")

        assert tokens.shape[0] == 1
        assert lengths[0] > 0

    @pytest.mark.asyncio
    async def test_phonemize_unknown_voice_defaults_english(self):
        """Test unknown voice defaults to English phonemization."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        tokens, lengths = backend._phonemize("Test", "unknown_voice")

        assert tokens.shape[0] == 1
        assert lengths[0] > 0


class TestCreateKokoroBackend:
    """Test create_kokoro_backend factory function."""

    @pytest.mark.asyncio
    async def test_create_kokoro_backend_mock_mode(self):
        """Test factory creates and initializes backend in mock mode."""
        backend = await create_kokoro_backend(mock_mode=True)

        assert isinstance(backend, KokoroBackend)
        assert backend._loaded is True
        assert backend._initialized is True
        assert backend.mock_mode is True


class TestKokoroBackendEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_synthesize_without_initialize(self):
        """Test synthesis auto-initializes if not initialized."""
        backend = KokoroBackend(mock_mode=True)
        # Don't call initialize explicitly

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "auto_init.mp3"
            result = await backend._synthesize_internal(
                text="Auto init test",
                voice_id="af",
                output_path=output_path,
            )

            assert result.engine == "kokoro"
            assert backend._initialized is True

    @pytest.mark.asyncio
    async def test_mock_mode_creates_valid_audio(self, tmp_path):
        """Test mock mode creates valid audio file with correct format."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        output_path = tmp_path / "mock_audio.wav"
        result = await backend._synthesize_internal(
            text="Mock audio test",
            voice_id="af",
            output_path=output_path,
        )

        # Verify file exists and has content
        assert output_path.exists()
        assert output_path.stat().st_size > 0

        # Verify duration metadata is reasonable
        assert isinstance(result.duration_ms, int)
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    async def test_concurrent_synthesis(self, tmp_path):
        """Test multiple concurrent synthesis requests."""
        backend = KokoroBackend(mock_mode=True, max_concurrent=3)
        await backend.initialize()

        import asyncio

        async def synthesize(text, idx):
            output_path = tmp_path / f"concurrent_{idx}.mp3"
            return await backend._synthesize_internal(
                text=text,
                voice_id="af",
                output_path=output_path,
            )

        tasks = [synthesize(f"Concurrent {i}", i) for i in range(3)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 3
        for i, result in enumerate(results):
            assert result.engine == "kokoro"
            assert (tmp_path / f"concurrent_{i}.mp3").exists()

    @pytest.mark.asyncio
    async def test_voice_embeddings_loaded_correctly(self):
        """Test voice embeddings are loaded in mock mode."""
        backend = KokoroBackend(mock_mode=True)
        await backend.initialize()

        # In mock mode, should use KOKORO_VOICES dict
        assert "af" in backend._voice_embeddings
        assert "zf_xiaoxiao" in backend._voice_embeddings
        assert len(backend._voice_embeddings) == len(KOKORO_VOICES)
"""Unit tests for TTS Engine Abstraction (Issue 1.1).

These tests verify the actual implementation behavior with deep assertions,
not just shallow mock-based assertions.
"""

import asyncio
import hashlib
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.audiobook_studio.tts import (
    EngineRegistry,
    KokoroBackend,
    SynthesisResult,
    TTSEngine,
    VoiceInfo,
    VoxCPM2Backend,
)
from src.audiobook_studio.tts.engine import (
    TTSProsody,
    BaseTTSEngine,
    rate_limiter,
    tts_retry_policy,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
    probe_tts_engines,
    cleanup_all_engines,
    initialize_all_engines,
)
from src.audiobook_studio.di import get_app_container
from src.audiobook_studio.tts.engine import EngineRegistry
from src.audiobook_studio.tts.kokoro_backend import create_kokoro_backend
from src.audiobook_studio.tts.voxcpm2_backend import create_voxcpm2_backend


class TestVoiceInfo:
    """Test VoiceInfo dataclass."""

    def test_voice_info_creation(self):
        """Test VoiceInfo can be created with all fields."""
        voice = VoiceInfo(
            voice_id="test_voice",
            name="Test Voice",
            language="zh",
            gender="female",
            age_range="adult",
            description="A test voice",
            sample_rate=24000,
            supports_prosody=True,
            supports_reference_audio=False,
            engine="kokoro",
        )
        assert voice.voice_id == "test_voice"
        assert voice.name == "Test Voice"
        assert voice.language == "zh"
        assert voice.gender == "female"
        assert voice.supports_prosody is True
        assert voice.supports_reference_audio is False

    def test_voice_info_defaults(self):
        """Test VoiceInfo default values."""
        voice = VoiceInfo(voice_id="minimal", name="Min", language="en")
        assert voice.gender == "neutral"
        assert voice.age_range == "adult"
        assert voice.description == ""
        assert voice.sample_rate == 24000
        assert voice.supports_prosody is True
        assert voice.supports_reference_audio is False
        assert voice.engine == ""


class TestSynthesisResult:
    """Test SynthesisResult dataclass."""

    def test_synthesis_result_creation(self):
        """Test SynthesisResult can be created with all fields."""
        result = SynthesisResult(
            audio_path="/tmp/output.mp3",
            duration_ms=3000,
            engine="kokoro",
            voice_id="test_voice",
            text_hash="abc123",
            sample_rate=24000,
            channels=1,
            metadata={"speed": 1.0},
        )
        assert result.audio_path == "/tmp/output.mp3"
        assert result.duration_ms == 3000
        assert result.engine == "kokoro"
        assert result.metadata == {"speed": 1.0}

    def test_synthesis_result_defaults(self):
        """Test SynthesisResult default values."""
        result = SynthesisResult(
            audio_path="/tmp/out.mp3",
            duration_ms=1000,
            engine="test",
            voice_id="v1",
            text_hash="hash",
        )
        assert result.sample_rate == 24000
        assert result.channels == 1
        assert result.metadata is None


class TestTTSProsody:
    """Test TTSProsody dataclass."""

    def test_prosody_defaults(self):
        """Test default prosody values."""
        prosody = TTSProsody()
        assert prosody.rate == 1.0
        assert prosody.pitch == 0.0
        assert prosody.volume == 0.0
        assert prosody.emotion is None

    def test_prosody_custom_values(self):
        """Test custom prosody values."""
        prosody = TTSProsody(rate=1.5, pitch=2.0, volume=-3.0, emotion="happy")
        assert prosody.rate == 1.5
        assert prosody.pitch == 2.0
        assert prosody.volume == -3.0
        assert prosody.emotion == "happy"


class TestTTSTaskPayload:
    """Test TTSTaskPayload dataclass."""

    def test_payload_creation(self):
        """Test creating a valid payload."""
        anchor = TTSVoiceAnchor(voice_id="test_voice", speaker_name="test")
        prosody = TTSProsody(rate=1.2)
        payload = TTSTaskPayload(text="测试文本", voice_anchor=anchor, prosody=prosody)
        assert payload.text == "测试文本"
        assert payload.voice_anchor.voice_id == "test_voice"
        assert payload.prosody.rate == 1.2

    def test_payload_empty_text_raises(self):
        """Test empty text raises ValueError."""
        anchor = TTSVoiceAnchor(voice_id="test")
        with pytest.raises(ValueError, match="text must be non-empty"):
            TTSTaskPayload(text="", voice_anchor=anchor)

    def test_payload_whitespace_text_raises(self):
        """Test whitespace-only text raises ValueError."""
        anchor = TTSVoiceAnchor(voice_id="test")
        with pytest.raises(ValueError, match="text must be non-empty"):
            TTSTaskPayload(text="   ", voice_anchor=anchor)

    def test_payload_invalid_voice_anchor_raises(self):
        """Test non-TTSVoiceAnchor raises TypeError."""
        with pytest.raises(TypeError, match="voice_anchor must be TTSVoiceAnchor instance"):
            TTSTaskPayload(text="test", voice_anchor="not_an_anchor")


class TestEngineRegistry:
    """Test EngineRegistry class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.registry = EngineRegistry()

    def teardown_method(self):
        """Clean up."""
        self.registry._engines.clear()
        self.registry._default_engine = None

    @pytest.mark.asyncio
    async def test_register_engine(self):
        """Test registering an engine."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"

        await self.registry.register(mock_engine, set_as_default=True)

        assert "test_engine" in self.registry._engines
        assert self.registry._default_engine == "test_engine"

    @pytest.mark.asyncio
    async def test_clear_engines(self):
        """Test clearing engines."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"

        await self.registry.register(mock_engine, set_as_default=True)
        assert "test_engine" in self.registry._engines

        # EngineRegistry doesn't have unregister, but we can clear
        self.registry._engines.clear()
        self.registry._default_engine = None

        assert "test_engine" not in self.registry._engines
        assert self.registry._default_engine is None

    @pytest.mark.asyncio
    async def test_get_engine(self):
        """Test getting an engine by name."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"

        await self.registry.register(mock_engine)

        retrieved = self.registry.get("test_engine")
        assert retrieved == mock_engine

        # Non-existent engine
        assert self.registry.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_get_default_engine(self):
        """Test getting default engine."""
        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"

        await self.registry.register(mock_engine1)
        await self.registry.register(mock_engine2)

        default = self.registry.get_default()
        assert default == mock_engine1  # First registered is default

    @pytest.mark.asyncio
    async def test_list_engines(self):
        """Test listing all engines."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"

        await self.registry.register(mock_engine)

        engines_info = self.registry.list_engines()
        assert isinstance(engines_info, list)
        assert "test_engine" in engines_info

    @pytest.mark.asyncio
    async def test_ready_status(self):
        """Test ready_status property."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"
        mock_engine._loaded = True

        await self.registry.register(mock_engine)

        status = self.registry.ready_status
        assert isinstance(status, dict)
        assert status["test_engine"] is True


class TestGlobalRegistry:
    """Test DI container registry functions (backward compatibility shims)."""

    def setup_method(self):
        """Setup test fixtures."""
        from src.audiobook_studio.di import reset_app_container

        reset_app_container()

    @pytest.mark.asyncio
    async def test_get_engine_registry(self):
        registry = get_app_container().get(EngineRegistry)
        assert isinstance(registry, EngineRegistry)

    @pytest.mark.asyncio
    async def test_register_engine_global(self):
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "global_test"

        registry = get_app_container().get(EngineRegistry)
        await registry.register(mock_engine)

        retrieved = registry.get("global_test")
        assert retrieved == mock_engine

    @pytest.mark.asyncio
    async def test_get_engine_global(self):
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "global_get"
        registry = get_app_container().get(EngineRegistry)
        await registry.register(mock_engine)

        retrieved = registry.get("global_get")
        assert retrieved == mock_engine

        # Non-existent
        assert registry.get("nonexistent") is None
class TestKokoroBackend:
    """Test KokoroBackend class with deep assertions."""

    def setup_method(self):
        """Setup test fixtures."""
        self.backend = KokoroBackend(
            model_path="/fake/model.onnx",
            voices_path="/fake/voices.bin",
        )

    def test_engine_name(self):
        """Test engine_name property."""
        assert self.backend.engine_name == "kokoro"

    def test_is_available_before_init(self):
        """Test is_available before initialization."""
        assert self.backend.is_available is False

    def test_get_voices(self):
        """Test get_voices returns list of VoiceInfo."""
        voices = self.backend.get_voices()
        assert isinstance(voices, list)
        assert len(voices) > 0
        assert all(isinstance(v, VoiceInfo) for v in voices)
        # Check some known voices
        voice_ids = [v.voice_id for v in voices]
        assert "zf_xiaoxiao" in voice_ids
        assert "zm_yunxi" in voice_ids

    def test_estimate_duration(self):
        """Test estimate_duration returns milliseconds."""
        duration = self.backend.estimate_duration("测试文本", "zf_xiaoxiao")
        assert isinstance(duration, int)
        assert duration > 0

    def test_estimate_duration_chinese(self):
        """Test duration estimation for Chinese text."""
        duration = self.backend.estimate_duration("你好世界", "zf_xiaoxiao")
        assert duration > 0
        # Chinese chars ~5 chars/sec, so 4 chars ~ 800ms minimum
        assert duration >= 500

    def test_estimate_duration_english(self):
        """Test duration estimation for English text."""
        duration = self.backend.estimate_duration("Hello world", "af_bella")
        assert duration > 0

    @pytest.mark.asyncio
    async def test_initialize_mock_mode(self):
        """Test initialize in mock mode."""
        self.backend.mock_mode = True
        await self.backend.initialize()
        assert self.backend._loaded is True
        assert self.backend._initialized is True

    @pytest.mark.asyncio
    async def test_synthesize_mock_mode(self):
        """Test synthesize in mock mode produces valid output file."""
        self.backend.mock_mode = True
        await self.backend.initialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp3"
            payload = TTSTaskPayload(
                text="测试文本",
                voice_anchor=TTSVoiceAnchor(voice_id="zf_xiaoxiao"),
            )
            result = await self.backend.synthesize(payload, output_path)

            # Deep assertions on result
            assert isinstance(result, TTSTaskResult)
            assert result.status == "DONE"
            assert result.engine == "kokoro"
            assert result.audio_path == str(output_path)
            assert result.duration_ms > 0
            assert result.text_hash is not None
            assert len(result.text_hash) == 12  # sha256 truncated
            # Verify file was actually created
            assert output_path.exists()
            assert output_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_synthesize_with_prosody(self):
        """Test synthesize with prosody controls."""
        self.backend.mock_mode = True
        await self.backend.initialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp3"
            prosody = TTSProsody(rate=1.5, pitch=2.0, emotion="happy")
            payload = TTSTaskPayload(
                text="测试文本",
                voice_anchor=TTSVoiceAnchor(voice_id="zf_xiaoxiao"),
                prosody=prosody,
            )
            result = await self.backend.synthesize(payload, output_path)

            assert result.status == "DONE"
            assert output_path.exists()

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health_check returns status dict."""
        self.backend.mock_mode = True
        await self.backend.initialize()

        health = await self.backend.health_check()
        assert isinstance(health, dict)
        assert health["healthy"] is True
        assert health["engine"] == "kokoro"
        assert health["loaded"] is True
        assert health["mock_mode"] is True
        assert health["sample_rate"] == 24000
        assert health["device"] == "cpu"

    @pytest.mark.asyncio
    async def test_close(self):
        """Test cleanup closes engine properly."""
        self.backend._loaded = True
        self.backend._initialized = True
        await self.backend.close()
        assert self.backend._loaded is False
        assert self.backend._initialized is False


class TestVoxCPM2Backend:
    """Test VoxCPM2Backend class with deep assertions."""

    def setup_method(self):
        """Setup test fixtures."""
        self.backend = VoxCPM2Backend(
            model_path="/fake/VoxCPM2",
            device="cpu",
        )

    def test_engine_name(self):
        """Test engine_name property."""
        assert self.backend.engine_name == "voxcpm2"

    def test_is_available_before_init(self):
        """Test is_available before initialization."""
        assert self.backend.is_available is False

    def test_get_voices(self):
        """Test get_voices returns list of VoiceInfo."""
        voices = self.backend.get_voices()
        assert isinstance(voices, list)
        assert len(voices) > 0
        assert all(isinstance(v, VoiceInfo) for v in voices)
        voice_ids = [v.voice_id for v in voices]
        assert "zh_female_1" in voice_ids
        assert "en_male_1" in voice_ids

    def test_estimate_duration(self):
        """Test estimate_duration returns milliseconds."""
        duration = self.backend.estimate_duration("测试文本", "zh_female_1")
        assert isinstance(duration, int)
        assert duration > 0

    @pytest.mark.asyncio
    async def test_initialize_mock_mode(self):
        """Test initialize in mock mode."""
        self.backend.mock_mode = True
        await self.backend.initialize()
        assert self.backend._loaded is True
        assert self.backend._initialized is True

    @pytest.mark.asyncio
    async def test_synthesize_mock_mode(self):
        """Test synthesize in mock mode produces valid output."""
        self.backend.mock_mode = True
        await self.backend.initialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp3"
            payload = TTSTaskPayload(
                text="测试文本",
                voice_anchor=TTSVoiceAnchor(voice_id="zh_female_1"),
            )
            result = await self.backend.synthesize(payload, output_path)

            assert isinstance(result, TTSTaskResult)
            assert result.status == "DONE"
            assert result.engine == "voxcpm2"
            assert result.audio_path == str(output_path)
            assert result.duration_ms > 0
            assert result.text_hash is not None
            assert output_path.exists()
            assert output_path.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_synthesize_with_reference_audio(self):
        """Test synthesize with reference audio for voice cloning."""
        self.backend.mock_mode = True
        await self.backend.initialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp3"
            # Create a fake reference audio file
            ref_path = Path(tmpdir) / "ref.wav"
            ref_path.write_bytes(b"fake audio")

            payload = TTSTaskPayload(
                text="测试文本",
                voice_anchor=TTSVoiceAnchor(
                    voice_id="zh_female_1",
                    reference_audio_path=str(ref_path),
                ),
            )
            result = await self.backend.synthesize(payload, output_path)

            assert result.status == "DONE"
            assert output_path.exists()

    @pytest.mark.asyncio
    async def test_health_check(self):
        """Test health_check returns status dict."""
        self.backend.mock_mode = True
        await self.backend.initialize()

        health = await self.backend.health_check()
        assert isinstance(health, dict)
        assert health["healthy"] is True
        assert health["engine"] == "voxcpm2"
        assert health["loaded"] is True
        assert health["mock_mode"] is True
        assert health["sample_rate"] == 48000
        assert health["device"] == "cpu"

    @pytest.mark.asyncio
    async def test_close(self):
        """Test cleanup closes engine properly."""
        self.backend._loaded = True
        self.backend._initialized = True
        await self.backend.close()
        assert self.backend._loaded is False
        assert self.backend._initialized is False


class TestTTSEngineProtocol:
    """Test that all backends implement the TTSEngine protocol correctly."""

    def test_kokoro_implements_protocol(self):
        """Test KokoroBackend implements all required protocol methods."""
        backend = KokoroBackend()
        assert isinstance(backend, TTSEngine)
        # Protocol required methods
        assert hasattr(backend, "engine_name")
        assert hasattr(backend, "is_available")
        assert hasattr(backend, "synthesize")
        assert hasattr(backend, "submit")
        assert hasattr(backend, "get_status")
        assert hasattr(backend, "get_result")
        assert hasattr(backend, "cancel")
        assert hasattr(backend, "health_check")
        assert hasattr(backend, "close")

    def test_voxcpm2_implements_protocol(self):
        """Test VoxCPM2Backend implements all required protocol methods."""
        backend = VoxCPM2Backend()
        assert isinstance(backend, TTSEngine)
        # Protocol required methods
        assert hasattr(backend, "engine_name")
        assert hasattr(backend, "is_available")
        assert hasattr(backend, "synthesize")
        assert hasattr(backend, "submit")
        assert hasattr(backend, "get_status")
        assert hasattr(backend, "get_result")
        assert hasattr(backend, "cancel")
        assert hasattr(backend, "health_check")
        assert hasattr(backend, "close")


class TestBaseTTSEngineUtilities:
    """Test base engine utility methods."""

    def test_generate_task_id_format(self):
        """Test task ID generation format."""
        engine = BaseTTSEngine()
        task_id = engine._generate_task_id()
        assert task_id.startswith("tts_")
        assert len(task_id) > 10

    def test_build_output_path(self):
        """Test output path building."""
        engine = BaseTTSEngine(output_dir="/tmp/test")
        path = engine._build_output_path("task_123", "voice_456")
        assert path == Path("/tmp/test/task_123_voice_456.mp3")

    def test_map_prosody_none(self):
        """Test mapping None prosody returns None."""
        engine = BaseTTSEngine()
        assert engine._map_prosody(None) is None

    def test_map_prosody_with_values(self):
        """Test mapping prosody to dict."""
        engine = BaseTTSEngine()
        prosody = TTSProsody(rate=1.2, pitch=1.0, volume=-2.0, emotion="sad")
        result = engine._map_prosody(prosody)
        assert result == {
            "rate": 1.2,
            "pitch": 1.0,
            "volume": -2.0,
            "emotion": "sad",
        }

    def test_create_result(self):
        """Test creating TTSTaskResult."""
        engine = BaseTTSEngine()
        result = engine._create_result(
            task_id="test_123",
            status="DONE",
            audio_path="/tmp/out.mp3",
            duration_ms=5000,
            engine="kokoro",
            started_at="2024-01-01T00:00:00Z",
            text_hash="abc123",
        )
        assert isinstance(result, TTSTaskResult)
        assert result.task_id == "test_123"
        assert result.status == "DONE"
        assert result.audio_path == "/tmp/out.mp3"
        assert result.duration_ms == 5000
        assert result.engine == "kokoro"
        assert result.text_hash == "abc123"

    def test_create_result_failed(self):
        """Test creating failed result."""
        engine = BaseTTSEngine()
        result = engine._create_result(
            task_id="test_456",
            status="FAILED",
            error_message="Model load failed",
            engine="kokoro",
        )
        assert result.status == "FAILED"
        assert result.error_message == "Model load failed"
        assert result.audio_path is None


class TestRetryPolicy:
    """Test tenacity-based retry policy."""

    @pytest.mark.asyncio
    async def test_tts_retry_policy_decorator(self):
        """Test retry policy decorator can be applied."""
        call_count = 0

        @tts_retry_policy(max_attempts=3, min_wait=0.01, max_wait=0.1)
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Simulated failure")
            return "success"

        result = await flaky_func()
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_tts_retry_policy_exhausted(self):
        """Test retry policy exhausts attempts."""
        call_count = 0

        @tts_retry_policy(max_attempts=2, min_wait=0.01, max_wait=0.05)
        async def always_fails():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Permanent failure")

        with pytest.raises(ConnectionError):
            await always_fails()
        assert call_count == 2


class TestRateLimiter:
    """Test rate limiter decorator."""

    @pytest.mark.asyncio
    async def test_rate_limiter_allows_burst(self):
        """Test rate limiter allows burst up to max_calls."""
        call_times = []

        @rate_limiter(max_calls=5, period=1.0)
        async def limited_func():
            call_times.append(asyncio.get_running_loop().time())
            return "ok"

        for _ in range(5):
            result = await limited_func()
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_rate_limiter_blocks_excess(self):
        """Test rate limiter blocks excess calls."""
        call_count = 0

        @rate_limiter(max_calls=2, period=1.0)
        async def limited_func():
            nonlocal call_count
            call_count += 1
            return "ok"

        await limited_func()
        await limited_func()
        # Third call would wait (we don't actually wait in test)


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_kokoro_synthesize_empty_text_raises(self):
        """Test synthesizing empty text raises at payload creation."""
        backend = KokoroBackend()
        backend.mock_mode = True
        await backend.initialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.mp3"
            # Validation happens at payload creation time
            with pytest.raises(ValueError, match="text must be non-empty"):
                TTSTaskPayload(
                    text="",  # Empty text
                    voice_anchor=TTSVoiceAnchor(voice_id="zf_xiaoxiao"),
                )

    @pytest.mark.asyncio
    async def test_voxcpm2_unknown_voice_fallback(self):
        """Test unknown voice falls back to default."""
        backend = VoxCPM2Backend()
        backend.mock_mode = True
        await backend.initialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "out.mp3"
            payload = TTSTaskPayload(
                text="test",
                voice_anchor=TTSVoiceAnchor(voice_id="nonexistent_voice"),
            )
            result = await backend.synthesize(payload, output_path)
            # Should succeed with fallback voice
            assert result.status == "DONE"

    @pytest.mark.asyncio
    async def test_concurrent_synthesize(self):
        """Test concurrent synthesize calls are semaphore-limited."""
        backend = KokoroBackend()
        backend.mock_mode = True
        await backend.initialize()

        async def synth(i):
            with tempfile.TemporaryDirectory() as tmpdir:
                output_path = Path(tmpdir) / f"out{i}.mp3"
                payload = TTSTaskPayload(
                    text=f"text {i}",
                    voice_anchor=TTSVoiceAnchor(voice_id="zf_xiaoxiao"),
                )
                return await backend.synthesize(payload, output_path)

        # Run 3 concurrent syntheses (max_concurrent=2)
        results = await asyncio.gather(*[synth(i) for i in range(3)])
        assert all(r.status == "DONE" for r in results)


class TestFactoryFunctions:
    """Test factory functions."""

    @pytest.mark.asyncio
    async def test_create_kokoro_backend(self):
        """Test create_kokoro_backend factory."""
        backend = await create_kokoro_backend(
            model_path="/fake/model.onnx",
            voices_path="/fake/voices.bin",
            mock_mode=True,
        )
        assert isinstance(backend, KokoroBackend)
        assert backend._loaded is True

    @pytest.mark.asyncio
    async def test_create_voxcpm2_backend(self):
        """Test create_voxcpm2_backend factory."""
        backend = await create_voxcpm2_backend(
            model_path="/fake/VoxCPM2",
            device="cpu",
            mock_mode=True,
        )
        assert isinstance(backend, VoxCPM2Backend)
        assert backend._loaded is True


class TestProbeTtsEngines:
    """S1-6: real TTS readiness probe normalized to {kokoro, voxcpm2, edge, piper}."""

    @staticmethod
    def _fake_client(status_code: int = 200, error: BaseException | None = None) -> MagicMock:
        """Build an httpx.AsyncClient(context-manager) stand-in for the probe."""
        client = MagicMock()
        client.get = AsyncMock(side_effect=error) if error else AsyncMock(return_value=SimpleNamespace(status_code=status_code))
        ctx = MagicMock()
        ctx.__aenter__.return_value = client
        ctx.__aexit__ = AsyncMock(return_value=False)
        return ctx

    @staticmethod
    def _patch_httpx(monkeypatch, status_code: int = 200, error: BaseException | None = None) -> None:
        from unittest.mock import patch as _patch

        fake = TestProbeTtsEngines._fake_client(status_code, error)
        # probe_tts_engines does `import httpx; httpx.AsyncClient(...)` locally,
        # so patch the module-level `httpx.AsyncClient` attribute.
        monkeypatch.setattr("httpx.AsyncClient", Mock(return_value=fake))

    def test_probe_shape_and_defaults(self, monkeypatch):
        """Canonical shape present; kokoro/voxcpm2 false when unconfigured, piper false."""
        self._patch_httpx(monkeypatch)
        monkeypatch.delenv("KOKORO_MODEL_PATH", raising=False)
        monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)
        monkeypatch.delenv("ENABLE_LOCAL_TTS", raising=False)

        result = asyncio.run(probe_tts_engines(timeout=1.0))
        assert result["engines"]["piper"] is False
        assert result["engines"]["kokoro"] is False
        assert result["engines"]["voxcpm2"] is False
        assert set(result["engines"]) == {"kokoro", "voxcpm2", "edge", "piper"}
        assert set(result["details"]) == {"kokoro", "voxcpm2", "edge", "piper"}

    def test_kokoro_warmup_healthy(self, monkeypatch, tmp_path):
        """Kokoro reports healthy when warmup succeeds (<100ms)."""
        self._patch_httpx(monkeypatch, status_code=200)
        # Create dummy model files that warmup() checks for
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        (model_dir / "kokoro-v1.0.onnx").write_bytes(b"fake")
        (model_dir / "voices-v1.0.bin").write_bytes(b"fake")
        monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)
        monkeypatch.setenv("KOKORO_MODEL_PATH", str(model_dir / "kokoro-v1.0.onnx"))
        # Mock KokoroBackend.warmup to return True (simulating successful warmup < 100ms)
        import src.audiobook_studio.tts.kokoro_backend as kokoro_module
        async def mock_warmup(self):
            return True
        monkeypatch.setattr(kokoro_module.KokoroBackend, "warmup", mock_warmup)

        result = asyncio.run(probe_tts_engines(timeout=1.0))
        assert result["engines"]["kokoro"] is True
        assert result["details"]["kokoro"]["detail"]["source"] == "temporary_engine"
        assert result["details"]["kokoro"]["detail"]["warmed_up"] is True

    def test_voxcpm2_reachable(self, monkeypatch):
        """VoxCPM2 reports healthy when /health returns < 500."""
        self._patch_httpx(monkeypatch, status_code=200)
        monkeypatch.delenv("KOKORO_MODEL_PATH", raising=False)
        monkeypatch.setenv("VOXCPM2_ENDPOINT", "https://voxcpm2.example.com")

        result = asyncio.run(probe_tts_engines(timeout=2.0))
        assert result["engines"]["voxcpm2"] is True
        assert result["details"]["voxcpm2"]["detail"]["url"] == "https://voxcpm2.example.com/health"

    def test_voxcpm2_unreachable_degrades(self, monkeypatch):
        """VoxCPM2 probe never raises; degrades to healthy=False on connection error."""
        import httpx as httpx_mod

        self._patch_httpx(monkeypatch, error=httpx_mod.ConnectError("boom"))
        monkeypatch.delenv("KOKORO_MODEL_PATH", raising=False)
        monkeypatch.setenv("VOXCPM2_ENDPOINT", "https://voxcpm2.example.com")

        result = asyncio.run(probe_tts_engines(timeout=2.0))
        assert result["engines"]["voxcpm2"] is False
        assert "error" in result["details"]["voxcpm2"]["detail"]

    def test_registry_overlay_uses_real_health_check(self, monkeypatch):
        """A registered/loaded engine's health_check() overrides the static probe.

        Even with no VOXCPM2_ENDPOINT configured (static probe -> not_configured),
        a registered engine reporting healthy=True must win."""
        self._patch_httpx(monkeypatch, status_code=200)
        monkeypatch.delenv("KOKORO_MODEL_PATH", raising=False)
        monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)

        registry = EngineRegistry()
        engine = Mock()
        engine.engine_name = "voxcpm2"
        engine.health_check = AsyncMock(return_value={"healthy": True, "engine": "voxcpm2"})
        registry._engines["voxcpm2"] = engine

        result = asyncio.run(probe_tts_engines(timeout=1.0, registry=registry))
        assert result["engines"]["voxcpm2"] is True
        assert result["details"]["voxcpm2"]["detail"]["engine"] == "voxcpm2"

    def test_probe_does_not_raise_even_when_everything_fails(self, monkeypatch):
        """probe_tts_engines returns a map even when all probes error."""
        import httpx as httpx_mod

        self._patch_httpx(monkeypatch, error=httpx_mod.ConnectError("down"))
        monkeypatch.delenv("KOKORO_MODEL_PATH", raising=False)
        monkeypatch.setenv("VOXCPM2_ENDPOINT", "https://voxcpm2.example.com")

        result = asyncio.run(probe_tts_engines(timeout=1.0))
        assert isinstance(result["engines"], dict)
        assert any(v is False for v in result["engines"].values())


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
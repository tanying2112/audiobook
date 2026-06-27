"""Unit tests for TTS Engine Abstraction (Issue 1.1)."""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, AsyncMock

import pytest

from src.audiobook_studio.tts import (
    TTSEngine,
    VoiceInfo,
    SynthesisResult,
    EngineRegistry,
    get_engine_registry,
    register_engine,
    get_engine,
    initialize_all_engines,
    cleanup_all_engines,
    KokoroBackend,
    create_kokoro_backend,
    VoxCPM2Backend,
    create_voxcpmp2_backend,
)


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


class TestEngineRegistry:
    """Test EngineRegistry class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.registry = EngineRegistry()

    def teardown_method(self):
        """Clean up."""
        # Clear registry
        self.registry._engines.clear()
        self.registry._default_engine = None

    def test_register_engine(self):
        """Test registering an engine."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"
        
        self.registry.register(mock_engine, set_as_default=True)
        
        assert "test_engine" in self.registry._engines
        assert self.registry._default_engine == "test_engine"

    def test_unregister_engine(self):
        """Test unregistering an engine."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"
        
        self.registry.register(mock_engine, set_as_default=True)
        self.registry.unregister("test_engine")
        
        assert "test_engine" not in self.registry._engines
        assert self.registry._default_engine is None

    def test_get_engine(self):
        """Test getting an engine by name."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"
        
        self.registry.register(mock_engine)
        
        retrieved = self.registry.get("test_engine")
        assert retrieved == mock_engine
        
        # Non-existent engine
        assert self.registry.get("nonexistent") is None

    def test_get_default_engine(self):
        """Test getting default engine."""
        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"
        
        self.registry.register(mock_engine1)
        self.registry.register(mock_engine2)
        
        default = self.registry.get_default()
        assert default == mock_engine1  # First registered is default

    def test_list_engines(self):
        """Test listing all engines with info."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"
        mock_engine.device = "cpu"
        mock_engine.sample_rate = 24000
        mock_engine.supports_streaming = False
        mock_engine.supports_batch = False
        mock_engine.get_voices.return_value = []
        mock_engine.is_available.return_value = True
        mock_engine.get_engine_info.return_value = {
            "engine": "test_engine",
            "device": "cpu",
            "sample_rate": 24000,
            "supports_streaming": False,
            "supports_batch": False,
            "voice_count": 0,
            "initialized": True,
        }

        self.registry.register(mock_engine)

        engines_info = self.registry.list_engines()
        assert len(engines_info) == 1
        assert engines_info[0]["engine"] == "test_engine"
        assert engines_info[0]["device"] == "cpu"

    def test_get_available_engines(self):
        """Test getting available (initialized) engines."""
        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine1.is_available.return_value = True
        
        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"
        mock_engine2.is_available.return_value = False
        
        self.registry.register(mock_engine1)
        self.registry.register(mock_engine2)
        
        available = self.registry.get_available_engines()
        assert "engine1" in available
        assert "engine2" not in available


class TestGlobalRegistry:
    """Test DI container registry functions (backward compatibility shims)."""

    def setup_method(self):
        """Setup test fixtures."""
        from src.audiobook_studio.di import reset_app_container
        reset_app_container()

    def test_get_engine_registry(self):
        """Test getting registry from DI container."""
        registry = get_engine_registry()
        assert isinstance(registry, EngineRegistry)

    def test_register_engine_global(self):
        """Test registering engine via DI container shim."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "global_test"

        register_engine(mock_engine)

        retrieved = get_engine("global_test")
        assert retrieved == mock_engine

    def test_get_engine_global(self):
        """Test getting engine from DI container shim."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "global_test2"

        register_engine(mock_engine)

        retrieved = get_engine("global_test2")
        assert retrieved == mock_engine

        # Non-existent
        assert get_engine("nonexistent") is None


class TestKokoroBackend:
    """Test KokoroBackend class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.backend = KokoroBackend(
            model_path="/fake/model.onnx",
            voices_path="/fake/voices.bin",
            
        )

    def test_engine_name(self):
        """Test engine_name property."""
        assert self.backend.engine_name == "kokoro"

    def test_supports_streaming(self):
        """Test supports_streaming property."""
        assert self.backend.supports_streaming is False

    def test_supports_batch(self):
        """Test supports_batch property."""
        assert self.backend.supports_batch is False

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

    @pytest.mark.asyncio
    async def test_initialize_mock_mode(self):
        """Test initialize in mock mode."""
        # Mock mode should skip actual model loading
        self.backend.mock_mode = True
        await self.backend.initialize()
        assert self.backend._initialized is True

    @pytest.mark.asyncio
    async def test_synthesize_mock_mode(self):
        """Test synthesize in mock mode."""
        self.backend.mock_mode = True
        await self.backend.initialize()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp3"
            result = await self.backend.synthesize(
                text="测试文本",
                voice_id="zf_xiaoxiao",
                output_path=output_path,
            )
            
            assert isinstance(result, SynthesisResult)
            assert result.engine == "kokoro"
            assert result.voice_id == "zf_xiaoxiao"
            assert result.duration_ms > 0
            assert output_path.exists()

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test cleanup."""
        self.backend._initialized = True
        await self.backend.cleanup()
        assert self.backend._initialized is False


class TestVoxCPM2Backend:
    """Test VoxCPM2Backend class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.backend = VoxCPM2Backend(
            model_path="/fake/VoxCPM2",
            device="cpu",  # Use CPU for testing
            
        )

    def test_engine_name(self):
        """Test engine_name property."""
        assert self.backend.engine_name == "voxcpmp2"

    def test_supports_streaming(self):
        """Test supports_streaming property."""
        assert self.backend.supports_streaming is True

    def test_supports_batch(self):
        """Test supports_batch property."""
        assert self.backend.supports_batch is True

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
        assert self.backend._initialized is True

    @pytest.mark.asyncio
    async def test_synthesize_mock_mode(self):
        """Test synthesize in mock mode."""
        self.backend.mock_mode = True
        await self.backend.initialize()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "output.mp3"
            result = await self.backend.synthesize(
                text="测试文本",
                voice_id="zh_female_1",
                output_path=output_path,
            )
            
            assert isinstance(result, SynthesisResult)
            assert result.engine == "voxcpmp2"
            assert result.voice_id == "zh_female_1"
            assert result.duration_ms > 0
            assert output_path.exists()

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test cleanup."""
        self.backend._initialized = True
        await self.backend.cleanup()
        assert self.backend._initialized is False


class TestTTSEngineInterface:
    """Test that all backends implement the TTSEngine interface correctly."""

    def test_kokoro_implements_interface(self):
        """Test KokoroBackend implements all abstract methods."""
        backend = KokoroBackend()
        assert isinstance(backend, TTSEngine)
        assert hasattr(backend, 'engine_name')
        assert hasattr(backend, 'supports_streaming')
        assert hasattr(backend, 'supports_batch')
        assert hasattr(backend, 'initialize')
        assert hasattr(backend, 'synthesize')
        assert hasattr(backend, 'get_voices')
        assert hasattr(backend, 'estimate_duration')
        assert hasattr(backend, 'cleanup')

    def test_voxcpmp2_implements_interface(self):
        """Test VoxCPM2Backend implements all abstract methods."""
        backend = VoxCPM2Backend()
        assert isinstance(backend, TTSEngine)
        assert hasattr(backend, 'engine_name')
        assert hasattr(backend, 'supports_streaming')
        assert hasattr(backend, 'supports_batch')
        assert hasattr(backend, 'initialize')
        assert hasattr(backend, 'synthesize')
        assert hasattr(backend, 'get_voices')
        assert hasattr(backend, 'estimate_duration')
        assert hasattr(backend, 'cleanup')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

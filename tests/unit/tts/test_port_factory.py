"""Tests for Port Factory and Engine Registry (tests/unit/tts/test_port_factory.py).

Target: 70%+ coverage of port_factory.py (121 lines, ~14% coverage).
Tests: engine creation, registry configuration, auto-detection, context manager, backward compat.
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from src.audiobook_studio.tts.port_factory import (
    _build_config_from_env,
    create_configured_registry,
    create_engine,
    engine_context,
    get_default_engine,
    get_engine_registry,
    get_port,
)
from src.audiobook_studio.tts.engine import EngineRegistry, TTSEngine


class TestCreateEngine:
    """Test create_engine factory function."""

    def test_create_fake_engine(self):
        """Test creating fake engine for testing."""
        engine = create_engine("fake")

        assert engine is not None
        assert hasattr(engine, "submit")
        assert hasattr(engine, "get_status")
        assert hasattr(engine, "get_result")

    def test_create_mock_engine(self):
        """Test creating mock engine for unit testing."""
        engine = create_engine("mock")

        assert engine is not None
        assert hasattr(engine, "submit")
        assert hasattr(engine, "get_status")
        assert hasattr(engine, "get_result")

    @pytest.mark.asyncio
    async def test_create_voxcpm2_engine(self):
        """Test creating VoxCPM2 engine via factory."""
        with patch.dict(os.environ, {"VOXCPM2_ENDPOINT": "http://test:8080"}):
            engine = create_engine("voxcpm2")
            assert engine is not None
            # RemoteVoxCPM2Port uses submit/get_status/get_result pattern, not synthesize
            assert hasattr(engine, "submit")

    @pytest.mark.asyncio
    async def test_create_kokoro_auto_local_enabled(self):
        """Test auto-detection selects Kokoro when local TTS enabled."""
        with patch.dict(os.environ, {"ENABLE_LOCAL_TTS": "true", "MOCK_LLM": "false", "TEST_MODE": "false"}):
            with patch("src.audiobook_studio.tts.port_factory.create_kokoro_port") as mock_create:
                mock_engine = Mock(spec=TTSEngine)
                mock_create.return_value = mock_engine

                engine = create_engine("auto")
                assert engine == mock_engine
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_edge_auto_local_disabled(self):
        """Test auto-detection selects Edge-TTS when local TTS disabled."""
        with patch.dict(os.environ, {"ENABLE_LOCAL_TTS": "false", "MOCK_LLM": "false", "TEST_MODE": "false"}):
            with patch("src.audiobook_studio.tts.port_factory.create_edge_tts_port") as mock_create:
                mock_engine = Mock(spec=TTSEngine)
                mock_create.return_value = mock_engine

                engine = create_engine("auto")
                assert engine == mock_engine
                mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_fake_when_mock_llm(self):
        """Test auto-detection selects fake when MOCK_LLM set."""
        with patch.dict(os.environ, {"MOCK_LLM": "true"}):
            engine = create_engine("auto")
            # Should create FakeRemoteTTSPort
            assert engine is not None
            assert hasattr(engine, "submit")

    @pytest.mark.asyncio
    async def test_create_fake_when_test_mode(self):
        """Test auto-detection selects fake when TEST_MODE set."""
        with patch.dict(os.environ, {"TEST_MODE": "true", "MOCK_LLM": "false"}):
            engine = create_engine("auto")
            assert engine is not None

    def test_create_unknown_engine_raises(self):
        """Test creating unknown engine type raises ValueError."""
        with pytest.raises(ValueError, match="Unknown engine type: unknown_engine"):
            create_engine("unknown_engine")

    def test_create_kokoro_direct(self):
        """Test creating kokoro engine directly."""
        engine = create_engine("kokoro", mock_mode=True)
        assert engine is not None

    def test_create_edge_direct(self):
        """Test creating edge engine directly."""
        engine = create_engine("edge", mock_mode=True)
        assert engine is not None


class TestEngineRegistry:
    """Test EngineRegistry configuration and initialization."""

    @pytest.fixture
    def registry(self):
        """Create a fresh EngineRegistry for each test."""
        return EngineRegistry()

    def test_registry_empty_initially(self, registry):
        """Test registry starts empty."""
        assert registry.list_engines() == []
        assert registry.get_default() is None
        assert registry.is_ready is False

    @pytest.mark.asyncio
    async def test_register_engine(self, registry):
        """Test registering an engine."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test_engine"

        await registry.register(mock_engine, name="custom_name", set_as_default=True)

        assert registry.get("custom_name") == mock_engine
        assert registry.get_default() == mock_engine
        assert "custom_name" in registry.list_engines()

    @pytest.mark.asyncio
    async def test_register_engine_use_name_property(self, registry):
        """Test registering engine uses engine_name when no name provided."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "my_engine"

        await registry.register(mock_engine)

        assert registry.get("my_engine") == mock_engine

    @pytest.mark.asyncio
    async def test_register_sets_default_first_engine(self, registry):
        """Test first registered engine becomes default."""
        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"

        await registry.register(mock_engine1)
        await registry.register(mock_engine2)

        assert registry.get_default() == mock_engine1

    @pytest.mark.asyncio
    async def test_initialize_from_config(self, registry):
        """Test initializing engines from config dict."""
        config = {
            "kokoro": {"output_dir": "./output", "max_concurrent": 2},
            "edge": {"output_dir": "./output", "max_concurrent": 4},
        }

        mock_kokoro = Mock(spec=TTSEngine)
        mock_kokoro.engine_name = "kokoro"
        mock_edge = Mock(spec=TTSEngine)
        mock_edge.engine_name = "edge"

        with patch("src.audiobook_studio.tts.kokoro_backend.create_kokoro_backend", return_value=mock_kokoro) as mock_kokoro_factory:
            with patch("src.audiobook_studio.tts.edge_tts_engine.create_edge_tts_engine", return_value=mock_edge) as mock_edge_factory:
                await registry.initialize(config)

        assert registry.get("kokoro") == mock_kokoro
        assert registry.get("edge") == mock_edge
        assert registry.get_default() is not None

    @pytest.mark.asyncio
    async def test_initialize_unknown_engine_warns(self, registry):
        """Test initialize warns for unknown engine type."""
        config = {"unknown_engine": {}}

        with patch("src.audiobook_studio.tts.engine.logger.warning") as mock_warn:
            await registry.initialize(config)
            mock_warn.assert_called_with("Unknown engine type: unknown_engine")

    @pytest.mark.asyncio
    async def test_initialize_does_not_eagerly_load(self, registry):
        """Test PERF-001: engines not eagerly initialized."""
        config = {"kokoro": {"output_dir": "./output"}}

        mock_kokoro = Mock(spec=TTSEngine)
        mock_kokoro.engine_name = "kokoro"

        with patch("src.audiobook_studio.tts.kokoro_backend.create_kokoro_backend", return_value=mock_kokoro):
            await registry.initialize(config)

        # Factory called but engine's initialize() NOT called
        assert not hasattr(mock_kokoro, "initialize") or not mock_kokoro.initialize.called


class TestEngineRegistryWarmup:
    """Test engine warmup functionality."""

    @pytest.mark.asyncio
    async def test_warmup_initializes_engines(self):
        """Test warmup() initializes all registered engines."""
        registry = EngineRegistry()

        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine1._loaded = False
        mock_engine1.initialize = AsyncMock()

        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"
        mock_engine2._loaded = True
        mock_engine2.initialize = AsyncMock()

        await registry.register(mock_engine1, name="engine1")
        await registry.register(mock_engine2, name="engine2")

        results = await registry.warmup()

        assert results["engine1"] is True
        assert results["engine2"] is True
        mock_engine1.initialize.assert_called_once()
        # engine2 already loaded, initialize not called again

    @pytest.mark.asyncio
    async def test_warmup_handles_failure(self):
        """Test warmup handles initialization failures."""
        registry = EngineRegistry()

        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "failing_engine"
        mock_engine._loaded = False
        mock_engine.initialize = AsyncMock(side_effect=RuntimeError("Init failed"))

        await registry.register(mock_engine)

        results = await registry.warmup()

        assert results["failing_engine"] is False

    @pytest.mark.asyncio
    async def test_is_ready_all_loaded(self):
        """Test is_ready returns True when all engines loaded."""
        registry = EngineRegistry()

        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine1._loaded = True

        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"
        mock_engine2._loaded = True

        await registry.register(mock_engine1)
        await registry.register(mock_engine2)

        assert registry.is_ready is True

    @pytest.mark.asyncio
    async def test_is_ready_false_when_not_all_loaded(self):
        """Test is_ready returns False when any engine not loaded."""
        registry = EngineRegistry()

        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine1._loaded = True

        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"
        mock_engine2._loaded = False

        await registry.register(mock_engine1)
        await registry.register(mock_engine2)

        assert registry.is_ready is False

    def test_ready_status_returns_per_engine_status(self):
        """Test ready_status returns per-engine load status."""
        registry = EngineRegistry()

        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine1._loaded = True

        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"
        mock_engine2._loaded = False

        registry._engines = {"engine1": mock_engine1, "engine2": mock_engine2}

        status = registry.ready_status
        assert status["engine1"] is True
        assert status["engine2"] is False


class TestEngineRegistryLifecycle:
    """Test registry lifecycle management."""

    @pytest.mark.asyncio
    async def test_close_all_closes_engines(self):
        """Test close_all() closes all registered engines."""
        registry = EngineRegistry()

        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine1.close = AsyncMock()

        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"
        mock_engine2.close = AsyncMock()

        await registry.register(mock_engine1)
        await registry.register(mock_engine2)

        await registry.close_all()

        mock_engine1.close.assert_called_once()
        mock_engine2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_all_handles_errors(self):
        """Test close_all() handles errors gracefully."""
        registry = EngineRegistry()

        mock_engine1 = Mock(spec=TTSEngine)
        mock_engine1.engine_name = "engine1"
        mock_engine1.close = AsyncMock(side_effect=RuntimeError("Close failed"))

        mock_engine2 = Mock(spec=TTSEngine)
        mock_engine2.engine_name = "engine2"
        mock_engine2.close = AsyncMock()

        await registry.register(mock_engine1)
        await registry.register(mock_engine2)

        # Should not raise
        await registry.close_all()

        mock_engine1.close.assert_called_once()
        mock_engine2.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_context_manager(self):
        """Test engine_context context manager."""
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test"
        mock_engine.close = AsyncMock()

        with patch("src.audiobook_studio.tts.port_factory.create_configured_registry") as mock_create:
            mock_registry = Mock(spec=EngineRegistry)
            mock_registry.close_all = AsyncMock()
            mock_create.return_value = mock_registry

            async with engine_context() as registry:
                assert registry == mock_registry

            mock_registry.close_all.assert_called_once()


class TestBuildConfigFromEnv:
    """Test _build_config_from_env function."""

    def test_build_kokoro_config_enabled(self):
        """Test Kokoro config when local TTS enabled."""
        with patch.dict(os.environ, {
            "ENABLE_LOCAL_TTS": "true",
            "AUDIO_OUTPUT_DIR": "/custom/output",
            "KOKORO_MAX_CONCURRENT": "4",
            "KOKORO_MODEL_PATH": "/custom/model.onnx",
        }):
            config = _build_config_from_env()

            assert "kokoro" in config
            assert config["kokoro"]["output_dir"] == "/custom/output"
            assert config["kokoro"]["max_concurrent"] == 4
            assert config["kokoro"]["model_path"] == "/custom/model.onnx"

    def test_build_kokoro_config_disabled(self):
        """Test no Kokoro config when local TTS disabled."""
        with patch.dict(os.environ, {"ENABLE_LOCAL_TTS": "false"}, clear=True):
            config = _build_config_from_env()
            assert "kokoro" not in config

    def test_build_edge_config_enabled(self):
        """Test Edge-TTS config when enabled."""
        with patch.dict(os.environ, {
            "EDGE_TTS_ENABLED": "true",
            "EDGE_MAX_CONCURRENT": "8",
            "EDGE_TTS_VOICE": "en-US-AriaNeural",
        }):
            config = _build_config_from_env()

            assert "edge" in config
            assert config["edge"]["output_dir"] == "./output"  # default
            assert config["edge"]["max_concurrent"] == 8
            assert config["edge"]["voice"] == "en-US-AriaNeural"

    def test_build_edge_config_default_when_no_kokoro(self):
        """Test Edge-TTS config defaults when no other engine configured."""
        with patch.dict(os.environ, {"EDGE_TTS_ENABLED": "false", "ENABLE_LOCAL_TTS": "false"}, clear=True):
            config = _build_config_from_env()

            # Should still have edge config as fallback
            assert "edge" in config

    def test_build_voxcpm2_config(self):
        """Test VoxCPM2 config from environment."""
        with patch.dict(os.environ, {
            "VOXCPM2_ENDPOINT": "http://voxcpm2:8000",
            "VOXCPM2_TIMEOUT_SEC": "120",
        }):
            config = _build_config_from_env()

            assert "voxcpm2" in config
            assert config["voxcpm2"]["endpoint"] == "http://voxcpm2:8000"
            assert config["voxcpm2"]["timeout_sec"] == 120


class TestBackwardCompatibility:
    """Test backward compatibility shims."""

    def test_get_engine_registry_singleton(self):
        """Test get_engine_registry returns same instance."""
        # Reset global registry
        import src.audiobook_studio.tts.port_factory as pf
        pf._global_registry = None

        reg1 = get_engine_registry()
        reg2 = get_engine_registry()

        assert reg1 is reg2
        assert isinstance(reg1, EngineRegistry)

    @pytest.mark.asyncio
    async def test_get_default_engine_initializes(self):
        """Test get_default_engine initializes registry if needed."""
        from src.audiobook_studio.di import DIContainer, set_app_container, reset_app_container

        # Create a fresh container for this test
        container = DIContainer()
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "default"
        mock_engine.initialize = AsyncMock()

        mock_registry = Mock(spec=EngineRegistry)
        # First call returns None (not initialized), second returns engine
        mock_registry.get_default = Mock(side_effect=[None, mock_engine])
        mock_registry.initialize = AsyncMock()

        container.register_singleton(EngineRegistry, mock_registry)
        set_app_container(container)

        try:
            engine = await get_default_engine()
            assert engine == mock_engine
            mock_registry.initialize.assert_called_once()
        finally:
            reset_app_container()

    @pytest.mark.asyncio
    async def test_get_port_returns_adapter(self):
        """Test get_port returns EnginePortAdapter."""
        from src.audiobook_studio.di import DIContainer, set_app_container, reset_app_container

        container = DIContainer()
        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test"
        mock_engine.output_dir = "./output"
        mock_engine.synthesize = AsyncMock()
        mock_engine.close = AsyncMock()

        mock_registry = Mock(spec=EngineRegistry)
        mock_registry.get_default = Mock(return_value=mock_engine)
        mock_registry.initialize = AsyncMock()

        container.register_singleton(EngineRegistry, mock_registry)
        set_app_container(container)

        try:
            port = await get_port()

            assert hasattr(port, "submit")
            assert hasattr(port, "get_status")
            assert hasattr(port, "get_result")
            assert hasattr(port, "cancel")
            assert hasattr(port, "health_check")
            assert hasattr(port, "close")
        finally:
            reset_app_container()


class TestPortFactoryEdgeCases:
    """Test edge cases in port factory."""

    def test_create_engine_mock_mode_from_env(self):
        """Test MOCK_TTS environment variable enables mock mode."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_engine("fake")
            # Should pass mock_mode=False to factory (fake port doesn't use it)
            assert engine is not None

    def test_create_engine_passes_kwargs(self):
        """Test kwargs passed to engine factory."""
        with patch("src.audiobook_studio.tts.port_factory.FakeRemoteTTSPort") as mock_fake:
            mock_fake.return_value = Mock()
            engine = create_engine("fake", custom_arg="value")

            mock_fake.assert_called_with(custom_arg="value")

    @pytest.mark.asyncio
    async def test_registry_config_setter(self):
        """Test registry.config setter."""
        registry = EngineRegistry()

        config = {"test": "value"}
        registry.config = config

        assert registry.config == config

    @pytest.mark.asyncio
    async def test_unregister_not_implemented(self):
        """Test unregister method behavior."""
        registry = EngineRegistry()

        # unregister not implemented in current version
        assert not hasattr(registry, "unregister")


class TestThreadSafety:
    """Test thread-safety of registry operations."""

    @pytest.mark.asyncio
    async def test_concurrent_register(self):
        """Test concurrent register operations."""
        import asyncio
        registry = EngineRegistry()

        async def register_engine(name):
            mock_engine = Mock(spec=TTSEngine)
            mock_engine.engine_name = name
            await registry.register(mock_engine, name=name)
            return name

        tasks = [register_engine(f"engine_{i}") for i in range(10)]
        results = await asyncio.gather(*tasks)

        assert len(results) == 10
        assert len(registry.list_engines()) == 10

    @pytest.mark.asyncio
    async def test_concurrent_get_default(self):
        """Test concurrent get operations."""
        import asyncio
        registry = EngineRegistry()

        mock_engine = Mock(spec=TTSEngine)
        mock_engine.engine_name = "test"
        await registry.register(mock_engine)

        async def get_default():
            return registry.get_default()

        tasks = [get_default() for _ in range(20)]
        results = await asyncio.gather(*tasks)

        assert all(r == mock_engine for r in results)
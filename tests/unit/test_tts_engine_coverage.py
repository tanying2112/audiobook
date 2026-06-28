"""Supplementary tests for tts/engine.py targeting 80%+ coverage.

Covers:
- EngineRegistry.initialize_all / cleanup_all exception paths
- EngineRegistry.get_default with no default engine
- EngineRegistry.unregister when it is the default
- Backward compatibility shims (get_engine_registry, register_engine, etc.)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.audiobook_studio.tts.engine import (
    EngineRegistry,
    SynthesisResult,
    TTSEngine,
    VoiceInfo,
)


class TestEngineRegistryEdgeCases:
    """Edge-case tests for EngineRegistry."""

    def setup_method(self):
        self.registry = EngineRegistry()

    def teardown_method(self):
        self.registry._engines.clear()
        self.registry._default_engine = None

    def test_get_default_no_engines(self):
        """get_default returns None when registry is empty and no default set."""
        assert self.registry.get_default() is None

    def test_unregister_default_engine_clears_default(self):
        """Unregistering the default engine sets default to None when only one engine."""
        eng = Mock(spec=TTSEngine)
        eng.engine_name = "only_engine"
        self.registry.register(eng, set_as_default=True)
        self.registry.unregister("only_engine")
        assert self.registry._default_engine is None
        assert self.registry.get_default() is None

    def test_unregister_default_engine_picks_next(self):
        """Unregistering default engine picks the next one as default."""
        eng1 = Mock(spec=TTSEngine)
        eng1.engine_name = "engine1"
        eng2 = Mock(spec=TTSEngine)
        eng2.engine_name = "engine2"
        self.registry.register(eng1, set_as_default=True)
        self.registry.register(eng2)
        self.registry.unregister("engine1")
        # unregister sets _default_engine to the next available engine
        assert self.registry._default_engine == "engine2"
        assert self.registry.get_default() == eng2

    def test_unregister_nonexistent_engine(self):
        """Unregistering a non-existent engine does nothing."""
        self.registry.unregister("nonexistent")
        assert len(self.registry._engines) == 0

    @pytest.mark.asyncio
    async def test_initialize_all_exception_path(self):
        """initialize_all catches exceptions from individual engines."""
        eng1 = Mock(spec=TTSEngine)
        eng1.engine_name = "failing_engine"
        eng1.initialize = AsyncMock(side_effect=RuntimeError("init failed"))
        eng2 = Mock(spec=TTSEngine)
        eng2.engine_name = "good_engine"
        eng2.initialize = AsyncMock(return_value=None)

        self.registry.register(eng1)
        self.registry.register(eng2)

        # Should not raise, should catch the exception
        await self.registry.initialize_all()
        eng2.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_all_exception_path(self):
        """cleanup_all catches exceptions from individual engines."""
        eng1 = Mock(spec=TTSEngine)
        eng1.engine_name = "failing_engine"
        eng1.cleanup = AsyncMock(side_effect=RuntimeError("cleanup failed"))
        eng2 = Mock(spec=TTSEngine)
        eng2.engine_name = "good_engine"
        eng2.cleanup = AsyncMock(return_value=None)

        self.registry.register(eng1)
        self.registry.register(eng2)

        await self.registry.cleanup_all()
        eng2.cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_initialize_all_empty(self):
        """initialize_all with no engines does nothing."""
        await self.registry.initialize_all()  # Should not raise

    @pytest.mark.asyncio
    async def test_cleanup_all_empty(self):
        """cleanup_all with no engines does nothing."""
        await self.registry.cleanup_all()  # Should not raise


class TestTTSEngineAbstractAndShims:
    """Test TTSEngine abstract interface details and backward compat shims."""

    def test_is_available_default(self):
        """is_available returns False before initialization."""

        class ConcreteEngine(TTSEngine):
            @property
            def engine_name(self):
                return "concrete"

            @property
            def supports_streaming(self):
                return False

            @property
            def supports_batch(self):
                return False

            async def initialize(self):
                pass

            async def synthesize(self, **kwargs):
                pass

            def get_voices(self):
                return []

            def estimate_duration(self, text, voice_id, **kwargs):
                return 1000

            async def cleanup(self):
                pass

        instance = ConcreteEngine()
        assert instance.is_available() is False
        instance._initialized = True
        assert instance.is_available() is True

    def test_get_engine_info(self):
        """get_engine_info returns correct metadata."""

        class ConcreteEngine(TTSEngine):
            @property
            def engine_name(self):
                return "concrete"

            @property
            def supports_streaming(self):
                return True

            @property
            def supports_batch(self):
                return False

            async def initialize(self):
                pass

            async def synthesize(self, **kwargs):
                pass

            def get_voices(self):
                return []

            def estimate_duration(self, text, voice_id, **kwargs):
                return 2000

            async def cleanup(self):
                pass

        instance = ConcreteEngine()
        instance.device = "cpu"
        instance.sample_rate = 24000
        instance._initialized = True

        info = instance.get_engine_info()
        assert info["engine"] == "concrete"
        assert info["device"] == "cpu"
        assert info["sample_rate"] == 24000
        assert info["supports_streaming"] is True
        assert info["supports_batch"] is False
        assert info["initialized"] is True
        assert info["voice_count"] == 0

    def test_repr(self):
        """__repr__ returns readable string."""

        class ConcreteEngine(TTSEngine):
            @property
            def engine_name(self):
                return "concrete"

            @property
            def supports_streaming(self):
                return False

            @property
            def supports_batch(self):
                return False

            async def initialize(self):
                pass

            async def synthesize(self, **kwargs):
                pass

            def get_voices(self):
                return []

            def estimate_duration(self, text, voice_id, **kwargs):
                return 1000

            async def cleanup(self):
                pass

        instance = ConcreteEngine()
        instance.device = "gpu"
        instance._initialized = True
        r = repr(instance)
        assert "concrete" in r
        assert "gpu" in r

    @pytest.mark.asyncio
    async def test_backward_compat_shims(self):
        """Test backward-compat module-level functions."""
        from src.audiobook_studio.di import reset_app_container

        reset_app_container()

        from src.audiobook_studio.tts.engine import (
            cleanup_all_engines,
            get_engine,
            get_engine_registry,
            initialize_all_engines,
            register_engine,
        )

        registry = get_engine_registry()
        assert isinstance(registry, EngineRegistry)

        eng = Mock(spec=TTSEngine)
        eng.engine_name = "shim_test"
        register_engine(eng, set_as_default=True)

        retrieved = get_engine("shim_test")
        assert retrieved == eng

        assert get_engine("nonexistent") is None

        await initialize_all_engines()
        await cleanup_all_engines()

        reset_app_container()

    def test_register_and_unregister_roundtrip(self):
        """Register then unregister leaves empty registry."""
        registry = EngineRegistry()
        eng = Mock(spec=TTSEngine)
        eng.engine_name = "temp"
        registry.register(eng)
        assert registry.get("temp") is eng
        registry.unregister("temp")
        assert registry.get("temp") is None

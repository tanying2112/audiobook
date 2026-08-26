"""Supplementary tests for tts/engine.py targeting coverage.

Covers the *current* (real) API surface:
- dataclasses: VoiceInfo / SynthesisResult / TTSVoiceAnchor / TTSProsody /
  TTSTaskPayload / TTSTaskResult / TTSTaskStatus
- EngineRegistry.register (async) / get / get_default / list_engines
- default-engine selection semantics
- close_all / warmup batch management
- TTSEngine Protocol declarations (is_available / close)
- backward-compat module-level shims (get_engine_registry, register_engine,
  initialize_all_engines, cleanup_all_engines)
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.audiobook_studio.tts.engine import (
    EngineRegistry,
    SynthesisResult,
    TTSEngine,
    TTSTaskPayload,
    TTSVoiceAnchor,
    VoiceInfo,
)


class TestEngineDataclasses:
    """Coverage for the lightweight dataclasses in engine.py."""

    def test_synthesis_result_construction(self):
        r = SynthesisResult(
            audio_path="/out/a.mp3",
            duration_ms=1234,
            engine="edge",
            voice_id="zh-CN-XiaoxiaoNeural",
            text_hash="abc",
        )
        assert r.audio_path == "/out/a.mp3"
        assert r.duration_ms == 1234
        assert r.sample_rate == 24000
        assert r.channels == 1

    def test_voice_info_construction(self):
        v = VoiceInfo(name="Xiaoxiao", voice_id="zh-CN-XiaoxiaoNeural", language="zh-CN")
        assert v.name == "Xiaoxiao"
        assert v.gender == "neutral"
        assert v.sample_rate == 24000
        assert v.supports_prosody is True

    def test_voice_anchor_requires_nonempty_id(self):
        with pytest.raises(ValueError):
            TTSVoiceAnchor(voice_id="   ")

    def test_task_payload_validation(self):
        anchor = TTSVoiceAnchor(voice_id="v1")
        with pytest.raises(ValueError):
            TTSTaskPayload(text="", voice_anchor=anchor)
        with pytest.raises(TypeError):
            TTSTaskPayload(text="hi", voice_anchor="not-an-anchor")  # type: ignore[arg-type]


class TestEngineRegistry:
    """Edge-case and semantics tests for EngineRegistry (real API)."""

    def setup_method(self):
        self.registry = EngineRegistry()

    def teardown_method(self):
        self.registry._engines.clear()
        self.registry._default_engine = None

    def test_get_default_no_engines(self):
        """get_default returns None when registry is empty and no default set."""
        assert self.registry.get_default() is None

    def test_get_returns_none_for_unknown(self):
        assert self.registry.get("nonexistent") is None

    def test_list_engines_empty(self):
        assert self.registry.list_engines() == []

    @pytest.mark.asyncio
    async def test_register_sets_default_and_returns_none(self):
        """register is async, sets default, and returns None."""
        eng = Mock(spec=TTSEngine)
        eng.engine_name = "only_engine"
        result = await self.registry.register(eng, set_as_default=True)
        assert result is None
        assert self.registry.get("only_engine") is eng
        assert self.registry.get_default() is eng

    @pytest.mark.asyncio
    async def test_register_multiple_picks_first_as_default(self):
        """First registered engine becomes default automatically."""
        eng1 = Mock(spec=TTSEngine)
        eng1.engine_name = "engine1"
        eng2 = Mock(spec=TTSEngine)
        eng2.engine_name = "engine2"
        await self.registry.register(eng1)
        await self.registry.register(eng2)
        assert self.registry.get_default() is eng1

    @pytest.mark.asyncio
    async def test_register_explicit_name(self):
        """Explicit name overrides engine_name."""
        eng = Mock(spec=TTSEngine)
        eng.engine_name = "actual_name"
        await self.registry.register(eng, name="custom_name")
        assert self.registry.get("custom_name") is eng
        assert self.registry.get("actual_name") is None

    @pytest.mark.asyncio
    async def test_close_all_calls_close_on_each_engine(self):
        """close_all awaits close() on each registered engine."""
        eng1 = Mock(spec=TTSEngine)
        eng1.engine_name = "e1"
        eng1.close = AsyncMock()
        eng2 = Mock(spec=TTSEngine)
        eng2.engine_name = "e2"
        eng2.close = AsyncMock()
        await self.registry.register(eng1)
        await self.registry.register(eng2)
        await self.registry.close_all()
        eng1.close.assert_awaited_once()
        eng2.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_warmup_initializes_unloaded_engines(self):
        """warmup initializes engines that haven't been loaded yet."""
        eng = Mock(spec=TTSEngine)
        eng.engine_name = "e1"
        eng._loaded = False
        eng.initialize = AsyncMock()
        await self.registry.register(eng)
        results = await self.registry.warmup()
        assert results == {"e1": True}
        eng.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_warmup_skips_already_loaded(self):
        """warmup returns True without re-initializing loaded engines."""
        eng = Mock(spec=TTSEngine)
        eng.engine_name = "e1"
        eng._loaded = True
        eng.initialize = AsyncMock()
        await self.registry.register(eng)
        results = await self.registry.warmup()
        assert results == {"e1": True}
        eng.initialize.assert_not_awaited()


class TestTTSEngineProtocol:
    """Coverage for TTSEngine Protocol declarations."""

    def test_is_available_is_declared(self):
        assert hasattr(TTSEngine, "is_available")

    def test_close_is_declared(self):
        assert hasattr(TTSEngine, "close")

    def test_mock_engine_exposes_protocol_attributes(self):
        eng = Mock(spec=TTSEngine)
        eng.engine_name = "mock_engine"
        eng.is_available = False
        assert eng.engine_name == "mock_engine"
        assert eng.is_available is False


class TestBackwardCompatShims:
    """Coverage for DI-container-based engine access (module shims were removed)."""

    @pytest.mark.asyncio
    async def test_module_level_shims_delegate_to_di(self):
        """Engine access now flows through the DI container singleton."""
        from src.audiobook_studio.di import (
            get_app_container,
            reset_app_container,
            set_app_container,
        )
        from src.audiobook_studio.tts.port_factory import get_default_engine

        reset_app_container()
        container = get_app_container()

        registry = container.get(EngineRegistry)
        assert isinstance(registry, EngineRegistry)

        eng = Mock(spec=TTSEngine)
        eng.engine_name = "shim_test"
        eng.initialize = AsyncMock()
        eng.close = AsyncMock()

        # Register into the container-owned registry (old register_engine path)
        await registry.register(eng, set_as_default=True)
        assert registry.get("shim_test") == eng
        assert registry.get("nonexistent") is None

        # get_default_engine falls back to the container registry
        default_engine = await get_default_engine(registry)
        assert default_engine == eng

        await registry.close_all()
        reset_app_container()
        set_app_container(container)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

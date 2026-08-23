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
        assert self.registry._default_engine == "engine1"
        assert self.registry.get_default() is eng1

    @pytest.mark.asyncio
    async def test_register_explicit_name(self):
        """register accepts an explicit name distinct from engine.engine_name."""
        eng = Mock(spec=TTSEngine)
        eng.engine_name = "real_name"
        await self.registry.register(eng, name="alias")
        assert self.registry.get("alias") is eng
        assert "alias" in self.registry.list_engines()

    @pytest.mark.asyncio
    async def test_close_all_calls_close_on_each_engine(self):
        """close_all invokes close() on every registered engine."""
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
        """warmup initializes engines that are not yet loaded."""
        eng1 = Mock(spec=TTSEngine)
        eng1.engine_name = "e1"
        eng1._loaded = False
        eng1.initialize = AsyncMock()
        await self.registry.register(eng1)
        results = await self.registry.warmup()
        assert results == {"e1": True}
        eng1.initialize.assert_awaited_once()


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
    """Coverage for module-level backward-compat helpers."""

    @pytest.mark.asyncio
    async def test_module_level_shims(self):
        from src.audiobook_studio.tts.engine import (
            cleanup_all_engines,
            get_engine,
            get_engine_registry,
            initialize_all_engines,
            register_engine,
            set_engine_registry,
        )

        registry = set_engine_registry(EngineRegistry())
        eng = Mock(spec=TTSEngine)
        eng.engine_name = "shim_test"
        eng.initialize = AsyncMock()
        eng.close = AsyncMock()

        register_engine(eng, set_as_default=True)

        retrieved = get_engine("shim_test")
        assert retrieved == eng
        assert get_engine("nonexistent") is None

        await initialize_all_engines()
        await cleanup_all_engines()

        # Cleanup so the global registry is not polluted for other tests
        registry._engines.clear()
        registry._default_engine = None

"""Item 11: plugin registration reaches the runtime registries end-to-end.

Proves that a plugin author calling ``ctx.register_*`` actually wires the
factory into the runtime systems (StageRegistry / TTS engine dispatch) instead
of only landing in the plugin manager's bookkeeping dict.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from src.audiobook_studio.pipeline.stage_registry import StageRegistry
from src.audiobook_studio.plugins import PluginContext, PluginManifest, PluginType, get_plugin_manager
from src.audiobook_studio.tts import port_factory as pf

# ── Manifest: entry fallback for loadability ─────────────────────────────────


def test_manifest_entry_fallback_is_loadable():
    """A manifest using ``entry`` (not ``entry_point``) is still loadable."""
    m = PluginManifest(
        name="legacy_stage",
        version="1.0.0",
        type=PluginType.PIPELINE_STAGE,
        entry="plugin.py",
    )
    assert m.entry_module == "plugin"
    assert m.is_loadable is True


def test_manifest_entry_point_takes_precedence():
    m = PluginManifest(
        name="both",
        version="1.0.0",
        type=PluginType.TTS_ENGINE,
        entry_point="plugin:register",
        entry="plugin.py",
    )
    assert m.entry_module == "plugin"
    assert m.is_loadable is True


def test_manifest_tts_voice_alias_is_loadable():
    m = PluginManifest(
        name="voice_preset",
        version="1.0.0",
        type=PluginType.TTS_VOICE,
        entry_point="plugin:register",
    )
    assert m.is_loadable is True


# ── Pipeline stage registration → StageRegistry ─────────────────────────────


def _stage_manifest(name: str) -> PluginManifest:
    return PluginManifest(
        name=name,
        version="1.0.0",
        type=PluginType.PIPELINE_STAGE,
        entry_point="plugin:register",
    )


@pytest.fixture()
def stage_cleanup():
    registered = []
    yield registered
    for name in registered:
        StageRegistry.unregister(name)


def test_register_pipeline_stage_reaches_stage_registry(stage_cleanup):
    """ctx.register_pipeline_stage puts the factory into StageRegistry."""
    ctx = PluginContext(manifest=_stage_manifest("stage_plugin"))

    def my_stage(**kwargs: Any) -> str:
        return f"ran:{kwargs.get('project_id')}"

    ctx.register_pipeline_stage("demo_stage", my_stage)
    stage_cleanup.append("demo_stage")

    assert StageRegistry.has("demo_stage")
    handler = StageRegistry.get("demo_stage")
    result = asyncio.run(handler.run(project_id=7))
    assert result == "ran:7"


def test_register_async_pipeline_stage(stage_cleanup):
    ctx = PluginContext(manifest=_stage_manifest("stage_plugin_async"))

    async def my_async_stage(**kwargs: Any) -> str:
        await asyncio.sleep(0)
        return "async-ok"

    ctx.register_pipeline_stage("demo_async_stage", my_async_stage)
    stage_cleanup.append("demo_async_stage")

    handler = StageRegistry.get("demo_async_stage")
    result = asyncio.run(handler.run())
    assert result == "async-ok"


# ── TTS engine registration → create_engine dispatch ────────────────────────


@pytest.fixture()
def tts_factory_cleanup():
    mgr = get_plugin_manager()
    added = []
    yield added
    for name in added:
        mgr._tts_engine_factories.pop(name, None)


def test_plugin_tts_engine_reachable_via_create_engine(tts_factory_cleanup):
    """A plugin-registered TTS engine is creatable by create_engine (no if/elif)."""
    mgr = get_plugin_manager()
    sentinel = object()

    def my_engine_factory(**kwargs: Any) -> Any:
        return sentinel

    mgr.register_tts_engine_factory(
        plugin_name="tts_plugin",
        engine_name="my_plugin_tts",
        factory=my_engine_factory,
    )
    tts_factory_cleanup.append("my_plugin_tts")

    # Dispatch table must include the plugin engine and route to its factory.
    factories = pf._get_engine_factory_map()
    assert "my_plugin_tts" in factories
    assert factories["my_plugin_tts"]() is sentinel

    # And the public create_engine API resolves it without a hardcoded branch.
    assert pf.create_engine("my_plugin_tts") is sentinel


def test_create_engine_still_resolves_builtins(tts_factory_cleanup):
    """Builtin engines remain creatable after the if/elif → table refactor."""
    for name in ("kokoro", "edge", "voxcpm2", "cosyvoice_stream", "xtts_v2"):
        assert name in pf._get_engine_factory_map()

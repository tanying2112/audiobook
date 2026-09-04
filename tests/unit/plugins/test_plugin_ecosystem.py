"""Tests for the plugin ecosystem (manifest, registry, loading)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from src.audiobook_studio.plugins import (
    PluginContext,
    PluginManager,
    PluginManifest,
    discover_plugins,
    get_plugin_manager,
    parse_manifest,
    read_installed_names,
)

# ======================================================================
# Manifest parsing tests
# ======================================================================


def test_parse_manifest_valid(tmp_path: Path) -> None:
    """Parse a valid manifest.json."""
    manifest_dir = tmp_path / "test_plugin"
    manifest_dir.mkdir()
    manifest_file = manifest_dir / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "name": "test_plugin",
                "version": "1.0.0",
                "type": "tts_engine",
                "description": "Test plugin",
                "models": ["voice1", "voice2"],
                "entry_point": "plugin:register",
            }
        )
    )

    parsed = parse_manifest(manifest_file)
    assert parsed is not None
    assert parsed.name == "test_plugin"
    assert parsed.version == "1.0.0"
    assert parsed.type == "tts_engine"
    assert parsed.models == ["voice1", "voice2"]
    assert parsed.is_loadable is True
    assert parsed.entry_module == "plugin"


def test_parse_manifest_invalid_json(tmp_path: Path) -> None:
    """Malformed JSON returns None (does not raise)."""
    manifest_dir = tmp_path / "bad_plugin"
    manifest_dir.mkdir()
    manifest_file = manifest_dir / "manifest.json"
    manifest_file.write_text("{ not valid json }")

    parsed = parse_manifest(manifest_file)
    assert parsed is None


def test_parse_manifest_missing(tmp_path: Path) -> None:
    """Missing manifest returns None."""
    parsed = parse_manifest(tmp_path / "nonexistent" / "manifest.json")
    assert parsed is None


def test_discover_plugins(tmp_path: Path) -> None:
    """Discover multiple plugins in a directory."""
    (tmp_path / "plugin_a").mkdir()
    (tmp_path / "plugin_a" / "manifest.json").write_text(
        json.dumps({"name": "plugin_a", "version": "1.0.0", "type": "tts_engine", "entry_point": "a:register"})
    )
    (tmp_path / "plugin_b").mkdir()
    (tmp_path / "plugin_b" / "manifest.json").write_text(
        json.dumps({"name": "plugin_b", "version": "2.0.0", "type": "llm_provider", "entry_point": "b:register"})
    )
    (tmp_path / "not_a_plugin").mkdir()  # no manifest, should be skipped

    manifests = discover_plugins(tmp_path)
    assert len(manifests) == 2
    assert {m.name for m in manifests} == {"plugin_a", "plugin_b"}


def test_read_installed_names(tmp_path: Path) -> None:
    """Read installed plugin names from JSON."""
    installed_file = tmp_path / "installed_plugins.json"
    installed_file.write_text(json.dumps({"installed": ["plugin_a", "plugin_b"]}))

    names = read_installed_names(installed_file)
    assert names == ["plugin_a", "plugin_b"]


def test_read_installed_names_missing(tmp_path: Path) -> None:
    """Missing file returns empty list."""
    names = read_installed_names(tmp_path / "nonexistent.json")
    assert names == []


# ======================================================================
# PluginContext tests
# ======================================================================


def test_plugin_context_tts_registration() -> None:
    """PluginContext.register_tts_engine delegates to manager."""
    # We can't easily test the full delegation without a real manager,
    # but we can verify the method exists and has correct signature.
    manifest = PluginManifest(name="test", version="1.0.0", type="tts_engine", entry_point="x:y", directory="/tmp")
    ctx = PluginContext(manifest=manifest)
    assert hasattr(ctx, "register_tts_engine")
    assert hasattr(ctx, "register_llm_provider")
    assert hasattr(ctx, "register_pipeline_stage")


# ======================================================================
# PluginManager / PluginRegistry tests
# ======================================================================


def test_plugin_manager_singleton() -> None:
    """PluginManager is a singleton."""
    mgr1 = get_plugin_manager()
    mgr2 = get_plugin_manager()
    assert mgr1 is mgr2


def test_plugin_manager_register_and_lookup() -> None:
    """Register and lookup TTS engine factories."""
    mgr = PluginManager()  # fresh instance for isolation

    def dummy_factory(**kwargs):
        return None

    mgr.register_tts_engine_factory("test_plugin", "my_tts", dummy_factory)
    mgr.register_llm_provider_factory("test_plugin", "my_llm", dummy_factory)

    registry = mgr.get_registry()
    assert "my_tts" in registry.list_tts_engine_names()
    assert "my_llm" in registry.list_llm_provider_names()

    tts_record = registry.get_tts_engine_factory("my_tts")
    assert tts_record is not None
    assert tts_record.plugin_name == "test_plugin"
    assert tts_record.engine_name == "my_tts"

    llm_record = registry.get_llm_provider_factory("my_llm")
    assert llm_record is not None
    assert llm_record.provider_name == "my_llm"


def test_plugin_manager_override_warning(caplog) -> None:
    """Registering same engine twice logs warning."""
    import logging

    caplog.set_level(logging.WARNING)

    mgr = PluginManager()

    def factory1():
        pass

    def factory2():
        pass

    mgr.register_tts_engine_factory("plugin_a", "dup_engine", factory1)
    mgr.register_tts_engine_factory("plugin_b", "dup_engine", factory2)

    assert "already registered" in caplog.text
    # Second registration wins
    record = mgr.get_tts_engine_factories()["dup_engine"]
    assert record.plugin_name == "plugin_b"


def test_plugin_manager_load_plugin_no_entry() -> None:
    """Plugin without entry point is not an error."""
    mgr = PluginManager()
    # Create manifest without entry (type tts_voice is not loadable)
    manifest = PluginManifest(name="no_entry", version="1.0.0", type="tts_voice", entry="", directory="/tmp")
    mgr._manifests["no_entry"] = manifest
    mgr._installed_names = ["no_entry"]

    # Call load_plugin directly to avoid discover() clearing our manifest
    result = mgr.load_plugin("no_entry")
    assert result is True  # not an error


def test_plugin_manager_load_plugin_import_error() -> None:
    """Plugin with missing entry module logs error."""

    mgr = PluginManager()

    # Create a temp directory with a plugin.py that has no register() function
    with tempfile.TemporaryDirectory() as tmpdir:
        plugin_file = Path(tmpdir) / "plugin.py"
        plugin_file.write_text("# no register function here\n")

        manifest = PluginManifest(
            name="bad_plugin", version="1.0.0", type="tts_engine", entry_point="plugin:register", directory=tmpdir
        )
        mgr._manifests["bad_plugin"] = manifest
        mgr._installed_names = ["bad_plugin"]

        result = mgr.load_plugin("bad_plugin")
        assert result is False
        assert "bad_plugin" in mgr.get_load_errors()


# ======================================================================
# Integration: EngineRegistry picks up plugin factories
# ======================================================================


@pytest.mark.asyncio
async def test_engine_registry_plugin_integration():
    """EngineRegistry.initialize() should find plugin-registered factories."""
    from src.audiobook_studio.tts.engine import EngineRegistry

    mgr = get_plugin_manager()

    class FakeEngine:
        engine_name = "test_plugin_tts"
        _loaded = False

        async def health_check(self):
            return {"healthy": True}

        async def close(self):
            pass

    async def fake_factory(**kwargs):
        return FakeEngine()

    mgr.register_tts_engine_factory("test_integration", "test_plugin_tts", fake_factory)

    registry = EngineRegistry()
    await registry.initialize({"test_plugin_tts": {"dummy": "config"}})

    assert "test_plugin_tts" in registry.list_engines()


# ======================================================================
# Integration: LLMProvidersConfig picks up plugin factories
# ======================================================================


def test_llm_providers_config_plugin_integration():
    """Test that PluginManager can register LLM provider factories (integration test via registry)."""
    from src.audiobook_studio.llm.config_loader import ProviderConfig, ProviderType, StageName

    mgr = get_plugin_manager()

    def make_provider():
        return ProviderConfig(
            name="test_plugin_llm",
            provider=ProviderType.OPENAI,
            model="test-model",
            api_key_env="TEST_KEY",
            priority=10,
            stages=[StageName.EXTRACT],
            enabled=True,
            extra_params={},
        )

    mgr.register_llm_provider_factory("test_integration", "test_plugin_llm", make_provider)

    # Verify the factory is registered in the manager
    registry = mgr.get_registry()
    assert "test_plugin_llm" in registry.list_llm_provider_names()

    record = registry.get_llm_provider_factory("test_plugin_llm")
    assert record is not None
    assert record.provider_name == "test_plugin_llm"
    assert record.plugin_name == "test_integration"

    # Call the factory and verify it returns a valid ProviderConfig
    provider = record.factory()
    assert provider.name == "test_plugin_llm"
    assert provider.provider == ProviderType.OPENAI
    assert provider.model == "test-model"
    assert provider.priority == 10


# ======================================================================
# Example plugin sanity checks
# ======================================================================


def test_example_tts_manifest_exists():
    """Example TTS plugin manifest is valid."""
    manifest_path = Path("plugins/example_tts/manifest.json")
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    assert data["name"] == "example_tts"
    assert data["type"] == "tts_engine"
    assert data["entry_point"] == "plugin:register"


def test_example_llm_manifest_exists():
    """Example LLM plugin manifest is valid."""
    manifest_path = Path("plugins/example_llm/manifest.json")
    assert manifest_path.exists()
    data = json.loads(manifest_path.read_text())
    assert data["name"] == "example_llm"
    assert data["type"] == "llm_provider"
    assert data["entry_point"] == "plugin:register"


def test_example_plugins_load():
    """Both example plugins load without error."""
    mgr = get_plugin_manager()
    mgr.discover()
    mgr.load_installed()

    # Install example plugins for this test
    mgr._installed_names = ["example_tts", "example_llm"]

    results = mgr.load_all_installed()
    assert results["example_tts"] is True
    assert results["example_llm"] is True

    registry = mgr.get_registry()
    assert "example_tts" in registry.list_tts_engine_names()
    assert "example_llm" in registry.list_llm_provider_names()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

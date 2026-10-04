"""Tests for S3.5 — plugin ecosystem + model marketplace.

验收(免费资源可达成部分):
- plugins/ 目录 + 清单 schema 可被发现
- GET /api/v1/models 展示可用模型(TTS 音色 + 插件)
- 一键安装(注册式,幂等,不触发网络下载)
"""

import json
from pathlib import Path

import pytest

import src.audiobook_studio.api.models_market as market_api
import src.audiobook_studio.plugins as plugins
from src.audiobook_studio.models_catalog import build_model_catalog


def test_discover_plugins_finds_sample():
    found = plugins.discover_plugins()
    names = {p.name for p in found}
    assert "sample_tts_voice" in names
    sample = next(p for p in found if p.name == "sample_tts_voice")
    assert sample.type == "tts_voice"
    assert len(sample.models) > 0


def test_install_plugin_is_idempotent_and_registration_only(tmp_path: Path):
    # Build an isolated plugins dir + installed registry in tmp_path.
    plugin_dir = tmp_path / "plugins" / "my_plugin"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "manifest.json").write_text(
        json.dumps(
            {
                "name": "my_plugin",
                "version": "1.0.0",
                "type": "tts_voice",
                "models": ["kokoro-zh"],
            }
        ),
        encoding="utf-8",
    )
    installed_path = tmp_path / "config" / "installed_plugins.json"

    orig_plugins_dir = plugins.PLUGINS_DIR
    orig_installed = plugins.INSTALLED_PLUGINS_PATH
    plugins.PLUGINS_DIR = tmp_path / "plugins"
    plugins.INSTALLED_PLUGINS_PATH = installed_path
    try:
        # First install
        r1 = plugins.install_plugin("my_plugin")
        assert r1["installed"] is True
        assert r1["already_installed"] is False
        # Idempotent second install
        r2 = plugins.install_plugin("my_plugin")
        assert r2["already_installed"] is True
        # Registry contains exactly one entry
        assert plugins.list_installed_plugins() == ["my_plugin"]
        # Uninstall
        r3 = plugins.uninstall_plugin("my_plugin")
        assert r3["removed"] is True
        assert plugins.list_installed_plugins() == []
    finally:
        plugins.PLUGINS_DIR = orig_plugins_dir
        plugins.INSTALLED_PLUGINS_PATH = orig_installed


def test_install_unknown_plugin_raises():
    with pytest.raises(KeyError):
        plugins.install_plugin("does_not_exist")


def test_build_model_catalog_structure():
    catalog = build_model_catalog()
    assert "tts_engines" in catalog
    assert "plugins" in catalog
    assert isinstance(catalog["tts_engines"], list)
    # Edge + Kokoro engines present
    engine_names = {e["engine"] for e in catalog["tts_engines"]}
    assert {"edge", "kokoro"} <= engine_names
    # Sample plugin surfaced
    plugin_names = {p["name"] for p in catalog["plugins"]}
    assert "sample_tts_voice" in plugin_names


def test_list_models_endpoint():
    resp = market_api.list_models()
    assert "tts_engines" in resp
    assert "plugins" in resp


def test_install_model_endpoint_404_for_unknown():
    from src.audiobook_studio.exceptions import NotFoundError

    with pytest.raises(NotFoundError) as exc:
        market_api.install_model(name="nope")
    assert exc.value.error_code == "NOT_FOUND"

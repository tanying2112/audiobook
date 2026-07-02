"""Tests for config loader module with Pydantic validation."""

import tempfile
from pathlib import Path

import pytest

from src.audiobook_studio.config.loader import (
    ConfigLoader,
    clear_config_cache,
    load_contract_versions,
    load_quality_thresholds,
    load_rules,
    reload_config_if_changed,
)


class TestConfigLoaderQualityThresholds:
    """Tests for ConfigLoader quality thresholds with Pydantic validation."""

    @pytest.fixture
    def loader(self):
        """Create a fresh ConfigLoader instance."""
        return ConfigLoader()

    def test_quality_thresholds_validation(self, loader, tmp_path):
        """Test Pydantic validation of quality thresholds."""
        config_file = tmp_path / "thresholds.yaml"
        config_file.write_text(
            """
overall:
  min_acceptable_score: 0.7
  excellent_score: 0.9
dimensions:
  speaker_clarity: 0.85
""",
            encoding="utf-8",
        )

        result = loader.load_quality_thresholds(str(config_file))
        assert result["overall"]["min_acceptable_score"] == 0.7
        assert result["dimensions"]["speaker_clarity"] == 0.85

    def test_quality_thresholds_defaults_for_missing(self, loader, tmp_path):
        """Test missing fields get Pydantic defaults."""
        config_file = tmp_path / "thresholds.yaml"
        config_file.write_text("overall:\n  min_acceptable_score: 0.8\n", encoding="utf-8")

        result = loader.load_quality_thresholds(str(config_file))
        # Missing fields should have defaults
        assert result["overall"]["excellent_score"] == 0.9  # default
        assert result["dimensions"]["speaker_clarity"] == 0.85  # default

    def test_quality_thresholds_nonexistent_file(self, loader, tmp_path):
        """Test nonexistent file returns default thresholds."""
        result = loader.load_quality_thresholds(str(tmp_path / "nonexistent.yaml"))
        assert "overall" in result
        assert "dimensions" in result
        assert result["overall"]["min_acceptable_score"] == 0.7


class TestConfigLoaderConstitutionalRules:
    """Tests for ConfigLoader constitutional rules with Pydantic validation."""

    @pytest.fixture
    def loader(self):
        """Create a fresh ConfigLoader instance."""
        return ConfigLoader()

    def test_constitutional_rules_validation(self, loader, tmp_path):
        """Test Pydantic validation of constitutional rules."""
        config_file = tmp_path / "rules.yaml"
        config_file.write_text(
            """
character_consistency:
  min_consistency_score: 0.95
  verify_voice_binding: true
""",
            encoding="utf-8",
        )

        result = loader.load_constitutional_rules(str(config_file))
        assert result["character_consistency"]["min_consistency_score"] == 0.95

    def test_constitutional_rules_nonexistent(self, loader, tmp_path):
        """Test nonexistent file returns empty dict."""
        result = loader.load_constitutional_rules(str(tmp_path / "nonexistent.yaml"))
        assert result == {}


class TestConfigLoaderContractVersions:
    """Tests for ConfigLoader contract versions with Pydantic validation."""

    @pytest.fixture
    def loader(self):
        """Create a fresh ConfigLoader instance."""
        return ConfigLoader()

    def test_contract_versions_with_global_alias(self, loader, tmp_path):
        """Test 'global' key is properly handled as alias."""
        config_file = tmp_path / "versions.yaml"
        config_file.write_text(
            """
global:
  current: 2
  schema: HARNESS_v2
stages:
  extract:
    current: 1
""",
            encoding="utf-8",
        )

        result = loader.load_contract_versions(str(config_file))
        # 'global' key should be preserved in output
        assert "global" in result or "global_contract" in result
        global_key = "global" if "global" in result else "global_contract"
        assert result[global_key]["current"] == 2

    def test_contract_versions_nonexistent(self, loader, tmp_path):
        """Test nonexistent file returns defaults."""
        result = loader.load_contract_versions(str(tmp_path / "nonexistent.yaml"))
        assert "stages" in result
        assert "compatibility" in result


class TestConfigLoaderPipelineConfig:
    """Tests for ConfigLoader pipeline configuration."""

    @pytest.fixture
    def loader(self):
        """Create a fresh ConfigLoader instance."""
        return ConfigLoader()

    def test_pipeline_config_validation(self, loader, tmp_path):
        """Test full pipeline config validation."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text(
            """
quality_thresholds:
  overall:
    min_acceptable_score: 0.75
constitutional_rules:
  character_consistency:
    min_consistency_score: 0.92
""",
            encoding="utf-8",
        )

        result = loader.load_pipeline_config(str(config_file))
        assert "quality_thresholds" in result
        assert "constitutional_rules" in result
        assert result["quality_thresholds"]["overall"]["min_acceptable_score"] == 0.75
        assert result["constitutional_rules"]["character_consistency"]["min_consistency_score"] == 0.92

    def test_pipeline_config_cache(self, loader, tmp_path):
        """Test config caching."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text(
            "quality_thresholds:\n  overall:\n    min_acceptable_score: 0.8\n",
            encoding="utf-8",
        )

        result1 = loader.load_pipeline_config(str(config_file))
        result2 = loader.load_pipeline_config(str(config_file))

        # Should return cached result
        assert result1 is result2

    def test_pipeline_config_clear_cache(self, loader, tmp_path):
        """Test cache clearing."""
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text(
            "quality_thresholds:\n  overall:\n    min_acceptable_score: 0.8\n",
            encoding="utf-8",
        )

        loader.load_pipeline_config(str(config_file))
        loader.clear_cache(str(config_file))

        # After clear, cache should be empty for this path
        assert str(config_file) not in loader._cache


class TestLegacyFunctions:
    """Tests for backward-compatible module-level functions."""

    def test_load_rules_legacy(self, tmp_path):
        """Test legacy load_rules function."""
        config_file = tmp_path / "rules.yaml"
        config_file.write_text("key1: value1\nkey2: value2\n", encoding="utf-8")

        result = load_rules(str(config_file))
        # With Pydantic validation, partial config gets merged with defaults
        assert isinstance(result, dict)
        assert "key1" in result or "character_consistency" in result

    def test_load_rules_nonexistent(self, tmp_path):
        """Test legacy load_rules with nonexistent file."""
        result = load_rules(str(tmp_path / "nonexistent.yaml"))
        assert result == {}

    def test_load_quality_thresholds_legacy(self, tmp_path):
        """Test legacy load_quality_thresholds function."""
        config_file = tmp_path / "thresholds.yaml"
        config_file.write_text("overall:\n  min_score: 0.8\n", encoding="utf-8")

        result = load_quality_thresholds(str(config_file))
        assert isinstance(result, dict)
        assert "overall" in result

    def test_load_contract_versions_legacy(self, tmp_path):
        """Test legacy load_contract_versions function."""
        config_file = tmp_path / "versions.yaml"
        config_file.write_text("global:\n  current: 3\n", encoding="utf-8")

        result = load_contract_versions(str(config_file))
        assert isinstance(result, dict)
        assert "global" in result or "global_contract" in result


class TestReloadConfigIfChanged:
    """Tests for reload_config_if_changed function."""

    def test_first_load(self, tmp_path):
        """Test first load returns config and modification time."""
        config_file = tmp_path / "rules.yaml"
        config_file.write_text("key: value\n", encoding="utf-8")

        config, mtime = reload_config_if_changed(str(config_file))
        assert isinstance(config, dict)
        assert mtime is not None

    def test_nonexistent_file(self, tmp_path):
        """Test nonexistent file returns empty config."""
        config, mtime = reload_config_if_changed(str(tmp_path / "nonexistent.yaml"))
        assert config == {}
        assert mtime is None


class TestConfigFileLock:
    """Tests for ConfigFileLock class."""

    def test_lock_acquire_release(self):
        """Test file lock acquire and release."""
        from src.audiobook_studio.config.loader import ConfigFileLock

        with ConfigFileLock.acquire("/tmp/test_config.yaml"):
            # Lock acquired
            pass
        # Lock released


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

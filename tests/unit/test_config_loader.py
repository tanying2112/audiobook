"""Tests for config loader module."""

import tempfile
from pathlib import Path

import pytest

from src.audiobook_studio.config.loader import (
    load_rules,
    load_quality_thresholds,
    load_contract_versions,
    reload_config_if_changed,
    _get_default_quality_thresholds,
    _get_default_contract_versions,
)


class TestLoadRules:
    """Tests for load_rules function."""

    def test_load_existing_file(self, tmp_path):
        """Test loading an existing YAML file."""
        config_file = tmp_path / "rules.yaml"
        config_file.write_text("key1: value1\nkey2: value2\n", encoding="utf-8")

        result = load_rules(str(config_file))
        assert result == {"key1": "value1", "key2": "value2"}

    def test_load_nonexistent_file(self, tmp_path):
        """Test loading a nonexistent file returns empty dict."""
        result = load_rules(str(tmp_path / "nonexistent.yaml"))
        assert result == {}

    def test_load_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML returns empty dict."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: content: [", encoding="utf-8")

        result = load_rules(str(config_file))
        assert result == {}

    def test_load_empty_file(self, tmp_path):
        """Test loading empty file returns empty dict."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("", encoding="utf-8")

        result = load_rules(str(config_file))
        assert result == {}

    def test_load_non_dict_yaml(self, tmp_path):
        """Test loading YAML that's not a dict returns empty dict."""
        config_file = tmp_path / "list.yaml"
        config_file.write_text("- item1\n- item2\n", encoding="utf-8")

        result = load_rules(str(config_file))
        assert result == {}


class TestLoadQualityThresholds:
    """Tests for load_quality_thresholds function."""

    def test_load_existing_file(self, tmp_path):
        """Test loading an existing quality thresholds file."""
        config_file = tmp_path / "thresholds.yaml"
        config_file.write_text("overall:\n  min_score: 0.8\n", encoding="utf-8")

        result = load_quality_thresholds(str(config_file))
        assert result == {"overall": {"min_score": 0.8}}

    def test_load_nonexistent_file_returns_defaults(self, tmp_path):
        """Test nonexistent file returns default thresholds."""
        result = load_quality_thresholds(str(tmp_path / "nonexistent.yaml"))

        # Should contain default values
        assert "overall" in result
        assert "dimensions" in result
        assert "errors" in result
        assert "feedback" in result
        assert "audio" in result

    def test_load_invalid_yaml_returns_defaults(self, tmp_path):
        """Test invalid YAML returns default thresholds."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: [", encoding="utf-8")

        result = load_quality_thresholds(str(config_file))

        # Should contain default values
        assert "overall" in result
        assert "dimensions" in result

    def test_default_thresholds_structure(self):
        """Test default quality thresholds have expected structure."""
        defaults = _get_default_quality_thresholds()

        assert defaults["overall"]["min_acceptable_score"] == 0.7
        assert defaults["overall"]["excellent_score"] == 0.9
        assert defaults["overall"]["schema_compliance_rate"] == 0.99

        assert defaults["dimensions"]["speaker_clarity"] == 0.85
        assert defaults["dimensions"]["emotion_match"] == 0.80
        assert defaults["dimensions"]["prosody_naturalness"] == 0.75
        assert defaults["dimensions"]["text_audio_alignment"] == 0.80

        assert defaults["errors"]["max_silent_segments"] == 0
        assert defaults["errors"]["max_stuttering_issues"] == 0

        assert defaults["feedback"]["wrong_speaker_consecutive"] == 3
        assert defaults["audio"]["silence_threshold_db"] == -40


class TestLoadContractVersions:
    """Tests for load_contract_versions function."""

    def test_load_existing_file(self, tmp_path):
        """Test loading an existing contract versions file."""
        config_file = tmp_path / "versions.yaml"
        config_file.write_text("global:\n  current: 2\n", encoding="utf-8")

        result = load_contract_versions(str(config_file))
        assert result == {"global": {"current": 2}}

    def test_load_nonexistent_file_returns_defaults(self, tmp_path):
        """Test nonexistent file returns default contract versions."""
        result = load_contract_versions(str(tmp_path / "nonexistent.yaml"))

        # Should contain default structure
        assert "global" in result
        assert "stages" in result
        assert "compatibility" in result
        assert "deprecation" in result
        assert "validation" in result

    def test_load_invalid_yaml_returns_defaults(self, tmp_path):
        """Test invalid YAML returns default contract versions."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: [", encoding="utf-8")

        result = load_contract_versions(str(config_file))

        assert "global" in result
        assert "stages" in result

    def test_default_contract_versions_structure(self):
        """Test default contract versions have expected structure."""
        defaults = _get_default_contract_versions()

        assert defaults["global"]["current"] == 1
        assert defaults["global"]["min_compatible"] == 1
        assert defaults["global"]["schema"] == "HARNESS_v1"

        # Check all stages present
        stages = defaults["stages"]
        assert "extract" in stages
        assert "analyze_structure" in stages
        assert "annotate_paragraph" in stages
        assert "edit_for_tts" in stages
        assert "tts_routing" in stages
        assert "synthesize" in stages
        assert "quality_check" in stages

        assert stages["extract"]["current"] == 1
        assert stages["extract"]["input_schema"] == "ExtractionInput"

        assert defaults["compatibility"]["version_format"] == "major.minor.patch"
        assert defaults["deprecation"]["cycles_before_removal"] == 3


class TestReloadConfigIfChanged:
    """Tests for reload_config_if_changed function."""

    def test_first_load(self, tmp_path):
        """Test first load returns config and modification time."""
        config_file = tmp_path / "rules.yaml"
        config_file.write_text("key: value\n", encoding="utf-8")

        config, mtime = reload_config_if_changed(str(config_file))
        assert config == {"key": "value"}
        assert mtime is not None

    def test_no_change(self, tmp_path):
        """Test no change returns cached config with same mtime."""
        config_file = tmp_path / "rules.yaml"
        config_file.write_text("key: value\n", encoding="utf-8")

        config1, mtime1 = reload_config_if_changed(str(config_file))
        config2, mtime2 = reload_config_if_changed(str(config_file), mtime1)

        assert config2 == config1
        assert mtime2 == mtime1

    def test_file_changed(self, tmp_path):
        """Test file change triggers reload."""
        config_file = tmp_path / "rules.yaml"
        config_file.write_text("key: value1\n", encoding="utf-8")

        config1, mtime1 = reload_config_if_changed(str(config_file))
        assert config1 == {"key": "value1"}

        # Modify file
        import time
        time.sleep(0.1)
        config_file.write_text("key: value2\n", encoding="utf-8")

        config2, mtime2 = reload_config_if_changed(str(config_file), mtime1)
        assert config2 == {"key": "value2"}
        assert mtime2 > mtime1

    def test_nonexistent_file(self, tmp_path):
        """Test nonexistent file returns empty config."""
        config, mtime = reload_config_if_changed(str(tmp_path / "nonexistent.yaml"))
        assert config == {}
        assert mtime is None

    def test_quality_thresholds_reload(self, tmp_path):
        """Test reload for quality thresholds file path."""
        config_file = tmp_path / "quality_thresholds.yaml"
        config_file.write_text("overall:\n  min_score: 0.9\n", encoding="utf-8")

        config, mtime = reload_config_if_changed(str(config_file))
        assert "overall" in config
        assert config["overall"]["min_score"] == 0.9

    def test_contract_versions_reload(self, tmp_path):
        """Test reload for contract versions file path."""
        config_file = tmp_path / "contract_versions.yaml"
        config_file.write_text("global:\n  current: 3\n", encoding="utf-8")

        config, mtime = reload_config_if_changed(str(config_file))
        assert "global" in config
        assert config["global"]["current"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
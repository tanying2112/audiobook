"""Tests for config loader module with Pydantic validation - Isolated version."""

import sys
import tempfile
from pathlib import Path

import pytest


# 隔离导入：直接加载 loader.py 而不触发包级导入
def _load_loader_module():
    """Load loader module in isolation."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "loader", Path(__file__).parent.parent / "src/audiobook_studio/config/loader.py"
    )
    module = importlib.util.module_from_spec(spec)
    # 注入必要依赖
    sys.modules["audiobook_studio.config.loader"] = module
    return module


class TestConfigLoaderQualityThresholds:
    """Tests for ConfigLoader quality thresholds with Pydantic validation."""

    @pytest.fixture
    def loader(self):
        """Create a fresh ConfigLoader instance."""
        from audiobook_studio.config.loader import ConfigLoader

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
        from audiobook_studio.config.loader import ConfigLoader

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
        from audiobook_studio.config.loader import ConfigLoader

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
        assert "global" in result or "global_contract" in result
        global_key = "global" if "global" in result else "global_contract"
        assert result[global_key]["current"] == 2


class TestConfigLoaderPipelineConfig:
    """Tests for ConfigLoader pipeline configuration."""

    @pytest.fixture
    def loader(self):
        """Create a fresh ConfigLoader instance."""
        from audiobook_studio.config.loader import ConfigLoader

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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

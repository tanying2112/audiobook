"""Tests for semantic_coherence.py (语义连贯性检查器)."""

from unittest.mock import MagicMock, patch

import pytest

from audiobook_studio.quality.semantic_coherence import SemanticCoherenceChecker


class TestSemanticCoherenceChecker:
    """Test SemanticCoherenceChecker class."""

    def test_get_default_config(self):
        """_get_default_config 返回含 audio 阈值的默认配置。"""
        checker = SemanticCoherenceChecker()
        config = checker._get_default_config()
        assert isinstance(config, dict)
        assert "audio" in config
        assert config["audio"]["semantic_coherence_threshold"] == 0.75
        assert config["audio"]["emotional_coherence_threshold"] == 0.80

    def test_init_default_config(self):
        """配置源返回空时构造器回退到默认配置（路径参数仅为兼容）。"""
        mock_unified = MagicMock()
        mock_unified.load_yaml_config.return_value = None
        with patch(
            "audiobook_studio.quality.semantic_coherence.get_unified_config",
            return_value=mock_unified,
        ):
            checker = SemanticCoherenceChecker("/nonexistent/dummy.yaml")
        assert checker.config == checker._get_default_config()
        # 模型属性存在(未装 sentence-transformers 时为 None, 已装时加载成功)
        assert hasattr(checker, "semantic_model")

    def test_init_with_config_file(self):
        """构造器经 UnifiedConfig 加载 quality_thresholds 配置。"""
        loaded = {
            "audio": {
                "semantic_coherence_threshold": 0.9,
                "emotional_coherence_threshold": 0.85,
            }
        }
        mock_unified = MagicMock()
        mock_unified.load_yaml_config.return_value = loaded
        with patch(
            "audiobook_studio.quality.semantic_coherence.get_unified_config",
            return_value=mock_unified,
        ):
            checker = SemanticCoherenceChecker("dummy/path.yaml")
        assert checker.config["audio"]["semantic_coherence_threshold"] == 0.9
        assert checker.config["audio"]["emotional_coherence_threshold"] == 0.85

    def test_calculate_semantic_similarity_fallback(self):
        """无模型时 _compute_semantic_similarity 走确定性回退路径。"""
        checker = SemanticCoherenceChecker()
        checker.semantic_model = None  # 强制回退路径
        sim_same = checker._compute_semantic_similarity("你好世界", "你好世界")
        sim_diff = checker._compute_semantic_similarity("你好世界", "xyzqwk")
        assert isinstance(sim_same, float)
        assert isinstance(sim_diff, float)
        # 相同文本相似度 >= 不同文本
        assert sim_same >= sim_diff

"""Tests for semantic_coherence.py (语义连贯性检查器)."""

from unittest.mock import MagicMock

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

    def test_init_default_config(self, tmp_path):
        """配置文件缺失时构造器回退到默认配置。"""
        cfg = tmp_path / "missing.yaml"  # 不存在 -> FileNotFoundError -> 默认配置
        checker = SemanticCoherenceChecker(str(cfg))
        assert checker.config == checker._get_default_config()
        # 模型属性存在(未装 sentence-transformers 时为 None, 已装时加载成功)
        assert hasattr(checker, "semantic_model")

    def test_init_with_config_file(self, tmp_path):
        """构造器从 YAML 文件加载配置。"""
        cfg = tmp_path / "quality_thresholds.yaml"
        cfg.write_text(
            "audio:\n"
            "  semantic_coherence_threshold: 0.9\n"
            "  emotional_coherence_threshold: 0.85\n",
            encoding="utf-8",
        )
        checker = SemanticCoherenceChecker(str(cfg))
        assert checker.config["audio"]["semantic_coherence_threshold"] == 0.9
        assert checker.config["audio"]["emotional_coherence_threshold"] == 0.85

    def test_calculate_semantic_similarity_fallback(self):
        """无模型时 _calculate_semantic_similarity 走确定性回退路径。"""
        checker = SemanticCoherenceChecker()
        checker.semantic_model = None  # 强制回退路径
        sim_same = checker._calculate_semantic_similarity("你好世界", "你好世界")
        sim_diff = checker._calculate_semantic_similarity("你好世界", "xyzqwk")
        assert isinstance(sim_same, float)
        assert isinstance(sim_diff, float)
        # 相同文本相似度 >= 不同文本
        assert sim_same >= sim_diff

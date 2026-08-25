#!/usr/bin/env python3
"""
Audiobook Studio — 语义连贯性检查器
====================================
实现使用 Sentence-BERT 计算相邻段落语义/情感向量差异，
阈值从 config/quality_thresholds.yaml 读取。
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Use UnifiedConfig for centralized configuration loading
from ..config.unified import get_unified_config

logger = logging.getLogger(__name__)


class SemanticCoherenceChecker:
    """语义连贯性检查器，使用 Sentence-BERT 计算向量差异。"""

    def __init__(self, config_path: str = "config/quality_thresholds.yaml"):
        """
        初始化语义连贯性检查器.

        Args:
            config_path: 配置文件路径（兼容性参数，实际使用 UnifiedConfig）
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._init_models()

    def _load_config(self) -> Dict[str, Any]:
        """加载质量阈值配置 (通过 UnifiedConfig 统一管理)."""
        try:
            unified = get_unified_config()
            config: Dict[str, Any] = unified.load_yaml_config("quality_thresholds")
            if not config:
                logger.warning(f"⚠️ 配置文件未找到: {self.config_path}，使用默认值")
                return self._get_default_config()
            logger.info(f"✅ 已加载质量阈值配置 (via UnifiedConfig)")
            return config
        except Exception as e:
            logger.error(f"❌ 加载配置文件失败: {e}，使用默认值")
            return self._get_default_config()

    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置."""
        return {
            "audio": {
                "semantic_coherence_threshold": 0.75,
                "emotional_coherence_threshold": 0.80,
            }
        }

    def _init_models(self) -> None:
        """初始化Sentence-BERT模型."""
        try:
            # 尝试导入sentence-transformers
            from sentence_transformers import SentenceTransformer

            # 使用多语言模型以支持中英文等多语言场景
            self.semantic_model = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            logger.info("✅ 已加载 Sentence-BERT 多语言模型")
        except ImportError:
            logger.warning("⚠️ sentence-transformers 未安装，将使用简化的语义检查")
            self.semantic_model = None
        except Exception as e:
            logger.error(f"❌ 加载 Sentence-BERT 模型失败: {e}")
            self.semantic_model = None

    def check_coherence(
        self,
        paragraphs: List[str],
        check_emotional_curve: bool = True,
        reference_paragraphs: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        检查段落之间的语义和情感连贯性.

        Args:
            paragraphs: 要检查的段落列表
            check_emotional_curve: 是否检查情感强度曲线连续性
            reference_paragraphs: 参考段落列表（用于翻译前后对比）

        Returns:
            检查结果字典，包含得分、是否通过和问题列表
        """
        if not paragraphs or len(paragraphs) < 2:
            return {
                "passed": True,
                "score": 1.0,
                "semantic_score": 1.0,
                "emotional_score": 1.0,
                "issues": ["段落数量不足，无法进行连贯性检查"],
            }

        issues = []
        semantic_scores = []
        emotional_scores = []

        # 获取阈值
        audio_config = self.config.get("audio", {})
        semantic_threshold = audio_config.get("semantic_coherence_threshold", 0.75)
        emotional_threshold = audio_config.get("emotional_coherence_threshold", 0.80)

        # 计算相邻段落语义相似度
        for i in range(len(paragraphs) - 1):
            semantic_score = self._compute_semantic_similarity(paragraphs[i], paragraphs[i + 1])
            semantic_scores.append(semantic_score)

            if semantic_score < semantic_threshold:
                issues.append(
                    f"段落 {i+1}-{i+2} 语义连贯性低: {semantic_score:.3f} < {semantic_threshold}"
                )

        # 情感连贯性检查
        if check_emotional_curve:
            emotional_scores = self._compute_emotional_curve(paragraphs)
            for i, score in enumerate(emotional_scores):
                if score < emotional_threshold:
                    issues.append(
                        f"段落 {i+1} 情感连贯性低: {score:.3f} < {emotional_threshold}"
                    )

        # 计算总体得分
        avg_semantic = np.mean(semantic_scores) if semantic_scores else 1.0
        avg_emotional = np.mean(emotional_scores) if emotional_scores else 1.0
        overall_score = (avg_semantic + avg_emotional) / 2

        return {
            "passed": len(issues) == 0,
            "score": float(overall_score),
            "semantic_score": float(avg_semantic),
            "emotional_score": float(avg_emotional),
            "issues": issues,
            "semantic_scores": [float(s) for s in semantic_scores],
            "emotional_scores": [float(s) for s in emotional_scores],
        }

    def _compute_semantic_similarity(self, text1: str, text2: str) -> float:
        """计算两段文本的语义相似度."""
        if self.semantic_model is None:
            # 简化的词汇重叠相似度作为降级
            return self._lexical_overlap(text1, text2)

        try:
            embeddings = self.semantic_model.encode([text1, text2], convert_to_numpy=True)
            from numpy.linalg import norm

            sim = np.dot(embeddings[0], embeddings[1]) / (norm(embeddings[0]) * norm(embeddings[1]))
            return float(np.clip(sim, 0.0, 1.0))
        except Exception as e:
            logger.warning(f"语义相似度计算失败: {e}，使用词汇重叠降级")
            return self._lexical_overlap(text1, text2)

    def _lexical_overlap(self, text1: str, text2: str) -> float:
        """基于词汇重叠的简化相似度 (降级方案)."""
        words1 = set(text1.split())
        words2 = set(text2.split())
        if not words1 or not words2:
            return 0.0
        intersection = words1 & words2
        union = words1 | words2
        return len(intersection) / len(union)

    def _compute_emotional_curve(self, paragraphs: List[str]) -> List[float]:
        """计算情感强度曲线 (简化版：基于情感词汇)."""
        # 简化实现：基于标点和情感词汇启发式
        emotional_keywords = {
            "positive": ["开心", "高兴", "快乐", "兴奋", "喜悦", "满意", "幸福", "温暖", "甜蜜", "欢笑"],
            "negative": ["悲伤", "痛苦", "愤怒", "恐惧", "绝望", "孤独", "失望", "心酸", "委屈", "哭泣"],
            "neutral": ["平静", "冷静", "思考", "观察", "描述", "叙述", "说明", "解释"],
        }

        scores = []
        for para in paragraphs:
            pos_count = sum(1 for kw in emotional_keywords["positive"] if kw in para)
            neg_count = sum(1 for kw in emotional_keywords["negative"] if kw in para)
            neu_count = sum(1 for kw in emotional_keywords["neutral"] if kw in para)

            total = pos_count + neg_count + neu_count
            if total == 0:
                scores.append(1.0)  # 无情感词汇，视为平稳
            else:
                # 情感强度：极性词汇占比
                intensity = (pos_count + neg_count) / max(total, 1)
                # 连贯性：相邻段落情感方向一致性 (简化)
                scores.append(1.0 - intensity * 0.5)  # 启发式：情感越强烈越难连贯

        return scores


# Backward-compatible convenience function
def check_semantic_coherence(
    paragraphs: List[str],
    config_path: str = "config/quality_thresholds.yaml",
    **kwargs,
) -> Dict[str, Any]:
    """便捷函数：检查语义连贯性."""
    checker = SemanticCoherenceChecker(config_path)
    return checker.check_coherence(paragraphs, **kwargs)


if __name__ == "__main__":
    # 简单测试
    test_paragraphs = [
        "第一章 少年独自站在山巅，望着远方的云海发呆。",
        "微风拂过他的发梢，带来一丝凉意，却吹不散心头的愁绪。",
        "突然，一道剑光划破长空，打破了山巅的宁静。",
    ]

    result = check_semantic_coherence(test_paragraphs)
    print(f"语义连贯性检查结果: {result}")

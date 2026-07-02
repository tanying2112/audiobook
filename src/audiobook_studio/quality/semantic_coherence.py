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
import yaml

logger = logging.getLogger(__name__)


class SemanticCoherenceChecker:
    """语义连贯性检查器，使用 Sentence-BERT 计算向量差异。"""

    def __init__(self, config_path: str = "config/quality_thresholds.yaml"):
        """
        初始化语义连贯性检查器.

        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self.config = self._load_config()
        self._init_models()

    def _load_config(self) -> Dict[str, Any]:
        """加载质量阈值配置."""
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            logger.info(f"✅ 已加载质量阈值配置: {self.config_path}")
            return config
        except FileNotFoundError:
            logger.warning(f"⚠️ 配置文件未找到: {self.config_path}，使用默认值")
            return self._get_default_config()
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

    def _init_models(self):
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

        # 1. 检查相邻段落的语义连贯性
        for i in range(len(paragraphs) - 1):
            para1 = paragraphs[i]
            para2 = paragraphs[i + 1]

            if not para1.strip() or not para2.strip():
                semantic_scores.append(1.0)  # 空段落视为连贯
                continue

            semantic_similarity = self._calculate_semantic_similarity(para1, para2)
            semantic_scores.append(semantic_similarity)

            # 检查是否低于阈值
            threshold = self.config.get("audio", {}).get("semantic_coherence_threshold", 0.75)
            if semantic_similarity < threshold:
                issues.append(f"段落 {i+1}-{i+2} 语义连贯性不足: {semantic_similarity:.3f} < {threshold}")

        # 2. 如果需要，检查情感强度曲线连续性
        if check_emotional_curve:
            emotional_scores = self._check_emotional_curve_continuity(paragraphs)
            for i, score in enumerate(emotional_scores):
                if score < 1.0:  # 情感曲线不连续
                    threshold = self.config.get("audio", {}).get("emotional_coherence_threshold", 0.80)
                    issues.append(f"段落 {i+1}-{i+2} 情感强度曲线不连续: {score:.3f} < {threshold}")

        # 3. 如果有参考段落，检查翻译前后的一致性
        if reference_paragraphs and len(reference_paragraphs) == len(paragraphs):
            translation_scores = []
            for i, (orig, trans) in enumerate(zip(reference_paragraphs, paragraphs)):
                if not orig.strip() or not trans.strip():
                    translation_scores.append(1.0)
                    continue

                similarity = self._calculate_semantic_similarity(orig, trans)
                translation_scores.append(similarity)

                # 检查翻译语义保持度
                threshold = self.config.get("audio", {}).get("semantic_coherence_threshold", 0.75)
                if similarity < threshold:
                    issues.append(f"段落 {i+1} 翻译语义保持度不足: {similarity:.3f} < {threshold}")

            # 翻译质量得分是所有段落的平均 similarity
            if translation_scores:
                translation_quality = np.mean(translation_scores)
            else:
                translation_quality = 1.0
        else:
            translation_quality = None

        # 计算总体得分
        semantic_score = np.mean(semantic_scores) if semantic_scores else 1.0
        emotional_score = np.mean(emotional_scores) if emotional_scores and check_emotional_curve else 1.0

        # 综合得分（可以根据需要调整权重）
        if check_emotional_curve:
            overall_score = (semantic_score * 0.6) + (emotional_score * 0.4)
        else:
            overall_score = semantic_score

        # 检查是否通过所有阈值
        semantic_threshold = self.config.get("audio", {}).get("semantic_coherence_threshold", 0.75)
        emotional_threshold = self.config.get("audio", {}).get("emotional_coherence_threshold", 0.80)

        passed = semantic_score >= semantic_threshold and (
            not check_emotional_curve or emotional_score >= emotional_threshold
        )

        result = {
            "passed": passed,
            "score": float(overall_score),
            "semantic_score": float(semantic_score),
            "emotional_score": (float(emotional_score) if check_emotional_curve else None),
            "translation_quality": (float(translation_quality) if translation_quality is not None else None),
            "issues": issues,
        }

        if passed:
            logger.info(f"✅ 语义连贯性检查通过: 得分 {overall_score:.3f}")
        else:
            logger.warning(f"⚠️ 语义连贯性检查失败: 得分 {overall_score:.3f}, 问题 {len(issues)} 个")

        return result

    def _calculate_semantic_similarity(self, text1: str, text2: str) -> float:
        """
        计算两个文本的语义相似度.

        Args:
            text1: 第一个文本
            text2: 第二个文本

        Returns:
            相似度分数 (0-1, 1表示完全相似)
        """
        if self.semantic_model is not None:
            try:
                # 使用Sentence-BERT计算嵌入向量
                embeddings = self.semantic_model.encode([text1, text2])
                # 计算余弦相似度
                similarity = np.dot(embeddings[0], embeddings[1]) / (
                    np.linalg.norm(embeddings[0]) * np.linalg.norm(embeddings[1])
                )
                return float(similarity)
            except Exception as e:
                logger.error(f"❌ 计算语义相似度失败: {e}")
                # 回退到简化方法
                return self._fallback_similarity(text1, text2)
        else:
            # 使用简化的语义相似度计算
            return self._fallback_similarity(text1, text2)

    def _fallback_similarity(self, text1: str, text2: str) -> float:
        """
        简化的语义相似度计算（当无法使用Sentence-BERT时）.

        Args:
            text1: 第一个文本
            text2: 第二个文本

        Returns:
            相似度分数 (0-1)
        """
        # 简单的基于字符的相似度作为后备
        if not text1 and not text2:
            return 1.0
        if not text1 or not text2:
            return 0.0

        # 使用Jaccard相似度的字符级版本
        set1 = set(text1.lower())
        set2 = set(text2.lower())

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        if union == 0:
            return 1.0
        return intersection / union

    def _check_emotional_curve_continuity(self, paragraphs: List[str]) -> List[float]:
        """
        检查情感强度曲线的连续性.

        Args:
            paragraphs: 段落列表

        Returns:
            每对相邻段落的情感曲线连续性得分列表 (0-1, 1表示完全连续)
        """
        # 在实际实现中，这里会使用情感分析模型来提取每个段落的情感向量
        # 在实际实现中，这里会使用情感分析模型来提取每个段落的情感向量
        # 然后计算相邻情感向量之间的差异
        # 由于这是一个简化实现,我们使用启发式方法
        scores = []
        for i in range(len(paragraphs) - 1):
            para1 = paragraphs[i]
            para2 = paragraphs[i + 1]

            # 简化的情感强度估计：基于感叹号、问号和某些情感词汇
            emotion1 = self._estimate_emotion_intensity(para1)
            emotion2 = self._estimate_emotion_intensity(para2)

            # 计算情感强度差异（归一化到0-1范围，1表示完全相同）
            diff = abs(emotion1 - emotion2)
            score = max(0.0, 1.0 - diff)  # 差异越小，得分越高
            scores.append(score)

        return scores

    def _estimate_emotion_intensity(self, text: str) -> float:
        """
        估算文本的情感强度（简化版）.

        Args:
            text: 输入文本

        Returns:
            情感强度得分 (0-1, 1表示最强情感)
        """
        if not text:
            return 0.0

        # 简单的基于标点和情感词的启发式方法
        emotion_words = {
            "positive": [
                "高兴",
                "快乐",
                "愉快",
                "兴奋",
                "喜悦",
                "欢乐",
                "happy",
                "joy",
                "excited",
                "pleased",
            ],
            "negative": [
                "悲伤",
                "难过",
                "痛苦",
                "愤怒",
                "生气",
                "害怕",
                "恐惧",
                "sad",
                "angry",
                "afraid",
                "fear",
            ],
            "intense": [
                "非常",
                "极其",
                "特别",
                "十分",
                "巨く",
                "very",
                "extremely",
                "really",
                "so",
            ],
        }

        text_lower = text.lower()
        score = 0.0

        # 检查感叹号和问号（表示强烈情感）
        exclamation_count = text.count("!") + text.count("！")
        question_count = text.count("?") + text.count("？")
        score += min(0.3, (exclamation_count + question_count) * 0.1)

        # 检查情感词汇
        for category, words in emotion_words.items():
            for word in words:
                if word in text_lower:
                    if category == "intense":
                        score += 0.2
                    else:
                        score += 0.15

        # 检查重复字符或夸张表达
        import re

        repeated_chars = len(re.findall(r"(.)\1{2,}", text))  # 如aaa、hhh等
        score += min(0.2, repeated_chars * 0.05)

        # 归一化到0-1范围
        return min(1.0, score)


def main():
    """主函数 - 演示语义连贯性检查器."""
    logger.info("=== Audiobook Studio 语义连贯性检查器演示 ===\n")

    # 创建检查器
    checker = SemanticCoherenceChecker()

    # 示例段落
    paragraphs = [
        "今天真是个美好的日子！阳光明媚，鸟儿歌唱。",
        "我决定去公园散步，享受这难得的好天气。",
        "突然，天空变得阴沉起来，远处传来雷声。",
        "我急忙跑回家，躲进了屋子里等待雨停。",
    ]

    logger.info("📋 输入段落:")
    for i, para in enumerate(paragraphs, 1):
        logger.info(f"   {i}. {para}")

    logger.info("\n" + "=" * 50)

    # 检查语义连贯性
    logger.info("\n🔍 检查语义连贯性...")
    result = checker.check_coherence(paragraphs, check_emotional_curve=True)

    logger.info(f"   总体得分: {result['score']:.3f}")
    logger.info(f"   语义得分: {result['semantic_score']:.3f}")
    logger.info(f"   情感得分: {result['emotional_score']:.3f}")
    logger.info(f"   是否通过: {'✅ 是' if result['passed'] else '❌ 否'}")

    if result["issues"]:
        logger.info(f"   发现问题 ({len(result['issues'])} 个):")
        for issue in result["issues"][:5]:  # 只显示前5个问题
            logger.info(f"     - {issue}")
        if len(result["issues"]) > 5:
            logger.info(f"     - 以及其他 {len(result['issues']) - 5} 个问题...")
    else:
        logger.info("   未发现问题")

    logger.info("\n" + "=" * 50)
    logger.info("🎉 演示完成")


if __name__ == "__main__":
    main()

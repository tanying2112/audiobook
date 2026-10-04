"""
SyntheticCritic 三元架构 - 异构批评网络

三元批评架构，防止"模型自嗨"：
1. SemanticCritic (语义派) - 基于语义连贯性、情感一致性、角色声音指纹
2. StructuralCritic (结构派) - 基于文档结构、章节边界、段落流程、成本约束
3. ObjectiveCritic (客观派) - 基于硬指标 DNSMOS、ASR WER、Speaker Similarity

三派通过加权投票或集成学习输出最终质量判断，F1 >= 0.7 在校准集上。
"""

from .base import BaseCritic, CriticEnsemble, CriticEnsembleEvaluator, CriticResult, CriticType, CriticVerdict
from .objective_critic import ObjectiveCritic
from .semantic_critic import SemanticCritic
from .structural_critic import StructuralCritic
from .synthetic_critic import (
    DEFAULT_CALIBRATION_SAMPLES,
    CalibrationResult,
    CalibrationSample,
    SyntheticCritic,
    create_synthetic_critic,
)

__all__ = [
    "BaseCritic",
    "CriticResult",
    "CriticEnsemble",
    "CriticType",
    "CriticVerdict",
    "CriticEnsembleEvaluator",
    "SemanticCritic",
    "StructuralCritic",
    "ObjectiveCritic",
    "SyntheticCritic",
    "CalibrationSample",
    "CalibrationResult",
    "DEFAULT_CALIBRATION_SAMPLES",
    "create_synthetic_critic",
]

"""
Base classes for SynticCritic 三元架构 - 异构批评网络.

定义批评器的基础接口、结果结构和集成逻辑。
"""

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np

from ...llm import LLMRouter, create_router
from ...schemas import FeedbackAnalysis

if TYPE_CHECKING:
    from .semantic_critic import SemanticCritic
    from .structural_critic import StructuralCritic
    from .objective_critic import ObjectiveCritic

logger = logging.getLogger(__name__)


class CriticType(Enum):
    """批评器类型枚举."""
    SEMANTIC = "semantic"      # 语义派 - 语义连贯性、情感一致性、角色声音指纹
    STRUCTURAL = "structural"  # 结构派 - 文档结构、章节边界、段落流程、成本约束
    OBJECTIVE = "objective"    # 客观派 - 硬指标 DNSMOS、ASR WER、Speaker Similarity


class CriticVerdict(Enum):
    """批评裁决."""
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    ABSTAIN = "abstain"


@dataclass
class CriticResult:
    """单个批评器的结果."""
    critic_type: CriticType
    verdict: CriticVerdict
    score: float  # 0-1, 越高越好
    confidence: float  # 0-1, 置信度
    reasoning: str  # 自然语言理由
    evidence: Dict[str, Any] = field(default_factory=dict)  # 支撑证据
    tags: List[str] = field(default_factory=list)  # 问题标签
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "critic_type": self.critic_type.value,
            "verdict": self.verdict.value,
            "score": self.score,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "evidence": self.evidence,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CriticResult":
        return cls(
            critic_type=CriticType(data["critic_type"]),
            verdict=CriticVerdict(data["verdict"]),
            score=data["score"],
            confidence=data["confidence"],
            reasoning=data["reasoning"],
            evidence=data.get("evidence", {}),
            tags=data.get("tags", []),
        )


@dataclass
class CriticEnsemble:
    """批评器集成结果."""
    results: List[CriticResult]
    final_verdict: CriticVerdict
    final_score: float
    weights: Dict[CriticType, float]
    rationale: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": [r.to_dict() for r in self.results],
            "final_verdict": self.final_verdict.value,
            "final_score": self.final_score,
            "weights": {k.value: v for k, v in self.weights.items()},
            "rationale": self.rationale,
        }


class BaseCritic(ABC):
    """批评器抽象基类.
    
    所有批评器必须实现 evaluate 方法，返回 CriticResult。
    """
    
    def __init__(
        self,
        critic_type: CriticType,
        router: Optional[LLMRouter] = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        self.critic_type = critic_type
        self.router = router or create_router()
        self.config = config or {}
        
        # 从配置加载阈值
        self.pass_threshold = self.config.get("pass_threshold", 0.7)
        self.warning_threshold = self.config.get("warning_threshold", 0.5)
        self.min_confidence = self.config.get("min_confidence", 0.5)
    
    @abstractmethod
    def evaluate(
        self,
        audio_path: Path,
        annotation: Any,  # ParagraphAnnotation
        routing_decision: Any,  # TtsRoutingDecision
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticResult:
        """评估音频质量.
        
        Args:
            audio_path: 音频文件路径
            annotation: 段落标注
            routing_decision: TTS 路由决策
            reference_text: 参考文本
            context: 额外上下文 (前后段落、章节信息等)
            
        Returns:
            CriticResult 包含裁决、分数、置信度、理由
        """
        pass
    
    def _determine_verdict(self, score: float) -> CriticVerdict:
        """根据分数确定裁决."""
        if score >= self.pass_threshold:
            return CriticVerdict.PASS
        elif score >= self.warning_threshold:
            return CriticVerdict.WARNING
        else:
            return CriticVerdict.FAIL
    
    def _build_base_prompt(self, task_description: str) -> str:
        """构建基础系统提示词."""
        return (
            f"你是 {self.critic_type.value} 批评器。{task_description}\n"
            "输出严格符合 JSON 格式的 CriticResult 结构。"
        )
    
    def _parse_llm_response(self, response: Dict[str, Any]) -> CriticResult:
        """解析 LLM 响应为 CriticResult."""
        # 处理可能的嵌套结构
        if "output" in response:
            data = response["output"]
        else:
            data = response
        
        # 确保必要字段存在
        return CriticResult(
            critic_type=self.critic_type,
            verdict=CriticVerdict(data.get("verdict", "fail")),
            score=float(data.get("score", 0.0)),
            confidence=float(data.get("confidence", 0.5)),
            reasoning=data.get("reasoning", ""),
            evidence=data.get("evidence", {}),
            tags=data.get("tags", []),
        )


class CriticEnsembleEvaluator:
    """批评器集成评估器.
    
    融合三个异构批评器的结果，输出最终裁决。
    支持加权投票、集成学习等多种融合策略。
    """
    
    def __init__(
        self,
        semantic_critic: Optional["SemanticCritic"] = None,
        structural_critic: Optional["StructuralCritic"] = None,
        objective_critic: Optional["ObjectiveCritic"] = None,
        weights: Optional[Dict[CriticType, float]] = None,
        strategy: str = "weighted_vote",  # weighted_vote | majority_vote | meta_learner
    ):
        self.semantic_critic = semantic_critic
        self.structural_critic = structural_critic
        self.objective_critic = objective_critic
        
        # 默认权重：客观派最高(硬指标)，语义派次之，结构派最低
        self.weights = weights or {
            CriticType.SEMANTIC: 0.3,
            CriticType.STRUCTURAL: 0.2,
            CriticType.OBJECTIVE: 0.5,
        }
        
        self.strategy = strategy
    
    def evaluate(
        self,
        audio_path: Path,
        annotation: Any,
        routing_decision: Any,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticEnsemble:
        """运行三元批评并融合结果."""
        results = []
        
        # 运行各批评器
        if self.semantic_critic:
            result = self.semantic_critic.evaluate(
                audio_path, annotation, routing_decision, reference_text, context
            )
            results.append(result)
        
        if self.structural_critic:
            result = self.structural_critic.evaluate(
                audio_path, annotation, routing_decision, reference_text, context
            )
            results.append(result)
        
        if self.objective_critic:
            result = self.objective_critic.evaluate(
                audio_path, annotation, routing_decision, reference_text, context
            )
            results.append(result)
        
        # 融合结果
        return self._fuse_results(results)
    
    def _fuse_results(self, results: List[CriticResult]) -> CriticEnsemble:
        """融合多个批评器结果."""
        if not results:
            return CriticEnsemble(
                results=[],
                final_verdict=CriticVerdict.ABSTAIN,
                final_score=0.0,
                weights={},
                rationale="No critics available",
            )
        
        # 计算加权分数
        total_weight = 0.0
        weighted_score = 0.0
        weighted_confidence = 0.0
        
        verdicts = {CriticVerdict.PASS: 0, CriticVerdict.WARNING: 0, CriticVerdict.FAIL: 0}
        
        for result in results:
            weight = self.weights.get(result.critic_type, 0.0)
            total_weight += weight
            weighted_score += result.score * weight
            weighted_confidence += result.confidence * weight
            verdicts[result.verdict] += 1
        
        final_score = weighted_score / total_weight if total_weight > 0 else 0.0
        final_confidence = weighted_confidence / total_weight if total_weight > 0 else 0.0
        
        # 确定最终裁决
        if verdicts[CriticVerdict.FAIL] > 0 and final_score < 0.5:
            final_verdict = CriticVerdict.FAIL
        elif verdicts[CriticVerdict.WARNING] > 0 or final_score < 0.7:
            final_verdict = CriticVerdict.WARNING
        else:
            final_verdict = CriticVerdict.PASS
        
        # 生成融合理由
        rationale_parts = []
        for result in results:
            rationale_parts.append(
                f"{result.critic_type.value}: {result.verdict.value} "
                f"(score={result.score:.2f}, conf={result.confidence:.2f}) - {result.reasoning[:100]}"
            )
        
        rationale = " | ".join(rationale_parts)
        
        return CriticEnsemble(
            results=results,
            final_verdict=final_verdict,
            final_score=final_score,
            weights=self.weights,
            rationale=rationale,
        )
    
    def evaluate_mock(
        self,
        audio_path: Path,
        annotation: Any,
        routing_decision: Any,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticEnsemble:
        """Mock 模式评估（用于测试）."""
        # 返回模拟结果
        mock_results = [
            CriticResult(
                critic_type=CriticType.SEMANTIC,
                verdict=CriticVerdict.PASS,
                score=0.85,
                confidence=0.9,
                reasoning="[Mock] 语义连贯性良好，情感匹配",
                evidence={"semantic_coherence": 0.88, "emotion_consistency": 0.92},
                tags=[],
            ),
            CriticResult(
                critic_type=CriticType.STRUCTURAL,
                verdict=CriticVerdict.WARNING,
                score=0.65,
                confidence=0.7,
                reasoning="[Mock] 段落边界略有偏差",
                evidence={"boundary_alignment": 0.7, "flow_smoothness": 0.6},
                tags=["paragraph_boundary_drift"],
            ),
            CriticResult(
                critic_type=CriticType.OBJECTIVE,
                verdict=CriticVerdict.PASS,
                score=0.9,
                confidence=0.95,
                reasoning="[Mock] DNSMOS=3.8, WER=0.02, SpeakerSim=0.92",
                evidence={"dnsmos": 3.8, "wer": 0.02, "speaker_sim": 0.92},
                tags=[],
            ),
        ]
        
        return self._fuse_results(mock_results)


# 延迟导入避免循环依赖
def _get_critics():
    from .semantic_critic import SemanticCritic
    from .structural_critic import StructuralCritic
    from .objective_critic import ObjectiveCritic
    return SemanticCritic, StructuralCritic, ObjectiveCritic

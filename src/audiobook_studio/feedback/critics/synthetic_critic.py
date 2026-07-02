"""
SyntheticCritic — 异构三元批评网络 (Issue 2.1)

防止"模型自嗨"的核心机制：三个异构批评器从不同维度独立评估质量，
通过加权投票/校准融合输出最终判定。

架构:
    SemanticCritic  (语义派) — 语义连贯性、情感一致性、角色声音指纹
    StructuralCritic(结构派) — 文档结构、章节边界、段落流程、成本约束
    ObjectiveCritic (客观派) — DNSMOS、ASR WER、Speaker Similarity

校准机制:
    - 内置校准数据集 (CalibrationSample) 含人工标注真值
    - F1 评估: 在校准集上计算 macro-F1, 目标 >= 0.7
    - 权重自适应: 通过校准集表现调整三派权重
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from .base import BaseCritic, CriticEnsemble, CriticEnsembleEvaluator, CriticResult, CriticType, CriticVerdict

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# 校准数据集
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CalibrationSample:
    """校准样本 — 包含模拟输入和人工标注真值.

    用于衡量批评网络在校准集上的 F1 分数。
    """

    sample_id: str
    description: str
    semantic_score: float
    structural_score: float
    objective_score: float
    ground_truth_verdict: CriticVerdict
    ground_truth_score: float
    ground_truth_tags: List[str] = field(default_factory=list)
    category: str = "general"
    difficulty: str = "medium"


# 内置校准数据集 — 20 个样本覆盖 PASS/WARNING/FAIL 各场景
DEFAULT_CALIBRATION_SAMPLES: List[CalibrationSample] = [
    # ─── PASS 样本 (高质量) ───
    CalibrationSample(
        sample_id="pass_001",
        description="优秀朗读：语义连贯、情感匹配、客观指标全优",
        semantic_score=0.88,
        structural_score=0.85,
        objective_score=0.92,
        ground_truth_verdict=CriticVerdict.PASS,
        ground_truth_score=0.88,
        ground_truth_tags=[],
        category="narration",
        difficulty="easy",
    ),
    CalibrationSample(
        sample_id="pass_002",
        description="对话场景：角色声音匹配、情感精准",
        semantic_score=0.90,
        structural_score=0.80,
        objective_score=0.90,
        ground_truth_verdict=CriticVerdict.PASS,
        ground_truth_score=0.87,
        ground_truth_tags=[],
        category="dialogue",
        difficulty="easy",
    ),
    CalibrationSample(
        sample_id="pass_003",
        description="情感丰富段落：悲伤语气准确传达",
        semantic_score=0.85,
        structural_score=0.82,
        objective_score=0.88,
        ground_truth_verdict=CriticVerdict.PASS,
        ground_truth_score=0.85,
        ground_truth_tags=[],
        category="emotion",
        difficulty="medium",
    ),
    CalibrationSample(
        sample_id="pass_004",
        description="旁白段落：自然流畅、节奏合适",
        semantic_score=0.87,
        structural_score=0.88,
        objective_score=0.90,
        ground_truth_verdict=CriticVerdict.PASS,
        ground_truth_score=0.88,
        ground_truth_tags=[],
        category="narration",
        difficulty="easy",
    ),
    CalibrationSample(
        sample_id="pass_005",
        description="章节开头：结构清晰、情感匹配",
        semantic_score=0.82,
        structural_score=0.90,
        objective_score=0.88,
        ground_truth_verdict=CriticVerdict.PASS,
        ground_truth_score=0.86,
        ground_truth_tags=[],
        category="structure",
        difficulty="easy",
    ),
    CalibrationSample(
        sample_id="pass_006",
        description="快节奏动作场景：语速匹配、情感到位",
        semantic_score=0.84,
        structural_score=0.78,
        objective_score=0.86,
        ground_truth_verdict=CriticVerdict.PASS,
        ground_truth_score=0.83,
        ground_truth_tags=[],
        category="action",
        difficulty="medium",
    ),
    CalibrationSample(
        sample_id="pass_007",
        description="多角色对话：声音区分清晰、语义连贯",
        semantic_score=0.86,
        structural_score=0.83,
        objective_score=0.89,
        ground_truth_verdict=CriticVerdict.PASS,
        ground_truth_score=0.86,
        ground_truth_tags=[],
        category="dialogue",
        difficulty="medium",
    ),
    # ─── WARNING 样本 (中等质量) ───
    CalibrationSample(
        sample_id="warn_001",
        description="段落边界略有偏差：结构分数较低",
        semantic_score=0.78,
        structural_score=0.62,
        objective_score=0.85,
        ground_truth_verdict=CriticVerdict.WARNING,
        ground_truth_score=0.75,
        ground_truth_tags=["paragraph_boundary_drift"],
        category="structure",
        difficulty="medium",
    ),
    CalibrationSample(
        sample_id="warn_002",
        description="情感略有偏差：语义连贯但情感不够饱满",
        semantic_score=0.65,
        structural_score=0.80,
        objective_score=0.82,
        ground_truth_verdict=CriticVerdict.WARNING,
        ground_truth_score=0.72,
        ground_truth_tags=["emotion_mismatch"],
        category="emotion",
        difficulty="medium",
    ),
    CalibrationSample(
        sample_id="warn_003",
        description="客观指标接近边界阈值",
        semantic_score=0.80,
        structural_score=0.78,
        objective_score=0.68,
        ground_truth_verdict=CriticVerdict.WARNING,
        ground_truth_score=0.75,
        ground_truth_tags=["dnsmos_below_threshold"],
        category="quality",
        difficulty="medium",
    ),
    CalibrationSample(
        sample_id="warn_004",
        description="说话人过渡突兀：结构流程存在问题",
        semantic_score=0.75,
        structural_score=0.60,
        objective_score=0.80,
        ground_truth_verdict=CriticVerdict.WARNING,
        ground_truth_score=0.70,
        ground_truth_tags=["speaker_transition_abrupt", "flow_discontinuity"],
        category="structure",
        difficulty="hard",
    ),
    CalibrationSample(
        sample_id="warn_005",
        description="成本接近上限：结构合规有警告",
        semantic_score=0.82,
        structural_score=0.55,
        objective_score=0.85,
        ground_truth_verdict=CriticVerdict.WARNING,
        ground_truth_score=0.72,
        ground_truth_tags=["cost_warning"],
        category="cost",
        difficulty="medium",
    ),
    CalibrationSample(
        sample_id="warn_006",
        description="角色声音略有漂移：客观声纹相似度下降",
        semantic_score=0.70,
        structural_score=0.78,
        objective_score=0.72,
        ground_truth_verdict=CriticVerdict.WARNING,
        ground_truth_score=0.73,
        ground_truth_tags=["speaker_fingerprint_drift"],
        category="voice",
        difficulty="hard",
    ),
    # ─── FAIL 样本 (低质量) ───
    CalibrationSample(
        sample_id="fail_001",
        description="语义断裂：上下文不连贯",
        semantic_score=0.35,
        structural_score=0.65,
        objective_score=0.70,
        ground_truth_verdict=CriticVerdict.FAIL,
        ground_truth_score=0.40,
        ground_truth_tags=["semantic_drift"],
        category="semantic",
        difficulty="easy",
    ),
    CalibrationSample(
        sample_id="fail_002",
        description="情感反向：悲伤场景用欢快语气",
        semantic_score=0.20,
        structural_score=0.70,
        objective_score=0.75,
        ground_truth_verdict=CriticVerdict.FAIL,
        ground_truth_score=0.25,
        ground_truth_tags=["emotion_reversed"],
        category="emotion",
        difficulty="easy",
    ),
    CalibrationSample(
        sample_id="fail_003",
        description="角色混淆：旁白和对话声音不分",
        semantic_score=0.30,
        structural_score=0.55,
        objective_score=0.65,
        ground_truth_verdict=CriticVerdict.FAIL,
        ground_truth_score=0.35,
        ground_truth_tags=["speaker_confusion"],
        category="voice",
        difficulty="easy",
    ),
    CalibrationSample(
        sample_id="fail_004",
        description="客观指标全面低下：DNSMOS极低、WER极高",
        semantic_score=0.45,
        structural_score=0.50,
        objective_score=0.25,
        ground_truth_verdict=CriticVerdict.FAIL,
        ground_truth_score=0.30,
        ground_truth_tags=[
            "dnsmos_below_threshold",
            "wer_above_threshold",
            "critical_failure",
        ],
        category="quality",
        difficulty="easy",
    ),
    CalibrationSample(
        sample_id="fail_005",
        description="章节边界完全错位 + 成本严重超支",
        semantic_score=0.50,
        structural_score=0.20,
        objective_score=0.60,
        ground_truth_verdict=CriticVerdict.FAIL,
        ground_truth_score=0.35,
        ground_truth_tags=["chapter_boundary_mismatch", "cost_overrun"],
        category="structure",
        difficulty="hard",
    ),
    CalibrationSample(
        sample_id="fail_006",
        description="三维度全面不合格",
        semantic_score=0.25,
        structural_score=0.30,
        objective_score=0.35,
        ground_truth_verdict=CriticVerdict.FAIL,
        ground_truth_score=0.25,
        ground_truth_tags=["semantic_drift", "flow_discontinuity", "critical_failure"],
        category="general",
        difficulty="easy",
    ),
    # ─── 边界案例 ───
    CalibrationSample(
        sample_id="edge_001",
        description="刚好及格线：各维度均在阈值边缘",
        semantic_score=0.70,
        structural_score=0.70,
        objective_score=0.70,
        ground_truth_verdict=CriticVerdict.PASS,
        ground_truth_score=0.70,
        ground_truth_tags=[],
        category="boundary",
        difficulty="hard",
    ),
]


# ═══════════════════════════════════════════════════════════════════════════
# F1 评估器
# ═══════════════════════════════════════════════════════════════════════════


@dataclass
class CalibrationResult:
    """校准结果报告."""

    f1_macro: float
    f1_per_class: Dict[str, float]
    precision_macro: float
    recall_macro: float
    accuracy: float
    total_samples: int
    threshold_pass: float
    threshold_warning: float
    weights: Dict[str, float]
    predictions: List[Dict[str, Any]] = field(default_factory=list)
    confusion_matrix: Dict[str, Dict[str, int]] = field(default_factory=dict)
    passed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "f1_macro": self.f1_macro,
            "f1_per_class": self.f1_per_class,
            "precision_macro": self.precision_macro,
            "recall_macro": self.recall_macro,
            "accuracy": self.accuracy,
            "total_samples": self.total_samples,
            "predictions": self.predictions,
            "confusion_matrix": self.confusion_matrix,
            "threshold_pass": self.threshold_pass,
            "threshold_warning": self.threshold_warning,
            "weights": self.weights,
            "passed": self.passed,
        }


def _compute_confusion_matrix(y_true: List[str], y_pred: List[str], labels: List[str]) -> Dict[str, Dict[str, int]]:
    """计算混淆矩阵."""
    matrix = {lt: {lp: 0 for lp in labels} for lt in labels}
    for true, pred in zip(y_true, y_pred):
        matrix[true][pred] += 1
    return matrix


def _compute_f1_per_class(confusion_matrix: Dict[str, Dict[str, int]], labels: List[str]) -> Dict[str, float]:
    """计算每类 F1 分数."""
    f1_scores = {}
    for label in labels:
        tp = confusion_matrix[label][label]
        fp = sum(confusion_matrix[o][label] for o in labels if o != label)
        fn = sum(confusion_matrix[label][o] for o in labels if o != label)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        f1_scores[label] = round(f1, 4)

    return f1_scores


# ═══════════════════════════════════════════════════════════════════════════
# SyntheticCritic — 三元批评网络主类
# ═══════════════════════════════════════════════════════════════════════════


class SyntheticCritic:
    """异构三元批评网络.

    防止"模型自嗨"的核心架构：
    1. 三个异构批评器独立评估（语义派/结构派/客观派）
    2. 加权投票融合结果（默认客观派权重最高，因为硬指标最可靠）
    3. 校准机制：通过校准数据集验证 F1 分数 >= 0.7
    4. 自适应权重：根据各批评器在校准集上的表现动态调整权重

    使用方式:
        critic = create_synthetic_critic()
        ensemble = critic.evaluate(audio_path, annotation, routing, text)
        result = critic.calibrate()
        assert result.passed  # F1 >= 0.7
    """

    def __init__(
        self,
        semantic_critic: Optional[Any] = None,
        structural_critic: Optional[Any] = None,
        objective_critic: Optional[Any] = None,
        weights: Optional[Dict[CriticType, float]] = None,
        strategy: str = "weighted_vote",
        pass_threshold: float = 0.7,
        warning_threshold: float = 0.5,
        calibration_samples: Optional[List[CalibrationSample]] = None,
        mock_mode: bool = False,
    ):
        self.pass_threshold = pass_threshold
        self.warning_threshold = warning_threshold
        self.strategy = strategy
        self.mock_mode = mock_mode

        self.semantic_critic = semantic_critic
        self.structural_critic = structural_critic
        self.objective_critic = objective_critic

        # 默认权重：客观派 > 语义派 > 结构派
        self.weights = weights or {
            CriticType.SEMANTIC: 0.30,
            CriticType.STRUCTURAL: 0.20,
            CriticType.OBJECTIVE: 0.50,
        }

        self.calibration_samples = calibration_samples or DEFAULT_CALIBRATION_SAMPLES

        self._ensemble = CriticEnsembleEvaluator(
            semantic_critic=self.semantic_critic,
            structural_critic=self.structural_critic,
            objective_critic=self.objective_critic,
            weights=self.weights,
            strategy=self.strategy,
        )

    def evaluate(
        self,
        audio_path: Path,
        annotation: Any,
        routing_decision: Any,
        reference_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticEnsemble:
        """运行三元批评并融合结果."""
        if self.mock_mode:
            return self.run_mock_evaluation(
                audio_path,
                annotation,
                routing_decision,
                reference_text,
                context,
            )
        return self._ensemble.evaluate(audio_path, annotation, routing_decision, reference_text, context)

    # ─── 校准与 F1 评估 ────────────────────────────────────────────────

    def calibrate(
        self,
        samples: Optional[List[CalibrationSample]] = None,
    ) -> CalibrationResult:
        """在校准数据集上评估批评网络的 F1 分数.

        流程:
        1. 对每个校准样本，用三派分数模拟批评器输出
        2. 通过加权投票得到预测裁决
        3. 与人工标注真值比较，计算 F1
        """
        samples = samples or self.calibration_samples
        labels = ["pass", "warning", "fail"]

        y_true = []
        y_pred = []

        for sample in samples:
            semantic_result = CriticResult(
                critic_type=CriticType.SEMANTIC,
                verdict=self._score_to_verdict(sample.semantic_score),
                score=sample.semantic_score,
                confidence=0.8,
                reasoning=(f"[Calibration] semantic score = " f"{sample.semantic_score}"),
                evidence={"score": sample.semantic_score},
            )
            structural_result = CriticResult(
                critic_type=CriticType.STRUCTURAL,
                verdict=self._score_to_verdict(sample.structural_score),
                score=sample.structural_score,
                confidence=0.75,
                reasoning=(f"[Calibration] structural score = " f"{sample.structural_score}"),
                evidence={"score": sample.structural_score},
            )
            objective_result = CriticResult(
                critic_type=CriticType.OBJECTIVE,
                verdict=self._score_to_verdict(sample.objective_score),
                score=sample.objective_score,
                confidence=0.9,
                reasoning=(f"[Calibration] objective score = " f"{sample.objective_score}"),
                evidence={"score": sample.objective_score},
            )

            results = [semantic_result, structural_result, objective_result]
            ensemble = self._ensemble._fuse_results(results)
            predicted_verdict = ensemble.final_verdict

            y_true.append(sample.ground_truth_verdict.value)
            y_pred.append(predicted_verdict.value)

        # 计算混淆矩阵
        confusion = _compute_confusion_matrix(y_true, y_pred, labels)

        # 计算每类 F1
        f1_per_class = _compute_f1_per_class(confusion, labels)

        # Macro-F1
        f1_macro = round(sum(f1_per_class.values()) / len(f1_per_class), 4)

        # Macro precision / recall
        precision_scores = []
        recall_scores = []
        for label in labels:
            tp = confusion[label][label]
            fp = sum(confusion[o][label] for o in labels if o != label)
            fn = sum(confusion[label][o] for o in labels if o != label)
            p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
            r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
            precision_scores.append(p)
            recall_scores.append(r)

        precision_macro = round(sum(precision_scores) / len(precision_scores), 4)
        recall_macro = round(sum(recall_scores) / len(recall_scores), 4)

        # Accuracy
        correct = sum(1 for t, p in zip(y_true, y_pred) if t == p)
        accuracy = round(correct / len(y_true), 4) if y_true else 0.0

        # 构建预测详情
        predictions = []
        for sample, pred in zip(samples, y_pred):
            predictions.append(
                {
                    "sample_id": sample.sample_id,
                    "true_verdict": sample.ground_truth_verdict.value,
                    "pred_verdict": pred,
                    "true_score": sample.ground_truth_score,
                    "category": sample.category,
                    "difficulty": sample.difficulty,
                    "correct": sample.ground_truth_verdict.value == pred,
                }
            )

        result = CalibrationResult(
            f1_macro=f1_macro,
            f1_per_class=f1_per_class,
            precision_macro=precision_macro,
            recall_macro=recall_macro,
            accuracy=accuracy,
            total_samples=len(samples),
            predictions=predictions,
            confusion_matrix=confusion,
            threshold_pass=self.pass_threshold,
            threshold_warning=self.warning_threshold,
            weights={k.value: v for k, v in self.weights.items()},
            passed=f1_macro >= 0.7,
        )

        logger.info(
            f"Calibration result: F1_macro={f1_macro:.4f}, "
            f"precision={precision_macro:.4f}, "
            f"recall={recall_macro:.4f}, "
            f"accuracy={accuracy:.4f}, passed={result.passed}"
        )

        return result

    def calibrate_with_adaptive_weights(
        self,
        samples: Optional[List[CalibrationSample]] = None,
        n_iterations: int = 20,
    ) -> CalibrationResult:
        """自适应权重校准.

        通过网格搜索在三派权重空间中找到最优权重组合，
        使校准集上的 F1 分数最大化。
        """
        samples = samples or self.calibration_samples
        best_result = None
        best_f1 = 0.0
        best_weights = self.weights.copy()

        for s_w in np.linspace(0.1, 0.5, n_iterations):
            for st_w in np.linspace(0.1, 0.4, max(n_iterations // 2, 5)):
                o_w = 1.0 - s_w - st_w
                if o_w < 0.2 or o_w > 0.7:
                    continue

                trial_weights = {
                    CriticType.SEMANTIC: round(s_w, 3),
                    CriticType.STRUCTURAL: round(st_w, 3),
                    CriticType.OBJECTIVE: round(o_w, 3),
                }

                old_weights = self._ensemble.weights
                self._ensemble.weights = trial_weights
                self.weights = trial_weights

                result = self.calibrate(samples)

                if result.f1_macro > best_f1:
                    best_f1 = result.f1_macro
                    best_result = result
                    best_weights = trial_weights.copy()

                self._ensemble.weights = old_weights
                self.weights = old_weights

        if best_weights:
            self.weights = best_weights
            self._ensemble.weights = best_weights

        if best_result:
            logger.info(f"Adaptive calibration: best F1={best_f1:.4f}, " f"weights={best_weights}")
            return best_result

        return self.calibrate(samples)

    def _score_to_verdict(self, score: float) -> CriticVerdict:
        """将分数映射为裁决."""
        if score >= self.pass_threshold:
            return CriticVerdict.PASS
        elif score >= self.warning_threshold:
            return CriticVerdict.WARNING
        else:
            return CriticVerdict.FAIL

    def run_mock_evaluation(
        self,
        audio_path: Path = Path("mock.wav"),
        annotation: Any = None,
        routing_decision: Any = None,
        reference_text: str = "测试文本",
        context: Optional[Dict[str, Any]] = None,
    ) -> CriticEnsemble:
        """Mock 模式全流程评估（用于测试和演示）."""
        mock_results = [
            CriticResult(
                critic_type=CriticType.SEMANTIC,
                verdict=CriticVerdict.PASS,
                score=0.85,
                confidence=0.88,
                reasoning=("[Mock] 语义连贯性良好，情感表达与标注一致"),
                evidence={
                    "semantic_coherence": 0.88,
                    "emotion_consistency": 0.90,
                    "speaker_fingerprint": 0.82,
                },
                tags=[],
            ),
            CriticResult(
                critic_type=CriticType.STRUCTURAL,
                verdict=CriticVerdict.WARNING,
                score=0.65,
                confidence=0.70,
                reasoning=("[Mock] 段落边界略有偏差，流程略有停顿"),
                evidence={
                    "document_structure": 0.80,
                    "paragraph_flow": 0.60,
                    "cost_compliance": 0.85,
                    "format_compliance": 0.90,
                },
                tags=["paragraph_boundary_drift"],
            ),
            CriticResult(
                critic_type=CriticType.OBJECTIVE,
                verdict=CriticVerdict.PASS,
                score=0.90,
                confidence=0.95,
                reasoning="[Mock] DNSMOS=3.8, WER=0.02, SpeakerSim=0.92",
                evidence={
                    "dnsmos": 3.8,
                    "wer": 0.02,
                    "speaker_similarity": 0.92,
                },
                tags=[],
            ),
        ]

        return self._ensemble._fuse_results(mock_results)

    def get_weights(self) -> Dict[str, float]:
        """获取当前三派权重."""
        return {k.value: v for k, v in self.weights.items()}

    def set_weights(self, weights: Dict[CriticType, float]) -> None:
        """设置三派权重."""
        total = sum(weights.values())
        if abs(total - 1.0) > 0.01:
            logger.warning(f"Weights sum to {total:.2f}, normalizing to 1.0")
            weights = {k: v / total for k, v in weights.items()}
        self.weights = weights
        self._ensemble.weights = weights


# ═══════════════════════════════════════════════════════════════════════════
# 工厂函数
# ═══════════════════════════════════════════════════════════════════════════


def create_synthetic_critic(
    weights: Optional[Dict[CriticType, float]] = None,
    pass_threshold: float = 0.7,
    warning_threshold: float = 0.5,
    router: Any = None,
    config: Optional[Dict[str, Any]] = None,
    mock_mode: bool = False,
) -> SyntheticCritic:
    """创建 SyntheticCritic 实例.

    Args:
        weights: 自定义三派权重
        pass_threshold: PASS 阈值
        warning_threshold: WARNING 阈值
        router: LLM Router 实例
        config: 额外配置

    Returns:
        初始化好的 SyntheticCritic 实例
    """
    config = config or {}
    semantic_critic = None
    structural_critic = None
    objective_critic = None

    try:
        from .objective_critic import ObjectiveCritic
        from .semantic_critic import SemanticCritic
        from .structural_critic import StructuralCritic

        semantic_critic = SemanticCritic(
            router=router,
            config=config.get("semantic", {}),
        )
        structural_critic = StructuralCritic(
            router=router,
            config=config.get("structural", {}),
        )
        objective_critic = ObjectiveCritic(
            router=router,
            config=config.get("objective", {}),
        )
    except Exception as e:
        logger.warning(f"Failed to init critics: {e}")

    return SyntheticCritic(
        semantic_critic=semantic_critic,
        structural_critic=structural_critic,
        objective_critic=objective_critic,
        weights=weights,
        pass_threshold=pass_threshold,
        warning_threshold=warning_threshold,
        mock_mode=mock_mode,
    )


__all__ = [
    "SyntheticCritic",
    "CalibrationSample",
    "CalibrationResult",
    "DEFAULT_CALIBRATION_SAMPLES",
    "create_synthetic_critic",
]

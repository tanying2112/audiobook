#!/usr/bin/env python3
"""
Audiobook Studio — Promotion Gate
=================================

4 项硬指标检验：
1. 格式合规率 ≥ 99%
2. 金数据集通过率 ≥ 95%
3. 质量分 ≥ 旧版 × 102%
4. 人工抽样偏好 ≥ 80%

任意一项不达标 → 拒绝升级
"""

import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class PromotionMetrics:
    """升级所需的指标"""
    format_compliance_rate: float  # 格式合规率 (0-1)
    golden_dataset_pass_rate: float  # 金数据集通过率 (0-1)
    quality_score_ratio: float  # 质量分相对于旧版的比例 (例如 1.02 表示比旧版高 2%)
    human_preference_score: float  # 人工抽样偏好 (0-1)
    timestamp: datetime


@dataclass
class PromotionGateResult:
    """Promotion Gate 结果"""
    passed: bool
    failed_criteria: list
    metrics: PromotionMetrics
    timestamp: datetime


class PromotionGate:
    """Promotion Gate，执行 4 项硬指标检验."""

    def __init__(
        self,
        format_compliance_threshold: float = 0.99,
        golden_dataset_threshold: float = 0.95,
        quality_score_threshold: float = 1.02,
        human_preference_threshold: float = 0.80
    ):
        """
        初始化 Promotion Gate.

        Args:
            format_compliance_threshold: 格式合规率阈值 (默认 99%)
            golden_dataset_threshold: 金数据集通过率阈值 (默认 95%)
            quality_score_threshold: 质量分阈值（相对于旧版，默认 102%）
            human_preference_threshold: 人工抽样偏好阈值 (默认 80%)
        """
        self.format_compliance_threshold = format_compliance_threshold
        self.golden_dataset_threshold = golden_dataset_threshold
        self.quality_score_threshold = quality_score_threshold
        self.human_preference_threshold = human_preference_threshold

        logger.info(
            f"PromotionGate initialized with thresholds: "
            f"format_compliance>={self.format_compliance_threshold:.0%}, "
            f"golden_dataset>={self.golden_dataset_threshold:.0%}, "
            f"quality_score>={self.quality_score_threshold:.0%}x, "
            f"human_preference>={self.human_preference_threshold:.0%}"
        )

    def evaluate(
        self,
        format_compliance_rate: float,
        golden_dataset_pass_rate: float,
        quality_score_ratio: float,
        human_preference_score: float,
        timestamp: Optional[datetime] = None
    ) -> PromotionGateResult:
        """
        执行 Promotion Gate 评估.

        Args:
            format_compliance_rate: 格式合规率 (0-1)
            golden_dataset_pass_rate: 金数据集通过率 (0-1)
            quality_score_ratio: 质量分比例（相对于旧版）
            human_preference_score: 人工抽样偏好 (0-1)
            timestamp: 评估时间戳

        Returns:
            PromotionGateResult 评估结果
        """
        if timestamp is None:
            timestamp = datetime.now()

        failed_criteria = []

        # 检查 1: 格式合规率 ≥ 99%
        if format_compliance_rate < self.format_compliance_threshold:
            failed_criteria.append(
                f"格式合规率 {format_compliance_rate:.2%} < 阈值 {self.format_compliance_threshold:.0%}"
            )

        # 检查 2: 金数据集通过率 ≥ 95%
        if golden_dataset_pass_rate < self.golden_dataset_threshold:
            failed_criteria.append(
                f"金数据集通过率 {golden_dataset_pass_rate:.2%} < 阈值 {self.golden_dataset_threshold:.0%}"
            )

        # 检查 3: 质量分 ≥ 旧版 × 102%
        if quality_score_ratio < self.quality_score_threshold:
            failed_criteria.append(
                f"质量分比例 {quality_score_ratio:.2f} < 阈值 {self.quality_score_threshold:.2f}"
            )

        # 检查 4: 人工抽样偏好 ≥ 80%
        if human_preference_score < self.human_preference_threshold:
            failed_criteria.append(
                f"人工抽样偏好 {human_preference_score:.2%} < 阈值 {self.human_preference_threshold:.0%}"
            )

        passed = len(failed_criteria) == 0

        metrics = PromotionMetrics(
            format_compliance_rate=format_compliance_rate,
            golden_dataset_pass_rate=golden_dataset_pass_rate,
            quality_score_ratio=quality_score_ratio,
            human_preference_score=human_preference_score,
            timestamp=timestamp
        )

        result = PromotionGateResult(
            passed=passed,
            failed_criteria=failed_criteria,
            metrics=metrics,
            timestamp=timestamp
        )

        if passed:
            logger.info("✅ Promotion Gate PASSED - all criteria met")
        else:
            logger.warning(
                f"❌ Promotion Gate FAILED - {len(failed_criteria)} criteria failed: "
                f"{', '.join(failed_criteria)}"
            )

        return result

    def evaluate_from_dict(self, metrics_dict: Dict[str, Any]) -> PromotionGateResult:
        """
        从字典评估 Promotion Gate.

        Args:
            metrics_dict: 包含指标的字典，键应为：
                - format_compliance_rate
                - golden_dataset_pass_rate
                - quality_score_ratio
                - human_preference_score
                - timestamp (可选)

        Returns:
            PromotionGateResult 评估结果
        """
        return self.evaluate(
            format_compliance_rate=metrics_dict.get("format_compliance_rate", 0.0),
            golden_dataset_pass_rate=metrics_dict.get("golden_dataset_pass_rate", 0.0),
            quality_score_ratio=metrics_dict.get("quality_score_ratio", 0.0),
            human_preference_score=metrics_dict.get("human_preference_score", 0.0),
            timestamp=metrics_dict.get("timestamp")
        )

    def get_status(self) -> Dict[str, Any]:
        """获取门禁状态."""
        return {
            "thresholds": {
                "format_compliance": self.format_compliance_threshold,
                "golden_dataset": self.golden_dataset_threshold,
                "quality_score": self.quality_score_threshold,
                "human_preference": self.human_preference_threshold
            },
            "description": "Promotion Gate with 4 hard criteria for version promotion"
        }


def main():
    """主函数 - 演示 Promotion Gate."""
    print("=== Audiobook Studio Promotion Gate Demo ===\n")

    # 创建 Promotion Gate 实例
    gate = PromotionGate()

    print("Promotion Gate Criteria:")
    status = gate.get_status()
    for criterion, threshold in status["thresholds"].items():
        print(f"  {criterion}: ≥ {threshold:.0%}" if "ratio" not in criterion else f"  {criterion}: ≥ {threshold:.2f}x")
    print()

    # 测试案例1: 所有指标达标
    print("Test Case 1: All metrics PASS")
    result1 = gate.evaluate(
        format_compliance_rate=0.995,  # 99.5% ≥ 99%
        golden_dataset_pass_rate=0.96,  # 96% ≥ 95%
        quality_score_ratio=1.03,      # 1.03 ≥ 1.02
        human_preference_score=0.85    # 85% ≥ 80%
    )
    print(f"Result: {'PASS' if result1.passed else 'FAIL'}")
    if not result1.passed:
        print(f"Failed criteria: {result1.failed_criteria}")
    print()

    # 测试案例2: 格式合规率不达标
    print("Test Case 2: Format compliance FAIL")
    result2 = gate.evaluate(
        format_compliance_rate=0.98,   # 98% < 99%
        golden_dataset_pass_rate=0.96,  # 96% ≥ 95%
        quality_score_ratio=1.03,      # 1.03 ≥ 1.02
        human_preference_score=0.85    # 85% ≥ 80%
    )
    print(f"Result: {'PASS' if result2.passed else 'FAIL'}")
    if not result2.passed:
        print(f"Failed criteria: {result2.failed_criteria}")
    print()

    # 测试案例3: 多项不达标
    print("Test Case 3: Multiple criteria FAIL")
    result3 = gate.evaluate(
        format_compliance_rate=0.98,   # 98% < 99%
        golden_dataset_pass_rate=0.90,  # 90% < 95%
        quality_score_ratio=1.01,      # 1.01 < 1.02
        human_preference_score=0.75    # 75% < 80%
    )
    print(f"Result: {'PASS' if result3.passed else 'FAIL'}")
    if not result3.passed:
        print(f"Failed criteria: {result3.failed_criteria}")
    print()

    # 使用字典接口
    print("Test Case 4: Using dictionary interface")
    metrics_dict = {
        "format_compliance_rate": 0.992,
        "golden_dataset_pass_rate": 0.97,
        "quality_score_ratio": 1.025,
        "human_preference_score": 0.82
    }
    result4 = gate.evaluate_from_dict(metrics_dict)
    print(f"Result: {'PASS' if result4.passed else 'FAIL'}")
    if not result4.passed:
        print(f"Failed criteria: {result4.failed_criteria}")

    print("\n=== Demo Complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
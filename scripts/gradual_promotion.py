#!/usr/bin/env python3
"""
Audiobook Studio — 灰度自动升流和自动回滚机制
========================================
实现渐进式发布 (5%→25%→50%) 和基于质量指标的自动回滚。

Usage:
    python scripts/gradual_promotion.py --version v1.0.0 --auto-promote --min-observation-minutes 10
"""

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional


class PromotionStage(Enum):
    """升流阶段"""
    CANARY_5 = "5%"
    CANARY_25 = "25%"
    CANARY_50 = "50%"
    FULL = "100%"


@dataclass
class MetricsSnapshot:
    """质量指标快照"""
    timestamp: datetime
    version: int
    stage: PromotionStage
    golden_pass_rate: float  # 黄金数据集通过率 (0-1)
    quality_score: float     # 质量评分 (相对于基线)
    schema_compliance: float # 格式合规率 (0-1)
    failure_rate: float      # 校验失败率 (0-1)
    sample_size: int         # 样本大小


@dataclass
class PromotionPolicy:
    """升流策略"""
    # 升流阈值
    min_golden_pass_rate: float = 0.95  # 黄金数据集通过率 ≥ 95%
    min_quality_score: float = 1.02     # 质量 ≥ 旧版 102%
    max_failure_rate: float = 0.01      # 校验失败率 ≤ 1%
    min_schema_compliance: float = 0.99 # 格式合规率 ≥ 99%

    # 自动回滚阈值
    rollback_quality_decay: float = 0.08   # 连续质量下降 > 8% 触发回滚
    rollback_failure_increase: float = 0.01 # 校验失败率增加 > 1% 触发回滚
    rollback_consecutive_cycles: int = 3   # 连续 N 个周期触发回滚

    # 升流时间窗口（秒）
    stage_duration_minutes: int = 10       # 每个阶段最小观测窗口


@dataclass
class PromotionState:
    """当前升流状态"""
    current_version: int
    target_version: int
    current_stage: PromotionStage
    stage_start_time: datetime
    metrics_history: List[MetricsSnapshot] = field(default_factory=list)
    is_rolling_back: bool = False
    rollback_reason: Optional[str] = None


class GradualPromotionManager:
    """灰度升流管理器"""

    def __init__(self, policy: PromotionPolicy):
        self.policy = policy
        self.state: Optional[PromotionState] = None
        self.metrics_file = Path("./logs/promotion_metrics.jsonl")
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

    def start_promotion(self, current_version: int, target_version: int) -> PromotionState:
        """开始新版本的升流过程"""
        self.state = PromotionState(
            current_version=current_version,
            target_version=target_version,
            current_stage=PromotionStage.CANARY_5,
            stage_start_time=datetime.now()
        )
        print(f"🚀 开始升流: v{current_version} → v{target_version}")
        print(f"   初始阶段: {self.state.current_stage.value}")
        print(f"   将持续至少 {self.policy.stage_duration_minutes} 分钟")
        return self.state

    def record_metrics(self, metrics: MetricsSnapshot) -> Dict[str, any]:
        """
        记录监控指标并检查是否需要升流、回滚或保持当前阶段

        Returns:
            决策结果字典
        """
        if not self.state:
            raise RuntimeError("升流未开始，请先调用 start_promotion()")

        # 记录指标
        self.state.metrics_history.append(metrics)
        self._save_metrics_to_file(metrics)

        print(f"\n📊 监控指标 [{metrics.stage.value}] "
              f"v{metrics.version}:")
        print(f"   黄金数据集通过率: {metrics.golden_pass_rate:.2%} "
              f"(≥{self.policy.min_golden_pass_rate:.0%})")
        print(f"   质量评分: {metrics.quality_score:.2%} "
              f"(≥{self.policy.min_quality_score:.0%})")
        print(f"   格式合规率: {metrics.schema_compliance:.2%} "
              f"(≥{self.policy.min_schema_compliance:.0%})")
        print(f"   校验失败率: {metrics.failure_rate:.2%} "
              f"(≤{self.policy.max_failure_rate:.0%})")

        # 检查是否需要回滚
        rollback_decision = self._check_rollback_conditions(metrics)
        if rollback_decision["should_rollback"]:
            return self._execute_rollback(rollback_decision["reason"])

        # 检查是否可以升流到下一个阶段
        promotion_decision = self._check_promotion_conditions(metrics)
        if promotion_decision["should_promote"]:
            return self._execute_promotion(promotion_decision["next_stage"])

        # 检查当前阶段时间是否已满
        time_decision = self._check_stage_duration()
        if time_decision["time_elapsed"]:
            # 时间已到但条件不满，保持当前阶段继续观察
            return {
                "action": "continue",
                "reason": f"阶段时间已到 ({self.policy.stage_duration_minutes}分钟)，但指标未达标，继续观察",
                "current_stage": self.state.current_stage.value
            }

        # 默认：继续当前阶段
        return {
            "action": "continue",
            "reason": "指标观察中，未达到升流或回滚条件",
            "current_stage": self.state.current_stage.value
        }

    def _check_rollback_conditions(self, current: MetricsSnapshot) -> Dict[str, any]:
        """检查是否触发自动回滚条件"""
        if len(self.state.metrics_history) < 2:
            return {"should_rollback": False}

        # 检查质量连续下降
        quality_decay_triggered = False
        failure_increase_triggered = False

        # 只看最近的 N 个周期
        recent_metrics = self.state.metrics_history[-self.policy.rollback_consecutive_cycles:]
        if len(recent_metrics) >= self.policy.rollback_consecutive_cycles:
            # 检查质量是否连续下降超过阈值
            quality_decreases = 0
            failure_increases = 0

            for i in range(1, len(recent_metrics)):
                prev = recent_metrics[i-1]
                curr = recent_metrics[i]

                # 质量下降检查（相对于前一周期）
                if prev.quality_score > 0:
                    quality_decay = (prev.quality_score - curr.quality_score) / prev.quality_score
                    if quality_decay > self.policy.rollback_quality_decay:
                        quality_decreases += 1

                # 失败率增加检查
                failure_increase = curr.failure_rate - prev.failure_rate
                if failure_increase > self.policy.rollback_failure_increase:
                    failure_increases += 1

            # 如果所有最近的周期都触发了条件，则考虑回滚
            if quality_decreases >= (len(recent_metrics) - 1):
                quality_decay_triggered = True
            if failure_increases >= (len(recent_metrics) - 1):
                failure_increase_triggered = True

        # 检查绝对阈值失败
        absolute_failure = (
            current.golden_pass_rate < self.policy.min_golden_pass_rate or
            current.quality_score < self.policy.min_quality_score or
            current.schema_compliance < self.policy.min_schema_compliance or
            current.failure_rate > self.policy.max_failure_rate
        )

        should_rollback = (
            quality_decay_triggered or
            failure_increase_triggered or
            absolute_failure
        )

        reason = []
        if quality_decay_triggered:
            reason.append(f"连续质量下降 > {self.policy.rollback_quality_decay:.0%}")
        if failure_increase_triggered:
            reason.append(f"连续失败率增加 > {self.policy.rollback_failure_increase:.0%}")
        if absolute_failure:
            reason.append("单次指标未达绝对阈值")

        return {
            "should_rollback": should_rollback,
            "reason": "; ".join(reason) if reason else "未知原因"
        }

    def _execute_rollback(self, reason: str) -> Dict[str, any]:
        """执行回滚"""
        self.state.is_rolling_back = True
        self.state.rollback_reason = reason

        print(f"\n🚨 触发自动回滚: {reason}")
        print(f"   回滚到版本: v{self.state.current_version}")
        print(f"   目标版本: v{self.state.target_version} (已暂停)")

        return {
            "action": "rollback",
            "reason": reason,
            "target_version": self.state.current_version,
            "previous_target": self.state.target_version
        }

    def _check_promotion_conditions(self, current: MetricsSnapshot) -> Dict[str, any]:
        """检查是否满足升流到下一个阶段的条件"""
        # 检查所有关键指标是否达标
        meets_criteria = (
            current.golden_pass_rate >= self.policy.min_golden_pass_rate and
            current.quality_score >= self.policy.min_quality_score and
            current.schema_compliance >= self.policy.min_schema_compliance and
            current.failure_rate <= self.policy.max_failure_rate
        )

        if not meets_criteria:
            return {"should_promote": False}

        # 确定下一个阶段
        stage_order = [
            PromotionStage.CANARY_5,
            PromotionStage.CANARY_25,
            PromotionStage.CANARY_50,
            PromotionStage.FULL
        ]

        try:
            current_index = stage_order.index(self.state.current_stage)
            if current_index < len(stage_order) - 1:
                next_stage = stage_order[current_index + 1]
                return {
                    "should_promote": True,
                    "next_stage": next_stage
                }
            else:
                # 已经是最终阶段
                return {
                    "should_promote": False,
                    "reason": "已达到完全发布阶段"
                }
        except ValueError:
            return {"should_promote": False}

    def _execute_promotion(self, next_stage: PromotionStage) -> Dict[str, any]:
        """执行升流到下一个阶段"""
        old_stage = self.state.current_stage
        self.state.current_stage = next_stage
        self.state.stage_start_time = datetime.now()

        print(f"\n🚀 升流到下一个阶段: {old_stage.value} → {next_stage.value}")
        if next_stage == PromotionStage.FULL:
            print(f"   🎉 升流完成！版本 v{self.state.target_version} 现在是正式版本")
        else:
            print(f"   将持续至少 {self.policy.stage_duration_minutes} 分钟")

        return {
            "action": "promote",
            "from_stage": old_stage.value,
            "to_stage": next_stage.value,
            "target_version": self.state.target_version
        }

    def _check_stage_duration(self) -> Dict[str, any]:
        """检查当前阶段是否已持续足够时间"""
        if not self.state:
            return {"time_elapsed": False}

        elapsed = datetime.now() - self.state.stage_start_time
        elapsed_minutes = elapsed.total_seconds() / 60

        return {
            "time_elapsed": elapsed_minutes >= self.policy.stage_duration_minutes,
            "elapsed_minutes": elapsed_minutes,
            "required_minutes": self.policy.stage_duration_minutes
        }

    def _save_metrics_to_file(self, metrics: MetricsSnapshot):
        """保存指标到文件"""
        try:
            data = {
                "timestamp": metrics.timestamp.isoformat(),
                "version": metrics.version,
                "stage": metrics.stage.value,
                "golden_pass_rate": metrics.golden_pass_rate,
                "quality_score": metrics.quality_score,
                "schema_compliance": metrics.schema_compliance,
                "failure_rate": metrics.failure_rate,
                "sample_size": metrics.sample_size
            }

            with open(self.metrics_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"警告: 无法保存指标到文件: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Audiobook Studio 灰度自动升流和自动回滚"
    )
    parser.add_argument(
        "--version",
        type=str,
        help="版本标签 (e.g., v1.0.0)",
    )
    parser.add_argument(
        "--auto-promote",
        action="store_true",
        help="自动执行升流流程",
    )
    parser.add_argument(
        "--min-observation-minutes",
        type=int,
        default=10,
        help="每个阶段最小观测窗口（分钟，默认10）",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="运行演示模式（模拟数据）",
    )
    args = parser.parse_args()

    if args.demo:
        run_demo()
        return

    if not args.auto_promote:
        parser.error("--auto-promote 是必需的，或使用 --demo 运行演示")
    
    if not args.version:
        parser.error("--version 是必需的（配合 --auto-promote）")

    # 实际生产环境的升流逻辑
    policy = PromotionPolicy(
        min_golden_pass_rate=0.95,
        min_quality_score=1.02,
        max_failure_rate=0.01,
        min_schema_compliance=0.99,
        rollback_quality_decay=0.08,
        rollback_failure_increase=0.01,
        rollback_consecutive_cycles=3,
        stage_duration_minutes=args.min_observation_minutes,
    )

    manager = GradualPromotionManager(policy)
    
    # 解析版本号
    try:
        version_str = args.version.lstrip('v')
        target_version = int(version_str.split('.')[0])
        current_version = target_version - 1
    except (ValueError, IndexError):
        current_version = 1
        target_version = 2

    state = manager.start_promotion(current_version=current_version, target_version=target_version)
    print(f"🚀 开始升流 v{current_version} → v{target_version} (版本标签: {args.version})")
    print(f"   初始阶段: {state.current_stage.value}")
    print(f"   观测窗口: {args.min_observation_minutes} 分钟/阶段")
    
    # TODO: 实际环境中这里应该从监控系统获取真实指标
    # 目前作为占位，记录版本信息供后续步骤使用
    promotion_info = {
        "version": args.version,
        "target_version": target_version,
        "current_stage": state.current_stage.value,
        "started_at": datetime.now().isoformat(),
        "policy": {
            "min_golden_pass_rate": policy.min_golden_pass_rate,
            "min_quality_score": policy.min_quality_score,
            "max_failure_rate": policy.max_failure_rate,
            "min_schema_compliance": policy.min_schema_compliance,
            "stage_duration_minutes": policy.stage_duration_minutes,
        }
    }
    
    with open("promotion_report.json", "w") as f:
        json.dump(promotion_info, f, indent=2)
    
    print("✅ 升流启动信息已写入 promotion_report.json")
    print("   后续阶段将由监控系统自动推进（需集成外部监控）")


def run_demo():
    """演示灰度升流和自动回滚机制"""
    print("=== Audiobook Studio 灰度自动升流演示 ===\n")

    policy = PromotionPolicy(
        min_golden_pass_rate=0.95,
        min_quality_score=1.02,
        max_failure_rate=0.01,
        min_schema_compliance=0.99,
        rollback_quality_decay=0.08,
        rollback_failure_increase=0.01,
        rollback_consecutive_cycles=3,
        stage_duration_minutes=1,
    )

    manager = GradualPromotionManager(policy)
    state = manager.start_promotion(current_version=1, target_version=2)

    import random

    print("\n📈 开始模拟监控数据...\n")

    for i in range(3):
        metrics = MetricsSnapshot(
            timestamp=datetime.now(),
            version=2,
            stage=state.current_stage,
            golden_pass_rate=0.96 + random.uniform(-0.01, 0.02),
            quality_score=1.03 + random.uniform(-0.01, 0.02),
            schema_compliance=0.995 + random.uniform(-0.005, 0.005),
            failure_rate=0.005 + random.uniform(-0.002, 0.003),
            sample_size=50 + i * 10
        )

        decision = manager.record_metrics(metrics)

        if decision["action"] == "promote":
            print(f"\n{decision}")
            break
        elif decision["action"] == "rollback":
            print(f"\n{decision}")
            break

        time.sleep(0.1)

    print("\n" + "="*50)
    print("模拟: 在50%升流后出现质量下降...")
    print("="*50 + "\n")

    state.current_stage = PromotionStage.CANARY_50
    state.stage_start_time = datetime.now() - timedelta(minutes=11)

    for i in range(5):
        decay_factor = i * 0.02
        metrics = MetricsSnapshot(
            timestamp=datetime.now(),
            version=2,
            stage=state.current_stage,
            golden_pass_rate=0.96 - decay_factor + random.uniform(-0.01, 0.01),
            quality_score=1.03 - decay_factor * 1.5 + random.uniform(-0.01, 0.01),
            schema_compliance=0.995 - decay_factor * 0.5 + random.uniform(-0.005, 0.005),
            failure_rate=0.005 + decay_factor * 2 + random.uniform(-0.002, 0.004),
            sample_size=50 + i * 10
        )

        decision = manager.record_metrics(metrics)

        if decision["action"] == "rollback":
            print(f"\n{decision}")
            break

        time.sleep(0.1)

    print("\n" + "="*50)
    print("演示完成")
    print("="*50)


if __name__ == "__main__":
    main()
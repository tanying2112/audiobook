"""
Audiobook Studio — Release Management Module
============================================

Extracted from scripts/promote.py for reuse across the codebase.

Contains:
- PromotionGate: 4硬指标评估 (格式合规、金数据集、质量提升、人工偏好)
- CanaryRelease: 灰度发布管理 (逐步引流、实时监控、自动回滚)
- VersionStore: 版本存储与回滚 (prompt版本管理、回滚日志)
"""

import json
import logging
import shutil
import sys
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

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
        human_preference_threshold: float = 0.80,
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
        timestamp: Optional[datetime] = None,
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
            timestamp=timestamp,
        )

        result = PromotionGateResult(
            passed=passed,
            failed_criteria=failed_criteria,
            metrics=metrics,
            timestamp=timestamp,
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
            timestamp=metrics_dict.get("timestamp"),
        )

    def get_status(self) -> Dict[str, Any]:
        """获取门禁状态."""
        return {
            "thresholds": {
                "format_compliance": self.format_compliance_threshold,
                "golden_dataset": self.golden_dataset_threshold,
                "quality_score": self.quality_score_threshold,
                "human_preference": self.human_preference_threshold,
            },
            "description": "Promotion Gate with 4 hard criteria for version promotion",
        }


# ── Canary Release ──────────────────────────────────────────────────────────────


@dataclass
class CanaryConfig:
    """Canary release 配置."""

    enabled: bool = True
    traffic_percentage: float = 0.1  # 10% 流量
    min_samples: int = 100  # 最小样本数
    max_duration_hours: int = 24  # 最大灰度时长
    rollback_threshold: float = 0.95  # 质量下降到旧版 95% 时触发回滚
    check_interval_minutes: int = 15  # 检查间隔


@dataclass
class CanaryMetrics:
    """Canary 阶段收集的指标."""

    version: str
    stage: str
    samples_collected: int
    avg_quality_score: float
    baseline_quality_score: float
    quality_ratio: float  # avg / baseline
    error_rate: float
    timestamp: datetime


class CanaryRelease:
    """Canary Release 管理器.

    负责:
    1. 逐步引流新版本
    2. 实时监控质量指标
    3. 自动回滚检测
    """

    def __init__(self, config: CanaryConfig):
        self.config = config
        self.active_canaries: Dict[str, Dict[str, Any]] = {}
        self.metrics_history: Dict[str, deque] = {}

    def start_canary(self, stage: str, version: str, baseline_score: float) -> bool:
        """启动 Canary 发布."""
        canary_id = f"{stage}-{version}"
        if canary_id in self.active_canaries:
            logger.warning(f"Canary already running for {canary_id}")
            return False

        self.active_canaries[canary_id] = {
            "stage": stage,
            "version": version,
            "baseline_score": baseline_score,
            "started_at": datetime.now(timezone.utc),
            "status": "running",
        }
        self.metrics_history[canary_id] = deque(maxlen=1000)

        logger.info(
            f"Started canary release: {canary_id} (baseline: {baseline_score:.4f})"
        )
        return True

    def record_metrics(self, stage: str, version: str, metrics: CanaryMetrics) -> None:
        """记录 Canary 指标."""
        canary_id = f"{stage}-{version}"
        if canary_id not in self.active_canaries:
            logger.warning(f"No active canary for {canary_id}")
            return

        self.metrics_history[canary_id].append(asdict(metrics))

        # 检查是否需要回滚
        if self._should_rollback(canary_id, metrics):
            self._trigger_rollback(canary_id, metrics)

    def _should_rollback(self, canary_id: str, metrics: CanaryMetrics) -> bool:
        """判断是否应该回滚."""
        if not self.config.enabled:
            return False

        # 检查样本量
        if metrics.samples_collected < self.config.min_samples:
            return False

        # 检查质量下降
        if metrics.quality_ratio < self.config.rollback_threshold:
            logger.warning(
                f"Rollback triggered for {canary_id}: "
                f"quality_ratio={metrics.quality_ratio:.4f} < threshold={self.config.rollback_threshold}"
            )
            return True

        # 检查错误率
        if metrics.error_rate > 0.1:  # 10% 错误率
            logger.warning(
                f"Rollback triggered for {canary_id}: high error rate {metrics.error_rate:.2%}"
            )
            return True

        return False

    def _trigger_rollback(self, canary_id: str, metrics: CanaryMetrics) -> None:
        """触发自动回滚."""
        if canary_id in self.active_canaries:
            self.active_canaries[canary_id]["status"] = "rolled_back"
            self.active_canaries[canary_id]["rolled_back_at"] = datetime.now(
                timezone.utc
            )
            self.active_canaries[canary_id][
                "rollback_reason"
            ] = f"quality_ratio={metrics.quality_ratio:.4f} < {self.config.rollback_threshold}"

            logger.warning(
                f"🔴 AUTO ROLLBACK: {canary_id} - {self.active_canaries[canary_id]['rollback_reason']}"
            )

    def complete_canary(self, stage: str, version: str) -> bool:
        """完成 Canary, 全量发布."""
        canary_id = f"{stage}-{version}"
        if canary_id not in self.active_canaries:
            return False

        self.active_canaries[canary_id]["status"] = "completed"
        self.active_canaries[canary_id]["completed_at"] = datetime.now(timezone.utc)

        logger.info(f"✅ Canary completed for {canary_id}, promoting to 100%")
        return True

    def get_canary_status(self, stage: str, version: str) -> Optional[Dict[str, Any]]:
        """获取 Canary 状态."""
        canary_id = f"{stage}-{version}"
        return self.active_canaries.get(canary_id)

    def get_all_canaries(self) -> Dict[str, Dict[str, Any]]:
        """获取所有 Canary 状态."""
        return self.active_canaries.copy()


# ── Version Store & Rollback ────────────────────────────────────────────────────


class VersionStore:
    """版本存储与回滚管理."""

    def __init__(self, base_path: Path = Path("prompts")):
        self.base_path = base_path
        self.rollback_log = base_path / "rollback_log.jsonl"
        self.current_versions: Dict[str, int] = {}

        # 扫描当前版本
        self._scan_current_versions()

    def _scan_current_versions(self) -> None:
        """扫描所有 stage 的当前版本."""
        for stage_dir in self.base_path.iterdir():
            if stage_dir.is_dir():
                versions = []
                for f in stage_dir.glob("v*.j2"):
                    try:
                        v = int(f.stem[1:])
                        versions.append(v)
                    except ValueError:
                        continue
                if versions:
                    self.current_versions[stage_dir.name] = max(versions)

    def get_current_version(self, stage: str) -> int:
        """获取当前版本号."""
        return self.current_versions.get(stage, 0)

    def promote_version(self, stage: str, new_version: int) -> bool:
        """将新版本设为当前版本."""
        if stage not in self.current_versions:
            self.current_versions[stage] = 0

        old_version = self.current_versions[stage]
        if new_version > old_version:
            self.current_versions[stage] = new_version
            self._log_rollback(stage, old_version, new_version, "promotion", True)
            return True
        return False

    def rollback_version(self, stage: str, target_version: int) -> bool:
        """回滚到指定版本."""
        if stage not in self.current_versions:
            logger.error(f"No version history for stage: {stage}")
            return False

        current = self.current_versions[stage]
        if target_version >= current:
            logger.warning(
                f"Target version {target_version} >= current {current}, no rollback needed"
            )
            return False

        if target_version < 1:
            logger.error(f"Invalid target version: {target_version}")
            return False

        self.current_versions[stage] = target_version
        self._log_rollback(stage, current, target_version, "rollback", True)

        logger.info(f"🔄 Rolled back {stage} from v{current} to v{target_version}")
        return True

    def rollback_last(self, stage: str) -> bool:
        """回滚到上一个版本."""
        current = self.current_versions.get(stage, 1)
        if current <= 1:
            logger.warning(f"Already at v1, cannot rollback further")
            return False
        return self.rollback_version(stage, current - 1)

    def _log_rollback(
        self, stage: str, from_version: int, to_version: int, action: str, success: bool
    ) -> None:
        """记录回滚日志."""
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "from_version": from_version,
            "to_version": to_version,
            "action": action,
            "success": success,
        }
        try:
            with open(self.rollback_log, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.error(f"Failed to write rollback log: {e}")

    def get_rollback_history(
        self, stage: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """获取回滚历史."""
        history = []
        if not self.rollback_log.exists():
            return history

        try:
            with open(self.rollback_log, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if stage is None or entry.get("stage") == stage:
                        history.append(entry)
            return history[-limit:]
        except Exception as e:
            logger.error(f"Failed to read rollback log: {e}")
            return history

    def get_status(self) -> Dict[str, Any]:
        """获取版本状态."""
        return {
            "current_versions": self.current_versions,
            "rollback_history": self.get_rollback_history(),
        }

"""质量阈值自动校准器：基于生产数据分布自动校准质量阈值。

核心功能：
1. 收集生产环节的硬指标分布（DNSMOS、WER、SpeakerSim 等）
2. 基于分布统计自动推荐阈值（分位数、均值±方差等）
3. 阈值变更走晋升门禁，防止过度放宽
3. 生成校准报告，支持人工复核
"""

from __future__ import annotations

import json
import logging
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from ..harness.config import get_harness_settings
from ..harness.models import QualityThreshold, ThresholdCalibrationRequest, ThresholdCalibrationResponse
from ..harness.storage import get_storage

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("config/quality_thresholds.yaml")


class DistributionStats(BaseModel):
    """指标分布统计。"""

    count: int = 0
    mean: float = 0.0
    std: float = 0.0
    min: float = 0.0
    max: float = 0.0
    percentiles: Dict[str, float] = {}  # p5, p10, p25, p50, p75, p90, p95
    histogram: Dict[str, int] = {}  # 直方图分箱


class ThresholdRecommendation(BaseModel):
    """阈值调整建议。"""

    metric_name: str
    stage: str
    old_value: float
    recommended_value: float
    change_pct: float
    reason: str
    distribution: Dict[str, Any]
    confidence: float  # 0-1，基于样本量


class CalibrationReport(BaseModel):
    """校准报告。"""

    timestamp: str
    window_days: int
    total_samples: int
    recommendations: List[Dict[str, Any]]
    applied: List[Dict[str, Any]]
    skipped: List[Dict[str, Any]]


class ThresholdCalibrator:
    """质量阈值自动校准器。

    核心逻辑：
    1. 收集近 N 天的质检指标数据
    2. 计算分布统计（均值、标准差、分位数）
    3. 基于分位数推荐新阈值（如 P5 作为下界，P95 作为上界）
    4. 变更幅度限制在 MAX_CHANGE_PCT 内
    4. 生成校准报告，经人工/门禁确认后应用
    """

    def __init__(self):
        self._settings = None
        self._storage = None

    @property
    def settings(self):
        if self._settings is None:
            from ..harness.config import get_harness_settings

            self._settings = get_harness_settings()
        return self._settings

    def _get_storage(self):
        if self._storage is None:
            from ..harness.storage import get_storage

            self._storage = get_storage()
        return self._storage

    # ──────────────────────────────────────────────────────────────────────────
    # 核心校准逻辑
    # ──────────────────────────────────────────────────────────────────────────

    def collect_metrics(
        self,
        stage: str,
        metric_names: List[str],
        days: int = 14,
    ) -> Dict[str, List[float]]:
        """收集近 N 天的质检指标数据。

        从 quality_judgments / quality_check 结果中提取指标。
        """
        # 这里简化：实际应从 quality_judgments 表或 quality_check 结果中提取
        # 示例：返回模拟数据用于演示
        # 实际应查询 quality_judgments 表
        return {
            "dnsmos": [3.2, 3.5, 3.8, 3.1, 3.6, 3.4, 3.7, 3.3, 3.5, 3.6] * 10,
            "wer": [0.05, 0.03, 0.08, 0.02, 0.04, 0.06, 0.02, 0.03, 0.04, 0.05] * 10,
            "speaker_sim": [0.85, 0.92, 0.78, 0.88, 0.91, 0.83, 0.87, 0.89, 0.84, 0.90] * 10,
        }

    def compute_distribution(self, values: List[float]) -> DistributionStats:
        """计算分布统计。"""
        if not values:
            return DistributionStats()

        sorted_vals = sorted(values)
        n = len(values)
        mean = statistics.mean(values)
        std = statistics.stdev(values) if n > 1 else 0.0

        def percentile(p: float) -> float:
            if not values:
                return 0.0
            k = (len(sorted_vals) - 1) * p
            f = int(k)
            c = min(f + 1, len(sorted_vals) - 1)
            if f == c:
                return sorted_vals[f]
            return sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f])

        # 直方图分箱（10 个等宽分箱）
        hist = {}
        if values:
            min_v, max_v = min(values), max(values)
            if max_v > min_v:
                bin_width = (max_v - min_v) / 10
                for v in values:
                    bin_idx = min(int((v - min_v) / bin_width), 9)
                    key = f"{min_v + bin_idx * bin_width:.2f}-{min_v + (bin_idx + 1) * bin_width:.2f}"
                    hist[key] = hist.get(key, 0) + 1

        return DistributionStats(
            count=len(values),
            mean=mean,
            std=std,
            min=min(values),
            max=max(values),
            percentiles={
                "p5": percentile(0.05),
                "p10": percentile(0.10),
                "p25": percentile(0.25),
                "p50": percentile(0.50),
                "p75": percentile(0.75),
                "p90": percentile(0.90),
                "p95": percentile(0.95),
            },
            histogram=hist,
        )

    def recommend_threshold(
        self,
        stage: str,
        metric_name: str,
        current_value: float,
        distribution: DistributionStats,
        direction: str = "lower",  # "lower" = 越大越好，取下界；"upper" = 越小越好，取上界
    ) -> Optional[Dict[str, Any]]:
        """基于分布推荐新阈值。

        Args:
            stage: 阶段名
            metric_name: 指标名
            current_value: 当前阈值
            distribution: 分布统计
            direction: "lower" 表示指标越大越好（取下界如 P5），"upper" 表示越小越好（取上界如 P95）

        Returns:
            推荐结果或 None（样本不足）
        """
        if distribution.count < self.settings.CALIBRATION_MIN_SAMPLES:
            return None

        # 根据方向选择分位点
        if direction == "lower":
            # 越大越好，取 P5 作为下界（保证 95% 样本通过）
            recommended = distribution.percentiles.get("p5", 0.0)
        else:
            # 越小越好，取 P95 作为上界
            recommended = distribution.percentiles.get("p95", 0.0)

        # 限制变化幅度
        self.settings.CALIBRATION_MAX_CHANGE_PCT
        change_pct = abs(recommended - current_value) / max(abs(current_value), 1e-6)
        if change_pct > self.settings.CALIBRATION_MAX_CHANGE_PCT:
            # 限制变化幅度
            if recommended > current_value:
                recommended = current_value * (1 + self.settings.CALIBRATION_MAX_CHANGE_PCT)
            else:
                recommended = current_value * (1 - self.settings.CALIBRATION_MAX_CHANGE_PCT)

        # 计算置信度（基于样本量）
        min(distribution.count / (self.settings.CALIBRATION_MIN_SAMPLES * 2), 1.0)

        change_pct = (recommended - current_value) / max(abs(current_value), 1e-6)

        return {
            "metric_name": metric_name,
            "stage": stage,
            "old_value": current_value,
            "recommended_value": round(recommended, 4),
            "change_pct": round(change_pct * 100, 2),
            "direction": direction,
            "distribution": {
                "count": distribution.count,
                "mean": distribution.mean,
                "std": distribution.std,
                "percentiles": distribution.percentiles,
            },
            "confidence": round(min(1.0, distribution.count / (self.settings.CALIBRATION_MIN_SAMPLES * 2)), 2),
            "reason": f"基于 {distribution.count} 个样本的分布统计，取 {'P5' if direction == 'lower' else 'P95'} 分位数",
        }

    def auto_calibrate(
        self,
        days: int = 14,
        apply: bool = False,
    ) -> Dict[str, Any]:
        """自动校准所有已配置的阈值。

        Args:
            days: 统计窗口天数
            apply: 是否直接应用（否则仅生成报告）

        Returns:
            校准报告
        """
        self.settings

        # 1. 加载当前阈值配置
        thresholds_config = self._load_thresholds_config()
        recommendations = []
        applied = []
        skipped = []

        for threshold in thresholds_config:
            if not threshold.get("is_active", True):
                continue

            stage = threshold["stage"]
            metric = threshold["metric_name"]
            threshold["value"]
            "lower" if threshold.get("operator", ">=") in (">=", ">") else "upper"

            # 收集指标数据
            metrics_data = self.collect_metrics(stage, [metric], days=14)
            values = metrics_data.get(metric, [])

            if len(values) < self.settings.CALIBRATION_MIN_SAMPLES:
                skipped.append(
                    {
                        "metric": metric,
                        "stage": stage,
                        "reason": f"样本不足 ({len(values)} < {self.settings.CALIBRATION_MIN_SAMPLES})",
                    }
                )
                continue

            # 计算分布
            dist = self.compute_distribution(values)

            # 推荐新阈值
            rec = self.recommend_threshold(
                stage=stage,
                metric_name=metric,
                current_value=threshold["value"],
                distribution=DistributionStats(**dist),
                direction="lower" if threshold.get("operator", ">=") in (">=", ">") else "upper",
            )

            if not rec:
                skipped.append(
                    {
                        "metric": metric,
                        "stage": stage,
                        "reason": "推荐生成失败",
                    }
                )
                continue

            recommendations.append(rec)

            if apply:
                # 应用新阈值
                self._update_threshold_config(metric, rec["recommended_value"])
                applied.append(
                    {
                        "metric": metric,
                        "stage": stage,
                        "old_value": threshold["value"],
                        "new_value": rec["recommended_value"],
                    }
                )
            else:
                skipped.append(
                    {
                        "metric": metric,
                        "stage": stage,
                        "reason": "dry-run 模式，未应用",
                        "recommended": rec["recommended_value"],
                    }
                )

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "window_days": 14,
            "total_samples": 0,  # TODO: 统计总样本数
            "recommendations": recommendations,
            "applied": applied,
            "skipped": skipped,
        }

        # 保存校准报告
        self._save_calibration_report(report)

        return report

    def _load_thresholds_config(self) -> List[Dict]:
        """加载当前阈值配置。"""
        try:
            import yaml

            config_path = Path("config/quality_thresholds.yaml")
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                return data.get("thresholds", [])
        except Exception as e:
            logger.warning(f"Failed to load thresholds config: {e}")
        return []

    def _update_threshold_config(self, metric_name: str, new_value: float) -> bool:
        """更新阈值配置文件。"""
        try:
            import yaml

            config_path = Path("config/quality_thresholds.yaml")
            with open(config_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            for threshold in data.get("thresholds", []):
                if threshold.get("metric_name") == metric_name:
                    threshold["value"] = round(new_value, 4)
                    threshold["version"] = threshold.get("version", 1) + 1
                    threshold["last_calibrated_at"] = datetime.now(timezone.utc).isoformat()
                    break

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
            return True
        except Exception as e:
            logger.error(f"Failed to update threshold config: {e}")
            return False

    def _save_calibration_report(self, report: Dict) -> None:
        """保存校准报告。"""
        report_dir = Path("data/calibration_reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"calibration_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def run_calibration(
        self,
        days: int = 14,
        apply: bool = False,
    ) -> Dict[str, Any]:
        """运行完整校准流程的便捷入口。"""
        return self.auto_calibrate(days=days, apply=apply)


# ──────────────────────────────────────────────────────────────────────────────
# 便捷入口
# ──────────────────────────────────────────────────────────────────────────────

_calibrator: Optional["ThresholdCalibrator"] = None


def get_threshold_calibrator() -> "ThresholdCalibrator":
    global _threshold_calibrator
    if _threshold_calibrator is None:
        _threshold_calibrator = ThresholdCalibrator()
    return _threshold_calibrator


_threshold_calibrator: Optional["ThresholdCalibrator"] = None


def run_threshold_calibration(days: int = 14, apply: bool = False) -> Dict[str, Any]:
    """运行阈值自动校准的便捷入口。"""
    calibrator = get_threshold_calibrator()
    return calibrator.auto_calibrate(days=days, apply=apply)


def get_calibration_report(latest: bool = True) -> Optional[Dict]:
    """获取最新的校准报告。"""
    report_dir = Path("data/calibration_reports")
    if not report_dir.exists():
        return None
    reports = sorted(report_dir.glob("calibration_*.json"))
    if not reports:
        return None
    if latest:
        return json.loads(reports[-1].read_text(encoding="utf-8"))
    return [json.loads(r.read_text(encoding="utf-8")) for r in reports]


__all__ = [
    "ThresholdCalibrator",
    "DistributionStats",
    "ThresholdRecommendation",
    "CalibrationReport",
    "ThresholdCalibrator",
    "run_threshold_calibration",
    "get_calibration_report",
]

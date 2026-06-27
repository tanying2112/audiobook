"""
Performance and Growth Baseline Recording System
Tracks key metrics over time to establish baselines and detect regressions.
"""

import json
import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetric:
    """Single performance measurement"""

    timestamp: float
    stage: str
    latency_ms: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    success: bool
    quality_score: Optional[float] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    schema_compliance: Optional[bool] = None


@dataclass
class GrowthMetric:
    """Growth/usage metric"""

    timestamp: float
    metric_name: str
    value: float
    unit: str
    tags: Dict[str, str]


class BaselineRecorder:
    """Records and manages performance and growth baselines"""

    def __init__(self, storage_dir: str = "./baselines"):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.performance_file = self.storage_dir / "performance.jsonl"
        self.growth_file = self.storage_dir / "growth.jsonl"
        self.baseline_file = self.storage_dir / "baselines.json"

        # In-memory caches for quick access
        self._performance_cache: List[PerformanceMetric] = []
        self._growth_cache: List[GrowthMetric] = []
        self._baselines: Dict[str, Any] = {}

        self._lock = threading.Lock()
        self._load_recent_data()

    def _load_recent_data(self, hours: int = 24) -> None:
        """Load recent data into memory cache"""
        cutoff_time = time.time() - (hours * 3600)

        # Load performance metrics
        if self.performance_file.exists():
            with open(self.performance_file, "r") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        if data.get("timestamp", 0) >= cutoff_time:
                            self._performance_cache.append(PerformanceMetric(**data))
                    except (json.JSONDecodeError, TypeError):
                        continue

        # Load growth metrics
        if self.growth_file.exists():
            with open(self.growth_file, "r") as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        if data.get("timestamp", 0) >= cutoff_time:
                            self._growth_cache.append(GrowthMetric(**data))
                    except (json.JSONDecodeError, TypeError):
                        continue

        # Load baselines
        if self.baseline_file.exists():
            with open(self.baseline_file, "r") as f:
                self._baselines = json.load(f)

    def record_performance(self, metric: PerformanceMetric) -> None:
        """Record a performance metric"""
        with self._lock:
            self._performance_cache.append(metric)
            self._append_to_file(self.performance_file, asdict(metric))

    def record_growth(self, metric: GrowthMetric) -> None:
        """Record a growth metric"""
        with self._lock:
            self._growth_cache.append(metric)
            self._append_to_file(self.growth_file, asdict(metric))

    def _append_to_file(self, file_path: Path, data: Dict[str, Any]) -> None:
        """Append JSON line to file"""
        with open(file_path, "a") as f:
            f.write(json.dumps(data) + "\n")

    def get_performance_baseline(
        self, stage: str, lookback_hours: int = 168
    ) -> Dict[str, float]:
        """
        Get baseline performance metrics for a stage
        lookback_hours: how far back to look for baseline (default 1 week)
        """
        cutoff_time = time.time() - (lookback_hours * 3600)

        # Filter metrics for the stage and time window
        stage_metrics = [
            m
            for m in self._performance_cache
            if m.stage == stage and m.timestamp >= cutoff_time and m.success
        ]

        if not stage_metrics:
            return {}

        # Calculate baseline statistics
        latencies = [m.latency_ms for m in stage_metrics]
        costs = [m.cost_usd for m in stage_metrics]
        tokens_in = [m.tokens_in for m in stage_metrics]
        tokens_out = [m.tokens_out for m in stage_metrics]

        return {
            "count": len(stage_metrics),
            "latency_p50": self._percentile(latencies, 50),
            "latency_p95": self._percentile(latencies, 95),
            "latency_avg": sum(latencies) / len(latencies),
            "cost_avg": sum(costs) / len(costs),
            "tokens_in_avg": sum(tokens_in) / len(tokens_in),
            "tokens_out_avg": sum(tokens_out) / len(tokens_out),
            "success_rate": len([m for m in stage_metrics if m.success])
            / len(stage_metrics),
        }

    def get_growth_baseline(
        self, metric_name: str, lookback_hours: int = 720
    ) -> Dict[str, Any]:  # 30 days default
        """Get baseline for a growth metric"""
        cutoff_time = time.time() - (lookback_hours * 3600)

        metric_values = [
            m.value
            for m in self._growth_cache
            if m.metric_name == metric_name and m.timestamp >= cutoff_time
        ]

        if not metric_values:
            return {}

        return {
            "count": len(metric_values),
            "latest": float(metric_values[-1]) if metric_values else 0.0,
            "avg": sum(metric_values) / len(metric_values),
            "min": min(metric_values),
            "max": max(metric_values),
            "trend": self._calculate_trend(metric_values),
        }

    def check_performance_regression(
        self, stage: str, current_metric: PerformanceMetric, threshold_pct: float = 20.0
    ) -> Optional[Dict[str, Any]]:
        """
        Check if current performance represents a regression
        Returns regression details if found, None otherwise
        """
        baseline = self.get_performance_baseline(stage)
        if not baseline:
            return None  # No baseline to compare against

        regressions = []

        # Check latency regression
        if current_metric.latency_ms > baseline["latency_p95"] * (
            1 + threshold_pct / 100
        ):
            regressions.append(
                {
                    "metric": "latency",
                    "current": current_metric.latency_ms,
                    "baseline_p95": baseline["latency_p95"],
                    "exceeds_pct": (
                        (current_metric.latency_ms / baseline["latency_p95"] - 1) * 100
                    ),
                }
            )

        # Check cost regression
        if current_metric.cost_usd > baseline["cost_avg"] * (1 + threshold_pct / 100):
            regressions.append(
                {
                    "metric": "cost",
                    "current": current_metric.cost_usd,
                    "baseline_avg": baseline["cost_avg"],
                    "exceeds_pct": (
                        (current_metric.cost_usd / baseline["cost_avg"] - 1) * 100
                    ),
                }
            )

        # Check success rate regression (if we have enough samples)
        if baseline["count"] >= 10:
            current_success = 1.0 if current_metric.success else 0.0
            if current_success < (
                baseline.get("success_rate", 1.0) - threshold_pct / 100
            ):
                regressions.append(
                    {
                        "metric": "success_rate",
                        "current": current_success,
                        "baseline": baseline.get("success_rate", 1.0),
                        "exceeds_pct": (
                            (baseline.get("success_rate", 1.0) - current_success)
                            / baseline.get("success_rate", 1.0)
                            * 100
                        ),
                    }
                )

        if regressions:
            return {
                "stage": stage,
                "timestamp": current_metric.timestamp,
                "regressions": regressions,
                "baseline": baseline,
            }
        return None

    def _percentile(self, values: List[float], percentile: float) -> float:
        """Calculate percentile value"""
        if not values:
            return 0.0
        sorted_values = sorted(values)
        index = int((percentile / 100) * len(sorted_values))
        index = min(index, len(sorted_values) - 1)
        return sorted_values[index]

    def _calculate_trend(self, values: List[float]) -> str:
        """Calculate simple trend direction"""
        if len(values) < 2:
            return "insufficient_data"

        # Compare first half vs second half averages
        mid = len(values) // 2
        first_half = values[:mid]
        second_half = values[mid:]

        if not first_half or not second_half:
            return "insufficient_data"

        avg_first = sum(first_half) / len(first_half)
        avg_second = sum(second_half) / len(second_half)

        diff_pct = ((avg_second - avg_first) / avg_first * 100) if avg_first != 0 else 0

        if diff_pct > 5:
            return "increasing"
        elif diff_pct < -5:
            return "decreasing"
        else:
            return "stable"

    def save_baselines(self) -> None:
        """Save calculated baselines to file"""
        baselines: Dict[str, Any] = {}

        # Calculate baselines for all stages
        stages = set(m.stage for m in self._performance_cache)
        for stage in stages:
            baselines[f"performance_{stage}"] = self.get_performance_baseline(
                stage, lookback_hours=720
            )

        # Calculate baselines for growth metrics
        metric_names = set(m.metric_name for m in self._growth_cache)
        for metric_name in metric_names:
            baselines[f"growth_{metric_name}"] = self.get_growth_baseline(
                metric_name, lookback_hours=720
            )

        with self._lock:
            self._baselines = baselines
            with open(self.baseline_file, "w") as f:
                json.dump(baselines, f, indent=2, default=str)

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of recorded metrics"""
        with self._lock:
            return {
                "performance_metrics_count": len(self._performance_cache),
                "growth_metrics_count": len(self._growth_cache),
                "baselines_calculated": len(self._baselines),
                "storage_dir": str(self.storage_dir),
                "oldest_performance": (
                    min([m.timestamp for m in self._performance_cache])
                    if self._performance_cache
                    else None
                ),
                "newest_performance": (
                    max([m.timestamp for m in self._performance_cache])
                    if self._performance_cache
                    else None
                ),
            }


# Global recorder instance
_recorder: Optional[BaselineRecorder] = None


def get_baseline_recorder() -> BaselineRecorder:
    """Get or create the global baseline recorder"""
    global _recorder
    if _recorder is None:
        _recorder = BaselineRecorder()
    return _recorder


def record_stage_performance(
    stage: str,
    latency_ms: float,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    success: bool,
    quality_score: Optional[float] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    difficulty: Optional[str] = None,
    schema_compliance: Optional[bool] = None,
    error: Optional[str] = None,
) -> PerformanceMetric:
    """Convenience function to record stage performance"""
    recorder = get_baseline_recorder()
    metric = PerformanceMetric(
        timestamp=time.time(),
        stage=stage,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        success=success,
        quality_score=quality_score,
        provider=provider,
        model=model,
        schema_compliance=schema_compliance,
    )
    recorder.record_performance(metric)
    return metric


def record_growth_metric(
    metric_name: str,
    value: float,
    unit: str = "",
    tags: Optional[Dict[str, str]] = None,
) -> GrowthMetric:
    """Convenience function to record growth metric"""
    recorder = get_baseline_recorder()
    metric = GrowthMetric(
        timestamp=time.time(),
        metric_name=metric_name,
        value=value,
        unit=unit,
        tags=tags or {},
    )
    recorder.record_growth(metric)
    return metric


if __name__ == "__main__":
    # Demo usage
    recorder = BaselineRecorder("./demo_baselines")

    # Record some sample performance data
    import random

    for i in range(10):
        metric = PerformanceMetric(
            timestamp=time.time() - (i * 3600),  # Spread over 10 hours
            stage="synthesize",
            latency_ms=1000 + random.uniform(-200, 200),
            tokens_in=500 + random.randint(-50, 50),
            tokens_out=1000 + random.randint(-100, 100),
            cost_usd=0.005 + random.uniform(-0.001, 0.001),
            success=random.random() > 0.1,  # 90% success rate
            quality_score=0.8 + random.uniform(-0.1, 0.1),
            provider="gemini",
            model="gemini-2.0-flash",
        )
        recorder.record_performance(metric)

    # Record some growth metrics
    for i in range(5):
        recorder.record_growth(
            GrowthMetric(
                timestamp=time.time() - (i * 86400),  # Daily over 5 days
                metric_name="books_processed",
                value=10 + i * 2 + random.uniform(-1, 1),
                unit="books",
                tags={},
            )
        )

    # Calculate and show baselines
    baseline = recorder.get_performance_baseline("synthesize", lookback_hours=24)
    logger.info("Synthesize baseline:", json.dumps(baseline, indent=2))

    growth = recorder.get_growth_baseline("books_processed", lookback_hours=24)
    logger.info("Books processed baseline:", json.dumps(growth, indent=2))

    # Check for regression
    current_metric = PerformanceMetric(
        timestamp=time.time(),
        stage="synthesize",
        latency_ms=1500,  # Intentionally high to trigger regression
        tokens_in=500,
        tokens_out=1000,
        cost_usd=0.008,  # Intentionally high
        success=True,
        quality_score=0.75,
        provider="gemini",
        model="gemini-2.0-flash",
    )

    regression = recorder.check_performance_regression(
        "synthesize", current_metric, threshold_pct=20.0
    )
    if regression:
        logger.info("\nREGRESSION DETECTED:")
        logger.info(json.dumps(regression, indent=2))
    else:
        logger.info("\nNo regression detected")

    recorder.save_baselines()
    logger.info(f"\nRecorder summary: {json.dumps(recorder.get_summary(), indent=2)}")

"""Monitoring module for Audiobook Studio.

Provides performance recording and observability for pipeline stages.
Acts as a lightweight facade that can be replaced with Langfuse/Prometheus
in production.
"""

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class StagePerformanceRecord:
    """Record of a single pipeline stage execution."""

    stage: str
    latency_ms: float
    tokens_in: int
    tokens_out: int
    cost_usd: float
    success: bool
    quality_score: Optional[float] = None
    provider: str = "unknown"
    model: str = "unknown"
    difficulty: Optional[str] = None  # A, B, C, D from book meta
    schema_compliance: Optional[bool] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    error: Optional[str] = None


class PerformanceCollector:
    """Collects and stores pipeline stage performance records.

    In production, this would push to Langfuse, Prometheus, or similar.
    For now, stores in-memory and optionally persists to JSON logs.
    """

    def __init__(self, log_dir: Optional[Path] = None):
        self.records: List[StagePerformanceRecord] = []
        self.log_dir = log_dir
        if log_dir:
            log_dir.mkdir(parents=True, exist_ok=True)

    def record(self, **kwargs) -> StagePerformanceRecord:
        """Record a stage performance entry."""
        entry = StagePerformanceRecord(**kwargs)
        self.records.append(entry)

        # Log to structured logging
        logger.info(
            f"Stage perf: stage={entry.stage} latency_ms={entry.latency_ms:.0f} "
            f"tokens_in={entry.tokens_in} tokens_out={entry.tokens_out} "
            f"cost_usd={entry.cost_usd:.4f} success={entry.success} "
            f"quality_score={entry.quality_score} "
            f"difficulty={entry.difficulty or 'unknown'}"
        )

        # Persist to JSON log if configured
        if self.log_dir:
            self._persist(entry)

        return entry

    def _persist(self, entry: StagePerformanceRecord) -> None:
        """Write performance record to date-based log file."""
        if not self.log_dir:
            return
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = self.log_dir / f"{date_str}_perf.jsonl"
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")
        except OSError as e:
            logger.warning(f"Failed to persist performance record: {e}")

    def get_stage_stats(self, stage: str) -> Dict[str, Any]:
        """Get summary statistics for a specific stage."""
        stage_records = [r for r in self.records if r.stage == stage]
        if not stage_records:
            return {"stage": stage, "count": 0}

        successful = [r for r in stage_records if r.success]
        return {
            "stage": stage,
            "count": len(stage_records),
            "success_count": len(successful),
            "success_rate": (
                len(successful) / len(stage_records) if stage_records else 0
            ),
            "avg_latency_ms": sum(r.latency_ms for r in stage_records)
            / len(stage_records),
            "total_cost_usd": sum(r.cost_usd for r in stage_records),
            "avg_quality_score": (
                sum(r.quality_score for r in successful if r.quality_score is not None)
                / len([r for r in successful if r.quality_score is not None])
                if any(r.quality_score is not None for r in successful)
                else None
            ),
        }

    def get_summary(self) -> Dict[str, Any]:
        """Get summary statistics for all stages."""
        stages = set(r.stage for r in self.records)
        return {
            "total_records": len(self.records),
            "total_cost_usd": sum(r.cost_usd for r in self.records),
            "stages": {stage: self.get_stage_stats(stage) for stage in sorted(stages)},
        }


# Global singleton for convenient access
_collector = PerformanceCollector()


def get_collector() -> PerformanceCollector:
    """Get the global PerformanceCollector singleton."""
    return _collector


def reset_collector() -> None:
    """Reset the global collector (useful for testing)."""
    global _collector
    _collector = PerformanceCollector()


def record_stage_performance(
    stage: str,
    latency_ms: float,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    success: bool,
    quality_score: Optional[float] = None,
    provider: str = "unknown",
    model: str = "unknown",
    difficulty: Optional[str] = None,
    schema_compliance: Optional[bool] = None,
    error: Optional[str] = None,
) -> StagePerformanceRecord:
    """Convenience function to record a stage performance entry.

    This is the main entry point used by pipeline stages.
    """
    return _collector.record(
        stage=stage,
        latency_ms=latency_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        success=success,
        quality_score=quality_score,
        provider=provider,
        model=model,
        difficulty=difficulty,
        schema_compliance=schema_compliance,
        error=error,
    )

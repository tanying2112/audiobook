"""Compliance Monitoring for Audiobook Studio.

Tracks schema compliance rates, contract version adherence, and quality threshold
compliance across all pipeline stages. Supports HARNESS §3 evaluation layer.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class ComplianceRecord:
    """Single compliance check record."""
    stage: str
    timestamp: str
    schema_compliance: bool
    contract_version: int
    quality_score: float
    errors: List[str] = field(default_factory=list)
    latency_ms: float = 0.0
    cost_usd: float = 0.0


@dataclass
class StageComplianceSummary:
    """Aggregated compliance summary for a pipeline stage."""
    stage: str
    total_calls: int = 0
    compliant_calls: int = 0
    total_latency_ms: float = 0.0
    total_cost_usd: float = 0.0
    total_quality_score: float = 0.0
    error_counts: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    contract_versions: Dict[int, int] = field(default_factory=lambda: defaultdict(int))

    @property
    def compliance_rate(self) -> float:
        return self.compliant_calls / self.total_calls if self.total_calls > 0 else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.total_calls if self.total_calls > 0 else 0.0

    @property
    def avg_quality_score(self) -> float:
        return self.total_quality_score / self.total_calls if self.total_calls > 0 else 0.0

    @property
    def avg_cost_usd(self) -> float:
        return self.total_cost_usd / self.total_calls if self.total_calls > 0 else 0.0


class ComplianceMonitor:
    """Monitors schema compliance, contract versions, and quality thresholds.

    Provides real-time compliance tracking across all 6 pipeline stages.
    Supports HARNESS evaluation layer requirements.
    """

    def __init__(self, storage_path: Optional[str] = None):
        self.storage_path = Path(storage_path) if storage_path else Path("./reports/compliance")
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.records: List[ComplianceRecord] = []
        self.stage_summaries: Dict[str, StageComplianceSummary] = {}
        self._session_start = datetime.now().isoformat()

    def record(
        self,
        stage: str,
        schema_compliance: bool,
        contract_version: int = 1,
        quality_score: float = 1.0,
        errors: Optional[List[str]] = None,
        latency_ms: float = 0.0,
        cost_usd: float = 0.0,
    ) -> ComplianceRecord:
        """Record a compliance check result."""
        record = ComplianceRecord(
            stage=stage,
            timestamp=datetime.now().isoformat(),
            schema_compliance=schema_compliance,
            contract_version=contract_version,
            quality_score=quality_score,
            errors=errors or [],
            latency_ms=latency_ms,
            cost_usd=cost_usd,
        )
        self.records.append(record)

        # Update stage summary
        if stage not in self.stage_summaries:
            self.stage_summaries[stage] = StageComplianceSummary(stage=stage)
        summary = self.stage_summaries[stage]
        summary.total_calls += 1
        if schema_compliance:
            summary.compliant_calls += 1
        summary.total_latency_ms += latency_ms
        summary.total_cost_usd += cost_usd
        summary.total_quality_score += quality_score
        for error in errors or []:
            summary.error_counts[error] += 1
        summary.contract_versions[contract_version] += 1

        # Log if non-compliant
        if not schema_compliance:
            logger.warning(f"Schema compliance failure in {stage}: {errors}")

        return record

    def get_stage_summary(self, stage: str) -> Optional[StageComplianceSummary]:
        """Get compliance summary for a specific stage."""
        return self.stage_summaries.get(stage)

    def get_all_summaries(self) -> Dict[str, StageComplianceSummary]:
        """Get all stage summaries."""
        return dict(self.stage_summaries)

    def get_overall_compliance_rate(self) -> float:
        """Get overall schema compliance rate across all stages."""
        total = sum(s.total_calls for s in self.stage_summaries.values())
        compliant = sum(s.compliant_calls for s in self.stage_summaries.values())
        return compliant / total if total > 0 else 0.0

    def get_contract_version_distribution(self) -> Dict[int, int]:
        """Get distribution of contract versions across all records."""
        distribution = defaultdict(int)
        for record in self.records:
            distribution[record.contract_version] += 1
        return dict(distribution)

    def check_thresholds(
        self,
        min_compliance_rate: float = 0.99,
        min_quality_score: float = 0.7,
    ) -> Dict[str, Any]:
        """Check if compliance meets thresholds.

        Returns dict with pass/fail status and details.
        """
        results = {
            "overall_pass": True,
            "overall_compliance_rate": self.get_overall_compliance_rate(),
            "min_required": min_compliance_rate,
            "stage_results": {},
        }

        for stage, summary in self.stage_summaries.items():
            stage_pass = (
                summary.compliance_rate >= min_compliance_rate
                and summary.avg_quality_score >= min_quality_score
            )
            if not stage_pass:
                results["overall_pass"] = False

            results["stage_results"][stage] = {
                "compliance_rate": summary.compliance_rate,
                "avg_quality_score": summary.avg_quality_score,
                "avg_latency_ms": summary.avg_latency_ms,
                "avg_cost_usd": summary.avg_cost_usd,
                "pass": stage_pass,
                "total_calls": summary.total_calls,
                "errors": dict(summary.error_counts),
            }

        return results

    def export_report(self, output_path: Optional[str] = None) -> str:
        """Export compliance report to JSON file."""
        if output_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = self.storage_path / f"compliance_report_{timestamp}.json"

        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        report = {
            "session_start": self._session_start,
            "report_generated": datetime.now().isoformat(),
            "total_records": len(self.records),
            "overall_compliance_rate": self.get_overall_compliance_rate(),
            "contract_version_distribution": self.get_contract_version_distribution(),
            "stage_summaries": {
                stage: {
                    "total_calls": summary.total_calls,
                    "compliant_calls": summary.compliant_calls,
                    "compliance_rate": summary.compliance_rate,
                    "avg_latency_ms": summary.avg_latency_ms,
                    "avg_cost_usd": summary.avg_cost_usd,
                    "avg_quality_score": summary.avg_quality_score,
                    "error_counts": dict(summary.error_counts),
                    "contract_versions": dict(summary.contract_versions),
                }
                for stage, summary in self.stage_summaries.items()
            },
            "recent_failures": [
                {
                    "stage": r.stage,
                    "timestamp": r.timestamp,
                    "errors": r.errors,
                    "quality_score": r.quality_score,
                }
                for r in self.records[-20:] if not r.schema_compliance
            ],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        logger.info(f"Compliance report exported to {output_path}")
        return str(output_path)

    def reset(self):
        """Reset all collected data."""
        self.records.clear()
        self.stage_summaries.clear()
        self._session_start = datetime.now().isoformat()


# Global compliance monitor instance
_global_monitor: Optional[ComplianceMonitor] = None


def get_compliance_monitor() -> ComplianceMonitor:
    """Get or create global compliance monitor."""
    global _global_monitor
    if _global_monitor is None:
        _global_monitor = ComplianceMonitor()
    return _global_monitor


def record_pipeline_compliance(
    stage: str,
    schema_compliance: bool,
    contract_version: int = 1,
    quality_score: float = 1.0,
    errors: Optional[List[str]] = None,
    latency_ms: float = 0.0,
    cost_usd: float = 0.0,
) -> ComplianceRecord:
    """Convenience function to record pipeline compliance."""
    monitor = get_compliance_monitor()
    return monitor.record(
        stage=stage,
        schema_compliance=schema_compliance,
        contract_version=contract_version,
        quality_score=quality_score,
        errors=errors,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
    )


if __name__ == "__main__":
    # Demo usage
    logging.basicConfig(level=logging.INFO)
    monitor = ComplianceMonitor()

    # Simulate some compliance checks
    for stage in ["extract", "analyze", "annotate", "edit", "synthesize", "quality"]:
        for i in range(10):
            monitor.record(
                stage=stage,
                schema_compliance=True,
                contract_version=1,
                quality_score=0.95,
                latency_ms=100.0 + i * 10,
                cost_usd=0.001,
            )
        # Add one failure
        monitor.record(
            stage=stage,
            schema_compliance=False,
            contract_version=1,
            quality_score=0.5,
            errors=["schema_validation_failed"],
        )

    print(f"Overall compliance: {monitor.get_overall_compliance_rate():.1%}")
    thresholds = monitor.check_thresholds()
    print(f"Thresholds met: {thresholds['overall_pass']}")
    print(json.dumps(thresholds, ensure_ascii=False, indent=2))

    report_path = monitor.export_report()
    print(f"Report saved to: {report_path}")
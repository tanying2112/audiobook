#!/usr/bin/env python3
"""
Audiobook Studio — Monitoring Dashboard
========================================
Reads structured JSON logs and displays a performance summary.
Usage:
    python scripts/monitoring_dashboard.py [--hours 24] [--json]
"""

import argparse
import json
import logging
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audiobook Studio Monitoring Dashboard"
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Lookback window in hours (default: 24)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted dashboard",
    )
    parser.add_argument(
        "--baselines-dir",
        type=str,
        default="./baselines",
        help="Path to baselines directory (default: ./baselines)",
    )
    parser.add_argument(
        "--logs-dir",
        type=str,
        default="./logs",
        help="Path to structured JSON logs directory (default: ./logs)",
    )
    return parser.parse_args()


def collect_logs(logs_dir: Path, hours: int) -> List[Dict[str, Any]]:
    """Collect performance records from JSONL log files."""
    records = []
    cutoff = datetime.now() - timedelta(hours=hours)

    if not logs_dir.exists():
        return records

    for log_file in sorted(logs_dir.glob("*_perf.jsonl")):
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                        ts = record.get("timestamp", "")
                        if ts:
                            try:
                                record_time = datetime.fromisoformat(ts)
                                if record_time >= cutoff:
                                    records.append(record)
                            except (ValueError, TypeError):
                                records.append(record)
                        else:
                            records.append(record)
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue

    return records


def compute_summary(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute summary statistics from performance records."""
    by_stage: Dict[str, List[Dict[str, Any]]] = defaultdict(list)

    for r in records:
        stage = r.get("stage", "unknown")
        by_stage[stage].append(r)

    summary: Dict[str, Any] = {
        "total_records": len(records),
        "unique_stages": len(by_stage),
        "stages": {},
        "overall": {},
    }

    all_latencies = []
    all_costs = []
    all_success = []
    all_quality = []
    all_schema_compliant = []
    all_schema_total = []

    for stage, stage_records in sorted(by_stage.items()):
        latencies = [r.get("latency_ms", 0) for r in stage_records]
        costs = [r.get("cost_usd", 0) for r in stage_records]
        success = [r.get("success", False) for r in stage_records]
        quality = [
            r.get("quality_score")
            for r in stage_records
            if r.get("quality_score") is not None
        ]
        schema_compliance_vals = [
            r.get("schema_compliance")
            for r in stage_records
            if r.get("schema_compliance") is not None
        ]

        # Calculate schema compliance rate
        schema_compliant = [
            r.get("schema_compliance") is True
            for r in stage_records
            if r.get("schema_compliance") is not None
        ]
        schema_compliant_count = sum(schema_compliant)
        denom = len(schema_compliant)
        schema_compliance_rate = (
            schema_compliant_count / denom if schema_compliant else None
        )

        latency_avg = sum(latencies) / len(latencies) if latencies else 0
        cost_avg = sum(costs) / len(costs) if costs else 0
        success_rate = sum(success) / len(success) if success else 0
        quality_avg = sum(quality) / len(quality) if quality else None

        stage_summary = {
            "count": len(stage_records),
            "latency_avg_ms": latency_avg,
            "latency_max_ms": max(latencies) if latencies else 0,
            "latency_min_ms": min(latencies) if latencies else 0,
            "cost_total_usd": sum(costs),
            "cost_avg_usd": cost_avg,
            "success_rate": success_rate,
            "quality_avg": quality_avg,
            "schema_compliance_rate": schema_compliance_rate,
            "providers": list(set(r.get("provider", "unknown") for r in stage_records)),
        }

        summary["stages"][stage] = stage_summary
        all_latencies.extend(latencies)
        all_costs.extend(costs)
        all_success.extend(success)
        all_quality.extend(quality)
        all_schema_compliant.extend([v for v in schema_compliance_vals if v is True])
        all_schema_total.extend([v for v in schema_compliance_vals if v is not None])

    if all_latencies:
        overall_latency = sum(all_latencies) / len(all_latencies)
        overall_cost = sum(all_costs)
        overall_success = sum(all_success) / len(all_success) if all_success else 0
        overall_quality = sum(all_quality) / len(all_quality) if all_quality else None
        overall_compliance = (
            sum(all_schema_compliant) / len(all_schema_total)
            if all_schema_total
            else None
        )
        summary["overall"] = {
            "latency_avg_ms": overall_latency,
            "cost_total_usd": overall_cost,
            "success_rate": overall_success,
            "quality_avg": overall_quality,
            "schema_compliance_rate": overall_compliance,
        }

    return summary


def detect_anomalies(summary: Dict[str, Any]) -> List[str]:
    """Detect anomalies / points of concern in the data."""
    anomalies = []

    for stage, s in summary.get("stages", {}).items():
        success_rate = s["success_rate"]
        if success_rate < 0.8:
            msg = f"⚠️  {stage}: Low success rate ({success_rate:.0%})"
            anomalies.append(msg)
        quality_avg = s.get("quality_avg")
        if quality_avg is not None and quality_avg < 0.6:
            msg = f"⚠️  {stage}: Low quality score ({quality_avg:.2f})"
            anomalies.append(msg)
        schema_compliance_rate = s.get("schema_compliance_rate")
        if schema_compliance_rate is not None and schema_compliance_rate < 0.99:
            msg = (
                f"⚠️  {stage}: Low schema compliance rate "
                f"({schema_compliance_rate:.2%})"
            )
            anomalies.append(msg)
        if s["count"] == 0:
            anomalies.append(f"ℹ️  {stage}: No data recorded")

    return anomalies


def format_dashboard(summary: Dict[str, Any], hours: int) -> str:
    """Format summary as a human-readable dashboard."""
    lines = []
    lines.append("=" * 60)
    lines.append("  Audiobook Studio — 性能监控面板")
    lines.append(
        f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  |  " f"回溯 {hours}h"
    )
    lines.append("=" * 60)
    lines.append("")

    overall = summary.get("overall", {})
    lines.append("📊  全局概览")
    lines.append("-" * 40)
    lines.append(f"  总记录数:      {summary['total_records']}")
    lines.append(f"  独立阶段数:    {summary['unique_stages']}")
    lines.append(f"  平均延迟:      {overall.get('latency_avg_ms', 0):.0f} ms")
    lines.append(f"  总成本:        ${overall.get('cost_total_usd', 0):.4f}")
    lines.append(f"  成功率:        {overall.get('success_rate', 0):.0%}")
    if overall.get("quality_avg") is not None:
        lines.append(f"  平均质量分:    {overall['quality_avg']:.2f}")
    if overall.get("schema_compliance_rate") is not None:
        lines.append(f"  平均合规率:    {overall['schema_compliance_rate']:.2%}")
    lines.append("")

    lines.append("📈  分阶段详情")
    lines.append("-" * 80)
    header = (
        f"{'阶段':<25} {'次数':>6} {'延迟(ms)':>12} "
        f"{'成本($)':>10} {'成功率':>8} {'质量分':>8} {'合规率':>8}"
    )
    lines.append(header)
    lines.append("-" * 80)

    for stage, s in summary.get("stages", {}).items():
        stage_label = stage[:24]
        quality_avg = s.get("quality_avg")
        quality_str = f"{quality_avg:.2f}" if quality_avg is not None else "N/A"
        schema_compliance = s.get("schema_compliance_rate")
        schema_str = (
            f"{schema_compliance:.2%}" if schema_compliance is not None else "N/A"
        )
        count = s["count"]
        lat_avg = s["latency_avg_ms"]
        cost_total = s["cost_total_usd"]
        success_rate = s["success_rate"]
        lat_str = f"{lat_avg:>8.0f}ms"
        cost_str = f"{cost_total:>8.4f}"
        succ_str = f"{success_rate:>7.0%}"
        line = f"{stage_label:<25} {count:>6} {lat_str} "
        line += f"{cost_str} {succ_str} {quality_str:>8} {schema_str:>8}"
        lines.append(line)

    lines.append("")

    # Anomalies
    anomalies = detect_anomalies(summary)
    if anomalies:
        lines.append("🔔  关注点")
        lines.append("-" * 40)
        for a in anomalies:
            lines.append(f"  {a}")
        lines.append("")

    # Provider usage
    all_providers = set()
    for s in summary.get("stages", {}).values():
        all_providers.update(s.get("providers", []))
    if all_providers:
        lines.append("⚙️  使用的 Provider")
        lines.append("-" * 40)
        for p in sorted(all_providers):
            lines.append(f"  • {p}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def main():
    args = parse_args()

    # Collect from structured JSON logs
    logs_dir = Path(args.logs_dir)
    log_records = collect_logs(logs_dir, args.hours)

    summary = compute_summary(log_records)

    if args.json:
        logger.info(json.dumps(summary, indent=2, ensure_ascii=False))
    else:
        logger.info(format_dashboard(summary, args.hours))

    # Return exit code based on health
    anomalies = detect_anomalies(summary)
    if any("Low success rate" in a or "Low quality" in a for a in anomalies):
        sys.exit(1)


# ==================== 补全缺失的看板类定义 ====================
class MonitoringDashboard:
    def __init__(self, *args, **kwargs):
        pass

    def start(self, *args, **kwargs):
        pass

    def run(self, *args, **kwargs):
        pass


# ============================================================


if __name__ == "__main__":
    main()

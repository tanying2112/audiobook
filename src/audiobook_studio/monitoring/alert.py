#!/usr/bin/env python3
"""
Audiobook Studio — 异常告警系统
========================================
监控关键指标并在异常时发送通知。
Usage:
    python scripts/alert.py [--hours 1] [--check-only]

监控项:
1. 格式合规率 (schema compliance) < 99% → 告警
2. 降级使用率 (fallback rate) > 5% → 告警
3. 日均成本超阈值 → 告警
4. 自迭代系统健康检查 → 告警
支持钉钉和Slack webhook通知
"""

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ==================== 补全模块所需的类定义 ====================
class AlertLevel(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertConfig(BaseModel):
    threshold: float = 0.8
    enabled: bool = True


class AlertRecord(BaseModel):
    level: AlertLevel
    message: str
    timestamp: float
    context: Optional[Dict[str, Any]] = None


class AlertManager:
    def __init__(self, config: Optional[AlertConfig] = None):
        self.config = config or AlertConfig()

    def trigger_alert(self, level: AlertLevel, message: str, context: Optional[Dict[str, Any]] = None):
        logger.info(f"[{level}] ALERT: {message} | Context: {context}")
        return True


# ============================================================


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audiobook Studio 异常告警系统")
    parser.add_argument(
        "--hours",
        type=int,
        default=1,
        help="Lookback window in hours (default: 1)",
    )
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="Only check and print results, do not send alerts",
    )
    parser.add_argument(
        "--logs-dir",
        type=str,
        default="./logs",
        help="Path to structured JSON logs directory (default: ./logs)",
    )
    parser.add_argument(
        "--dingtalk-webhook",
        type=str,
        help="Dingtalk webhook URL (optional)",
    )
    parser.add_argument(
        "--slack-webhook",
        type=str,
        help="Slack webhook URL (optional)",
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


def collect_self_iteration_logs(logs_dir: Path, hours: int) -> List[Dict[str, Any]]:
    """Collect self-iteration feedback loop records from JSONL log files."""
    records = []
    cutoff = datetime.now() - timedelta(hours=hours)

    if not logs_dir.exists():
        return records

    # Look for self-iteration specific log files
    for log_file in sorted(logs_dir.glob("*_self_iteration.jsonl")):
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


def compute_self_iteration_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute metrics for self-iteration alerting."""
    if not records:
        return {
            "total_iterations": 0,
            "promotion_rate": 0.0,
            "avg_feedback_per_iteration": 0.0,
            "system_health_score": 100.0,
            "alerts": [],
        }

    total_iterations = len(records)

    # Promotion rate
    promoted_count = sum(1 for r in records if r.get("promoted", False))
    promotion_rate = promoted_count / total_iterations if total_iterations > 0 else 0.0

    # Average feedback per iteration
    feedback_counts = [r.get("feedback_count", 0) for r in records]
    avg_feedback = sum(feedback_counts) / len(feedback_counts) if feedback_counts else 0.0

    # System health score (from canary validation)
    health_scores = [r.get("system_health_score", 100) for r in records if "system_health_score" in r]
    avg_health = sum(health_scores) / len(health_scores) if health_scores else 100.0

    # Check alert conditions
    alerts = []

    # 1. Low promotion rate (might indicate quality issues)
    if promotion_rate < 0.3 and total_iterations >= 5:
        alerts.append(
            {
                "type": "low_promotion_rate",
                "severity": "warning",
                "message": f"自迭代提升率过低: {promotion_rate:.1%} (近 {total_iterations} 次迭代)",
                "value": promotion_rate,
                "threshold": 0.3,
            }
        )

    # 2. No feedback being collected
    if avg_feedback < 1.0:
        alerts.append(
            {
                "type": "insufficient_feedback",
                "severity": "warning",
                "message": f"反馈收集不足: 平均 {avg_feedback:.1f} 条/次迭代",
                "value": avg_feedback,
                "threshold": 1.0,
            }
        )

    # 3. System health degradation
    if avg_health < 50:
        alerts.append(
            {
                "type": "system_health_degraded",
                "severity": "critical" if avg_health < 30 else "warning",
                "message": f"系统健康度下降: {avg_health:.1f}/100 (阈值: ≥50)",
                "value": avg_health,
                "threshold": 50,
            }
        )

    return {
        "total_iterations": total_iterations,
        "promotion_rate": promotion_rate,
        "avg_feedback_per_iteration": avg_feedback,
        "system_health_score": avg_health,
        "alerts": alerts,
    }


def compute_metrics(records: List[Dict[str, Any]], hours: float = 1.0) -> Dict[str, Any]:
    """Compute metrics for alerting."""
    if not records:
        return {
            "total_records": 0,
            "schema_compliance_rate": 0.0,
            "fallback_rate": 0.0,
            "total_cost_usd": 0.0,
            "alerts": [],
        }

    total_records = len(records)

    # Schema compliance rate
    schema_compliant = sum(1 for r in records if r.get("schema_compliance", False) is True)
    schema_compliance_rate = schema_compliant / total_records if total_records > 0 else 0.0

    # Fallback rate (heuristic_fallback or fallback in model name)
    fallback_count = sum(
        1 for r in records if "fallback" in r.get("model", "").lower() or "heuristic" in r.get("model", "").lower()
    )
    fallback_rate = fallback_count / total_records if total_records > 0 else 0.0

    # Total cost
    total_cost = sum(r.get("cost_usd", 0.0) for r in records)

    # Check alert conditions
    alerts = []

    # 1. Schema compliance < 99%
    if schema_compliance_rate < 0.99:
        alerts.append(
            {
                "type": "schema_compliance",
                "severity": "warning" if schema_compliance_rate >= 0.95 else "critical",
                "message": f"LLM格式合规率过低: {schema_compliance_rate:.2%} (阈值: ≥99%)",
                "value": schema_compliance_rate,
                "threshold": 0.99,
            }
        )

    # 2. Fallback rate > 5%
    if fallback_rate > 0.05:
        alerts.append(
            {
                "type": "fallback_rate",
                "severity": "warning" if fallback_rate <= 0.10 else "critical",
                "message": f"LLM降级使用率过高: {fallback_rate:.2%} (阈值: ≤5%)",
                "value": fallback_rate,
                "threshold": 0.05,
            }
        )

    # 3. Cost check (would need daily aggregate, simplified here)
    # In production, this would check against daily limit from config
    # For now, we'll check if hourly cost extrapolated exceeds reasonable limits
    hourly_cost = total_cost
    estimated_daily_cost = hourly_cost * (24 / max(hours, 1))
    daily_limit = 10.0  # From config/llm_providers.yaml

    if estimated_daily_cost > daily_limit:
        alerts.append(
            {
                "type": "cost_overrun",
                "severity": ("warning" if estimated_daily_cost <= daily_limit * 1.5 else "critical"),
                "message": f"预估日成本超阈值: ${estimated_daily_cost:.2f} (阈值: ≤${daily_limit})",
                "value": estimated_daily_cost,
                "threshold": daily_limit,
            }
        )

    return {
        "total_records": total_records,
        "schema_compliance_rate": schema_compliance_rate,
        "fallback_rate": fallback_rate,
        "total_cost_usd": total_cost,
        "estimated_daily_cost": estimated_daily_cost,
        "alerts": alerts,
    }


def send_dingtalk_alert(webhook_url: str, message: str) -> bool:
    """Send alert to Dingtalk via webhook."""
    try:
        payload = {
            "msgtype": "text",
            "text": {"content": f"🚨 Audiobook Studio 告警\n{message}"},
        }
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to send Dingtalk alert: {e}")
        return False


def send_slack_alert(webhook_url: str, message: str) -> bool:
    """Send alert to Slack via webhook."""
    try:
        payload = {"text": f":warning: *Audiobook Studio 告警*\n{message}"}
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"Failed to send Slack alert: {e}")
        return False


def format_alert_message(metrics: Dict[str, Any]) -> str:
    """Format alert message for notification."""
    lines = [
        f"📊 监控周期: {metrics['total_records']} 条记录",
        f"📈 格式合规率: {metrics['schema_compliance_rate']:.2%}",
        f"🔄 降级使用率: {metrics['fallback_rate']:.2%}",
        f"💰 预估日成本: ${metrics['estimated_daily_cost']:.2f}",
        "",
        "⚠️ 触发的告警:",
    ]

    for alert in metrics["alerts"]:
        severity_emoji = "🔴" if alert["severity"] == "critical" else "🟡"
        lines.append(f"  {severity_emoji} {alert['message']}")

    return "\n".join(lines)


def main():
    args = parse_args()

    # Collect from structured JSON logs
    logs_dir = Path(args.logs_dir)
    log_records = collect_logs(logs_dir, args.hours)

    # Also collect self-iteration logs
    self_iteration_records = collect_self_iteration_logs(logs_dir, args.hours)

    # Combine all alerts
    all_alerts = []
    all_metrics = {}

    if log_records:
        metrics = compute_metrics(log_records)
        all_metrics["llm_metrics"] = metrics
        all_alerts.extend(metrics["alerts"])

    if self_iteration_records:
        si_metrics = compute_self_iteration_metrics(self_iteration_records)
        all_metrics["self_iteration_metrics"] = si_metrics
        all_alerts.extend(si_metrics["alerts"])

    if not log_records and not self_iteration_records:
        logger.warning("警告: 未找到性能记录数据")
        if args.check_only:
            logger.error(json.dumps({"error": "No data found"}, indent=2, ensure_ascii=False))
        return

    # Always print metrics
    logger.info("=== Audiobook Studio 异常检测 ===")
    logger.info(f"监控时间窗口: 最近 {args.hours} 小时")
    logger.info("")

    if "llm_metrics" in all_metrics:
        m = all_metrics["llm_metrics"]
        logger.info("--- LLM Pipeline Metrics ---")
        logger.info(f"总记录数: {m['total_records']}")
        logger.info(f"格式合规率: {m['schema_compliance_rate']:.2%} (阈值: ≥99.00%)")
        logger.info(f"降级使用率: {m['fallback_rate']:.2%} (阈值: ≤5.00%)")
        logger.info(f"当前小时成本: ${m['total_cost_usd']:.4f}")
        logger.info(f"预估日成本: ${m['estimated_daily_cost']:.2f} (阈值: ≤$10.00)")
        logger.info("")

    if "self_iteration_metrics" in all_metrics:
        m = all_metrics["self_iteration_metrics"]
        logger.info("--- Self-Iteration Metrics ---")
        logger.info(f"总迭代次数: {m['total_iterations']}")
        logger.info(f"提升通过率: {m['promotion_rate']:.1%} (阈值: ≥30%)")
        logger.info(f"平均反馈/迭代: {m['avg_feedback_per_iteration']:.1f} (阈值: ≥1.0)")
        logger.info(f"系统健康度: {m['system_health_score']:.1f}/100 (阈值: ≥50)")
        logger.info("")

    if all_alerts:
        logger.info("🚨 检测到异常:")
        for alert in all_alerts:
            severity = alert["severity"].upper()
            logger.info(f"  [{severity}] {alert['message']}")
        logger.info("")
    else:
        logger.info("✅ 所有指标正常")
        logger.info("")

    # Send alerts if not check-only and alerts exist
    if not args.check_only and all_alerts:
        # Format combined alert message
        alert_message_lines = ["=== Audiobook Studio 告警 ==="]

        if "llm_metrics" in all_metrics:
            m = all_metrics["llm_metrics"]
            alert_message_lines.extend(
                [
                    f"📊 LLM Pipeline: {m['total_records']} 条记录",
                    f"📈 格式合规率: {m['schema_compliance_rate']:.2%}",
                    f"🔄 降级使用率: {m['fallback_rate']:.2%}",
                    f"💰 预估日成本: ${m['estimated_daily_cost']:.2f}",
                ]
            )

        if "self_iteration_metrics" in all_metrics:
            m = all_metrics["self_iteration_metrics"]
            alert_message_lines.extend(
                [
                    f"🔄 自迭代: {m['total_iterations']} 次迭代",
                    f"📈 提升通过率: {m['promotion_rate']:.1%}",
                    f"💬 平均反馈/迭代: {m['avg_feedback_per_iteration']:.1f}",
                    f"🏥 系统健康度: {m['system_health_score']:.1f}/100",
                ]
            )

        alert_message_lines.append("")
        alert_message_lines.append("⚠️ 触发的告警:")
        for alert in all_alerts:
            severity_emoji = "🔴" if alert["severity"] == "critical" else "🟡"
            alert_message_lines.append(f"  {severity_emoji} {alert['message']}")

        alert_message = "\n".join(alert_message_lines)

        # Send to Dingtalk if webhook provided
        dingtalk_webhook = args.dingtalk_webhook or os.getenv("DINGTALK_WEBHOOK")
        if dingtalk_webhook:
            if send_dingtalk_alert(dingtalk_webhook, alert_message):
                logger.info("✅ Dingtalk告警已发送")
            else:
                logger.error("❌ Dingtalk告警发送失败")

        # Send to Slack if webhook provided
        slack_webhook = args.slack_webhook or os.getenv("SLACK_WEBHOOK")
        if slack_webhook:
            if send_slack_alert(slack_webhook, alert_message):
                logger.info("✅ Slack告警已发送")
            else:
                logger.error("❌ Slack告警发送失败")
    elif args.check_only:
        # Output JSON for programmatic consumption
        logger.info(json.dumps(all_metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

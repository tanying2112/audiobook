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
支持钉钉和Slack webhook通知
"""

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audiobook Studio 异常告警系统"
    )
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


def compute_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute metrics for alerting."""
    if not records:
        return {
            "total_records": 0,
            "schema_compliance_rate": 0.0,
            "fallback_rate": 0.0,
            "total_cost_usd": 0.0,
            "alerts": []
        }

    total_records = len(records)

    # Schema compliance rate
    schema_compliant = sum(
        1 for r in records
        if r.get("schema_compliance", False) is True
    )
    schema_compliance_rate = schema_compliant / total_records if total_records > 0 else 0.0

    # Fallback rate (heuristic_fallback or fallback in model name)
    fallback_count = sum(
        1 for r in records
        if "fallback" in r.get("model", "").lower()
           or "heuristic" in r.get("model", "").lower()
    )
    fallback_rate = fallback_count / total_records if total_records > 0 else 0.0

    # Total cost
    total_cost = sum(r.get("cost_usd", 0.0) for r in records)

    # Check alert conditions
    alerts = []

    # 1. Schema compliance < 99%
    if schema_compliance_rate < 0.99:
        alerts.append({
            "type": "schema_compliance",
            "severity": "warning" if schema_compliance_rate >= 0.95 else "critical",
            "message": f"LLM格式合规率过低: {schema_compliance_rate:.2%} (阈值: ≥99%)",
            "value": schema_compliance_rate,
            "threshold": 0.99
        })

    # 2. Fallback rate > 5%
    if fallback_rate > 0.05:
        alerts.append({
            "type": "fallback_rate",
            "severity": "warning" if fallback_rate <= 0.10 else "critical",
            "message": f"LLM降级使用率过高: {fallback_rate:.2%} (阈值: ≤5%)",
            "value": fallback_rate,
            "threshold": 0.05
        })

    # 3. Cost check (would need daily aggregate, simplified here)
    # In production, this would check against daily limit from config
    # For now, we'll check if hourly cost extrapolated exceeds reasonable limits
    hourly_cost = total_cost
    estimated_daily_cost = hourly_cost * (24 / max(hours, 1))
    daily_limit = 10.0  # From config/llm_providers.yaml

    if estimated_daily_cost > daily_limit:
        alerts.append({
            "type": "cost_overrun",
            "severity": "warning" if estimated_daily_cost <= daily_limit * 1.5 else "critical",
            "message": f"预估日成本超阈值: ${estimated_daily_cost:.2f} (阈值: ≤${daily_limit})",
            "value": estimated_daily_cost,
            "threshold": daily_limit
        })

    return {
        "total_records": total_records,
        "schema_compliance_rate": schema_compliance_rate,
        "fallback_rate": fallback_rate,
        "total_cost_usd": total_cost,
        "estimated_daily_cost": estimated_daily_cost,
        "alerts": alerts
    }


def send_dingtalk_alert(webhook_url: str, message: str) -> bool:
    """Send alert to Dingtalk via webhook."""
    try:
        payload = {
            "msgtype": "text",
            "text": {
                "content": f"🚨 Audiobook Studio 告警\n{message}"
            }
        }
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send Dingtalk alert: {e}", file=sys.stderr)
        return False


def send_slack_alert(webhook_url: str, message: str) -> bool:
    """Send alert to Slack via webhook."""
    try:
        payload = {
            "text": f":warning: *Audiobook Studio 告警*\n{message}"
        }
        response = requests.post(webhook_url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send Slack alert: {e}", file=sys.stderr)
        return False


def format_alert_message(metrics: Dict[str, Any]) -> str:
    """Format alert message for notification."""
    lines = [
        f"📊 监控周期: {metrics['total_records']} 条记录",
        f"📈 格式合规率: {metrics['schema_compliance_rate']:.2%}",
        f"🔄 降级使用率: {metrics['fallback_rate']:.2%}",
        f"💰 预估日成本: ${metrics['estimated_daily_cost']:.2f}",
        "",
        "⚠️ 触发的告警:"
    ]

    for alert in metrics["alerts"]:
        severity_emoji = "🔴" if alert["severity"] == "critical" else "🟡"
        lines.append(
            f"  {severity_emoji} {alert['message']}"
        )

    return "\n".join(lines)


def main():
    args = parse_args()

    # Collect from structured JSON logs
    logs_dir = Path(args.logs_dir)
    log_records = collect_logs(logs_dir, args.hours)

    if not log_records:
        print("警告: 未找到性能记录数据")
        if args.check_only:
            print(json.dumps({"error": "No data found"}, indent=2, ensure_ascii=False))
        return

    metrics = compute_metrics(log_records)

    # Always print metrics
    print("=== Audiobook Studio 异常检测 ===")
    print(f"监控时间窗口: 最近 {args.hours} 小时")
    print(f"总记录数: {metrics['total_records']}")
    print(f"格式合规率: {metrics['schema_compliance_rate']:.2%} (阈值: ≥99.00%)")
    print(f"降级使用率: {metrics['fallback_rate']:.2%} (阈值: ≤5.00%)")
    print(f"当前小时成本: ${metrics['total_cost_usd']:.4f}")
    print(f"预估日成本: ${metrics['estimated_daily_cost']:.2f} (阈值: ≤$10.00)")
    print()

    if metrics["alerts"]:
        print("🚨 检测到异常:")
        for alert in metrics["alerts"]:
            severity = alert["severity"].upper()
            print(f"  [{severity}] {alert['message']}")
        print()
    else:
        print("✅ 所有指标正常")
        print()

    # Send alerts if not check-only and alerts exist
    if not args.check_only and metrics["alerts"]:
        alert_message = format_alert_message(metrics)

        # Send to Dingtalk if webhook provided
        dingtalk_webhook = args.dingtalk_webhook or os.getenv("DINGTALK_WEBHOOK")
        if dingtalk_webhook:
            if send_dingtalk_alert(dingtalk_webhook, alert_message):
                print("✅ Dingtalk告警已发送")
            else:
                print("❌ Dingtalk告警发送失败")

        # Send to Slack if webhook provided
        slack_webhook = args.slack_webhook or os.getenv("SLACK_WEBHOOK")
        if slack_webhook:
            if send_slack_alert(slack_webhook, alert_message):
                print("✅ Slack告警已发送")
            else:
                print("❌ Slack告警发送失败")
    elif args.check_only:
        # Output JSON for programmatic consumption
        print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
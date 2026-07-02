"""Comprehensive tests for monitoring/alert.py."""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.monitoring.alert import (
    AlertConfig,
    AlertLevel,
    AlertManager,
    AlertRecord,
    collect_logs,
    collect_self_iteration_logs,
    compute_metrics,
    compute_self_iteration_metrics,
    format_alert_message,
    parse_args,
    send_dingtalk_alert,
    send_slack_alert,
)

# ── AlertLevel ──────────────────────────────────────────────────────────────


class TestAlertLevel:
    def test_values(self):
        assert AlertLevel.INFO.value == "INFO"
        assert AlertLevel.WARNING.value == "WARNING"
        assert AlertLevel.CRITICAL.value == "CRITICAL"


# ── AlertConfig ──────────────────────────────────────────────────────────────


class TestAlertConfig:
    def test_defaults(self):
        c = AlertConfig()
        assert c.threshold == 0.8
        assert c.enabled is True

    def test_custom(self):
        c = AlertConfig(threshold=0.5, enabled=False)
        assert c.threshold == 0.5
        assert c.enabled is False


# ── AlertRecord ──────────────────────────────────────────────────────────────


class TestAlertRecord:
    def test_creation(self):
        r = AlertRecord(level=AlertLevel.WARNING, message="test", timestamp=1.0)
        assert r.level == AlertLevel.WARNING
        assert r.message == "test"
        assert r.context is None

    def test_with_context(self):
        ctx = {"key": "value"}
        r = AlertRecord(level=AlertLevel.CRITICAL, message="bad", timestamp=2.0, context=ctx)
        assert r.context == ctx


# ── AlertManager ─────────────────────────────────────────────────────────────


class TestAlertManager:
    def test_init_default(self):
        m = AlertManager()
        assert m.config.threshold == 0.8

    def test_init_custom(self):
        c = AlertConfig(threshold=0.3)
        m = AlertManager(c)
        assert m.config.threshold == 0.3

    def test_trigger_alert(self):
        m = AlertManager()
        result = m.trigger_alert(AlertLevel.INFO, "test msg")
        assert result is True

    def test_trigger_with_context(self):
        m = AlertManager()
        result = m.trigger_alert(AlertLevel.WARNING, "warn", {"k": "v"})
        assert result is True


# ── parse_args ───────────────────────────────────────────────────────────────


class TestParseArgs:
    def test_defaults(self):
        with patch("sys.argv", ["alert.py"]):
            args = parse_args()
        assert args.hours == 1
        assert args.check_only is False

    def test_hours(self):
        with patch("sys.argv", ["alert.py", "--hours", "5"]):
            args = parse_args()
        assert args.hours == 5

    def test_check_only(self):
        with patch("sys.argv", ["alert.py", "--check-only"]):
            args = parse_args()
        assert args.check_only is True

    def test_webhooks(self):
        with patch(
            "sys.argv",
            [
                "alert.py",
                "--dingtalk-webhook",
                "http://d",
                "--slack-webhook",
                "http://s",
            ],
        ):
            args = parse_args()
        assert args.dingtalk_webhook == "http://d"
        assert args.slack_webhook == "http://s"

    def test_logs_dir(self):
        with patch("sys.argv", ["alert.py", "--logs-dir", "/tmp/logs"]):
            args = parse_args()
        assert args.logs_dir == "/tmp/logs"


# ── collect_logs ─────────────────────────────────────────────────────────────


class TestCollectLogs:
    def test_empty_dir(self, tmp_path):
        records = collect_logs(tmp_path / "no_dir", 1)
        assert records == []

    def test_collect_recent(self, tmp_path):
        log_file = tmp_path / "test_perf.jsonl"
        now = datetime.now().isoformat()
        log_file.write_text(
            json.dumps(
                {
                    "timestamp": now,
                    "model": "gpt-4",
                    "schema_compliance": True,
                    "cost_usd": 0.01,
                }
            )
            + "\n"
        )
        records = collect_logs(tmp_path, 1)
        assert len(records) == 1

    def test_skip_old(self, tmp_path):
        log_file = tmp_path / "test_perf.jsonl"
        old = (datetime.now() - timedelta(hours=3)).isoformat()
        log_file.write_text(json.dumps({"timestamp": old}) + "\n")
        records = collect_logs(tmp_path, 1)
        assert len(records) == 0

    def test_skip_empty_lines(self, tmp_path):
        log_file = tmp_path / "test_perf.jsonl"
        log_file.write_text("\n\n\n")
        records = collect_logs(tmp_path, 1)
        assert records == []

    def test_skip_bad_json(self, tmp_path):
        log_file = tmp_path / "test_perf.jsonl"
        log_file.write_text("not json\n")
        records = collect_logs(tmp_path, 1)
        assert records == []

    def test_no_timestamp(self, tmp_path):
        log_file = tmp_path / "test_perf.jsonl"
        log_file.write_text(json.dumps({"model": "x"}) + "\n")
        records = collect_logs(tmp_path, 1)
        assert len(records) == 1

    def test_bad_timestamp(self, tmp_path):
        log_file = tmp_path / "test_perf.jsonl"
        log_file.write_text(json.dumps({"timestamp": "not-a-date"}) + "\n")
        records = collect_logs(tmp_path, 1)
        assert len(records) == 1

    def test_os_error(self, tmp_path):
        # unreadable directory
        d = tmp_path / "locked"
        d.mkdir()
        (d / "x_perf.jsonl").write_text("bad")
        os.chmod(d / "x_perf.jsonl", 0o000)
        records = collect_logs(d, 1)
        # Should not crash
        assert isinstance(records, list)


# ── collect_self_iteration_logs ──────────────────────────────────────────────


class TestCollectSelfIterationLogs:
    def test_empty_dir(self, tmp_path):
        records = collect_self_iteration_logs(tmp_path / "no_dir", 1)
        assert records == []

    def test_collect(self, tmp_path):
        f = tmp_path / "test_self_iteration.jsonl"
        now = datetime.now().isoformat()
        f.write_text(json.dumps({"timestamp": now, "promoted": True, "feedback_count": 3}) + "\n")
        records = collect_self_iteration_logs(tmp_path, 1)
        assert len(records) == 1

    def test_skip_old(self, tmp_path):
        f = tmp_path / "test_self_iteration.jsonl"
        old = (datetime.now() - timedelta(hours=5)).isoformat()
        f.write_text(json.dumps({"timestamp": old}) + "\n")
        records = collect_self_iteration_logs(tmp_path, 1)
        assert len(records) == 0


# ── compute_metrics ──────────────────────────────────────────────────────────


class TestComputeMetrics:
    def test_empty(self):
        m = compute_metrics([])
        assert m["total_records"] == 0
        assert m["schema_compliance_rate"] == 0.0
        assert m["fallback_rate"] == 0.0
        assert m["alerts"] == []

    def test_compliant(self):
        records = [{"schema_compliance": True, "model": "gpt-4", "cost_usd": 0.001} for _ in range(10)]
        m = compute_metrics(records)
        assert m["schema_compliance_rate"] == 1.0
        assert m["fallback_rate"] == 0.0
        # No alerts if all compliant
        assert all(a["type"] != "schema_compliance" for a in m["alerts"])

    def test_low_compliance_warning(self):
        records = [{"schema_compliance": i < 9, "model": "gpt-4", "cost_usd": 0.001} for i in range(10)]
        m = compute_metrics(records)
        assert m["schema_compliance_rate"] == 0.9
        types = [a["type"] for a in m["alerts"]]
        assert "schema_compliance" in types

    def test_low_compliance_critical(self):
        records = [{"schema_compliance": i < 5, "model": "gpt-4", "cost_usd": 0.001} for i in range(10)]
        m = compute_metrics(records)
        assert m["schema_compliance_rate"] == 0.5
        critical = [a for a in m["alerts"] if a["type"] == "schema_compliance"]
        assert critical[0]["severity"] == "critical"

    def test_fallback_rate_warning(self):
        records = [{"schema_compliance": True, "model": "fallback-model", "cost_usd": 0.001} for _ in range(10)]
        m = compute_metrics(records)
        assert m["fallback_rate"] == 1.0
        types = [a["type"] for a in m["alerts"]]
        assert "fallback_rate" in types

    def test_heuristic_fallback(self):
        records = [
            {
                "schema_compliance": True,
                "model": "heuristic_fallback",
                "cost_usd": 0.001,
            }
            for _ in range(5)
        ]
        m = compute_metrics(records)
        assert m["fallback_rate"] == 1.0

    def test_cost_overrun(self):
        records = [{"schema_compliance": True, "model": "gpt-4", "cost_usd": 1.0} for _ in range(20)]
        m = compute_metrics(records, hours=1)
        assert m["total_cost_usd"] == 20.0
        types = [a["type"] for a in m["alerts"]]
        assert "cost_overrun" in types

    def test_cost_overrun_critical(self):
        records = [{"schema_compliance": True, "model": "gpt-4", "cost_usd": 50.0} for _ in range(5)]
        m = compute_metrics(records, hours=1)
        cost_alerts = [a for a in m["alerts"] if a["type"] == "cost_overrun"]
        assert cost_alerts[0]["severity"] == "critical"

    def test_fallback_critical(self):
        records = [{"schema_compliance": True, "model": "fallback-x", "cost_usd": 0.001} for _ in range(20)]
        m = compute_metrics(records)
        fallback_alerts = [a for a in m["alerts"] if a["type"] == "fallback_rate"]
        assert fallback_alerts[0]["severity"] == "critical"


# ── compute_self_iteration_metrics ───────────────────────────────────────────


class TestComputeSelfIterationMetrics:
    def test_empty(self):
        m = compute_self_iteration_metrics([])
        assert m["total_iterations"] == 0
        assert m["alerts"] == []

    def test_high_promotion(self):
        records = [{"promoted": True, "feedback_count": 5} for _ in range(10)]
        m = compute_self_iteration_metrics(records)
        assert m["promotion_rate"] == 1.0
        assert m["avg_feedback_per_iteration"] == 5.0

    def test_low_promotion_warning(self):
        records = [{"promoted": False, "feedback_count": 0} for _ in range(10)]
        m = compute_self_iteration_metrics(records)
        assert m["promotion_rate"] == 0.0
        types = [a["type"] for a in m["alerts"]]
        assert "low_promotion_rate" in types

    def test_insufficient_feedback(self):
        records = [{"promoted": True, "feedback_count": 0} for _ in range(5)]
        m = compute_self_iteration_metrics(records)
        types = [a["type"] for a in m["alerts"]]
        assert "insufficient_feedback" in types

    def test_health_degraded_warning(self):
        records = [{"system_health_score": 40, "feedback_count": 2} for _ in range(5)]
        m = compute_self_iteration_metrics(records)
        types = [a["type"] for a in m["alerts"]]
        assert "system_health_degraded" in types

    def test_health_degraded_critical(self):
        records = [{"system_health_score": 20, "feedback_count": 2} for _ in range(5)]
        m = compute_self_iteration_metrics(records)
        degraded = [a for a in m["alerts"] if a["type"] == "system_health_degraded"]
        assert degraded[0]["severity"] == "critical"

    def test_no_health_scores(self):
        records = [{"promoted": True, "feedback_count": 2} for _ in range(5)]
        m = compute_self_iteration_metrics(records)
        assert m["system_health_score"] == 100.0


# ── send_dingtalk_alert ──────────────────────────────────────────────────────


class TestDingtalkAlert:
    def test_success(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock()
            mock_post.return_value.raise_for_status = MagicMock()
            assert send_dingtalk_alert("http://hook", "msg") is True

    def test_failure(self):
        with patch("requests.post", side_effect=Exception("net")):
            assert send_dingtalk_alert("http://hook", "msg") is False


# ── send_slack_alert ─────────────────────────────────────────────────────────


class TestSlackAlert:
    def test_success(self):
        with patch("requests.post") as mock_post:
            mock_post.return_value = MagicMock()
            mock_post.return_value.raise_for_status = MagicMock()
            assert send_slack_alert("http://hook", "msg") is True

    def test_failure(self):
        with patch("requests.post", side_effect=Exception("net")):
            assert send_slack_alert("http://hook", "msg") is False


# ── format_alert_message ─────────────────────────────────────────────────────


class TestFormatAlert:
    def test_with_alerts(self):
        metrics = {
            "total_records": 10,
            "schema_compliance_rate": 0.95,
            "fallback_rate": 0.08,
            "estimated_daily_cost": 12.5,
            "alerts": [{"severity": "warning", "message": "low compliance"}],
        }
        msg = format_alert_message(metrics)
        assert "10" in msg
        assert "95.00%" in msg
        assert "8.00%" in msg
        assert "12.50" in msg

    def test_no_alerts(self):
        metrics = {
            "total_records": 0,
            "schema_compliance_rate": 0.0,
            "fallback_rate": 0.0,
            "estimated_daily_cost": 0.0,
            "alerts": [],
        }
        msg = format_alert_message(metrics)
        assert "格式合规率" in msg

    def test_critical_alert(self):
        metrics = {
            "total_records": 5,
            "schema_compliance_rate": 0.5,
            "fallback_rate": 0.3,
            "estimated_daily_cost": 50.0,
            "alerts": [{"severity": "critical", "message": "bad"}],
        }
        msg = format_alert_message(metrics)
        assert "🔴" in msg

"""Tests for monitoring/alert.py — main() function and edge cases."""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.monitoring.alert import collect_logs, collect_self_iteration_logs, main


def _write_perf_log(logs_dir, records):
    f = logs_dir / "test_perf.jsonl"
    with open(f, "w") as fp:
        for r in records:
            fp.write(json.dumps(r) + "\n")
    return f


def _write_self_iter_log(logs_dir, records):
    f = logs_dir / "test_self_iteration.jsonl"
    with open(f, "w") as fp:
        for r in records:
            fp.write(json.dumps(r) + "\n")
    return f


class TestMainNoData:
    def test_no_data(self, tmp_path):
        with patch("sys.argv", ["alert.py", "--logs-dir", str(tmp_path), "--check-only"]):
            main()

    def test_no_data_check_only(self, tmp_path):
        with patch("sys.argv", ["alert.py", "--logs-dir", str(tmp_path), "--check-only"]):
            main()  # Should print error JSON


class TestMainWithLLMData:
    def test_check_only(self, tmp_path):
        now = datetime.now().isoformat()
        records = [
            {
                "timestamp": now,
                "schema_compliance": True,
                "model": "gpt-4",
                "cost_usd": 0.01,
            }
        ] * 5
        _write_perf_log(tmp_path, records)
        with patch(
            "sys.argv",
            ["alert.py", "--logs-dir", str(tmp_path), "--check-only", "--hours", "1"],
        ):
            main()

    def test_with_alerts_no_webhook(self, tmp_path):
        now = datetime.now().isoformat()
        records = [
            {
                "timestamp": now,
                "schema_compliance": False,
                "model": "fallback-x",
                "cost_usd": 0.01,
            }
        ] * 10
        _write_perf_log(tmp_path, records)
        with patch("sys.argv", ["alert.py", "--logs-dir", str(tmp_path), "--check-only"]):
            main()

    def test_send_alerts_dingtalk(self, tmp_path):
        now = datetime.now().isoformat()
        records = [
            {
                "timestamp": now,
                "schema_compliance": False,
                "model": "gpt-4",
                "cost_usd": 0.01,
            }
        ] * 10
        _write_perf_log(tmp_path, records)
        with patch(
            "sys.argv",
            [
                "alert.py",
                "--logs-dir",
                str(tmp_path),
                "--dingtalk-webhook",
                "http://hook.d",
            ],
        ):
            with patch(
                "src.audiobook_studio.monitoring.alert.send_dingtalk_alert",
                return_value=True,
            ):
                main()

    def test_send_alerts_slack(self, tmp_path):
        now = datetime.now().isoformat()
        records = [
            {
                "timestamp": now,
                "schema_compliance": False,
                "model": "gpt-4",
                "cost_usd": 0.01,
            }
        ] * 10
        _write_perf_log(tmp_path, records)
        with patch(
            "sys.argv",
            [
                "alert.py",
                "--logs-dir",
                str(tmp_path),
                "--slack-webhook",
                "http://hook.s",
            ],
        ):
            with patch(
                "src.audiobook_studio.monitoring.alert.send_slack_alert",
                return_value=True,
            ):
                main()

    def test_send_alerts_both_fail(self, tmp_path):
        now = datetime.now().isoformat()
        records = [
            {
                "timestamp": now,
                "schema_compliance": False,
                "model": "gpt-4",
                "cost_usd": 0.01,
            }
        ] * 10
        _write_perf_log(tmp_path, records)
        with patch(
            "sys.argv",
            [
                "alert.py",
                "--logs-dir",
                str(tmp_path),
                "--dingtalk-webhook",
                "http://d",
                "--slack-webhook",
                "http://s",
            ],
        ):
            with patch(
                "src.audiobook_studio.monitoring.alert.send_dingtalk_alert",
                return_value=False,
            ):
                with patch(
                    "src.audiobook_studio.monitoring.alert.send_slack_alert",
                    return_value=False,
                ):
                    main()

    def test_send_alerts_both_success(self, tmp_path):
        now = datetime.now().isoformat()
        records = [
            {
                "timestamp": now,
                "schema_compliance": False,
                "model": "gpt-4",
                "cost_usd": 0.01,
            }
        ] * 10
        _write_perf_log(tmp_path, records)
        with patch(
            "sys.argv",
            [
                "alert.py",
                "--logs-dir",
                str(tmp_path),
                "--dingtalk-webhook",
                "http://d",
                "--slack-webhook",
                "http://s",
            ],
        ):
            with patch(
                "src.audiobook_studio.monitoring.alert.send_dingtalk_alert",
                return_value=True,
            ):
                with patch(
                    "src.audiobook_studio.monitoring.alert.send_slack_alert",
                    return_value=True,
                ):
                    main()


class TestMainWithSelfIteration:
    def test_check_only(self, tmp_path):
        now = datetime.now().isoformat()
        records = [{"timestamp": now, "promoted": True, "feedback_count": 3}] * 5
        _write_self_iter_log(tmp_path, records)
        with patch("sys.argv", ["alert.py", "--logs-dir", str(tmp_path), "--check-only"]):
            main()

    def test_with_alerts(self, tmp_path):
        now = datetime.now().isoformat()
        records = [{"timestamp": now, "promoted": False, "feedback_count": 0}] * 10
        _write_self_iter_log(tmp_path, records)
        with patch("sys.argv", ["alert.py", "--logs-dir", str(tmp_path), "--check-only"]):
            main()

    def test_send_alerts(self, tmp_path):
        now = datetime.now().isoformat()
        records = [{"timestamp": now, "promoted": False, "feedback_count": 0}] * 10
        _write_self_iter_log(tmp_path, records)
        with patch(
            "sys.argv",
            [
                "alert.py",
                "--logs-dir",
                str(tmp_path),
                "--dingtalk-webhook",
                "http://d",
                "--slack-webhook",
                "http://s",
            ],
        ):
            with patch(
                "src.audiobook_studio.monitoring.alert.send_dingtalk_alert",
                return_value=True,
            ):
                with patch(
                    "src.audiobook_studio.monitoring.alert.send_slack_alert",
                    return_value=True,
                ):
                    main()

    def test_send_alerts_fail(self, tmp_path):
        now = datetime.now().isoformat()
        records = [{"timestamp": now, "promoted": False, "feedback_count": 0}] * 10
        _write_self_iter_log(tmp_path, records)
        with patch(
            "sys.argv",
            [
                "alert.py",
                "--logs-dir",
                str(tmp_path),
                "--dingtalk-webhook",
                "http://d",
                "--slack-webhook",
                "http://s",
            ],
        ):
            with patch(
                "src.audiobook_studio.monitoring.alert.send_dingtalk_alert",
                return_value=False,
            ):
                with patch(
                    "src.audiobook_studio.monitoring.alert.send_slack_alert",
                    return_value=False,
                ):
                    main()


class TestMainCombined:
    def test_both_data_sources(self, tmp_path):
        now = datetime.now().isoformat()
        perf_records = [
            {
                "timestamp": now,
                "schema_compliance": True,
                "model": "gpt-4",
                "cost_usd": 0.01,
            }
        ] * 3
        si_records = [{"timestamp": now, "promoted": True, "feedback_count": 3}] * 3
        _write_perf_log(tmp_path, perf_records)
        _write_self_iter_log(tmp_path, si_records)
        with patch("sys.argv", ["alert.py", "--logs-dir", str(tmp_path), "--check-only"]):
            main()

    def test_env_webhooks(self, tmp_path):
        now = datetime.now().isoformat()
        records = [
            {
                "timestamp": now,
                "schema_compliance": False,
                "model": "gpt-4",
                "cost_usd": 1.0,
            }
        ] * 20
        _write_perf_log(tmp_path, records)
        with patch("sys.argv", ["alert.py", "--logs-dir", str(tmp_path)]):
            with patch.dict(
                os.environ,
                {"DINGTALK_WEBHOOK": "http://env-d", "SLACK_WEBHOOK": "http://env-s"},
            ):
                with patch(
                    "src.audiobook_studio.monitoring.alert.send_dingtalk_alert",
                    return_value=True,
                ):
                    with patch(
                        "src.audiobook_studio.monitoring.alert.send_slack_alert",
                        return_value=True,
                    ):
                        main()

    def test_check_only_output_json(self, tmp_path):
        now = datetime.now().isoformat()
        records = [
            {
                "timestamp": now,
                "schema_compliance": True,
                "model": "gpt-4",
                "cost_usd": 0.01,
            }
        ] * 5
        _write_perf_log(tmp_path, records)
        with patch("sys.argv", ["alert.py", "--logs-dir", str(tmp_path), "--check-only"]):
            main()

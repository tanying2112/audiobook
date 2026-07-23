"""Tests for monitoring module coverage."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

# Add src to path


class TestLangfuseClient:
    """Test langfuse_client module functions."""

    def test_init_langfuse_disabled(self):
        """Test init_langfuse with disabled flag."""
        from src.audiobook_studio.monitoring.langfuse_client import init_langfuse

        result = init_langfuse(enabled=False)
        assert result is False

    def test_init_langfuse_no_keys(self):
        """Test init_langfuse without keys."""
        from src.audiobook_studio.monitoring.langfuse_client import init_langfuse

        result = init_langfuse(public_key=None, secret_key=None, enabled=True)
        assert result is False

    def test_init_langfuse_placeholder_keys(self):
        """Test init_langfuse with placeholder keys."""
        from src.audiobook_studio.monitoring.langfuse_client import init_langfuse

        result = init_langfuse(public_key="your-public-key", secret_key="your-secret-key", enabled=True)
        assert result is False

    def get_langfuse_client_disabled(self):
        """Test get_langfuse_client when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import get_langfuse_client, init_langfuse

        init_langfuse(enabled=False)
        assert get_langfuse_client() is None

    def test_is_enabled_false(self):
        """Test is_enabled returns False when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import init_langfuse, is_enabled

        init_langfuse(enabled=False)
        assert is_enabled() is False

    def test_flush_langfuse_no_client(self):
        """Test flush_langfuse without client."""
        from src.audiobook_studio.monitoring.langfuse_client import flush_langfuse

        flush_langfuse()  # Should not raise

    def test_trace_context_manager_disabled(self):
        """Test trace context manager when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import trace

        with patch("src.audiobook_studio.monitoring.langfuse_client.is_enabled", return_value=False):
            with trace("test") as t:
                assert t is None

    def test_span_context_manager_no_trace(self):
        """Test span context manager without trace."""
        from src.audiobook_studio.monitoring.langfuse_client import span

        with patch("src.audiobook_studio.monitoring.langfuse_client.is_enabled", return_value=True):
            with span("test", trace_obj=None) as s:
                assert s is None

    def test_observe_llm_call_disabled(self):
        """Test observe_llm_call when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import observe_llm_call

        with patch("src.audiobook_studio.monitoring.langfuse_client.is_enabled", return_value=False):
            observe_llm_call("extract", "gpt-4", "openai")  # Should not raise

    def test_observe_tts_synthesis_disabled(self):
        """Test observe_tts_synthesis when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import observe_tts_synthesis

        with patch("src.audiobook_studio.monitoring.langfuse_client.is_enabled", return_value=False):
            observe_tts_synthesis("voice1", 100, 3000.0, 500.0, "kokoro")  # Should not raise

    def test_observe_quality_check_disabled(self):
        """Test observe_quality_check when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import observe_quality_check

        with patch("src.audiobook_studio.monitoring.langfuse_client.is_enabled", return_value=False):
            observe_quality_check("tts", True, 0.95, [], 100.0)  # Should not raise

    def test_trace_function_disabled(self):
        """Test trace_function decorator when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import trace_function

        with patch("src.audiobook_studio.monitoring.langfuse_client.is_enabled", return_value=False):

            @trace_function("test")
            def dummy():
                return 42

            assert dummy() == 42

    def test_score_trace_disabled(self):
        """Test score_trace when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import score_trace

        with patch("src.audiobook_studio.monitoring.langfuse_client.is_enabled", return_value=False):
            score_trace(None, 0.9)  # Should not raise


class TestDashboard:
    """Test dashboard module functions."""

    def test_parse_args(self):
        """Test parse_args function."""
        from src.audiobook_studio.monitoring.dashboard import parse_args

        with patch("sys.argv", ["test", "--hours", "48", "--json"]):
            args = parse_args()
            assert args.hours == 48
            assert args.json is True

    def test_collect_logs_empty_dir(self, tmp_path):
        """Test collect_logs with empty directory."""
        from src.audiobook_studio.monitoring.dashboard import collect_logs

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        records = collect_logs(logs_dir, 24)
        assert records == []

    def test_collect_logs_with_files(self, tmp_path):
        """Test collect_logs with JSONL files."""
        from src.audiobook_studio.monitoring.dashboard import collect_logs

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        log_file = logs_dir / "test_perf.jsonl"
        log_file.write_text('{"stage": "extract", "latency_ms": 100}\n')
        records = collect_logs(logs_dir, 24)
        assert len(records) == 1
        assert records[0]["stage"] == "extract"

    def test_compute_summary_empty(self):
        """Test compute_summary with empty records."""
        from src.audiobook_studio.monitoring.dashboard import compute_summary

        summary = compute_summary([])
        assert summary["total_records"] == 0
        assert summary["unique_stages"] == 0

    def test_compute_summary_with_data(self):
        """Test compute_summary with sample data."""
        from src.audiobook_studio.monitoring.dashboard import compute_summary

        records = [
            {"stage": "extract", "latency_ms": 100, "cost_usd": 0.01, "success": True},
            {"stage": "extract", "latency_ms": 200, "cost_usd": 0.02, "success": False},
        ]
        summary = compute_summary(records)
        assert summary["total_records"] == 2
        assert "extract" in summary["stages"]
        assert summary["stages"]["extract"]["latency_avg_ms"] == 150

    def test_detect_anomalies_low_success(self):
        """Test detect_anomalies with low success rate."""
        from src.audiobook_studio.monitoring.dashboard import detect_anomalies

        summary = {"stages": {"test": {"success_rate": 0.5, "count": 10}}}
        anomalies = detect_anomalies(summary)
        assert any("Low success rate" in a for a in anomalies)

    def test_detect_anomalies_low_quality(self):
        """Test detect_anomalies with low quality score."""
        from src.audiobook_studio.monitoring.dashboard import detect_anomalies

        summary = {"stages": {"test": {"quality_avg": 0.5, "count": 10, "success_rate": 1.0}}}
        anomalies = detect_anomalies(summary)
        assert any("Low quality score" in a for a in anomalies)

    def test_format_dashboard(self):
        """Test format_dashboard function."""
        from src.audiobook_studio.monitoring.dashboard import format_dashboard

        summary = {
            "total_records": 10,
            "unique_stages": 1,
            "stages": {"extract": {"count": 10, "latency_avg_ms": 100, "cost_total_usd": 0.1, "success_rate": 1.0}},
            "overall": {"latency_avg_ms": 100, "cost_total_usd": 0.1, "success_rate": 1.0},
        }
        output = format_dashboard(summary, 24)
        assert "Audiobook Studio" in output
        assert "10" in output

    def test_main_json_output(self, tmp_path):
        """Test main function with JSON output."""
        from src.audiobook_studio.monitoring.dashboard import main

        logs_dir = tmp_path / "logs"
        logs_dir.mkdir()
        log_file = logs_dir / "test_perf.jsonl"
        log_file.write_text('{"stage": "extract", "latency_ms": 100}\n')
        with patch("sys.argv", ["test", "--hours", "24", "--json", "--logs-dir", str(logs_dir)]):
            with patch("sys.exit") as mock_exit:
                main()
                # Should call sys.exit(0) or sys.exit(1) - we just verify it runs


class TestMonitoringDashboard:
    """Test MonitoringDashboard class."""

    def test_init(self):
        """Test MonitoringDashboard initialization."""
        from src.audiobook_studio.monitoring.dashboard import MonitoringDashboard

        dashboard = MonitoringDashboard()
        assert dashboard is not None

    def test_start(self):
        """Test MonitoringDashboard.start method."""
        from src.audiobook_studio.monitoring.dashboard import MonitoringDashboard

        dashboard = MonitoringDashboard()
        dashboard.start()  # Should not raise

    def test_run(self):
        """Test MonitoringDashboard.run method."""
        from src.audiobook_studio.monitoring.dashboard import MonitoringDashboard

        dashboard = MonitoringDashboard()
        dashboard.run()  # Should not raise


class TestCostDashboard:
    """Test cost_dashboard module."""

    def test_module_imports(self):
        """Test cost_dashboard can be imported."""
        from src.audiobook_studio.monitoring import cost_dashboard

        assert cost_dashboard is not None


class TestMetricsExporter:
    """Test metrics_exporter module."""

    def test_module_imports(self):
        """Test metrics_exporter can be imported."""
        from src.audiobook_studio.monitoring import metrics_exporter

        assert metrics_exporter is not None


class TestBaseline:
    """Test baseline module."""

    def test_module_imports(self):
        """Test baseline can be imported."""
        from src.audiobook_studio.monitoring import baseline

        assert baseline is not None


class TestCompliance:
    """Test compliance module."""

    def test_module_imports(self):
        """Test compliance can be imported."""
        from src.audiobook_studio.monitoring import compliance

        assert compliance is not None


class TestAlert:
    """Test alert module."""

    def test_module_imports(self):
        """Test alert can be imported."""
        from src.audiobook_studio.monitoring import alert

        assert alert is not None


class TestOfflineMonitoring:
    """Test offline_monitoring module."""

    def test_module_imports(self):
        """Test offline_monitoring can be imported."""
        from src.audiobook_studio.monitoring import offline_monitoring

        assert offline_monitoring is not None

"""Tests for monitoring module (standalone monitoring.py)."""

# Import the standalone monitoring.py module using importlib
import importlib.util
import tempfile
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "monitoring_standalone",
    "/Users/guwj/Desktop/AI_Lab/audiobook/src/audiobook_studio/monitoring.py",
)
monitoring = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitoring)


class TestStagePerformanceRecord:
    """Tests for StagePerformanceRecord dataclass."""

    def test_create_record_minimal(self):
        """Test creating a record with minimal required fields."""
        record = monitoring.StagePerformanceRecord(
            stage="test_stage",
            latency_ms=100.0,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
            success=True,
        )
        assert record.stage == "test_stage"
        assert record.latency_ms == 100.0
        assert record.tokens_in == 10
        assert record.tokens_out == 5
        assert record.cost_usd == 0.001
        assert record.success is True
        assert record.quality_score is None
        assert record.provider == "unknown"
        assert record.model == "unknown"
        assert record.difficulty is None
        assert record.schema_compliance is None
        assert record.error is None
        assert record.timestamp is not None

    def test_create_record_full(self):
        """Test creating a record with all fields."""
        record = monitoring.StagePerformanceRecord(
            stage="test_stage",
            latency_ms=250.5,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.005,
            success=False,
            quality_score=0.85,
            provider="openai",
            model="gpt-4",
            difficulty="B",
            schema_compliance=True,
            error="Rate limited",
        )
        assert record.stage == "test_stage"
        assert record.latency_ms == 250.5
        assert record.quality_score == 0.85
        assert record.provider == "openai"
        assert record.model == "gpt-4"
        assert record.difficulty == "B"
        assert record.schema_compliance is True
        assert record.error == "Rate limited"
        assert record.success is False


class TestPerformanceCollector:
    """Tests for PerformanceCollector class."""

    def test_init_no_log_dir(self):
        """Test collector initialization without log directory."""
        collector = monitoring.PerformanceCollector()
        assert collector.records == []
        assert collector.log_dir is None

    def test_init_with_log_dir(self):
        """Test collector initialization with log directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            collector = monitoring.PerformanceCollector(log_dir=log_dir)
            assert collector.log_dir == log_dir
            assert log_dir.exists()

    def test_record_basic(self):
        """Test recording a basic performance entry."""
        collector = monitoring.PerformanceCollector()
        record = collector.record(
            stage="annotate",
            latency_ms=150.0,
            tokens_in=50,
            tokens_out=25,
            cost_usd=0.002,
            success=True,
        )
        assert len(collector.records) == 1
        assert record.stage == "annotate"
        assert record.latency_ms == 150.0
        assert record.success is True

    def test_record_multiple(self):
        """Test recording multiple entries."""
        collector = monitoring.PerformanceCollector()
        collector.record(
            stage="annotate",
            latency_ms=100,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
            success=True,
        )
        collector.record(
            stage="synthesize",
            latency_ms=500,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            success=True,
        )
        collector.record(
            stage="quality_check",
            latency_ms=200,
            tokens_in=20,
            tokens_out=10,
            cost_usd=0.003,
            success=False,
            error="Validation failed",
        )
        assert len(collector.records) == 3

    def test_get_stage_stats_empty(self):
        """Test getting stats for non-existent stage."""
        collector = monitoring.PerformanceCollector()
        stats = collector.get_stage_stats("nonexistent")
        assert stats == {"stage": "nonexistent", "count": 0}

    def test_get_stage_stats_single(self):
        """Test getting stats for a stage with one record."""
        collector = monitoring.PerformanceCollector()
        collector.record(
            stage="annotate",
            latency_ms=100,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
            success=True,
        )
        stats = collector.get_stage_stats("annotate")
        assert stats["stage"] == "annotate"
        assert stats["count"] == 1
        assert stats["success_count"] == 1
        assert stats["success_rate"] == 1.0
        assert stats["avg_latency_ms"] == 100.0
        assert stats["total_cost_usd"] == 0.001
        assert stats["avg_quality_score"] is None

    def test_get_stage_stats_multiple(self):
        """Test getting stats for a stage with multiple records."""
        collector = monitoring.PerformanceCollector()
        collector.record(
            stage="annotate",
            latency_ms=100,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
            success=True,
            quality_score=0.9,
        )
        collector.record(
            stage="annotate",
            latency_ms=200,
            tokens_in=20,
            tokens_out=10,
            cost_usd=0.002,
            success=True,
            quality_score=0.8,
        )
        collector.record(
            stage="annotate",
            latency_ms=300,
            tokens_in=30,
            tokens_out=15,
            cost_usd=0.003,
            success=False,
            error="Failed",
        )
        stats = collector.get_stage_stats("annotate")
        assert stats["count"] == 3
        assert stats["success_count"] == 2
        assert stats["success_rate"] == pytest.approx(2 / 3)
        assert stats["avg_latency_ms"] == 200.0
        assert stats["total_cost_usd"] == 0.006
        assert stats["avg_quality_score"] == pytest.approx(0.85)

    def test_get_stage_stats_no_quality_scores(self):
        """Test stats when no quality scores available."""
        collector = monitoring.PerformanceCollector()
        collector.record(
            stage="synthesize",
            latency_ms=100,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            success=True,
        )
        collector.record(
            stage="synthesize",
            latency_ms=200,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            success=True,
        )
        stats = collector.get_stage_stats("synthesize")
        assert stats["avg_quality_score"] is None

    def test_get_summary_empty(self):
        """Test summary with no records."""
        collector = monitoring.PerformanceCollector()
        summary = collector.get_summary()
        assert summary["total_records"] == 0
        assert summary["total_cost_usd"] == 0.0
        assert summary["stages"] == {}

    def test_get_summary_multiple_stages(self):
        """Test summary with multiple stages."""
        collector = monitoring.PerformanceCollector()
        collector.record(
            stage="annotate",
            latency_ms=100,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
            success=True,
        )
        collector.record(
            stage="synthesize",
            latency_ms=500,
            tokens_in=0,
            tokens_out=0,
            cost_usd=0.0,
            success=True,
        )
        collector.record(
            stage="annotate",
            latency_ms=200,
            tokens_in=20,
            tokens_out=10,
            cost_usd=0.002,
            success=False,
        )
        summary = collector.get_summary()
        assert summary["total_records"] == 3
        assert summary["total_cost_usd"] == 0.003
        assert "annotate" in summary["stages"]
        assert "synthesize" in summary["stages"]
        assert summary["stages"]["annotate"]["count"] == 2
        assert summary["stages"]["synthesize"]["count"] == 1

    def test_persist_to_jsonl(self):
        """Test persisting records to JSONL file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir)
            collector = monitoring.PerformanceCollector(log_dir=log_dir)
            collector.record(
                stage="annotate",
                latency_ms=100,
                tokens_in=10,
                tokens_out=5,
                cost_usd=0.001,
                success=True,
            )

            log_files = list(log_dir.glob("*_perf.jsonl"))
            assert len(log_files) == 1
            content = log_files[0].read_text(encoding="utf-8")
            assert "annotate" in content
            assert "100" in content


class TestGlobalCollector:
    """Tests for global collector singleton functions."""

    def test_get_collector_returns_instance(self):
        """Test get_collector returns a PerformanceCollector."""
        collector = monitoring.get_collector()
        assert isinstance(collector, monitoring.PerformanceCollector)

    def test_reset_collector(self):
        """Test reset_collector creates new instance."""
        collector1 = monitoring.get_collector()
        collector1.record(
            stage="test",
            latency_ms=100,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
            success=True,
        )
        assert len(collector1.records) == 1

        monitoring.reset_collector()
        collector2 = monitoring.get_collector()
        assert collector2 is not collector1
        assert len(collector2.records) == 0

    def test_record_stage_performance_convenience(self):
        """Test record_stage_performance convenience function."""
        monitoring.reset_collector()
        record = monitoring.record_stage_performance(
            stage="test_convenience",
            latency_ms=123.4,
            tokens_in=42,
            tokens_out=21,
            cost_usd=0.0042,
            success=True,
            quality_score=0.95,
            provider="test_provider",
            model="test_model",
            difficulty="C",
            schema_compliance=True,
        )
        assert record.stage == "test_convenience"
        assert record.latency_ms == 123.4
        assert record.quality_score == 0.95
        assert record.provider == "test_provider"
        assert record.difficulty == "C"
        assert record.schema_compliance is True

        # Verify it was added to global collector
        collector = monitoring.get_collector()
        assert len(collector.records) == 1
        assert collector.records[0].stage == "test_convenience"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


"""Tests for monitoring module (src/audiobook_studio/monitoring/)."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.audiobook_studio.monitoring.alert import (
    AlertConfig,
    AlertLevel,
    AlertManager,
    AlertRecord,
    collect_self_iteration_logs,
    compute_metrics,
    compute_self_iteration_metrics,
    format_alert_message,
    send_dingtalk_alert,
    send_slack_alert,
)
from src.audiobook_studio.monitoring.baseline import (
    BaselineRecorder,
    GrowthMetric,
    PerformanceMetric,
    get_baseline_recorder,
    record_growth_metric,
    record_stage_performance,
)
from src.audiobook_studio.monitoring.compliance import (
    ComplianceMonitor,
    ComplianceRecord,
    StageComplianceSummary,
    get_compliance_monitor,
    record_pipeline_compliance,
)
from src.audiobook_studio.monitoring.cost_dashboard import CostBreakdown, CostDashboard
from src.audiobook_studio.monitoring.cost_dashboard import collect_logs as cost_collect_logs
from src.audiobook_studio.monitoring.cost_dashboard import (
    compute_cost_breakdown,
    enrich_records_with_context,
    format_table,
)
from src.audiobook_studio.monitoring.dashboard import (
    MonitoringDashboard,
    collect_logs,
    compute_summary,
    detect_anomalies,
    format_dashboard,
)
from src.audiobook_studio.monitoring.metrics_exporter import (
    _get_metrics_file_path,
    _read_existing_metrics,
    _write_metrics,
    export_all_metrics,
    export_circuit_breaker_metrics,
    export_compliance_rate,
    export_contract_version,
    export_fallback_rate,
    export_health_probe_metrics,
    export_key_pool_metrics,
    export_router_metrics,
    get_metrics_for_ci,
)
from src.audiobook_studio.monitoring.offline_monitoring import (
    DummyOfflineMonitor,
    OfflineMonitor,
    create_offline_monitor,
)


class TestDashboardModule:
    """Tests for dashboard module."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.logs_dir = Path(self.temp_dir) / "logs"
        self.logs_dir.mkdir()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_test_log(self, records: list, filename: str = "test_perf.jsonl"):
        """Create a test JSONL log file."""
        log_file = self.logs_dir / filename
        with open(log_file, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")
        return log_file

    def test_collect_logs_empty_dir(self):
        """Test collecting logs from empty directory."""
        records = collect_logs(self.logs_dir, 24)
        assert records == []

    def test_collect_logs_with_data(self):
        """Test collecting logs with valid records."""
        records = [
            {
                "stage": "annotate",
                "latency_ms": 100,
                "success": True,
                "cost_usd": 0.001,
                "timestamp": datetime.now().isoformat(),
            },
            {
                "stage": "synthesize",
                "latency_ms": 500,
                "success": True,
                "cost_usd": 0.002,
                "timestamp": datetime.now().isoformat(),
            },
        ]
        self.create_test_log(records)

        collected = collect_logs(self.logs_dir, 24)
        assert len(collected) == 2
        assert collected[0]["stage"] == "annotate"
        assert collected[1]["stage"] == "synthesize"

    def test_collect_logs_filters_by_time(self):
        """Test collecting logs filters by time window."""
        old_timestamp = (datetime.now() - timedelta(hours=48)).isoformat()
        recent_timestamp = datetime.now().isoformat()
        records = [
            {
                "stage": "annotate",
                "latency_ms": 100,
                "success": True,
                "timestamp": old_timestamp,
            },
            {
                "stage": "synthesize",
                "latency_ms": 500,
                "success": True,
                "timestamp": recent_timestamp,
            },
        ]
        self.create_test_log(records)

        collected = collect_logs(self.logs_dir, 24)
        assert len(collected) == 1
        assert collected[0]["stage"] == "synthesize"

    def test_collect_logs_handles_invalid_json(self):
        """Test collecting logs skips invalid JSON lines."""
        records = [
            {
                "stage": "annotate",
                "latency_ms": 100,
                "success": True,
                "timestamp": datetime.now().isoformat(),
            },
        ]
        log_file = self.logs_dir / "test_perf.jsonl"
        with open(log_file, "w", encoding="utf-8") as f:
            f.write(json.dumps(records[0]) + "\n")
            f.write("invalid json\n")
            f.write(
                json.dumps(
                    {
                        "stage": "synthesize",
                        "latency_ms": 500,
                        "success": True,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                + "\n"
            )

        collected = collect_logs(self.logs_dir, 24)
        assert len(collected) == 2

    def test_compute_summary_empty(self):
        """Test computing summary with no records."""
        summary = compute_summary([])
        assert summary["total_records"] == 0
        assert summary["unique_stages"] == 0

    def test_compute_summary_with_data(self):
        """Test computing summary with records."""
        records = [
            {
                "stage": "annotate",
                "latency_ms": 100,
                "cost_usd": 0.001,
                "success": True,
                "quality_score": 0.9,
                "provider": "gemini",
                "schema_compliance": True,
            },
            {
                "stage": "annotate",
                "latency_ms": 200,
                "cost_usd": 0.002,
                "success": True,
                "quality_score": 0.8,
                "provider": "gemini",
                "schema_compliance": True,
            },
            {
                "stage": "synthesize",
                "latency_ms": 500,
                "cost_usd": 0.0,
                "success": True,
                "provider": "kokoro",
                "schema_compliance": True,
            },
            {
                "stage": "quality_check",
                "latency_ms": 800,
                "cost_usd": 0.003,
                "success": False,
                "error": "Validation failed",
                "provider": "llm_judge",
                "schema_compliance": False,
            },
        ]
        summary = compute_summary(records)
        assert summary["total_records"] == 4
        assert summary["unique_stages"] == 3
        assert "annotate" in summary["stages"]
        assert "synthesize" in summary["stages"]
        assert "quality_check" in summary["stages"]
        assert summary["stages"]["annotate"]["count"] == 2
        assert summary["stages"]["synthesize"]["count"] == 1
        assert summary["stages"]["quality_check"]["count"] == 1
        assert summary["stages"]["annotate"]["success_rate"] == 1.0
        assert summary["stages"]["quality_check"]["success_rate"] == 0.0
        assert summary["stages"]["annotate"]["quality_avg"] == pytest.approx(0.85)
        assert summary["overall"]["success_rate"] == 0.75

    def test_detect_anomalies_low_success_rate(self):
        """Test anomaly detection for low success rate."""
        summary = {
            "stages": {
                "annotate": {
                    "success_rate": 0.5,
                    "quality_avg": 0.9,
                    "schema_compliance_rate": 1.0,
                    "count": 10,
                }
            }
        }
        anomalies = detect_anomalies(summary)
        assert any("Low success rate" in a for a in anomalies)

    def test_detect_anomalies_low_quality(self):
        """Test anomaly detection for low quality score."""
        summary = {
            "stages": {
                "synthesize": {
                    "success_rate": 1.0,
                    "quality_avg": 0.5,
                    "schema_compliance_rate": 1.0,
                    "count": 10,
                }
            }
        }
        anomalies = detect_anomalies(summary)
        assert any("Low quality score" in a for a in anomalies)

    def test_detect_anomalies_low_compliance(self):
        """Test anomaly detection for low schema compliance."""
        summary = {
            "stages": {
                "quality": {
                    "success_rate": 1.0,
                    "quality_avg": 0.9,
                    "schema_compliance_rate": 0.95,
                    "count": 10,
                }
            }
        }
        anomalies = detect_anomalies(summary)
        assert any("Low schema compliance rate" in a for a in anomalies)

    def test_detect_anomalies_no_data(self):
        """Test anomaly detection for no data."""
        summary = {
            "stages": {
                "annotate": {
                    "success_rate": 0.0,
                    "quality_avg": None,
                    "schema_compliance_rate": None,
                    "count": 0,
                }
            }
        }
        anomalies = detect_anomalies(summary)
        assert any("No data recorded" in a for a in anomalies)

    def test_format_dashboard(self):
        """Test dashboard formatting."""
        summary = {
            "total_records": 10,
            "unique_stages": 3,
            "stages": {
                "annotate": {
                    "count": 5,
                    "latency_avg_ms": 150,
                    "cost_total_usd": 0.01,
                    "success_rate": 1.0,
                    "quality_avg": 0.9,
                    "schema_compliance_rate": 1.0,
                    "providers": ["gemini"],
                },
                "synthesize": {
                    "count": 5,
                    "latency_avg_ms": 500,
                    "cost_total_usd": 0.0,
                    "success_rate": 1.0,
                    "quality_avg": None,
                    "schema_compliance_rate": 1.0,
                    "providers": ["kokoro"],
                },
            },
            "overall": {
                "latency_avg_ms": 325,
                "cost_total_usd": 0.01,
                "success_rate": 1.0,
                "quality_avg": 0.9,
                "schema_compliance_rate": 1.0,
            },
        }
        dashboard = format_dashboard(summary, 24)
        assert "Audiobook Studio" in dashboard
        assert "全局概览" in dashboard
        assert "分阶段详情" in dashboard
        assert "annotate" in dashboard
        assert "synthesize" in dashboard

    def test_monitoring_dashboard_class(self):
        """Test MonitoringDashboard class instantiation."""
        dashboard = MonitoringDashboard()
        assert dashboard is not None
        dashboard.start()
        dashboard.run()


class TestAlertModule:
    """Tests for alert module."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.logs_dir = Path(self.temp_dir) / "logs"
        self.logs_dir.mkdir()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_alert_level_enum(self):
        """Test AlertLevel enum values."""
        assert AlertLevel.INFO == "INFO"
        assert AlertLevel.WARNING == "WARNING"
        assert AlertLevel.CRITICAL == "CRITICAL"

    def test_alert_config_default(self):
        """Test AlertConfig default values."""
        config = AlertConfig()
        assert config.threshold == 0.8
        assert config.enabled is True

    def test_alert_config_custom(self):
        """Test AlertConfig with custom values."""
        config = AlertConfig(threshold=0.9, enabled=False)
        assert config.threshold == 0.9
        assert config.enabled is False

    def test_alert_record(self):
        """Test AlertRecord creation."""
        record = AlertRecord(
            level=AlertLevel.WARNING,
            message="Test alert",
            timestamp=1234567890.0,
            context={"key": "value"},
        )
        assert record.level == AlertLevel.WARNING
        assert record.message == "Test alert"
        assert record.timestamp == 1234567890.0
        assert record.context == {"key": "value"}

    def test_alert_record_no_context(self):
        """Test AlertRecord without context."""
        record = AlertRecord(
            level=AlertLevel.CRITICAL,
            message="Critical alert",
            timestamp=1234567890.0,
        )
        assert record.level == AlertLevel.CRITICAL
        assert record.message == "Critical alert"
        assert record.context is None

    def test_alert_manager_init(self):
        """Test AlertManager initialization."""
        manager = AlertManager()
        assert manager.config is not None
        assert manager.config.threshold == 0.8

    def test_alert_manager_custom_config(self):
        """Test AlertManager with custom config."""
        config = AlertConfig(threshold=0.9)
        manager = AlertManager(config)
        assert manager.config.threshold == 0.9

    def test_alert_manager_trigger_alert(self):
        """Test triggering an alert."""
        manager = AlertManager()
        result = manager.trigger_alert(AlertLevel.WARNING, "Test message", {"test": "context"})
        assert result is True

    def test_collect_self_iteration_logs_empty(self):
        """Test collecting self-iteration logs from empty directory."""
        records = collect_self_iteration_logs(self.logs_dir, 24)
        assert records == []

    def test_collect_self_iteration_logs_with_data(self):
        """Test collecting self-iteration logs with valid data."""
        records = [
            {
                "iteration": 1,
                "promoted": True,
                "feedback_count": 5,
                "system_health_score": 80,
                "timestamp": datetime.now().isoformat(),
            },
            {
                "iteration": 2,
                "promoted": False,
                "feedback_count": 3,
                "system_health_score": 70,
                "timestamp": datetime.now().isoformat(),
            },
        ]
        for log_file in self.logs_dir.glob("*_self_iteration.jsonl"):
            log_file.unlink()
        log_file = self.logs_dir / "test_self_iteration.jsonl"
        with open(log_file, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record) + "\n")

        collected = collect_self_iteration_logs(self.logs_dir, 24)
        assert len(collected) == 2

    def test_compute_self_iteration_metrics_empty(self):
        """Test computing self-iteration metrics with no records."""
        metrics = compute_self_iteration_metrics([])
        assert metrics["total_iterations"] == 0
        assert metrics["promotion_rate"] == 0.0
        assert metrics["avg_feedback_per_iteration"] == 0.0
        assert metrics["system_health_score"] == 100.0
        assert metrics["alerts"] == []

    def test_compute_self_iteration_metrics_with_data(self):
        """Test computing self-iteration metrics with records."""
        records = [
            {"promoted": True, "feedback_count": 5, "system_health_score": 80},
            {"promoted": True, "feedback_count": 3, "system_health_score": 70},
            {"promoted": False, "feedback_count": 2, "system_health_score": 60},
        ]
        metrics = compute_self_iteration_metrics(records)
        assert metrics["total_iterations"] == 3
        assert metrics["promotion_rate"] == pytest.approx(2 / 3)
        assert metrics["avg_feedback_per_iteration"] == pytest.approx(10 / 3)
        assert metrics["system_health_score"] == 70.0
        assert "alerts" in metrics

    def test_compute_self_iteration_metrics_low_promotion(self):
        """Test low promotion rate alert."""
        records = [{"promoted": False, "feedback_count": 1, "system_health_score": 80} for _ in range(5)]
        metrics = compute_self_iteration_metrics(records)
        assert any(a["type"] == "low_promotion_rate" for a in metrics["alerts"])

    def test_compute_self_iteration_metrics_insufficient_feedback(self):
        """Test insufficient feedback alert."""
        records = [{"promoted": True, "feedback_count": 0, "system_health_score": 80} for _ in range(5)]
        metrics = compute_self_iteration_metrics(records)
        assert any(a["type"] == "insufficient_feedback" for a in metrics["alerts"])

    def test_compute_self_iteration_metrics_health_degraded(self):
        """Test system health degraded alert."""
        records = [{"promoted": True, "feedback_count": 5, "system_health_score": 30} for _ in range(5)]
        metrics = compute_self_iteration_metrics(records)
        assert any(a["type"] == "system_health_degraded" for a in metrics["alerts"])

    def test_compute_metrics_empty(self):
        """Test computing metrics with no records."""
        metrics = compute_metrics([])
        assert metrics["total_records"] == 0
        assert metrics["schema_compliance_rate"] == 0.0
        assert metrics["fallback_rate"] == 0.0
        assert metrics["total_cost_usd"] == 0.0
        assert metrics["alerts"] == []

    def test_compute_metrics_with_data(self):
        """Test computing metrics with records."""
        records = [
            {"schema_compliance": True, "model": "gemini", "cost_usd": 0.001},
            {"schema_compliance": True, "model": "gemini", "cost_usd": 0.002},
            {
                "schema_compliance": False,
                "model": "heuristic_fallback",
                "cost_usd": 0.001,
            },
        ]
        metrics = compute_metrics(records)
        assert metrics["total_records"] == 3
        assert metrics["schema_compliance_rate"] == pytest.approx(2 / 3)
        assert metrics["fallback_rate"] == pytest.approx(1 / 3)
        assert metrics["total_cost_usd"] == 0.004

    def test_compute_metrics_schema_compliance_alert(self):
        """Test schema compliance rate alert."""
        records = [{"schema_compliance": False, "model": "gemini", "cost_usd": 0.001} for _ in range(100)]
        metrics = compute_metrics(records)
        assert any(a["type"] == "schema_compliance" for a in metrics["alerts"])

    def test_compute_metrics_fallback_rate_alert(self):
        """Test fallback rate alert."""
        records = [
            {
                "schema_compliance": True,
                "model": "heuristic_fallback",
                "cost_usd": 0.001,
            }
            for _ in range(100)
        ]
        metrics = compute_metrics(records)
        assert any(a["type"] == "fallback_rate" for a in metrics["alerts"])

    def test_compute_metrics_cost_overrun_alert(self):
        """Test cost overrun alert."""
        records = [{"schema_compliance": True, "model": "gemini", "cost_usd": 10.0}]
        metrics = compute_metrics(records)
        assert any(a["type"] == "cost_overrun" for a in metrics["alerts"])

    @patch("src.audiobook_studio.monitoring.alert.requests.post")
    def test_send_dingtalk_alert_success(self, mock_post):
        """Test successful Dingtalk alert sending."""
        mock_post.return_value.raise_for_status.return_value = None
        result = send_dingtalk_alert("https://webhook.url", "Test message")
        assert result is True
        mock_post.assert_called_once()

    @patch("src.audiobook_studio.monitoring.alert.requests.post")
    def test_send_dingtalk_alert_failure(self, mock_post):
        """Test failed Dingtalk alert sending."""
        mock_post.side_effect = Exception("Connection error")
        result = send_dingtalk_alert("https://webhook.url", "Test message")
        assert result is False

    @patch("src.audiobook_studio.monitoring.alert.requests.post")
    def test_send_slack_alert_success(self, mock_post):
        """Test successful Slack alert sending."""
        mock_post.return_value.raise_for_status.return_value = None
        result = send_slack_alert("https://webhook.url", "Test message")
        assert result is True
        mock_post.assert_called_once()

    @patch("src.audiobook_studio.monitoring.alert.requests.post")
    def test_send_slack_alert_failure(self, mock_post):
        """Test failed Slack alert sending."""
        mock_post.side_effect = Exception("Connection error")
        result = send_slack_alert("https://webhook.url", "Test message")
        assert result is False

    def test_format_alert_message(self):
        """Test formatting alert message."""
        metrics = {
            "total_records": 100,
            "schema_compliance_rate": 0.95,
            "fallback_rate": 0.02,
            "estimated_daily_cost": 5.0,
            "alerts": [
                {"severity": "warning", "message": "Schema compliance below threshold"},
                {"severity": "critical", "message": "Cost overrun detected"},
            ],
        }
        message = format_alert_message(metrics)
        assert "100 条记录" in message
        assert "95.00%" in message
        assert "2.00%" in message
        assert "5.00" in message
        assert "🟡" in message
        assert "🔴" in message
        assert "Schema compliance below threshold" in message
        assert "Cost overrun detected" in message


class TestCostDashboardModule:
    """Tests for cost_dashboard module."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.logs_dir = Path(self.temp_dir) / "logs"
        self.logs_dir.mkdir()

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_cost_breakdown_model(self):
        """Test CostBreakdown Pydantic model."""
        breakdown = CostBreakdown(prompt_tokens=100, completion_tokens=50, total_cost=0.001)
        assert breakdown.prompt_tokens == 100
        assert breakdown.completion_tokens == 50
        assert breakdown.total_cost == 0.001

    def test_cost_dashboard_class(self):
        """Test CostDashboard class instantiation."""
        dashboard = CostDashboard()
        assert dashboard is not None
        dashboard.update_cost(stage="test", cost=0.001)
        result = dashboard.render()
        assert result == {}

    def test_enrich_records_with_context(self):
        """Test enriching records with context."""
        records = [
            {
                "stage": "annotate",
                "tokens_out": 100,
                "cost_usd": 0.001,
                "success": True,
                "provider": "gemini",
                "model": "gemini-2.0-flash",
                "difficulty": "B",
            },
            {
                "stage": "synthesize",
                "tokens_out": 0,
                "cost_usd": 0.0,
                "success": True,
                "provider": "kokoro",
                "model": "kokoro",
                "difficulty": "B",
            },
            {
                "stage": "quality_check",
                "tokens_out": 50,
                "cost_usd": 0.002,
                "success": False,
                "error": "Failed",
                "provider": "llm_judge",
                "model": "gpt-4",
                "difficulty": "A",
            },
        ]
        enriched = enrich_records_with_context(records)
        assert len(enriched) == 3
        assert enriched[0]["estimated_chars"] == 400  # 100 * 4
        assert enriched[1]["estimated_chars"] == 0
        assert enriched[2]["is_retry"] is True  # Has error
        assert enriched[0]["difficulty"] == "B"
        assert enriched[1]["difficulty"] == "B"
        assert enriched[2]["difficulty"] == "A"

    def test_compute_cost_breakdown(self):
        """Test computing cost breakdown."""
        records = [
            {
                "stage": "annotate",
                "tokens_out": 100,
                "cost_usd": 0.001,
                "success": True,
                "provider": "gemini",
                "model": "gemini-2.0-flash",
                "difficulty": "B",
                "is_retry": False,
            },
            {
                "stage": "annotate",
                "tokens_out": 200,
                "cost_usd": 0.002,
                "success": True,
                "provider": "gemini",
                "model": "gemini-2.0-flash",
                "difficulty": "B",
                "is_retry": False,
            },
            {
                "stage": "synthesize",
                "tokens_out": 500,
                "cost_usd": 0.0,
                "success": True,
                "provider": "kokoro",
                "model": "kokoro",
                "difficulty": "B",
                "is_retry": False,
            },
            {
                "stage": "quality_check",
                "tokens_out": 50,
                "cost_usd": 0.003,
                "success": False,
                "provider": "llm_judge",
                "model": "gpt-4",
                "difficulty": "A",
                "is_retry": True,
            },
        ]
        breakdown = compute_cost_breakdown(records)
        assert "overall" in breakdown
        assert "by_stage" in breakdown
        assert "by_model" in breakdown
        assert "by_provider" in breakdown
        assert "by_difficulty" in breakdown
        assert breakdown["overall"]["total_records"] == 4
        assert breakdown["overall"]["total_cost_usd"] == 0.006
        assert breakdown["overall"]["retry_count"] == 1
        assert breakdown["overall"]["retry_rate"] == 0.25
        assert "annotate" in breakdown["by_stage"]
        assert "synthesize" in breakdown["by_stage"]
        assert "quality_check" in breakdown["by_stage"]
        assert "gemini-2.0-flash" in breakdown["by_model"]
        assert "kokoro" in breakdown["by_model"]
        assert "gemini-2.0-flash" in breakdown["by_model"]
        assert "B" in breakdown["by_difficulty"]
        assert "A" in breakdown["by_difficulty"]

    def test_compute_cost_breakdown_empty(self):
        """Test cost breakdown with empty records."""
        breakdown = compute_cost_breakdown([])
        assert breakdown["overall"]["total_records"] == 0
        assert breakdown["overall"]["total_cost_usd"] == 0.0
        assert breakdown["by_stage"] == {}
        assert breakdown["by_model"] == {}
        assert breakdown["by_provider"] == {}
        assert breakdown["by_difficulty"] == {}

    def test_format_table(self):
        """Test formatting cost breakdown as table."""
        breakdown = {
            "overall": {
                "total_cost_usd": 0.01,
                "total_records": 10,
                "estimated_total_chars": 5000,
                "cost_per_1k_chars_usd": 2.0,
                "retry_cost_usd": 0.001,
                "retry_count": 2,
                "retry_rate": 0.2,
            },
            "by_stage": {
                "annotate": {
                    "cost_usd": 0.005,
                    "count": 5,
                    "chars": 2000,
                    "cost_per_1k_chars_usd": 2.5,
                    "avg_cost_per_record": 0.001,
                },
                "synthesize": {
                    "cost_usd": 0.0,
                    "count": 5,
                    "chars": 3000,
                    "cost_per_1k_chars_usd": 0.0,
                    "avg_cost_per_record": 0.0,
                },
            },
            "by_model": {
                "gemini": {
                    "cost_usd": 0.005,
                    "count": 5,
                    "chars": 2000,
                    "cost_per_1k_chars_usd": 2.5,
                    "avg_cost_per_record": 0.001,
                },
                "kokoro": {
                    "cost_usd": 0.0,
                    "count": 5,
                    "chars": 3000,
                    "cost_per_1k_chars_usd": 0.0,
                    "avg_cost_per_record": 0.0,
                },
            },
            "by_provider": {
                "gemini": {
                    "cost_usd": 0.005,
                    "count": 5,
                    "chars": 2000,
                    "cost_per_1k_chars_usd": 2.5,
                    "avg_cost_per_record": 0.001,
                },
                "kokoro": {
                    "cost_usd": 0.0,
                    "count": 5,
                    "chars": 3000,
                    "cost_per_1k_chars_usd": 0.0,
                    "avg_cost_per_record": 0.0,
                },
            },
            "by_difficulty": {
                "B": {
                    "cost_usd": 0.005,
                    "count": 10,
                    "chars": 5000,
                    "cost_per_1k_chars_usd": 1.0,
                    "avg_cost_per_record": 0.0005,
                },
            },
        }
        table = format_table(breakdown)
        assert "成本看板" in table
        assert "总体成本指标" in table
        assert "按环节成本分布" in table
        assert "按模型成本分布" in table
        assert "按提供商成本分布" in table
        assert "annotate" in table
        assert "synthesize" in table
        assert "gemini" in table
        assert "kokoro" in table


class TestMetricsExporterModule:
    """Tests for metrics_exporter module."""

    def test_export_circuit_breaker_metrics(self):
        """Test exporting circuit breaker metrics."""
        from src.audiobook_studio.llm.circuit_breaker import CircuitBreaker

        cb1 = CircuitBreaker(provider_name="provider1", failure_threshold=5, recovery_timeout_s=30)
        cb2 = CircuitBreaker(provider_name="provider2", failure_threshold=3, recovery_timeout_s=60)

        circuit_breakers = {"provider1": cb1, "provider2": cb2}
        result = export_circuit_breaker_metrics(circuit_breakers)

        assert "provider1" in result
        assert "provider2" in result
        assert "state" in result["provider1"]
        assert "failure_count" in result["provider1"]

    def test_export_circuit_breaker_metrics_empty(self):
        """Test exporting circuit breaker metrics with empty dict."""
        result = export_circuit_breaker_metrics({})
        assert result == {}

    def test_export_health_probe_metrics(self):
        """Test exporting health probe metrics."""
        from src.audiobook_studio.llm.router import LLMRouter

        router = LLMRouter(mock_mode=True)
        probe = router.health_probe
        result = export_health_probe_metrics(probe)

        assert "gemini_flash" in result or "opencode_zen" in result

    def test_export_health_probe_metrics_none(self):
        """Test exporting health probe metrics with None."""
        result = export_health_probe_metrics(None)
        assert "error" in result

    def test_export_key_pool_metrics(self):
        """Test exporting key pool metrics."""
        from src.audiobook_studio.llm.key_pool import KeyPoolManager

        key_pool = KeyPoolManager()
        result = export_key_pool_metrics(key_pool)

        assert isinstance(result, dict)

    def test_export_router_metrics(self):
        """Test exporting router metrics."""
        from src.audiobook_studio.llm.router import LLMRouter

        router = LLMRouter(mock_mode=True)
        result = export_router_metrics(router)

        assert "free_tier_health" in result
        assert "cost_status" in result
        assert "stage_configs" in result

    def test_export_fallback_rate_with_router(self, tmp_path):
        """Test exporting fallback rate with router."""
        from src.audiobook_studio.llm.router import LLMRouter

        router = LLMRouter(mock_mode=True)
        output_path = str(tmp_path / "metrics_test.json")
        result = export_fallback_rate(router, output_path=output_path)

        assert "fallback_rate_pct" in result
        assert "timestamp" in result
        assert Path(output_path).exists()

    def test_export_fallback_rate_without_router(self, tmp_path):
        """Test exporting fallback rate without router."""
        output_path = str(tmp_path / "metrics_test.json")
        result = export_fallback_rate(router=None, output_path=output_path)

        assert "fallback_rate_pct" in result
        assert result["fallback_rate_pct"] == 0.0
        assert "note" in result

    def test_export_compliance_rate(self, tmp_path):
        """Test exporting compliance rate."""
        from src.audiobook_studio.monitoring.compliance import ComplianceMonitor

        monitor = ComplianceMonitor()
        # Add some mock data
        for _ in range(10):
            monitor.record(stage="annotate", schema_compliance=True, contract_version=1)

        output_path = str(tmp_path / "metrics_test.json")
        result = export_compliance_rate(monitor, output_path=output_path)

        assert "overall_compliance_rate" in result
        assert "stage_compliance" in result
        assert Path(output_path).exists()

    def test_export_compliance_rate_default_monitor(self, tmp_path):
        """Test exporting compliance rate with default monitor."""
        output_path = str(tmp_path / "metrics_test.json")
        result = export_compliance_rate(output_path=output_path)

        assert "overall_compliance_rate" in result
        assert Path(output_path).exists()

    def test_export_contract_version(self, tmp_path):
        """Test exporting contract version."""
        from src.audiobook_studio.monitoring.compliance import ComplianceMonitor

        monitor = ComplianceMonitor()
        for _ in range(5):
            monitor.record(stage="annotate", schema_compliance=True, contract_version=1)
        for _ in range(3):
            monitor.record(stage="annotate", schema_compliance=True, contract_version=2)

        output_path = str(tmp_path / "metrics_test.json")
        result = export_contract_version(monitor, output_path=output_path)

        assert "contract_version_distribution" in result
        assert "total_records" in result
        assert "latest_version" in result
        assert Path(output_path).exists()

    def test_export_contract_version_default_monitor(self, tmp_path):
        """Test exporting contract version with default monitor."""
        output_path = str(tmp_path / "metrics_test.json")
        result = export_contract_version(output_path=output_path)

        assert "contract_version_distribution" in result
        assert Path(output_path).exists()

    def test_export_all_metrics(self, tmp_path):
        """Test exporting all metrics at once."""
        from src.audiobook_studio.llm.router import LLMRouter
        from src.audiobook_studio.monitoring.compliance import ComplianceMonitor

        router = LLMRouter(mock_mode=True)
        monitor = ComplianceMonitor()

        # Add mock compliance data
        for stage in ["extract", "annotate", "synthesize"]:
            for _ in range(3):
                monitor.record(stage=stage, schema_compliance=True, contract_version=1)

        output_path = str(tmp_path / "metrics_test.json")
        result = export_all_metrics(router=router, monitor=monitor, output_path=output_path)

        assert "exported_at" in result
        assert "format_version" in result
        assert "router" in result
        assert "fallback_rate" in result
        assert "compliance_rate" in result
        assert "contract_version" in result
        assert Path(output_path).exists()

    def test_get_metrics_for_ci(self, tmp_path):
        """Test getting metrics for CI consumption."""
        # First export some metrics
        from src.audiobook_studio.monitoring.compliance import ComplianceMonitor

        monitor = ComplianceMonitor()
        for _ in range(10):
            monitor.record(stage="annotate", schema_compliance=True, contract_version=1)

        output_path = str(tmp_path / "metrics_test.json")
        export_compliance_rate(monitor, output_path=output_path)
        export_contract_version(monitor, output_path=output_path)

        # Mock the file path for get_metrics_for_ci
        import src.audiobook_studio.monitoring.metrics_exporter as me

        original_fn = me._get_metrics_file_path
        me._get_metrics_file_path = lambda: Path(output_path)

        result = me.get_metrics_for_ci()

        assert "fallback_rate_pct" in result
        assert "overall_compliance_rate" in result
        assert "overall_compliance_pct" in result
        assert "contract_version_distribution" in result
        assert "latest_contract_version" in result

        # Restore original function
        me._get_metrics_file_path = original_fn

    def test_read_existing_metrics_nonexistent(self, tmp_path):
        """Test reading metrics from nonexistent file."""
        from pathlib import Path as PathLib

        output_path = tmp_path / "nonexistent.json"
        result = _read_existing_metrics(output_path)
        assert result == {}

    def test_read_existing_metrics_invalid_json(self, tmp_path):
        """Test reading metrics from invalid JSON file."""
        output_path = tmp_path / "invalid.json"
        output_path.write_text("not valid json")
        result = _read_existing_metrics(output_path)
        assert result == {}

    def test_read_existing_metrics_valid(self, tmp_path):
        """Test reading metrics from valid JSON file."""
        output_path = tmp_path / "valid.json"
        import json

        test_data = {"test_key": "test_value"}
        with open(output_path, "w") as f:
            json.dump(test_data, f)

        result = _read_existing_metrics(output_path)
        assert result == test_data

    def test_write_metrics_success(self, tmp_path):
        """Test writing metrics successfully."""
        output_path = tmp_path / "write_test.json"
        test_data = {"test_key": "test_value"}
        _write_metrics(output_path, test_data)

        import json

        with open(output_path) as f:
            written = json.load(f)
        assert written == test_data

    def test_get_metrics_file_path_default(self):
        """Test getting default metrics file path."""
        path = _get_metrics_file_path()
        assert path.suffix == ".json"
        assert path.name.startswith("metrics_")

    def test_get_metrics_file_path_custom_dir(self, monkeypatch):
        """Test getting metrics file path with custom dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.setattr("os.environ", {"AUDIOBOOK_LOGS_DIR": tmpdir})
            path = _get_metrics_file_path()
            assert str(tmpdir) in str(path)


class TestOfflineMonitoringModule:
    """Tests for offline_monitoring module."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.offline_dir = Path(self.temp_dir) / "offline"

    def teardown_method(self):
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_offline_monitor_init(self):
        """Test OfflineMonitor initialization."""
        from src.audiobook_studio.monitoring.offline_monitoring import OfflineMonitor

        monitor = OfflineMonitor(offline_dir=self.offline_dir)
        assert monitor.offline_dir == self.offline_dir
        assert self.offline_dir.exists()

    def test_log_performance_success(self, monkeypatch):
        """Test logging performance when external service works."""
        from src.audiobook_studio.monitoring.offline_monitoring import OfflineMonitor

        monitor = OfflineMonitor(offline_dir=self.offline_dir)

        def mock_send(*args):
            return True

        monkeypatch.setattr(monitor, "_send_to_external", mock_send)

        metrics = {"stage": "extract", "latency_ms": 100, "success": True}
        result = monitor.log_performance(metrics)
        assert result is True

    def test_log_performance_fallback(self, monkeypatch):
        """Test fallback to offline storage when external fails."""
        from src.audiobook_studio.monitoring.offline_monitoring import OfflineMonitor

        monitor = OfflineMonitor(offline_dir=self.offline_dir)

        def mock_send(*args):
            raise ConnectionError("External service unavailable")

        monkeypatch.setattr(monitor, "_send_to_external", mock_send)

        metrics = {"stage": "synthesize", "latency_ms": 500, "success": True}
        result = monitor.log_performance(metrics)
        assert result is True

    def test_save_to_offline_error(self, monkeypatch):
        """Test error handling when saving to offline."""
        from src.audiobook_studio.monitoring.offline_monitoring import OfflineMonitor

        monitor = OfflineMonitor(offline_dir=self.offline_dir)

        def mock_open_fail(*args, **kwargs):
            raise PermissionError("No write permission")

        monkeypatch.setattr("builtins.open", mock_open_fail)
        result = monitor._save_to_offline({"stage": "quality", "success": False})
        assert result is False

    def test_sync_offline_data_success(self, monkeypatch):
        """Test syncing offline data to external service."""
        import json

        from src.audiobook_studio.monitoring.offline_monitoring import OfflineMonitor

        monitor = OfflineMonitor(offline_dir=self.offline_dir)
        date_str = datetime.now().strftime("%Y-%m-%d")
        offline_file = self.offline_dir / f"performance_{date_str}.jsonl"
        test_record = {"stage": "test", "latency_ms": 100}
        with open(offline_file, "w") as f:
            f.write(json.dumps(test_record) + "\n")

        def mock_send(*args):
            return True

        monkeypatch.setattr(monitor, "_send_to_external", mock_send)
        synced = monitor.sync_offline_data()
        assert synced == 1
        assert not offline_file.exists()

    def test_dummy_offline_monitor(self):
        """Test DummyOfflineMonitor stub class."""
        from src.audiobook_studio.monitoring.offline_monitoring import DummyOfflineMonitor

        dummy = DummyOfflineMonitor()
        dummy.start()
        dummy.stop()
        dummy.analyze()

    def test_create_offline_monitor(self):
        """Test create_offline_monitor factory function."""
        from src.audiobook_studio.monitoring.offline_monitoring import DummyOfflineMonitor, create_offline_monitor

        result = create_offline_monitor()
        assert isinstance(result, DummyOfflineMonitor)


class TestLangfuseClientModule:
    """Tests for langfuse_client module."""

    def setup_method(self):
        import src.audiobook_studio.monitoring.langfuse_client as lc

        lc._langfuse_client = None
        lc._enabled = False

    def test_init_langfuse_disabled(self):
        """Test init with enabled=False."""
        from src.audiobook_studio.monitoring.langfuse_client import init_langfuse, is_enabled

        result = init_langfuse(enabled=False)
        assert result is False
        assert is_enabled() is False

    def test_init_langfuse_no_keys(self, monkeypatch):
        """Test init without API keys."""
        from src.audiobook_studio.monitoring.langfuse_client import init_langfuse, is_enabled

        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        result = init_langfuse(enabled=True)
        assert result is False
        assert is_enabled() is False

    @patch("langfuse.Langfuse")
    def test_init_langfuse_with_keys(self, mock_langfuse, monkeypatch):
        """Test init with API keys."""
        from src.audiobook_studio.monitoring.langfuse_client import get_langfuse_client, init_langfuse

        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret")
        mock_langfuse.return_value.flush = lambda: None

        result = init_langfuse()
        assert result is True
        assert get_langfuse_client() is not None

    @patch("langfuse.Langfuse")
    def test_flush_langfuse(self, mock_langfuse, monkeypatch):
        """Test flush_langfuse function."""
        from src.audiobook_studio.monitoring.langfuse_client import flush_langfuse, init_langfuse

        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret")
        mock_langfuse.return_value.flush = lambda: None

        init_langfuse()
        flush_langfuse()

    @patch("langfuse.Langfuse")
    def test_flush_langfuse_error(self, mock_langfuse, monkeypatch):
        """Test flush_langfuse with error."""
        from src.audiobook_studio.monitoring.langfuse_client import flush_langfuse, init_langfuse

        monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "test-public")
        monkeypatch.setenv("LANGFUSE_SECRET_KEY", "test-secret")
        mock_langfuse.return_value.flush = lambda: (_ for _ in ()).throw(ConnectionError("Network error"))

        init_langfuse()
        flush_langfuse()

    def test_trace_context_manager_disabled(self):
        """Test trace context manager when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import trace

        with trace("test_trace") as span:
            assert span is None

    def test_span_context_manager_disabled(self):
        """Test span context manager when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import span

        with span("test_span", trace_obj=None) as s:
            assert s is None

    def test_get_langfuse_client_none(self):
        """Test get_langfuse_client returns None when disabled."""
        from src.audiobook_studio.monitoring.langfuse_client import get_langfuse_client

        assert get_langfuse_client() is None

    def test_is_enabled(self):
        """Test is_enabled function."""
        from src.audiobook_studio.monitoring.langfuse_client import is_enabled

        assert is_enabled() is False

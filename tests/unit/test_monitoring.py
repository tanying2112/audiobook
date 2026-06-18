"""Tests for monitoring module (standalone monitoring.py)."""

import tempfile
from pathlib import Path

import pytest

# Import the standalone monitoring.py module using importlib
import importlib.util

spec = importlib.util.spec_from_file_location(
    'monitoring_standalone',
    '/Users/guwj/Desktop/AI_Lab/audiobook/src/audiobook_studio/monitoring.py'
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
        collector.record(stage="annotate", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
        collector.record(stage="synthesize", latency_ms=500, tokens_in=0, tokens_out=0, cost_usd=0.0, success=True)
        collector.record(stage="quality_check", latency_ms=200, tokens_in=20, tokens_out=10, cost_usd=0.003, success=False, error="Validation failed")
        assert len(collector.records) == 3

    def test_get_stage_stats_empty(self):
        """Test getting stats for non-existent stage."""
        collector = monitoring.PerformanceCollector()
        stats = collector.get_stage_stats("nonexistent")
        assert stats == {"stage": "nonexistent", "count": 0}

    def test_get_stage_stats_single(self):
        """Test getting stats for a stage with one record."""
        collector = monitoring.PerformanceCollector()
        collector.record(stage="annotate", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
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
        collector.record(stage="annotate", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True, quality_score=0.9)
        collector.record(stage="annotate", latency_ms=200, tokens_in=20, tokens_out=10, cost_usd=0.002, success=True, quality_score=0.8)
        collector.record(stage="annotate", latency_ms=300, tokens_in=30, tokens_out=15, cost_usd=0.003, success=False, error="Failed")
        stats = collector.get_stage_stats("annotate")
        assert stats["count"] == 3
        assert stats["success_count"] == 2
        assert stats["success_rate"] == pytest.approx(2/3)
        assert stats["avg_latency_ms"] == 200.0
        assert stats["total_cost_usd"] == 0.006
        assert stats["avg_quality_score"] == pytest.approx(0.85)

    def test_get_stage_stats_no_quality_scores(self):
        """Test stats when no quality scores available."""
        collector = monitoring.PerformanceCollector()
        collector.record(stage="synthesize", latency_ms=100, tokens_in=0, tokens_out=0, cost_usd=0.0, success=True)
        collector.record(stage="synthesize", latency_ms=200, tokens_in=0, tokens_out=0, cost_usd=0.0, success=True)
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
        collector.record(stage="annotate", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
        collector.record(stage="synthesize", latency_ms=500, tokens_in=0, tokens_out=0, cost_usd=0.0, success=True)
        collector.record(stage="annotate", latency_ms=200, tokens_in=20, tokens_out=10, cost_usd=0.002, success=False)
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
            collector.record(stage="annotate", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)

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
        collector1.record(stage="test", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
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
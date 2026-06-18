"""Tests for monitoring baseline module."""

import tempfile
import time
from pathlib import Path

import pytest

from src.audiobook_studio.monitoring.baseline import (
    BaselineRecorder,
    GrowthMetric,
    PerformanceMetric,
    get_baseline_recorder,
    record_growth_metric,
    record_stage_performance,
)


class TestPerformanceMetric:
    """Tests for PerformanceMetric dataclass."""

    def test_create_minimal(self):
        """Test creating a performance metric with minimal fields."""
        metric = PerformanceMetric(
            timestamp=time.time(),
            stage="test_stage",
            latency_ms=100.0,
            tokens_in=10,
            tokens_out=5,
            cost_usd=0.001,
            success=True,
        )
        assert metric.stage == "test_stage"
        assert metric.latency_ms == 100.0
        assert metric.tokens_in == 10
        assert metric.tokens_out == 5
        assert metric.cost_usd == 0.001
        assert metric.success is True
        assert metric.quality_score is None
        assert metric.provider is None
        assert metric.model is None
        assert metric.schema_compliance is None

    def test_create_full(self):
        """Test creating a performance metric with all fields."""
        metric = PerformanceMetric(
            timestamp=time.time(),
            stage="test_stage",
            latency_ms=250.5,
            tokens_in=100,
            tokens_out=50,
            cost_usd=0.005,
            success=False,
            quality_score=0.85,
            provider="openai",
            model="gpt-4",
            schema_compliance=True,
        )
        assert metric.quality_score == 0.85
        assert metric.provider == "openai"
        assert metric.model == "gpt-4"
        assert metric.schema_compliance is True
        assert metric.success is False


class TestGrowthMetric:
    """Tests for GrowthMetric dataclass."""

    def test_create(self):
        """Test creating a growth metric."""
        metric = GrowthMetric(
            timestamp=time.time(),
            metric_name="books_processed",
            value=42.0,
            unit="books",
            tags={"author": "test"},
        )
        assert metric.metric_name == "books_processed"
        assert metric.value == 42.0
        assert metric.unit == "books"
        assert metric.tags == {"author": "test"}


class TestBaselineRecorder:
    """Tests for BaselineRecorder class."""

    def test_init_default(self):
        """Test initialization with default storage dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            assert recorder.storage_dir == Path(tmpdir)
            assert recorder.performance_file.exists() is False
            assert recorder.growth_file.exists() is False
            assert recorder.baseline_file.exists() is False

    def test_init_creates_dir(self):
        """Test that storage directory is created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "baselines"
            recorder = BaselineRecorder(storage_dir=str(storage_path))
            assert storage_path.exists()

    def test_record_performance(self):
        """Test recording performance metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            metric = PerformanceMetric(
                timestamp=time.time(),
                stage="annotate",
                latency_ms=150.0,
                tokens_in=50,
                tokens_out=25,
                cost_usd=0.002,
                success=True,
            )
            recorder.record_performance(metric)

            # Check cache
            assert len(recorder._performance_cache) == 1
            assert recorder._performance_cache[0].stage == "annotate"

            # Check file persistence
            assert recorder.performance_file.exists()
            content = recorder.performance_file.read_text()
            assert "annotate" in content

    def test_record_growth(self):
        """Test recording growth metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            metric = GrowthMetric(
                timestamp=time.time(),
                metric_name="books_processed",
                value=10.0,
                unit="books",
                tags={},
            )
            recorder.record_growth(metric)

            assert len(recorder._growth_cache) == 1
            assert recorder._growth_cache[0].metric_name == "books_processed"
            assert recorder.growth_file.exists()

    def test_get_performance_baseline_empty(self):
        """Test getting baseline with no data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            baseline = recorder.get_performance_baseline("annotate")
            assert baseline == {}

    def test_get_performance_basic(self):
        """Test getting baseline with some data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            # Add some metrics
            for i in range(5):
                recorder.record_performance(
                    PerformanceMetric(
                        timestamp=now - i * 3600,
                        stage="synthesize",
                        latency_ms=1000 + i * 50,
                        tokens_in=500,
                        tokens_out=1000,
                        cost_usd=0.005,
                        success=True,
                    )
                )

            baseline = recorder.get_performance_baseline("synthesize", lookback_hours=24)
            assert baseline["count"] == 5
            assert "latency_p50" in baseline
            assert "latency_p95" in baseline
            assert "latency_avg" in baseline
            assert "cost_avg" in baseline
            assert baseline["success_rate"] == 1.0

    def test_get_performance_baseline_filters_stage(self):
        """Test baseline only includes matching stage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            recorder.record_performance(
                PerformanceMetric(timestamp=now, stage="annotate", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
            )
            recorder.record_performance(
                PerformanceMetric(timestamp=now, stage="synthesize", latency_ms=500, tokens_in=0, tokens_out=0, cost_usd=0.0, success=True)
            )

            annotate_baseline = recorder.get_performance_baseline("annotate")
            synthesize_baseline = recorder.get_performance_baseline("synthesize")

            assert annotate_baseline["count"] == 1
            assert synthesize_baseline["count"] == 1

    def test_get_performance_baseline_filters_success(self):
        """Test baseline only includes successful runs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            recorder.record_performance(
                PerformanceMetric(timestamp=now, stage="test", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
            )
            recorder.record_performance(
                PerformanceMetric(timestamp=now, stage="test", latency_ms=200, tokens_in=10, tokens_out=5, cost_usd=0.001, success=False)
            )

            baseline = recorder.get_performance_baseline("test")
            assert baseline["count"] == 1  # Only success counted
            assert baseline["success_rate"] == 1.0

    def test_get_performance_baseline_lookback(self):
        """Test lookback_hours filters old data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            # Old metric (48 hours ago)
            recorder.record_performance(
                PerformanceMetric(timestamp=now - 48 * 3600, stage="test", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
            )
            # Recent metric (1 hour ago)
            recorder.record_performance(
                PerformanceMetric(timestamp=now - 1 * 3600, stage="test", latency_ms=200, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
            )

            # Lookback 24 hours - should only get recent
            baseline = recorder.get_performance_baseline("test", lookback_hours=24)
            assert baseline["count"] == 1
            assert baseline["latency_avg"] == 200

    def test_get_growth_baseline_empty(self):
        """Test growth baseline with no data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            baseline = recorder.get_growth_baseline("books_processed")
            assert baseline == {}

    def test_get_growth_baseline(self):
        """Test growth baseline calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            for i in range(5):
                recorder.record_growth(
                    GrowthMetric(
                        timestamp=now - i * 86400,
                        metric_name="books_processed",
                        value=10 + i * 2.0,
                        unit="books",
                        tags={},
                    )
                )

            baseline = recorder.get_growth_baseline("books_processed", lookback_hours=720)
            assert baseline["count"] == 5
            # Note: latest returns the last cached value (oldest timestamp in our test)
            # because items are appended in chronological order
            assert baseline["latest"] == 18.0  # Oldest value (i=4) is last in cache
            assert baseline["avg"] == 14.0  # (10+12+14+16+18)/5 = 70/5 = 14
            assert baseline["min"] == 10.0
            assert baseline["max"] == 18.0
            assert "trend" in baseline

    def test_check_performance_regression_no_baseline(self):
        """Test regression check with no baseline returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            metric = PerformanceMetric(
                timestamp=time.time(),
                stage="unknown_stage",
                latency_ms=1000,
                tokens_in=500,
                tokens_out=1000,
                cost_usd=0.005,
                success=True,
            )
            result = recorder.check_performance_regression("unknown_stage", metric)
            assert result is None

    def test_check_performance_regression_latency(self):
        """Test regression detection for latency."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            # Establish baseline with consistent latency ~1000ms
            for i in range(10):
                recorder.record_performance(
                    PerformanceMetric(
                        timestamp=now - i * 3600,
                        stage="synthesize",
                        latency_ms=1000,
                        tokens_in=500,
                        tokens_out=1000,
                        cost_usd=0.005,
                        success=True,
                    )
                )

            # Current metric with high latency
            current = PerformanceMetric(
                timestamp=now,
                stage="synthesize",
                latency_ms=1500,  # 50% higher than baseline
                tokens_in=500,
                tokens_out=1000,
                cost_usd=0.005,
                success=True,
            )

            regression = recorder.check_performance_regression("synthesize", current, threshold_pct=20.0)
            assert regression is not None
            assert len(regression["regressions"]) >= 1
            assert any(r["metric"] == "latency" for r in regression["regressions"])

    def test_check_performance_regression_cost(self):
        """Test regression detection for cost."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            # Establish baseline
            for i in range(10):
                recorder.record_performance(
                    PerformanceMetric(
                        timestamp=now - i * 3600,
                        stage="synthesize",
                        latency_ms=1000,
                        tokens_in=500,
                        tokens_out=1000,
                        cost_usd=0.005,
                        success=True,
                    )
                )

            # Current metric with high cost
            current = PerformanceMetric(
                timestamp=now,
                stage="synthesize",
                latency_ms=1000,
                tokens_in=500,
                tokens_out=1000,
                cost_usd=0.01,  # 100% higher
                success=True,
            )

            regression = recorder.check_performance_regression("synthesize", current, threshold_pct=20.0)
            assert regression is not None
            assert any(r["metric"] == "cost" for r in regression["regressions"])

    def test_check_performance_regression_success_rate(self):
        """Test regression detection for success rate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            # Establish baseline with 100% success (10 samples)
            for i in range(10):
                recorder.record_performance(
                    PerformanceMetric(
                        timestamp=now - i * 3600,
                        stage="synthesize",
                        latency_ms=1000,
                        tokens_in=500,
                        tokens_out=1000,
                        cost_usd=0.005,
                        success=True,
                    )
                )

            # Current metric with failure
            current = PerformanceMetric(
                timestamp=now,
                stage="synthesize",
                latency_ms=1000,
                tokens_in=500,
                tokens_out=1000,
                cost_usd=0.005,
                success=False,
            )

            regression = recorder.check_performance_regression("synthesize", current, threshold_pct=20.0)
            # Success rate drops from 1.0 to 0.0, which is >20% drop
            assert regression is not None
            assert any(r["metric"] == "success_rate" for r in regression["regressions"])

    def test_percentile(self):
        """Test percentile calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)

            values = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
            assert recorder._percentile(values, 50) == 6  # median
            assert recorder._percentile(values, 95) == 10  # 95th percentile

            # Edge cases
            assert recorder._percentile([], 50) == 0.0
            assert recorder._percentile([5], 50) == 5

    def test_calculate_trend(self):
        """Test trend calculation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)

            assert recorder._calculate_trend([1, 2, 3, 4, 5]) == "increasing"
            assert recorder._calculate_trend([5, 4, 3, 2, 1]) == "decreasing"
            assert recorder._calculate_trend([5, 5, 5, 5, 5]) == "stable"
            assert recorder._calculate_trend([10]) == "insufficient_data"
            assert recorder._calculate_trend([]) == "insufficient_data"

    def test_save_baselines(self):
        """Test saving baselines to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            recorder.record_performance(
                PerformanceMetric(timestamp=now, stage="annotate", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
            )
            recorder.record_growth(
                GrowthMetric(timestamp=now, metric_name="test_metric", value=42.0, unit="units", tags={})
            )

            recorder.save_baselines()

            assert recorder.baseline_file.exists()
            import json
            with open(recorder.baseline_file) as f:
                baselines = json.load(f)
            assert "performance_annotate" in baselines
            assert "growth_test_metric" in baselines

    def test_get_summary(self):
        """Test getting summary."""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = BaselineRecorder(storage_dir=tmpdir)
            now = time.time()

            recorder.record_performance(
                PerformanceMetric(timestamp=now - 100, stage="test", latency_ms=100, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
            )
            recorder.record_performance(
                PerformanceMetric(timestamp=now, stage="test", latency_ms=200, tokens_in=10, tokens_out=5, cost_usd=0.001, success=True)
            )

            summary = recorder.get_summary()
            assert summary["performance_metrics_count"] == 2
            assert summary["growth_metrics_count"] == 0
            assert summary["storage_dir"] == str(Path(tmpdir))
            assert summary["oldest_performance"] == now - 100
            assert summary["newest_performance"] == now


class TestConvenienceFunctions:
    """Tests for module-level convenience functions."""

    def test_record_stage_performance(self):
        """Test record_stage_performance convenience function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Patch the global recorder to use our temp dir
            import src.audiobook_studio.monitoring.baseline as baseline_mod
            original_recorder = baseline_mod._recorder
            baseline_mod._recorder = BaselineRecorder(storage_dir=tmpdir)

            try:
                metric = record_stage_performance(
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
                assert metric.stage == "test_convenience"
                assert metric.latency_ms == 123.4
                assert metric.quality_score == 0.95
            finally:
                baseline_mod._recorder = original_recorder

    def test_record_growth_metric(self):
        """Test record_growth_metric convenience function."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import src.audiobook_studio.monitoring.baseline as baseline_mod
            original_recorder = baseline_mod._recorder
            baseline_mod._recorder = BaselineRecorder(storage_dir=tmpdir)

            try:
                metric = record_growth_metric(
                    metric_name="test_growth",
                    value=100.0,
                    unit="items",
                    tags={"key": "value"},
                )
                assert metric.metric_name == "test_growth"
                assert metric.value == 100.0
                assert metric.unit == "items"
                assert metric.tags == {"key": "value"}
            finally:
                baseline_mod._recorder = original_recorder

    def test_get_baseline_recorder_singleton(self):
        """Test get_baseline_recorder returns singleton."""
        import src.audiobook_studio.monitoring.baseline as baseline_mod
        original_recorder = baseline_mod._recorder
        baseline_mod._recorder = None

        try:
            r1 = get_baseline_recorder()
            r2 = get_baseline_recorder()
            assert r1 is r2
        finally:
            baseline_mod._recorder = original_recorder


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""Tests for Compliance Monitoring."""

import tempfile
from pathlib import Path

import pytest

from src.audiobook_studio.monitoring.compliance import (
    ComplianceMonitor,
    ComplianceRecord,
    StageComplianceSummary,
    get_compliance_monitor,
    record_pipeline_compliance,
)


class TestComplianceMonitor:
    """Test ComplianceMonitor class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.monitor = ComplianceMonitor(storage_path=self.temp_dir)

    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_creates_storage_dir(self):
        """Test monitor creates storage directory."""
        assert self.monitor.storage_path.exists()

    def test_record_compliance(self):
        """Test recording a compliance check."""
        record = self.monitor.record(
            stage="extract",
            schema_compliance=True,
            contract_version=1,
            quality_score=0.95,
            latency_ms=100.0,
            cost_usd=0.001,
        )

        assert isinstance(record, ComplianceRecord)
        assert record.stage == "extract"
        assert record.schema_compliance is True
        assert record.contract_version == 1
        assert record.quality_score == 0.95

        # Check stage summary updated
        summary = self.monitor.get_stage_summary("extract")
        assert summary is not None
        assert summary.total_calls == 1
        assert summary.compliant_calls == 1
        assert summary.compliance_rate == 1.0

    def test_record_non_compliance(self):
        """Test recording a non-compliant check."""
        record = self.monitor.record(
            stage="analyze",
            schema_compliance=False,
            contract_version=1,
            quality_score=0.5,
            errors=["missing_field", "type_mismatch"],
        )

        assert record.schema_compliance is False
        assert record.errors == ["missing_field", "type_mismatch"]

        summary = self.monitor.get_stage_summary("analyze")
        assert summary is not None
        assert summary.total_calls == 1
        assert summary.compliant_calls == 0
        assert summary.compliance_rate == 0.0
        assert summary.error_counts["missing_field"] == 1
        assert summary.error_counts["type_mismatch"] == 1

    def test_multiple_calls_aggregation(self):
        """Test multiple calls aggregate correctly."""
        for i in range(5):
            self.monitor.record(
                stage="annotate",
                schema_compliance=i < 4,  # 4 compliant, 1 not
                contract_version=1,
                quality_score=0.9,
                latency_ms=50.0,
            )

        summary = self.monitor.get_stage_summary("annotate")
        assert summary.total_calls == 5
        assert summary.compliant_calls == 4
        assert summary.compliance_rate == 0.8
        assert summary.avg_latency_ms == 50.0

    def test_get_all_summaries(self):
        """Test getting all stage summaries."""
        stages = ["extract", "analyze", "annotate"]
        for stage in stages:
            self.monitor.record(stage=stage, schema_compliance=True)

        summaries = self.monitor.get_all_summaries()
        assert len(summaries) == 3
        for stage in stages:
            assert stage in summaries

    def test_overall_compliance_rate(self):
        """Test overall compliance rate calculation."""
        self.monitor.record("extract", True)
        self.monitor.record("analyze", True)
        self.monitor.record("annotate", False)

        overall = self.monitor.get_overall_compliance_rate()
        assert overall == 2 / 3

    def test_contract_version_distribution(self):
        """Test contract version distribution."""
        self.monitor.record("extract", True, contract_version=1)
        self.monitor.record("analyze", True, contract_version=1)
        self.monitor.record("annotate", True, contract_version=2)

        dist = self.monitor.get_contract_version_distribution()
        assert dist[1] == 2
        assert dist[2] == 1

    def test_check_thresholds(self):
        """Test threshold checking."""
        # Add compliant records
        for _ in range(9):
            self.monitor.record("extract", True, quality_score=0.9)
        # Add one non-compliant
        self.monitor.record("extract", False, quality_score=0.5)

        # Should pass at 0.8 compliance rate
        result = self.monitor.check_thresholds(min_compliance_rate=0.8, min_quality_score=0.7)
        assert result["overall_pass"] is True
        assert result["stage_results"]["extract"]["pass"] is True

        # Should fail at 0.95 compliance rate
        result = self.monitor.check_thresholds(min_compliance_rate=0.95, min_quality_score=0.7)
        assert result["overall_pass"] is False
        assert result["stage_results"]["extract"]["pass"] is False

    def test_export_report(self):
        """Test exporting compliance report."""
        self.monitor.record("extract", True, quality_score=0.95)
        self.monitor.record("analyze", False, quality_score=0.5, errors=["test_error"])

        report_path = self.monitor.export_report()

        assert Path(report_path).exists()
        import json

        with open(report_path) as f:
            report = json.load(f)

        assert report["total_records"] == 2
        assert "stage_summaries" in report
        assert "extract" in report["stage_summaries"]
        assert "analyze" in report["stage_summaries"]

    def test_reset(self):
        """Test resetting monitor."""
        self.monitor.record("extract", True)
        self.monitor.reset()

        assert len(self.monitor.records) == 0
        assert len(self.monitor.stage_summaries) == 0


class TestConvenienceFunctions:
    """Test convenience functions."""

    def setup_method(self):
        """Reset global monitor."""
        import src.audiobook_studio.monitoring.compliance as compliance_module

        compliance_module._global_monitor = None

    def test_get_compliance_monitor(self):
        """Test getting global monitor."""
        monitor = get_compliance_monitor()
        assert isinstance(monitor, ComplianceMonitor)

    def test_record_pipeline_compliance(self):
        """Test convenience record function."""
        record = record_pipeline_compliance(
            stage="edit",
            schema_compliance=True,
            contract_version=1,
            quality_score=0.9,
        )

        assert isinstance(record, ComplianceRecord)
        assert record.stage == "edit"

        # Verify it used global monitor
        monitor = get_compliance_monitor()
        summary = monitor.get_stage_summary("edit")
        assert summary.total_calls == 1


class TestStageComplianceSummary:
    """Test StageComplianceSummary dataclass."""

    def test_properties(self):
        """Test computed properties."""
        summary = StageComplianceSummary(
            stage="test",
            total_calls=10,
            compliant_calls=8,
            total_latency_ms=1000.0,
            total_cost_usd=0.05,
            total_quality_score=8.5,
        )

        assert summary.compliance_rate == 0.8
        assert summary.avg_latency_ms == 100.0
        assert summary.avg_cost_usd == 0.005
        assert summary.avg_quality_score == 0.85

    def test_empty_summary(self):
        """Test empty summary."""
        summary = StageComplianceSummary(stage="test")
        assert summary.compliance_rate == 0.0
        assert summary.avg_latency_ms == 0.0
        assert summary.avg_quality_score == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

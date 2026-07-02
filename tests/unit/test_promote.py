"""Tests for promote.py - Canary Release & Promotion Gate."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest
from scripts.promote import (
    CanaryConfig,
    CanaryMetrics,
    CanaryRelease,
    PromotionGate,
    PromotionGateResult,
    PromotionMetrics,
    VersionStore,
    cmd_canary_complete,
    cmd_canary_record,
    cmd_canary_start,
    cmd_evaluate,
    cmd_history,
    cmd_rollback,
    cmd_status,
)


class TestPromotionGate:
    """Tests for PromotionGate class."""

    def test_gate_initialization(self):
        gate = PromotionGate(
            format_compliance_threshold=0.99,
            golden_dataset_threshold=0.95,
            quality_score_threshold=1.02,
            human_preference_threshold=0.80,
        )
        assert gate.format_compliance_threshold == 0.99
        assert gate.golden_dataset_threshold == 0.95
        assert gate.quality_score_threshold == 1.02
        assert gate.human_preference_threshold == 0.80

    def test_evaluate_all_pass(self):
        gate = PromotionGate()
        result = gate.evaluate(
            format_compliance_rate=0.995,
            golden_dataset_pass_rate=0.96,
            quality_score_ratio=1.03,
            human_preference_score=0.85,
        )
        assert result.passed is True
        assert len(result.failed_criteria) == 0
        assert result.metrics.format_compliance_rate == 0.995

    def test_evaluate_format_fail(self):
        gate = PromotionGate()
        result = gate.evaluate(
            format_compliance_rate=0.98,  # < 0.99
            golden_dataset_pass_rate=0.96,
            quality_score_ratio=1.03,
            human_preference_score=0.85,
        )
        assert result.passed is False
        assert len(result.failed_criteria) == 1
        assert "格式合规率" in result.failed_criteria[0]

    def test_evaluate_multiple_fail(self):
        gate = PromotionGate()
        result = gate.evaluate(
            format_compliance_rate=0.98,
            golden_dataset_pass_rate=0.90,
            quality_score_ratio=1.01,
            human_preference_score=0.75,
        )
        assert result.passed is False
        assert len(result.failed_criteria) == 4

    def test_evaluate_from_dict(self):
        gate = PromotionGate()
        metrics_dict = {
            "format_compliance_rate": 0.992,
            "golden_dataset_pass_rate": 0.97,
            "quality_score_ratio": 1.025,
            "human_preference_score": 0.82,
        }
        result = gate.evaluate_from_dict(metrics_dict)
        assert result.passed is True

    def test_get_status(self):
        gate = PromotionGate()
        status = gate.get_status()
        assert "thresholds" in status
        assert status["thresholds"]["format_compliance"] == 0.99


class TestCanaryRelease:
    """Tests for CanaryRelease class."""

    def test_start_canary(self):
        config = CanaryConfig(traffic_percentage=0.1, min_samples=100)
        canary = CanaryRelease(config)
        success = canary.start_canary("edit_for_tts", "v2", 0.85)
        assert success is True

        status = canary.get_canary_status("edit_for_tts", "v2")
        assert status is not None
        assert status["status"] == "running"
        assert status["baseline_score"] == 0.85

    def test_cannot_start_duplicate(self):
        config = CanaryConfig()
        canary = CanaryRelease(config)
        canary.start_canary("edit_for_tts", "v2", 0.85)
        success = canary.start_canary("edit_for_tts", "v2", 0.85)
        assert success is False

    def test_record_metrics_no_rollback(self):
        config = CanaryConfig(min_samples=100, rollback_threshold=0.95)
        canary = CanaryRelease(config)
        canary.start_canary("edit_for_tts", "v2", 0.85)

        metrics = CanaryMetrics(
            version="v2",
            stage="edit_for_tts",
            samples_collected=150,
            avg_quality_score=0.87,
            baseline_quality_score=0.85,
            quality_ratio=0.87 / 0.85,
            error_rate=0.02,
            timestamp=datetime.now(timezone.utc),
        )
        canary.record_metrics("edit_for_tts", "v2", metrics)

        status = canary.get_canary_status("edit_for_tts", "v2")
        assert status["status"] == "running"

    def test_record_metrics_triggers_rollback(self):
        config = CanaryConfig(min_samples=100, rollback_threshold=0.95)
        canary = CanaryRelease(config)
        canary.start_canary("edit_for_tts", "v2", 0.85)

        # Quality drops below threshold
        metrics = CanaryMetrics(
            version="v2",
            stage="edit_for_tts",
            samples_collected=150,
            avg_quality_score=0.78,  # 0.78/0.85 = 0.917 < 0.95
            baseline_quality_score=0.85,
            quality_ratio=0.78 / 0.85,
            error_rate=0.02,
            timestamp=datetime.now(timezone.utc),
        )
        canary.record_metrics("edit_for_tts", "v2", metrics)

        status = canary.get_canary_status("edit_for_tts", "v2")
        assert status["status"] == "rolled_back"
        assert "rollback_reason" in status

    def test_record_metrics_high_error_rate_rollback(self):
        config = CanaryConfig(min_samples=100, rollback_threshold=0.95)
        canary = CanaryRelease(config)
        canary.start_canary("edit_for_tts", "v2", 0.85)

        # High error rate triggers rollback
        metrics = CanaryMetrics(
            version="v2",
            stage="edit_for_tts",
            samples_collected=150,
            avg_quality_score=0.87,
            baseline_quality_score=0.85,
            quality_ratio=0.87 / 0.85,
            error_rate=0.15,  # > 0.1
            timestamp=datetime.now(timezone.utc),
        )
        canary.record_metrics("edit_for_tts", "v2", metrics)

        status = canary.get_canary_status("edit_for_tts", "v2")
        assert status["status"] == "rolled_back"

    def test_insufficient_samples_no_rollback(self):
        config = CanaryConfig(min_samples=100, rollback_threshold=0.95)
        canary = CanaryRelease(config)
        canary.start_canary("edit_for_tts", "v2", 0.85)

        # Not enough samples yet
        metrics = CanaryMetrics(
            version="v2",
            stage="edit_for_tts",
            samples_collected=50,  # < 100
            avg_quality_score=0.50,  # Very bad but insufficient samples
            baseline_quality_score=0.85,
            quality_ratio=0.50 / 0.85,
            error_rate=0.02,
            timestamp=datetime.now(timezone.utc),
        )
        canary.record_metrics("edit_for_tts", "v2", metrics)

        status = canary.get_canary_status("edit_for_tts", "v2")
        assert status["status"] == "running"  # No rollback yet

    def test_complete_canary(self):
        config = CanaryConfig()
        canary = CanaryRelease(config)
        canary.start_canary("edit_for_tts", "v2", 0.85)
        success = canary.complete_canary("edit_for_tts", "v2")
        assert success is True

        status = canary.get_canary_status("edit_for_tts", "v2")
        assert status["status"] == "completed"

    def test_complete_nonexistent(self):
        config = CanaryConfig()
        canary = CanaryRelease(config)
        success = canary.complete_canary("edit_for_tts", "v2")
        assert success is False


class TestVersionStore:
    """Tests for VersionStore class."""

    @pytest.fixture
    def temp_prompts(self, tmp_path):
        """Create temporary prompts directory structure."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()

        # Create stage directories with version files
        for stage in ["edit_for_tts", "quality_judge", "annotate_paragraph"]:
            stage_dir = prompts_dir / stage
            stage_dir.mkdir()
            for v in [1, 2]:
                (stage_dir / f"v{v}.j2").write_text(f"prompt v{v}")

        return prompts_dir

    def test_scan_current_versions(self, temp_prompts):
        store = VersionStore(temp_prompts)
        assert store.get_current_version("edit_for_tts") == 2
        assert store.get_current_version("quality_judge") == 2
        assert store.get_current_version("annotate_paragraph") == 2

    def test_promote_version(self, temp_prompts):
        store = VersionStore(temp_prompts)
        # Add v3 file
        (temp_prompts / "edit_for_tts" / "v3.j2").write_text("prompt v3")

        success = store.promote_version("edit_for_tts", 3)
        assert success is True
        assert store.get_current_version("edit_for_tts") == 3

    def test_promote_lower_version_fails(self, temp_prompts):
        store = VersionStore(temp_prompts)
        success = store.promote_version("edit_for_tts", 1)  # Already at v2
        assert success is False
        assert store.get_current_version("edit_for_tts") == 2

    def test_rollback_version(self, temp_prompts):
        store = VersionStore(temp_prompts)
        success = store.rollback_version("edit_for_tts", 1)
        assert success is True
        assert store.get_current_version("edit_for_tts") == 1

    def test_rollback_invalid_target(self, temp_prompts):
        store = VersionStore(temp_prompts)
        success = store.rollback_version("edit_for_tts", 3)  # Target >= current
        assert success is False

    def test_rollback_last(self, temp_prompts):
        store = VersionStore(temp_prompts)
        success = store.rollback_last("edit_for_tts")
        assert success is True
        assert store.get_current_version("edit_for_tts") == 1

    def test_rollback_at_v1(self, temp_prompts):
        store = VersionStore(temp_prompts)
        # First rollback to v1
        store.rollback_last("edit_for_tts")
        # Try to rollback again
        success = store.rollback_last("edit_for_tts")
        assert success is False

    def test_rollback_log_created(self, temp_prompts):
        store = VersionStore(temp_prompts)
        store.rollback_version("edit_for_tts", 1)

        rollback_log = temp_prompts / "rollback_log.jsonl"
        assert rollback_log.exists()

        content = rollback_log.read_text()
        entry = json.loads(content.strip())
        assert entry["stage"] == "edit_for_tts"
        assert entry["from_version"] == 2
        assert entry["to_version"] == 1
        assert entry["action"] == "rollback"

    def test_get_rollback_history(self, temp_prompts):
        store = VersionStore(temp_prompts)
        store.rollback_version("edit_for_tts", 1)
        store.promote_version("edit_for_tts", 2)  # Log promotion
        history = store.get_rollback_history("edit_for_tts")
        assert len(history) == 2


class TestCLICommands:
    """Tests for CLI command functions."""

    def test_cmd_evaluate_pass(self, capsys):
        class Args:
            stage = "edit_for_tts"
            format = 0.995
            golden = 0.96
            quality = 1.03
            human = 0.85
            threshold_format = 0.99
            threshold_golden = 0.95
            threshold_quality = 1.02
            threshold_human = 0.80

        result = cmd_evaluate(Args())
        assert result == 0

    def test_cmd_evaluate_fail(self, capsys):
        class Args:
            stage = "edit_for_tts"
            format = 0.98
            golden = 0.96
            quality = 1.03
            human = 0.85
            threshold_format = 0.99
            threshold_golden = 0.95
            threshold_quality = 1.02
            threshold_human = 0.80

        result = cmd_evaluate(Args())
        assert result == 1

    def test_cmd_canary_start(self):
        class Args:
            stage = "edit_for_tts"
            version = "v2"
            baseline = 0.85
            traffic = 0.1
            min_samples = 100
            rollback_threshold = 0.95

        result = cmd_canary_start(Args())
        assert result == 0

    def test_cmd_canary_record_no_rollback(self):
        class Args:
            stage = "edit_for_tts"
            version = "v2"
            samples = 150
            quality = 0.87
            baseline = 0.85
            errors = 0.02

        result = cmd_canary_record(Args())
        assert result == 0

    def test_cmd_canary_record_with_rollback(self):
        # Need to start canary first - use same CanaryRelease instance
        from datetime import datetime, timezone

        from src.audiobook_studio.feedback.release import CanaryConfig, CanaryMetrics, CanaryRelease

        config = CanaryConfig(rollback_threshold=0.95)
        canary = CanaryRelease(config)
        canary.start_canary("edit_for_tts", "v2", 0.85)

        # Now record metrics that should trigger rollback
        metrics = CanaryMetrics(
            version="v2",
            stage="edit_for_tts",
            samples_collected=150,
            avg_quality_score=0.78,  # Below threshold (0.78/0.85 = 0.9176 < 0.95)
            baseline_quality_score=0.85,
            quality_ratio=0.78 / 0.85,
            error_rate=0.02,
            timestamp=datetime.now(timezone.utc),
        )
        canary.record_metrics("edit_for_tts", "v2", metrics)

        # Check status
        status = canary.get_canary_status("edit_for_tts", "v2")
        assert status is not None
        assert status.get("status") == "rolled_back"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

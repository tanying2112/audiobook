"""Unit tests for src/audiobook_studio/feedback/ab_test_manager.py."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.feedback.ab_test_manager import ABTestConfig, ABTestManager, ABTestResult


class TestABTestManager:
    def test_init_creates_directory(self, tmp_path):
        """Test that ABTestManager creates the results directory."""
        results_dir = tmp_path / "test_results"
        assert not results_dir.exists()

        with patch("src.audiobook_studio.feedback.ab_test_manager.logger"):
            manager = ABTestManager(str(results_dir))

        assert results_dir.exists()
        assert manager.results_dir == results_dir.resolve()
        assert manager.test_history == []

    def test_run_comparison_test_default_parameters(self):
        """Test run_comparison_test with default parameters."""
        with (
            patch("src.audiobook_studio.feedback.ab_test_manager.logger"),
            patch.object(ABTestManager, "_execute_ab_test") as mock_execute,
            patch.object(ABTestManager, "_save_test_result") as mock_save,
        ):

            mock_execute.return_value = ABTestResult(
                test_id="test123",
                variant_a_score=0.8,
                variant_b_score=0.85,
                winner="B",
                confidence=0.9,
                p_value=0.05,
                details=[],
                timestamp=datetime.now(),
                passed_quality_gate=True,
            )

            manager = ABTestManager("/tmp/test")
            result = manager.run_comparison_test(current_prompt="current", proposed_prompt="proposed")

            # Check that the mocks were called
            mock_execute.assert_called_once()
            mock_save.assert_called_once()

            # Check the returned structure
            assert "test_id" in result
            assert result["test_id"] == "test123"
            assert result["winner"] == "B"
            assert result["confidence"] == 0.9
            assert result["passed_quality_gate"] is True
            assert "variant_a" in result
            assert "variant_b" in result
            assert "details" in result

    def test_run_comparison_test_custom_segments_and_criteria(self):
        """Test run_comparison_test with custom segments and criteria."""
        with (
            patch("src.audiobook_studio.feedback.ab_test_manager.logger"),
            patch.object(ABTestManager, "_execute_ab_test") as mock_execute,
            patch.object(ABTestManager, "_save_test_result"),
        ):

            mock_execute.return_value = ABTestResult(
                test_id="test456",
                variant_a_score=0.7,
                variant_b_score=0.75,
                winner="B",
                confidence=0.8,
                p_value=0.1,
                details=[],
                timestamp=datetime.now(),
                passed_quality_gate=False,
            )

            manager = ABTestManager("/tmp/test")
            custom_segments = ["segment1", "segment2"]
            custom_criteria = ["criteria1", "criteria2"]

            result = manager.run_comparison_test(
                current_prompt="current",
                proposed_prompt="proposed",
                test_name="test",
                test_segments=custom_segments,
                judge_criteria=custom_criteria,
            )

            # Check that the config passed to _execute_ab_test has the custom values
            called_args = mock_execute.call_args[0][0]  # First positional arg
            assert isinstance(called_args, ABTestConfig)
            assert called_args.test_segments == custom_segments
            assert called_args.judge_criteria == custom_criteria
            assert called_args.name == "test"

    def test_execute_ab_test_mocked(self):
        """Test _execute_ab_test with mocked random to get deterministic results."""
        with (
            patch("src.audiobook_studio.feedback.ab_test_manager.logger"),
            patch("random.uniform") as mock_uniform,
            patch("random.random") as mock_random,
        ):

            # Make the random values deterministic
            mock_uniform.side_effect = [0.8, 0.05, 0.85, 0.02, 0.75, 0.03, 0.88, 0.01]  # enough calls
            mock_random.return_value = 0.5  # less than 0.6, so B will be better

            manager = ABTestManager("/tmp/test")
            config = ABTestConfig(
                test_id="test123",
                name="test",
                description="desc",
                variant_a_prompt="A",
                variant_b_prompt="B",
                test_segments=["seg1", "seg2"],
                judge_criteria=["c1", "c2"],
                sample_size=2,
                confidence_threshold=0.8,
            )

            result = manager._execute_ab_test(config)

            # Check that we got a result
            assert isinstance(result, ABTestResult)
            assert result.test_id == "test123"
            assert isinstance(result.variant_a_score, float)
            assert isinstance(result.variant_b_score, float)
            assert result.winner in ("A", "B", "TIE")
            assert 0.0 <= result.confidence <= 1.0
            assert 0.0 <= result.p_value <= 1.0
            assert isinstance(result.details, list)
            assert len(result.details) == 2  # two segments

    def test_save_test_result(self, tmp_path):
        """Test _save_test_result creates files."""
        with (
            patch("src.audiobook_studio.feedback.ab_test_manager.logger"),
            patch("src.audiobook_studio.feedback.ab_test_manager.json.dump") as mock_dump,
        ):

            manager = ABTestManager(str(tmp_path))
            # Provide a detailed result with all expected fields
            result = ABTestResult(
                test_id="test123",
                variant_a_score=0.8,
                variant_b_score=0.9,
                winner="B",
                confidence=0.85,
                p_value=0.02,
                details=[
                    {
                        "segment_id": 0,
                        "segment_preview": "主人公走进了昏暗的房间，心跳急剧加速。",
                        "variant_a_score": 0.75,
                        "variant_b_score": 0.85,
                        "winner": "B",
                        "score_difference": 0.1,
                    }
                ],
                timestamp=datetime(2023, 1, 1, 12, 0, 0),
                passed_quality_gate=True,
            )

            # Mock the file operations
            with patch("builtins.open", mock_open()) as mock_file:
                manager._save_test_result(result)

                # Check that open was called twice (JSON and HTML)
                assert mock_file.call_count == 2
                # Check that json.dump was called
                mock_dump.assert_called_once()

    def test_get_recent_tests_empty(self):
        """Test get_recent_tests when no tests have been run."""
        with patch("src.audiobook_studio.feedback.ab_test_manager.logger"):
            manager = ABTestManager("/tmp/test")

        recent = manager.get_recent_tests(5)
        assert recent == []

    def test_get_recent_tests_with_data(self):
        """Test get_recent_tests with some test history."""
        with patch("src.audiobook_studio.feedback.ab_test_manager.logger"):
            manager = ABTestManager("/tmp/test")
            # Add some mock results
            manager.test_history = [
                ABTestResult(
                    test_id="test1",
                    variant_a_score=0.8,
                    variant_b_score=0.85,
                    winner="B",
                    confidence=0.9,
                    p_value=0.01,
                    details=[],
                    timestamp=datetime(2023, 1, 1, 12, 0, 0),
                    passed_quality_gate=True,
                ),
                ABTestResult(
                    test_id="test2",
                    variant_a_score=0.7,
                    variant_b_score=0.65,
                    winner="A",
                    confidence=0.75,
                    p_value=0.05,
                    details=[],
                    timestamp=datetime(2023, 1, 2, 12, 0, 0),
                    passed_quality_gate=False,
                ),
            ]

        recent = manager.get_recent_tests(1)
        assert len(recent) == 1
        assert recent[0]["test_id"] == "test2"
        assert recent[0]["winner"] == "A"

        recent = manager.get_recent_tests(5)
        assert len(recent) == 2
        assert recent[0]["test_id"] == "test2"  # most recent first
        assert recent[1]["test_id"] == "test1"

    def test_get_status(self):
        """Test get_status returns expected structure."""
        with patch("src.audiobook_studio.feedback.ab_test_manager.logger"):
            manager = ABTestManager("/tmp/test")

        status = manager.get_status()
        assert "results_dir" in status
        assert status["results_dir"] == "/tmp/test"
        assert status["tests_run"] == 0
        assert isinstance(status["recent_tests"], list)
        assert len(status["recent_tests"]) == 0
        assert "description" in status


# Helper to mock open for file writing
from unittest.mock import mock_open

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

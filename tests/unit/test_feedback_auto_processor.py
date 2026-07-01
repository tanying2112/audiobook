"""Unit tests for feedback/auto_processor.py."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

import pytest

from src.audiobook_studio.feedback.auto_processor import (
    FeedbackAutoProcessor,
    create_auto_processor,
    run_feedback_analysis_cli,
)
from src.audiobook_studio.feedback.processor import AggregateAnalysis


class TestFeedbackAutoProcessor:
    def test_init_sets_attributes(self):
        """Test that __init__ sets all attributes correctly."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=42,
            min_feedback_count=5,
            check_interval_seconds=100,
            enable_auto_trigger=False,
        )

        assert processor.db_session_factory == db_session_factory
        assert processor.project_id == 42
        assert processor.min_feedback_count == 5
        assert processor.check_interval_seconds == 100
        assert processor.enable_auto_trigger is False
        assert processor._stop_event is not None
        assert processor._worker_thread is None
        assert processor._last_analysis_count == 0
        assert processor._feedback_dir.name == "raw"
        assert "feedback" in str(processor._feedback_dir)

    def test_start_when_disabled_does_not_start_worker(self, caplog):
        """Test that start() does not start worker when disabled."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
            enable_auto_trigger=False,
        )

        with caplog.at_level("INFO"):
            processor.start()

        assert processor._worker_thread is None
        assert "Auto-trigger disabled, not starting worker" in caplog.text

    def test_start_when_already_running_warns(self, caplog):
        """Test that start() warns when worker is already running."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
            enable_auto_trigger=True,
        )
        # Simulate an existing thread
        processor._worker_thread = MagicMock()
        processor._worker_thread.is_alive.return_value = True

        with caplog.at_level("WARNING"):
            processor.start()

        assert "Worker already running" in caplog.text
        # Should not create a new thread
        assert processor._worker_thread is not None
        assert processor._worker_thread.is_alive.called

    def test_start_creates_and_starts_thread(self):
        """Test that start() creates and starts a worker thread."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
            enable_auto_trigger=True,
        )

        # Mock the Thread class to capture arguments
        with patch("threading.Thread") as mock_thread_class:
            mock_thread_instance = MagicMock()
            mock_thread_class.return_value = mock_thread_instance
            mock_thread_instance.is_alive.return_value = False  # Not alive initially

            processor.start()

            # Verify thread was created with correct target and daemon flag
            mock_thread_class.assert_called_once()
            args, kwargs = mock_thread_class.call_args
            assert kwargs["target"] == processor._monitor_loop
            assert kwargs["daemon"] is True
            # Verify thread was started
            mock_thread_instance.start.assert_called_once()

    def test_stop_sets_stop_event_and_joins_thread(self):
        """Test that stop() sets stop event and joins the thread."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
            enable_auto_trigger=True,
        )
        # Setup a mock thread
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        processor._worker_thread = mock_thread
        processor._stop_event = MagicMock()

        processor.stop()

        # Verify stop event was set
        processor._stop_event.set.assert_called_once()
        # Verify join was called with timeout
        mock_thread.join.assert_called_once_with(timeout=10)

    def test_stop_when_not_running_does_nothing(self):
        """Test that stop() does nothing when worker is not running."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
            enable_auto_trigger=True,
        )
        # No thread or thread not alive
        processor._worker_thread = None
        processor._stop_event = MagicMock()

        # Should not raise
        processor.stop()
        # Should not call set or join
        processor._stop_event.set.assert_not_called()
        if processor._worker_thread:
            processor._worker_thread.join.assert_not_called()

    def test_worker_thread_alive_when_thread_exists_and_alive(self):
        """Test _worker_thread_alive returns True when thread is alive."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
        )
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        processor._worker_thread = mock_thread

        assert processor._worker_thread_alive() is True

    def test_worker_thread_alive_false_when_thread_none_or_not_alive(self):
        """Test _worker_thread_alive returns False when thread is None or not alive."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
        )

        # Case 1: thread is None
        processor._worker_thread = None
        assert processor._worker_thread_alive() is False

        # Case 2: thread exists but not alive
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = False
        processor._worker_thread = mock_thread
        assert processor._worker_thread_alive() is False

    def test_check_and_trigger_does_nothing_when_below_threshold(self):
        """Test _check_and_trigger does nothing when feedback count is below threshold."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
            min_feedback_count=10,
        )
        # Mock the database session and query
        mock_db = MagicMock()
        db_session_factory.return_value = mock_db
        # Mock list_unprocessed_feedback to return fewer than threshold
        with patch(
            "src.audiobook_studio.feedback.auto_processor.list_unprocessed_feedback",
            return_value=[1, 2, 3],  # 3 items
        ) as mock_list:
            processor._check_and_trigger()
            # Should not call _trigger_analysis
            # We can't directly assert on _trigger_analysis because it's called via db session,
            # but we can check that the count didn't change
            assert processor._last_analysis_count == 0

    def test_check_and_trigger_triggers_when_above_threshold_and_count_changed(self):
        """Test _check_and_trigger triggers analysis when count reaches threshold and changed."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
            min_feedback_count=10,
        )
        mock_db = MagicMock()
        db_session_factory.return_value = mock_db

        # Mock list_unprocessed_feedback to return 12 items (above threshold)
        fake_feedback = list(range(12))
        with patch(
            "src.audiobook_studio.feedback.auto_processor.list_unprocessed_feedback",
            return_value=fake_feedback,
        ) as mock_list, patch.object(
            processor, "_trigger_analysis", return_value="result"
        ) as mock_trigger:
            processor._check_and_trigger()
            # Should have called _trigger_analysis
            mock_trigger.assert_called_once_with(mock_db)
            # Should have updated last_analysis_count
            assert processor._last_analysis_count == 12

    def test_check_and_trigger_does_not_trigger_if_count_same_even_if_above_threshold(self):
        """Test _check_and_trigger does not trigger if count unchanged."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
            min_feedback_count=10,
        )
        processor._last_analysis_count = 15  # Already at 15
        mock_db = MagicMock()
        db_session_factory.return_value = mock_db

        # Still 15 unprocessed (same as last_analysis_count)
        fake_feedback = list(range(15))
        with patch(
            "src.audiobook_studio.feedback.auto_processor.list_unprocessed_feedback",
            return_value=fake_feedback,
        ), patch.object(processor, "_trigger_analysis") as mock_trigger:
            processor._check_and_trigger()
            # Should NOT have called _trigger_analysis
            mock_trigger.assert_not_called()
            # last_analysis_count should remain unchanged
            assert processor._last_analysis_count == 15

    def test_trigger_analysis_calls_analyze_batch_and_saves_report(self):
        """Test _trigger_analysis calls analyze_batch and saves report."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
        )
        mock_db = MagicMock()
        # Mock analyze_batch to return a fake result
        fake_analysis = MagicMock(spec=AggregateAnalysis)
        fake_analysis.total_analyzed = 5
        fake_analysis.pattern_frequency = {"pattern1": 3}
        fake_analysis.stage_distribution = {"stage1": 2}
        fake_analysis.top_patterns = [("pattern1", 3)]
        fake_analysis.recommendations = ["rec1"]
        fake_analysis.generated_at = datetime.now(timezone.utc)

        with patch(
            "src.audiobook_studio.feedback.auto_processor.analyze_batch",
            return_value=fake_analysis,
        ) as mock_analyze, patch.object(
            processor, "_save_analysis_report", return_path=Path("/tmp/report.json")
        ) as mock_save:
            result = processor._trigger_analysis(mock_db)

            # Should have called analyze_batch with correct args
            mock_analyze.assert_called_once_with(
                mock_db, project_id=1, limit=1000
            )
            # Should have called _save_analysis_report with the analysis
            mock_save.assert_called_once_with(fake_analysis)
            # Should have returned the analysis
            assert result == fake_analysis

    def test_trigger_analysis_returns_none_on_exception(self):
        """Test _trigger_analysis returns None if analyze_batch raises."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
        )
        mock_db = MagicMock()
        # Make analyze_batch raise an exception
        with patch(
            "src.audiobook_studio.feedback.auto_processor.analyze_batch",
            side_effect=Exception("DB error"),
        ):
            result = processor._trigger_analysis(mock_db)
            # Should return None on error
            assert result is None

    def test_save_analysis_report_creates_file_with_correct_content(self):
        """Test _save_analysis_report writes correct JSON to file."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=99,
        )
        # Create a fake analysis object
        fixed_time = "2023-01-01T12:00:00+00:00"
        fake_analysis = MagicMock(spec=AggregateAnalysis)
        fake_analysis.total_analyzed = 42
        fake_analysis.pattern_frequency = {"patA": 10, "patB": 5}
        fake_analysis.stage_distribution = {"stageX": 20, "stageY": 22}
        fake_analysis.top_patterns = [("patA", 10), ("patB", 5)]
        fake_analysis.recommendations = ["rec1", "rec2"]
        fake_analysis.generated_at = fixed_time

        with patch(
            "src.audiobook_studio.feedback.auto_processor.Path.mkdir"
        ) as mock_mkdir, patch(
            "builtins.open", mock_open()
        ) as mock_file:
            # We need to mock the _feedback_dir as well
            with patch.object(
                processor, "_feedback_dir", Path("/tmp/fake/feedback/raw")
            ):
                result_path = processor._save_analysis_report(fake_analysis)

                # Should have called mkdir on the analysis directory
                mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
                # The file path should be under analysis directory
                expected_dir = Path("/tmp/fake/feedback/analysis")
                assert result_path.parent == expected_dir
                assert result_path.name.startswith("analysis_")
                assert result_path.name.endswith(".json")
                # Should have written JSON content
                handle = mock_file()
                assert handle.write.call_count > 0
                written_json = "".join(call.args[0] for call in handle.write.call_args_list)
                data = json.loads(written_json)
                assert data["project_id"] == 99
                assert data["total_analyzed"] == 42
                assert data["pattern_frequency"] == {"patA": 10, "patB": 5}
                assert data["stage_distribution"] == {"stageX": 20, "stageY": 22}
                assert data["top_patterns"] == [["patA", 10], ["patB", 5]]
                assert data["recommendations"] == ["rec1", "rec2"]
                # Check timestamp format
                assert data["generated_at"] == "2023-01-01T12:00:00+00:00"

    def test_trigger_now_creates_closes_db_and_returns_result(self):
        """Test trigger_now creates and closes db session and returns result."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=5,
        )
        mock_db = MagicMock()
        db_session_factory.return_value = mock_db
        fake_result = MagicMock(spec=AggregateAnalysis)
        with patch.object(processor, "_trigger_analysis", return_value=fake_result):
            result = processor.trigger_now()
            # Should have created a db session
            db_session_factory.assert_called_once()
            # Should have called _trigger_analysis with that session
            processor._trigger_analysis.assert_called_once_with(mock_db)
            # Should have closed the session
            mock_db.close.assert_called_once()
            assert result == fake_result

    def test_get_status_returns_correct_dict(self):
        """Test get_status returns a dictionary with expected fields."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=7,
            min_feedback_count=20,
            check_interval_seconds=500,
        )
        processor._last_analysis_count = 7
        mock_db = MagicMock()
        db_session_factory.return_value = mock_db
        # Mock list_unprocessed_feedback to return 3 items
        with patch(
            "src.audiobook_studio.feedback.auto_processor.list_unprocessed_feedback",
            return_value=[1, 2, 3],
        ), patch.object(
            processor, "_worker_thread_alive", return_value=True
        ):
            status = processor.get_status()
            assert status["project_id"] == 7
            assert status["running"] is True
            assert status["enable_auto_trigger"] is True  # default
            assert status["min_feedback_count"] == 20
            assert status["check_interval_seconds"] == 500
            assert status["unprocessed_feedback_count"] == 3
            assert status["last_analysis_count"] == 7
            assert status["next_check_in_seconds"] == 500

    def test_get_status_when_stopped_returns_none_for_next_check(self):
        """Test get_status returns None for next_check_in_seconds when stopped."""
        db_session_factory = MagicMock()
        processor = FeedbackAutoProcessor(
            db_session_factory=db_session_factory,
            project_id=1,
        )
        # Make worker thread appear not alive
        with patch.object(processor, "_worker_thread_alive", return_value=False):
            status = processor.get_status()
            assert status["next_check_in_seconds"] is None

    def test_create_auto_processor_factory_returns_instance(self):
        """Test create_auto_processor factory function."""
        db_session_factory = MagicMock()
        processor = create_auto_processor(
            db_session_factory=db_session_factory,
            project_id=123,
            min_feedback_count=99,
            check_interval_seconds=1234,
            enable_auto_trigger=False,
        )
        assert isinstance(processor, FeedbackAutoProcessor)
        assert processor.db_session_factory == db_session_factory
        assert processor.project_id == 123
        assert processor.min_feedback_count == 99
        assert processor.check_interval_seconds == 1234
        assert processor.enable_auto_trigger is False

    def test_run_feedback_analysis_cli_calls_analyze_batch_and_logs(self, caplog):
        """Test run_feedback_analysis_cli calls analyze_batch and logs appropriately."""
        db_session_factory = MagicMock()
        mock_db = MagicMock()
        db_session_factory.return_value = mock_db
        fake_result = MagicMock(spec=AggregateAnalysis)
        fake_result.total_analyzed = 100
        fake_result.recommendations = ["rec1", "rec2"]
        with patch(
            "src.audiobook_studio.feedback.auto_processor.analyze_batch",
            return_value=fake_result,
        ) as mock_analyze, caplog.at_level("INFO"):
            result = run_feedback_analysis_cli(
                db_session_factory=db_session_factory,
                project_id=55,
                limit=500,
            )
            # Should have called analyze_batch with correct args
            mock_analyze.assert_called_once_with(
                mock_db, project_id=55, limit=500
            )
            # Should have logged the start and completion
            assert "Running manual feedback analysis for project 55" in caplog.text
            assert "Analysis complete: 100 records processed" in caplog.text
            assert "2 recommendations" in caplog.text
            assert "- rec1" in caplog.text
            assert "- rec2" in caplog.text
            # Should have returned the result
            assert result == fake_result

    def test_run_feedback_analysis_cli_closes_db_session(self):
        """Test run_feedback_analysis_cli closes the db session."""
        db_session_factory = MagicMock()
        mock_db = MagicMock()
        db_session_factory.return_value = mock_db
        fake_result = MagicMock(spec=AggregateAnalysis)
        fake_result.total_analyzed = 0
        fake_result.recommendations = []
        with patch(
            "src.audiobook_studio.feedback.auto_processor.analyze_batch",
            return_value=fake_result,
        ):
            run_feedback_analysis_cli(
                db_session_factory=db_session_factory,
                project_id=1,
            )
            # Should have closed the db session
            mock_db.close.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
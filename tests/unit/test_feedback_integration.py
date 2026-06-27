"""Tests for feedback/integration.py — SelfIterationLoop, helpers, and factory."""

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.skip(
    reason="Sprint G Placeholder — SelfIterationLoop is a stub, not real usable code"
)


class TestCollectPipelineFeedback:
    def test_collects_with_all_fields(self):
        from src.audiobook_studio.feedback.integration import collect_pipeline_feedback
        mock_collector = MagicMock()
        mock_capture = MagicMock()
        mock_collector.capture_stage.return_value = mock_capture

        result = collect_pipeline_feedback(
            mock_collector, "annotate",
            chapter_index=1, paragraph_index=5,
            chapter_id=10, paragraph_id=20,
            input_snapshot={"text": "hello"},
        )
        mock_collector.capture_stage.assert_called_once_with(
            stage="annotate",
            chapter_index=1,
            paragraph_index=5,
            chapter_id=10,
            paragraph_id=20,
            input_snapshot={"text": "hello"},
        )
        assert result == mock_capture

    def test_collects_minimal_fields(self):
        from src.audiobook_studio.feedback.integration import collect_pipeline_feedback
        mock_collector = MagicMock()
        collect_pipeline_feedback(mock_collector, "edit", chapter_index=2)
        mock_collector.capture_stage.assert_called_once_with(
            stage="edit", chapter_index=2,
            paragraph_index=None, chapter_id=None,
            paragraph_id=None, input_snapshot=None,
        )


class TestSaveQualityFeedback:
    def test_saves_with_quality_judge_source(self):
        from src.audiobook_studio.feedback.integration import save_quality_feedback
        mock_collector = MagicMock()
        mock_capture = MagicMock()
        mock_collector.capture_stage.return_value = mock_capture

        save_quality_feedback(
            mock_collector, "quality", 1, 2, 10, 20,
            quality_judgment={"score": 0.8},
            corrected_judgment={"score": 0.9},
            rationale="Quality needs improvement for natural prosody",
        )
        mock_capture.set_llm_output.assert_called_once_with({"score": 0.8})
        mock_capture.set_corrected_output.assert_called_once_with({"score": 0.9})
        mock_capture.set_source.assert_called_once_with("quality_judge")
        mock_collector.save_feedback.assert_called_once_with(mock_capture)


class TestSaveUserRatingFeedback:
    def test_saves_with_user_rating_source(self):
        from src.audiobook_studio.feedback.integration import save_user_rating_feedback
        mock_collector = MagicMock()
        mock_capture = MagicMock()
        mock_collector.capture_stage.return_value = mock_capture

        save_user_rating_feedback(
            mock_collector, "annotate", 1, 2, 10, 20,
            user_rating={"rating": 4},
            rationale="User rated this segment well overall",
        )
        mock_capture.set_llm_output.assert_called_once_with({"rating": 4})
        mock_capture.set_corrected_output.assert_called_once_with({"rating": 4})
        mock_capture.set_source.assert_called_once_with("user_rating")


class TestCreateSelfIterationLoop:
    def test_creates_loop_with_defaults(self):
        from src.audiobook_studio.feedback.integration import create_self_iteration_loop
        mock_factory = MagicMock()
        loop = create_self_iteration_loop(db_session_factory=mock_factory, project_id=1)
        assert loop.project_id == 1
        assert loop.canary_percentage == 0.1
        assert loop._iteration_count == 0

    def test_creates_loop_with_custom_params(self):
        from src.audiobook_studio.feedback.integration import create_self_iteration_loop
        mock_factory = MagicMock()
        loop = create_self_iteration_loop(
            db_session_factory=mock_factory, project_id=42,
            canary_percentage=0.2,
        )
        assert loop.project_id == 42
        assert loop.canary_percentage == 0.2


class TestSelfIterationLoop:
    def test_get_status_when_not_running(self):
        from src.audiobook_studio.feedback.integration import create_self_iteration_loop
        mock_factory = MagicMock()
        loop = create_self_iteration_loop(db_session_factory=mock_factory, project_id=1)
        status = loop.get_status()
        assert status["project_id"] == 1
        assert status["running"] is False
        assert status["iteration_count"] == 0
        assert status["upgraded_prompts"] == {}

    def test_stop_when_not_started(self):
        from src.audiobook_studio.feedback.integration import create_self_iteration_loop
        mock_factory = MagicMock()
        loop = create_self_iteration_loop(db_session_factory=mock_factory, project_id=1)
        # Should not raise even when not started
        loop.stop()

    def test_log_event(self):
        from src.audiobook_studio.feedback.integration import _log_self_iteration_event
        import json
        import tempfile
        from pathlib import Path
        with patch("src.audiobook_studio.feedback.integration.Path") as mock_path_class:
            tmpdir = Path(tempfile.mkdtemp())
            mock_path_class.return_value = tmpdir
            _log_self_iteration_event("test_event", {"key": "value"})
            # Should not raise

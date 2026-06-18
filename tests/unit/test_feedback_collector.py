"""Tests for feedback collector module."""

import pytest
from unittest.mock import MagicMock, patch

from src.audiobook_studio.feedback.collector import (
    capture_feedback,
    capture_quality_feedback,
    capture_edit_feedback,
    list_unprocessed_feedback,
    mark_feedback_processed,
)


class TestCaptureFeedback:
    """Tests for capture_feedback function."""

    def test_capture_basic_feedback(self):
        """Test basic feedback capture."""
        mock_db = MagicMock()
        mock_record = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()
        mock_db.query = MagicMock()

        # Mock the FeedbackRecordModel creation
        with patch('src.audiobook_studio.feedback.collector.FeedbackRecordModel') as mock_model:
            mock_model.return_value = mock_record
            mock_record.id = "test-id"
            mock_record.feedback_id = "test-feedback-id"

            result = capture_feedback(
                db=mock_db,
                project_id=1,
                source="human_edit",
                stage="edit_for_tts",
                input_snapshot={"text": "input"},
                llm_output={"edited": "output"},
                corrected_output={"edited": "corrected"},
                rationale="User correction",
            )

            mock_db.add.assert_called_once()
            mock_db.commit.assert_called_once()
            mock_db.refresh.assert_called_once()
            assert result == mock_record

    def test_capture_feedback_short_rationale_padded(self):
        """Test short rationale gets padded."""
        mock_db = MagicMock()
        mock_record = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        with patch('src.audiobook_studio.feedback.collector.FeedbackRecordModel') as mock_model:
            mock_model.return_value = mock_record

            result = capture_feedback(
                db=mock_db,
                project_id=1,
                source="human_edit",
                stage="edit_for_tts",
                input_snapshot={"text": "input"},
                llm_output={"edited": "output"},
                corrected_output={"edited": "corrected"},
                rationale="Short",  # Less than 10 chars
            )

            # Check the rationale was padded
            call_args = mock_model.call_args
            assert "自动采集反馈记录" in call_args.kwargs.get('rationale', '')

    def test_capture_feedback_with_optional_fields(self):
        """Test capture with all optional fields."""
        mock_db = MagicMock()
        mock_record = MagicMock()
        mock_db.add = MagicMock()
        mock_db.commit = MagicMock()
        mock_db.refresh = MagicMock()

        with patch('src.audiobook_studio.feedback.collector.FeedbackRecordModel') as mock_model:
            mock_model.return_value = mock_record

            result = capture_feedback(
                db=mock_db,
                project_id=1,
                source="quality_judge",
                stage="quality_judge",
                input_snapshot={"input": "data"},
                llm_output={"score": 0.8},
                corrected_output={"score": 0.9},
                rationale="Quality correction",
                chapter_id=5,
                paragraph_id=10,
                paragraph_index=3,
                chapter_index=2,
                diff_summary="Score adjusted",
                pattern_tags=["tag1", "tag2"],
            )

            call_kwargs = mock_model.call_args.kwargs
            assert call_kwargs['project_id'] == 1
            assert call_kwargs['source'] == "quality_judge"
            assert call_kwargs['stage'] == "quality_judge"
            assert call_kwargs.get('chapter_id') == 5
            assert call_kwargs.get('paragraph_id') == 10


class TestCaptureQualityFeedback:
    """Tests for capture_quality_feedback function."""

    def test_capture_quality_feedback(self):
        """Test quality feedback capture."""
        mock_db = MagicMock()
        mock_record = MagicMock()

        with patch('src.audiobook_studio.feedback.collector.capture_feedback', return_value=mock_record) as mock_capture:
            result = capture_quality_feedback(
                db=mock_db,
                project_id=1,
                chapter_id=2,
                paragraph_id=3,
                paragraph_index=1,
                chapter_index=1,
                input_data={"audio": "data"},
                llm_judgment={"score": 0.7},
                corrected_judgment={"score": 0.9},
                rationale="Manual quality correction",
            )

            mock_capture.assert_called_once()
            call_args = mock_capture.call_args
            assert call_args.kwargs['source'] == "quality_judge"
            assert call_args.kwargs['stage'] == "quality_judge"
            assert call_args.kwargs['project_id'] == 1
            assert call_args.kwargs['chapter_id'] == 2
            assert call_args.kwargs['paragraph_id'] == 3
            assert call_args.kwargs['paragraph_index'] == 1
            assert call_args.kwargs['chapter_index'] == 1
            assert result == mock_record


class TestCaptureEditFeedback:
    """Tests for capture_edit_feedback function."""

    def test_capture_edit_feedback(self):
        """Test edit feedback capture."""
        mock_db = MagicMock()
        mock_record = MagicMock()

        with patch('src.audiobook_studio.feedback.collector.capture_feedback', return_value=mock_record) as mock_capture:
            result = capture_edit_feedback(
                db=mock_db,
                project_id=1,
                chapter_id=2,
                paragraph_id=3,
                paragraph_index=1,
                chapter_index=1,
                original_text="Original text",
                edited_text="Edited text",
                llm_suggested_edit="LLM suggestion",
                user_rationale="User's reason",
            )

            mock_capture.assert_called_once()
            call_args = mock_capture.call_args
            assert call_args.kwargs['source'] == "human_edit"
            assert call_args.kwargs['stage'] == "edit_for_tts"
            assert call_args.kwargs['input_snapshot'] == {"original_text": "Original text"}
            assert call_args.kwargs['llm_output'] == {"edited_text": "LLM suggestion"}
            assert call_args.kwargs['corrected_output'] == {"edited_text": "Edited text"}
            assert call_args.kwargs['rationale'] == "User's reason"
            assert result == mock_record


class TestListUnprocessedFeedback:
    """Tests for list_unprocessed_feedback function."""

    def test_list_unprocessed_feedback(self):
        """Test listing unprocessed feedback."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter1 = MagicMock()
        mock_filter2 = MagicMock()
        mock_order = MagicMock()
        mock_limit = MagicMock()

        mock_db.query.return_value = mock_query
        # First filter for processed == False
        mock_query.filter.return_value = mock_filter1
        # Second filter for project_id
        mock_filter1.filter.return_value = mock_filter2
        mock_filter2.order_by.return_value = mock_order
        mock_order.limit.return_value = mock_limit
        mock_limit.all.return_value = ["record1", "record2"]

        result = list_unprocessed_feedback(mock_db, project_id=1, limit=100)

        assert result == ["record1", "record2"]
        mock_db.query.assert_called_once()

    def test_list_unprocessed_feedback_no_project(self):
        """Test listing unprocessed feedback without project filter."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_order = MagicMock()
        mock_limit = MagicMock()

        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.order_by.return_value = mock_order
        mock_order.limit.return_value = mock_limit
        mock_limit.all.return_value = ["record1"]

        result = list_unprocessed_feedback(mock_db, project_id=None, limit=50)

        assert result == ["record1"]
        # Should only have one filter call (for processed == False)
        assert mock_query.filter.call_count == 1


class TestMarkFeedbackProcessed:
    """Tests for mark_feedback_processed function."""

    def test_mark_processed(self):
        """Test marking feedback as processed."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_record = MagicMock()

        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = mock_record

        mark_feedback_processed(
            mock_db,
            "feedback-123",
            pattern_tags=["tag1"],
            diff_summary="Summary of diff",
        )

        assert mock_record.processed is True
        assert mock_record.pattern_tags == ["tag1"]
        assert mock_record.diff_summary == "Summary of diff"
        mock_db.commit.assert_called_once()

    def test_mark_processed_not_found(self):
        """Test marking non-existent feedback."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()

        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = None

        mark_feedback_processed(mock_db, "nonexistent")

        mock_db.commit.assert_not_called()

    def test_mark_processed_no_optional_args(self):
        """Test marking processed without optional args."""
        mock_db = MagicMock()
        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_record = MagicMock()

        mock_db.query.return_value = mock_query
        mock_query.filter.return_value = mock_filter
        mock_filter.first.return_value = mock_record

        mark_feedback_processed(mock_db, "feedback-123")

        assert mock_record.processed is True
        # pattern_tags and diff_summary should not be modified
        mock_db.commit.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
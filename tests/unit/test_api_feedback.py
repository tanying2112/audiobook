"""Tests for feedback API endpoints - covers src/audiobook_studio/api/feedback.py"""

from datetime import datetime
from unittest.mock import patch, MagicMock
import pytest


class TestFeedbackAPI:
    """Tests for feedback API endpoints."""
    
    def setup_method(self):
        """Clear the feedback store before each test."""
        from src.audiobook_studio.api.feedback import _feedback_store
        _feedback_store.clear()

    def test_create_feedback_basic(self):
        """Test creating basic feedback."""
        from src.audiobook_studio.api.feedback import create_feedback, FeedbackCreate
        
        feedback_data = FeedbackCreate(
            source="human_edit",
            stage="edit_for_tts",
            book_id="book123",
            input_snapshot={"text": "Hello"},
            llm_output={"text": "Hi"},
            corrected_output={"text": "Hello there"},
            rationale="Added greeting for naturalness",
        )
        
        import asyncio
        result = asyncio.run(create_feedback(feedback_data))
        
        assert result.id is not None
        assert result.source == "human_edit"
        assert result.stage == "edit_for_tts"
        assert result.book_id == "book123"
        assert result.rationale == "Added greeting for naturalness"
        assert "human_edit" in result.pattern_tags

    def test_create_feedback_emotion_tag(self):
        """Test feedback with emotion-related rationale."""
        from src.audiobook_studio.api.feedback import create_feedback, FeedbackCreate
        
        feedback_data = FeedbackCreate(
            source="quality_judge",
            stage="tts_synthesis",
            book_id="book456",
            input_snapshot={"text": "I'm happy"},
            llm_output={"text": "I'm happy"},
            corrected_output={"text": "I'm so happy!"},
            rationale="Emotion needs to be stronger and more joyful",
        )
        
        import asyncio
        result = asyncio.run(create_feedback(feedback_data))
        
        assert "emotion_mismatch" in result.pattern_tags

    def test_create_feedback_speaker_tag(self):
        """Test feedback with speaker-related rationale."""
        from src.audiobook_studio.api.feedback import create_feedback, FeedbackCreate
        
        feedback_data = FeedbackCreate(
            source="human_edit",
            stage="edit_for_tts",
            book_id="book789",
            input_snapshot={"text": "He said"},
            llm_output={"text": "She said"},
            corrected_output={"text": "He said"},
            rationale="Speaker is wrong, should be male voice",
        )
        
        import asyncio
        result = asyncio.run(create_feedback(feedback_data))
        
        assert "speaker_error" in result.pattern_tags

    def test_create_feedback_speed_tag(self):
        """Test feedback with speed-related rationale."""
        from src.audiobook_studio.api.feedback import create_feedback, FeedbackCreate
        
        feedback_data = FeedbackCreate(
            source="user_rating",
            stage="tts_synthesis",
            book_id="book111",
            input_snapshot={"text": "Fast text"},
            llm_output={"text": "Fast text"},
            corrected_output={"text": "Fast text"},
            rationale="语速太快了，需要慢一点",
        )
        
        import asyncio
        result = asyncio.run(create_feedback(feedback_data))
        
        assert "wrong_speed" in result.pattern_tags

    def test_create_feedback_pitch_tag(self):
        """Test feedback with pitch-related rationale."""
        from src.audiobook_studio.api.feedback import create_feedback, FeedbackCreate
        
        feedback_data = FeedbackCreate(
            source="quality_judge",
            stage="tts_synthesis",
            book_id="book222",
            input_snapshot={"text": "High pitch"},
            llm_output={"text": "High pitch"},
            corrected_output={"text": "High pitch"},
            rationale="音高不正确，需要降低音调",
        )
        
        import asyncio
        result = asyncio.run(create_feedback(feedback_data))
        
        assert "wrong_pitch" in result.pattern_tags

    def test_list_feedback_empty(self):
        """Test listing feedback when empty."""
        from src.audiobook_studio.api.feedback import list_feedback
        
        import asyncio
        result = asyncio.run(list_feedback(limit=50, offset=0))
        
        assert result.items == []
        assert result.total == 0

    def test_list_feedback_with_data(self):
        """Test listing feedback with data."""
        from src.audiobook_studio.api.feedback import create_feedback, list_feedback, FeedbackCreate
        
        # Create some feedback
        fb1 = FeedbackCreate(
            source="human_edit", stage="edit_for_tts", book_id="book1",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Test feedback 1"
        )
        fb2 = FeedbackCreate(
            source="quality_judge", stage="tts_synthesis", book_id="book2",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Test feedback 2"
        )
        
        import asyncio
        asyncio.run(create_feedback(fb1))
        asyncio.run(create_feedback(fb2))
        
        result = asyncio.run(list_feedback(limit=50, offset=0))
        
        assert result.total == 2
        assert len(result.items) == 2

    def test_list_feedback_filter_by_book_id(self):
        """Test filtering feedback by book_id."""
        from src.audiobook_studio.api.feedback import create_feedback, list_feedback, FeedbackCreate
        
        fb1 = FeedbackCreate(
            source="human_edit", stage="edit_for_tts", book_id="book1",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Feedback for book 1"
        )
        fb2 = FeedbackCreate(
            source="quality_judge", stage="tts_synthesis", book_id="book2",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Feedback for book 2"
        )
        
        import asyncio
        asyncio.run(create_feedback(fb1))
        asyncio.run(create_feedback(fb2))
        
        result = asyncio.run(list_feedback(book_id="book1", limit=50, offset=0))
        
        assert result.total == 1
        assert result.items[0].book_id == "book1"

    def test_list_feedback_filter_by_stage(self):
        """Test filtering feedback by stage."""
        from src.audiobook_studio.api.feedback import create_feedback, list_feedback, FeedbackCreate
        
        fb1 = FeedbackCreate(
            source="human_edit", stage="edit_for_tts", book_id="book1",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Edit feedback"
        )
        fb2 = FeedbackCreate(
            source="quality_judge", stage="tts_synthesis", book_id="book2",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="TTS feedback"
        )
        
        import asyncio
        asyncio.run(create_feedback(fb1))
        asyncio.run(create_feedback(fb2))
        
        result = asyncio.run(list_feedback(stage="edit_for_tts", limit=50, offset=0))
        
        assert result.total == 1
        assert result.items[0].stage == "edit_for_tts"

    def test_list_feedback_filter_by_source(self):
        """Test filtering feedback by source."""
        from src.audiobook_studio.api.feedback import create_feedback, list_feedback, FeedbackCreate
        
        fb1 = FeedbackCreate(
            source="human_edit", stage="edit_for_tts", book_id="book1",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Human edit"
        )
        fb2 = FeedbackCreate(
            source="quality_judge", stage="tts_synthesis", book_id="book2",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Quality judge"
        )
        
        import asyncio
        asyncio.run(create_feedback(fb1))
        asyncio.run(create_feedback(fb2))
        
        result = asyncio.run(list_feedback(source="quality_judge", limit=50, offset=0))
        
        assert result.total == 1
        assert result.items[0].source == "quality_judge"

    def test_list_feedback_pagination(self):
        """Test feedback list pagination."""
        from src.audiobook_studio.api.feedback import create_feedback, list_feedback, FeedbackCreate
        
        for i in range(5):
            fb = FeedbackCreate(
                source="human_edit", stage="edit_for_tts", book_id=f"book{i}",
                input_snapshot={}, llm_output={}, corrected_output={},
                rationale=f"Feedback {i}"
            )
            import asyncio
            asyncio.run(create_feedback(fb))
        
        import asyncio
        # First page
        result = asyncio.run(list_feedback(limit=2, offset=0))
        assert len(result.items) == 2
        assert result.total == 5
        
        # Second page
        result = asyncio.run(list_feedback(limit=2, offset=2))
        assert len(result.items) == 2
        
        # Third page
        result = asyncio.run(list_feedback(limit=2, offset=4))
        assert len(result.items) == 1

    def test_get_feedback_found(self):
        """Test getting specific feedback by ID."""
        from src.audiobook_studio.api.feedback import create_feedback, get_feedback, FeedbackCreate
        
        fb = FeedbackCreate(
            source="human_edit", stage="edit_for_tts", book_id="book1",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Test feedback"
        )
        
        import asyncio
        created = asyncio.run(create_feedback(fb))
        
        result = asyncio.run(get_feedback(created.id))
        
        assert result.id == created.id
        assert result.book_id == "book1"

    def test_get_feedback_not_found(self):
        """Test getting non-existent feedback."""
        from src.audiobook_studio.api.feedback import get_feedback
        from fastapi import HTTPException
        
        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(get_feedback("nonexistent"))
        
        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.detail.lower()

    def test_get_feedback_stats(self):
        """Test getting feedback statistics."""
        from src.audiobook_studio.api.feedback import create_feedback, get_feedback_stats, FeedbackCreate
        
        fb1 = FeedbackCreate(
            source="human_edit", stage="edit_for_tts", book_id="book1",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Emotion test feedback"
        )
        fb2 = FeedbackCreate(
            source="human_edit", stage="edit_for_tts", book_id="book1",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Speaker error feedback"
        )
        fb3 = FeedbackCreate(
            source="quality_judge", stage="tts_synthesis", book_id="book2",
            input_snapshot={}, llm_output={}, corrected_output={},
            rationale="Quality check"
        )
        
        import asyncio
        asyncio.run(create_feedback(fb1))
        asyncio.run(create_feedback(fb2))
        asyncio.run(create_feedback(fb3))
        
        # Stats for book1
        result = asyncio.run(get_feedback_stats(book_id="book1"))
        
        assert result["total_feedback"] == 2
        assert result["by_stage"]["edit_for_tts"] == 2
        assert result["by_source"]["human_edit"] == 2
        assert ("emotion_mismatch", 1) in result["top_pattern_tags"]
        assert ("speaker_error", 1) in result["top_pattern_tags"]
        
        # Stats for all
        result = asyncio.run(get_feedback_stats())
        
        assert result["total_feedback"] == 3
        assert result["by_stage"]["edit_for_tts"] == 2
        assert result["by_stage"]["tts_synthesis"] == 1
        assert result["by_source"]["human_edit"] == 2
        assert result["by_source"]["quality_judge"] == 1


class TestFeedbackAPIModels:
    """Test feedback request/response models."""
    
    def test_feedback_create_model(self):
        """Test FeedbackCreate model validation."""
        from src.audiobook_studio.api.feedback import FeedbackCreate
        
        fb = FeedbackCreate(
            source="human_edit",
            stage="edit_for_tts",
            book_id="book123",
            input_snapshot={"key": "value"},
            llm_output={"key": "value"},
            corrected_output={"key": "new_value"},
            rationale="This is a valid rationale with enough length",
        )
        
        assert fb.source == "human_edit"
        assert fb.stage == "edit_for_tts"
        assert fb.book_id == "book123"
        assert fb.rationale == "This is a valid rationale with enough length"

    def test_feedback_create_short_rationale_fails(self):
        """Test that short rationale fails validation."""
        from src.audiobook_studio.api.feedback import FeedbackCreate
        from pydantic import ValidationError
        
        with pytest.raises(ValidationError):
            FeedbackCreate(
                source="human_edit",
                stage="edit_for_tts",
                book_id="book123",
                input_snapshot={},
                llm_output={},
                corrected_output={},
                rationale="Short",  # Too short, min 10 chars
            )

    def test_feedback_response_model(self):
        """Test FeedbackResponse model."""
        from src.audiobook_studio.api.feedback import FeedbackResponse
        from datetime import datetime
        
        fb = FeedbackResponse(
            id="test-id",
            timestamp=datetime.utcnow(),
            source="human_edit",
            stage="edit_for_tts",
            book_id="book123",
            paragraph_index=1,
            chapter_index=2,
            rationale="Test rationale",
            diff_summary="Modified",
            pattern_tags=["human_edit"],
            contract_version=1,
        )
        
        assert fb.id == "test-id"
        assert fb.paragraph_index == 1
        assert fb.chapter_index == 2

    def test_feedback_list_response_model(self):
        """Test FeedbackListResponse model."""
        from src.audiobook_studio.api.feedback import FeedbackListResponse, FeedbackResponse
        from datetime import datetime
        
        fb = FeedbackResponse(
            id="test-id",
            timestamp=datetime.utcnow(),
            source="human_edit",
            stage="edit_for_tts",
            book_id="book123",
            paragraph_index=None,
            chapter_index=None,
            rationale="Test rationale",
            diff_summary="Modified",
            pattern_tags=["human_edit"],
            contract_version=1,
        )
        
        resp = FeedbackListResponse(items=[fb], total=1)
        
        assert len(resp.items) == 1
        assert resp.total == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Test suite for templates API (api/templates.py).

Covers:
- Template CRUD: list, confirm, reject
- Batch apply template to project (all/chapter/pattern scope)
- Background re-run of downstream pipeline stages
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Import the FastAPI app
from src.audiobook_studio.main import app
from src.audiobook_studio.database import get_db
from src.audiobook_studio.models.feedback_record import FeedbackRecord as FeedbackRecordModel
from src.audiobook_studio.models import Paragraph, TTSEdit, Routing, Quality
from src.audiobook_studio.api.templates import _apply_template_background

client = TestClient(app)
# Disable raise_server_exceptions to allow catching 500 errors in tests
client = TestClient(app, raise_server_exceptions=False)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_db_session():
    """Mock database session."""
    return MagicMock(spec=Session)


@pytest.fixture(autouse=True)
def override_get_db(mock_db_session):
    """Override get_db dependency for all tests."""
    def _get_db():
        yield mock_db_session
    
    app.dependency_overrides[get_db] = _get_db
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def sample_feedback_record():
    """Sample FeedbackRecord for testing."""
    record = MagicMock(spec=FeedbackRecordModel)
    record.id = 1
    record.feedback_id = "fb_001"
    record.source = "human_edit"
    record.stage = "edit_for_tts"
    record.pattern_tags = ["emotion_too_mild", "dialogue_attribution"]
    record.diff_summary = "Changed emotion from neutral to happy"
    record.rationale = "情感不足，需要更热情"
    record.created_at = datetime.now(timezone.utc)
    record.input_snapshot = {"text": "你好", "emotion": "neutral"}
    record.llm_output = {"edited_text": "你好", "emotion": "neutral"}
    record.corrected_output = {"edited_text": "你好！", "emotion": "happy"}
    record.processed = True
    record.promoted = True
    record.project_id = 1
    return record


@pytest.fixture
def sample_paragraph():
    """Sample Paragraph for testing."""
    para = MagicMock(spec=Paragraph)
    para.id = 10
    para.project_id = 1
    para.chapter_id = 1
    para.text = "原文"
    para.edited_text = "编辑后文本"
    para.is_dialogue = True
    para.emotion = "neutral"
    para.emotion_intensity = 0.5
    para.speech_rate = 1.0
    para.speaker_canonical_name = "Narrator"
    para.edit_difficulty = "B"
    para.edit_forbid_edit = False
    para.edit_changes_made = []
    para.edit_confidence = 0.9
    para.edit_rationale = ""
    para.routing_engine = "kokoro"
    para.routing_voice_id = "kokoro_narrator"
    para.routing_prosody_overrides = {}
    para.routing_fallback = "edge"
    para.routing_reasoning = ""
    para.routing_estimated_cost = 0.0
    para.routing_estimated_duration = 5000
    para.actual_engine = None
    para.actual_cost_usd = None
    para.actual_duration_ms = None
    para.status = "completed"
    para.voice = "kokoro_narrator"
    para.confidence = 0.9
    para.notes = ""
    para.needs_sfx = False
    para.sfx_tags = []
    return para


# ─────────────────────────────────────────────────────────────────────────────
# Helper: Create query chain mock
# ─────────────────────────────────────────────────────────────────────────────

def setup_query_mock(mock_db_session, return_records=None, return_count=0):
    """Setup mock query chain for FeedbackRecord queries."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    
    # filter, order_by, limit all return the same mock_query
    mock_query.filter.return_value = mock_query
    mock_query.order_by.return_value = mock_query
    mock_query.limit.return_value = mock_query
    
    if return_records is not None:
        mock_query.all.return_value = return_records
    if return_count is not None:
        mock_query.count.return_value = return_count
    
    return mock_query


def setup_first_query_mock(mock_db_session, return_record=None):
    """Setup mock query chain for single record (first())."""
    mock_query = MagicMock()
    mock_db_session.query.return_value = mock_query
    mock_query.filter.return_value = mock_query
    mock_query.first.return_value = return_record
    return mock_query


# ─────────────────────────────────────────────────────────────────────────────
# Test: List Templates
# ─────────────────────────────────────────────────────────────────────────────

class TestListTemplates:
    """Tests for GET /api/projects/{project_id}/templates"""

    def test_list_templates_success(self, mock_db_session, sample_feedback_record):
        """Should return list of confirmed templates."""
        setup_query_mock(mock_db_session, return_records=[sample_feedback_record], return_count=1)

        response = client.get("/api/projects/1/templates")

        assert response.status_code == 200
        data = response.json()
        assert data["total_count"] == 1
        assert data["pending_count"] == 1
        assert len(data["templates"]) == 1
        assert data["templates"][0]["feedback_id"] == "fb_001"
        assert data["templates"][0]["stage"] == "edit_for_tts"

    def test_list_templates_with_filters(self, mock_db_session):
        """Should apply filters: source, stage, pattern_tag, pending_only."""
        setup_query_mock(mock_db_session, return_records=[], return_count=0)

        response = client.get(
            "/api/projects/1/templates",
            params={
                "source": "human_edit",
                "stage": "edit_for_tts",
                "pattern_tag": "emotion_too_mild",
                "pending_only": "true"
            }
        )

        assert response.status_code == 200
        # Verify query was called
        assert mock_db_session.query.called

    def test_list_templates_empty(self, mock_db_session):
        """Should return empty list when no templates."""
        setup_query_mock(mock_db_session, return_records=[], return_count=0)

        response = client.get("/api/projects/1/templates")

        assert response.status_code == 200
        data = response.json()
        assert data["templates"] == []
        assert data["total_count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Test: Confirm / Reject Template
# ─────────────────────────────────────────────────────────────────────────────

class TestConfirmTemplate:
    """Tests for POST /api/projects/{project_id}/templates/{template_id}/confirm"""

    def test_confirm_template_success(self, mock_db_session, sample_feedback_record):
        """Should confirm template (processed=true, promoted=true)."""
        sample_feedback_record.processed = False
        sample_feedback_record.promoted = False
        setup_first_query_mock(mock_db_session, return_record=sample_feedback_record)

        response = client.post(
            "/api/projects/1/templates/1/confirm",
            json={"action": "confirm", "pattern_tags": ["new_tag"]}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["processed"] is True
        assert data["promoted"] is True
        assert sample_feedback_record.pattern_tags == ["new_tag"]
        mock_db_session.commit.assert_called()

    def test_reject_template_success(self, mock_db_session, sample_feedback_record):
        """Should reject template (processed=true, promoted=false)."""
        sample_feedback_record.processed = False
        sample_feedback_record.promoted = False
        setup_first_query_mock(mock_db_session, return_record=sample_feedback_record)

        response = client.post(
            "/api/projects/1/templates/1/confirm",
            json={"action": "reject"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["processed"] is True
        assert data["promoted"] is False
        mock_db_session.commit.assert_called()

    def test_confirm_invalid_action(self, mock_db_session):
        """Should return 400 for invalid action."""
        setup_first_query_mock(mock_db_session, return_record=MagicMock())

        response = client.post(
            "/api/projects/1/templates/1/confirm",
            json={"action": "invalid"}
        )
        assert response.status_code == 400

    def test_confirm_template_not_found(self, mock_db_session):
        """Should return 404 for non-existent template."""
        setup_first_query_mock(mock_db_session, return_record=None)

        response = client.post(
            "/api/projects/1/templates/999/confirm",
            json={"action": "confirm"}
        )
        assert response.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Test: Apply Template (Batch)
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyTemplate:
    """Tests for POST /api/projects/{project_id}/templates/apply"""

    def test_apply_template_success(self, mock_db_session, sample_feedback_record):
        """Should queue background task and return task_id."""
        setup_first_query_mock(mock_db_session, return_record=sample_feedback_record)

        response = client.post(
            "/api/projects/1/templates/apply",
            json={
                "template_id": 1,
                "scope": "all",
                "chapter_ids": None,
                "pattern_filter": None
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "queued"
        assert data["scope"] == "all"

    def test_apply_template_not_confirmed(self, mock_db_session, sample_feedback_record):
        """Should return 400 if template not confirmed."""
        sample_feedback_record.processed = True
        sample_feedback_record.promoted = False  # Not promoted
        setup_first_query_mock(mock_db_session, return_record=sample_feedback_record)

        response = client.post(
            "/api/projects/1/templates/apply",
            json={"template_id": 1, "scope": "all"}
        )

        assert response.status_code == 400
        assert "not confirmed" in response.json()["detail"]

    def test_apply_template_not_found(self, mock_db_session):
        """Should return 404 for non-existent template."""
        setup_first_query_mock(mock_db_session, return_record=None)

        response = client.post(
            "/api/projects/1/templates/apply",
            json={"template_id": 999, "scope": "all"}
        )

        assert response.status_code == 404

    def test_apply_template_scope_chapter(self, mock_db_session, sample_feedback_record):
        """Should work with chapter scope."""
        setup_first_query_mock(mock_db_session, return_record=sample_feedback_record)

        response = client.post(
            "/api/projects/1/templates/apply",
            json={
                "template_id": 1,
                "scope": "chapter",
                "chapter_ids": [1, 2, 3]
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "chapter"

    def test_apply_template_scope_pattern(self, mock_db_session, sample_feedback_record):
        """Should work with pattern scope."""
        setup_first_query_mock(mock_db_session, return_record=sample_feedback_record)

        response = client.post(
            "/api/projects/1/templates/apply",
            json={
                "template_id": 1,
                "scope": "pattern",
                "pattern_filter": "emotion:anger, speaker:Narrator"
            }
        )

        assert response.status_code == 200
        data = response.json()
        assert data["scope"] == "pattern"


# ─────────────────────────────────────────────────────────────────────────────
# Test: Background Template Application (Direct Function Tests)
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyTemplateBackground:
    """Tests for _apply_template_background helper functions."""

    def test_apply_annotation_template(self, mock_db_session, sample_paragraph):
        """Should apply annotation template to paragraphs."""
        from src.audiobook_studio.api.templates import _apply_annotation_template

        template = MagicMock(spec=FeedbackRecordModel)
        template.id = 1
        template.stage = "annotate"
        template.corrected_output = {
            "speaker_canonical_name": "Character A",
            "is_dialogue": True,
            "emotion": "angry",
            "emotion_intensity": 0.9,
            "speech_rate": 1.2,
            "confidence": 0.95,
            "needs_sfx": True,
            "sfx_tags": ["door_slam"],
            "notes": "Applied via template"
        }
        template.pattern_tags = ["emotion_too_mild"]

        _apply_annotation_template(mock_db_session, sample_paragraph, template.corrected_output)

        # Verify paragraph updated
        assert sample_paragraph.speaker_canonical_name == "Character A"
        assert sample_paragraph.emotion == "angry"
        assert sample_paragraph.emotion_intensity == 0.9
        assert sample_paragraph.speech_rate == 1.2
        assert sample_paragraph.confidence == 0.95
        assert sample_paragraph.needs_sfx is True
        assert "door_slam" in sample_paragraph.sfx_tags
        assert sample_paragraph.notes == "Applied via template"
        mock_db_session.add.assert_called()
        mock_db_session.commit.assert_called()

    def test_apply_edit_template(self, mock_db_session, sample_paragraph):
        """Should apply edit template (create TTSEdit)."""
        from src.audiobook_studio.api.templates import _apply_edit_template

        template = MagicMock(spec=FeedbackRecordModel)
        template.id = 1
        template.stage = "edit_for_tts"
        template.corrected_output = {
            "edited_text": "编辑后的文本",
            "voice": "kokoro_female",
            "changes_made": ["口语化", "拆分长句"],
            "forbidden_content_removed": False,
            "confidence": 0.9,
            "rationale": "更自然",
            "difficulty": "B",
            "forbid_edit": False,
            "source": "template",
            "llm_model": "gpt-4",
            "prompt_version": "v1"
        }

        _apply_edit_template(mock_db_session, sample_paragraph, template.corrected_output)

        # Verify TTSEdit created and paragraph updated
        assert sample_paragraph.edited_text == "编辑后的文本"
        assert sample_paragraph.edit_changes_made == ["口语化", "拆分长句"]
        assert sample_paragraph.edit_confidence == 0.9
        assert sample_paragraph.edit_rationale == "更自然"
        mock_db_session.add.assert_called()
        mock_db_session.commit.assert_called()

    def test_apply_routing_template(self, mock_db_session, sample_paragraph):
        """Should apply routing template (create Routing)."""
        from src.audiobook_studio.api.templates import _apply_routing_template

        template = MagicMock(spec=FeedbackRecordModel)
        template.id = 1
        template.stage = "routing"
        template.corrected_output = {
            "engine_choice": "edge_tts",
            "voice_id": "zh-CN-XiaoxiaoNeural",
            "prosody_overrides": {"rate": "+10%"},
            "fallback_engine": "kokoro",
            "reasoning": "更适合中文",
            "estimated_cost_usd": 0.001,
            "estimated_duration_ms": 3000,
            "status": "completed",
            "voice": "zh-CN-XiaoxiaoNeural",
            "confidence": 0.92
        }

        _apply_routing_template(mock_db_session, sample_paragraph, template.corrected_output)

        # Verify Routing created and paragraph updated
        assert sample_paragraph.routing_engine == "edge_tts"
        assert sample_paragraph.routing_voice_id == "zh-CN-XiaoxiaoNeural"
        assert sample_paragraph.routing_prosody_overrides == {"rate": "+10%"}
        assert sample_paragraph.routing_fallback == "kokoro"
        mock_db_session.add.assert_called()
        mock_db_session.commit.assert_called()

    def test_apply_quality_template(self, mock_db_session, sample_paragraph):
        """Should apply quality template (create Quality record)."""
        from src.audiobook_studio.api.templates import _apply_quality_template

        # Setup TTSEdit for this paragraph
        tts_edit = MagicMock(spec=TTSEdit)
        tts_edit.id = 5

        template = MagicMock(spec=FeedbackRecordModel)
        template.id = 1
        template.stage = "quality"
        template.corrected_output = {
            "speaker_clarity": 0.95,
            "emotion_match": 0.9,
            "prosody_naturalness": 0.85,
            "text_audio_alignment": 0.9,
            "overall_score": 0.9,
            "score": 90,
            "comments": "质量很好",
            "issues": []
        }

        # Mock the query chain for TTSEdit lookup
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = tts_edit

        _apply_quality_template(mock_db_session, sample_paragraph, template.corrected_output)

        # Verify Quality created
        mock_db_session.add.assert_called()
        mock_db_session.commit.assert_called()

    def test_apply_quality_template_no_tts_edit(self, mock_db_session, sample_paragraph):
        """Should skip if no TTSEdit found."""
        from src.audiobook_studio.api.templates import _apply_quality_template

        template = MagicMock(spec=FeedbackRecordModel)
        template.id = 1
        template.stage = "quality"
        template.corrected_output = {"overall_score": 0.9}

        # Mock the query chain for TTSEdit lookup - return None
        mock_query = MagicMock()
        mock_db_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = None

        with patch('src.audiobook_studio.api.templates.logger') as mock_logger:
            _apply_quality_template(mock_db_session, sample_paragraph, template.corrected_output)
            mock_logger.warning.assert_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test: Downstream Pipeline Re-run
# ─────────────────────────────────────────────────────────────────────────────

class TestRerunDownstreamStages:
    """Tests for _rerun_downstream_stages function."""

    def test_rerun_after_annotation(self, mock_db_session, sample_paragraph):
        """Should re-run edit, routing, synthesize, quality after annotate."""
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        paragraphs = [sample_paragraph]

        with patch('src.audiobook_studio.pipeline.orchestrator.run_stage') as mock_run:
            _rerun_downstream_stages(mock_db_session, 1, "annotate", paragraphs)

            # Should trigger downstream stages
            assert mock_run.call_count >= 3  # edit, routing, quality at minimum

    def test_rerun_after_edit(self, mock_db_session, sample_paragraph):
        """Should re-run routing, synthesize, quality after edit."""
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        paragraphs = [sample_paragraph]

        with patch('src.audiobook_studio.pipeline.orchestrator.run_stage') as mock_run:
            _rerun_downstream_stages(mock_db_session, 1, "edit_for_tts", paragraphs)

            # Should trigger routing and quality
            assert mock_run.call_count >= 2

    def test_rerun_after_routing(self, mock_db_session, sample_paragraph):
        """Should re-run quality after routing."""
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        paragraphs = [sample_paragraph]

        with patch('src.audiobook_studio.pipeline.orchestrator.run_stage') as mock_run:
            _rerun_downstream_stages(mock_db_session, 1, "routing", paragraphs)

            # Should trigger quality
            assert mock_run.call_count >= 1

    def test_rerun_after_quality(self, mock_db_session, sample_paragraph):
        """Should not re-run any stage after quality (final stage)."""
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        paragraphs = [sample_paragraph]

        with patch('src.audiobook_studio.pipeline.orchestrator.run_stage') as mock_run:
            _rerun_downstream_stages(mock_db_session, 1, "quality", paragraphs)

            # No downstream stages after quality
            mock_run.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Test: Pattern Matching (Scope: pattern)
# ─────────────────────────────────────────────────────────────────────────────

class TestPatternMatching:
    """Tests for pattern tag based paragraph filtering."""

    def test_pattern_emotion_tag(self, mock_db_session, sample_paragraph):
        """Should match paragraphs by emotion tag."""
        sample_paragraph.emotion = "anger"
        setup_first_query_mock(mock_db_session, return_record=MagicMock(
            spec=FeedbackRecordModel,
            id=1, stage="annotate", pattern_tags=["emotion:anger"],
            processed=True, promoted=True, corrected_output={"emotion": "angry"}
        ))

        response = client.post(
            "/api/projects/1/templates/apply",
            json={
                "template_id": 1,
                "scope": "pattern",
                "pattern_filter": "emotion:anger"
            }
        )

        assert response.status_code == 200

    def test_pattern_speaker_tag(self, mock_db_session, sample_paragraph):
        """Should match paragraphs by speaker tag."""
        sample_paragraph.speaker_canonical_name = "Narrator"
        setup_first_query_mock(mock_db_session, return_record=MagicMock(
            spec=FeedbackRecordModel,
            id=1, stage="annotate", pattern_tags=["speaker:Narrator"],
            processed=True, promoted=True, corrected_output={"speaker_canonical_name": "Narrator"}
        ))

        response = client.post(
            "/api/projects/1/templates/apply",
            json={
                "template_id": 1,
                "scope": "pattern",
                "pattern_filter": "speaker:Narrator"
            }
        )

        assert response.status_code == 200

    def test_pattern_dialogue_tag(self, mock_db_session, sample_paragraph):
        """Should match dialogue paragraphs."""
        sample_paragraph.is_dialogue = True
        setup_first_query_mock(mock_db_session, return_record=MagicMock(
            spec=FeedbackRecordModel,
            id=1, stage="annotate", pattern_tags=["dialogue"],
            processed=True, promoted=True, corrected_output={"is_dialogue": True}
        ))

        response = client.post(
            "/api/projects/1/templates/apply",
            json={
                "template_id": 1,
                "scope": "pattern",
                "pattern_filter": "dialogue"
            }
        )

        assert response.status_code == 200


# ─────────────────────────────────────────────────────────────────────────────
# Test: Progress Tracking (Unit test for in-memory dict)
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplateApplyProgress:
    """Tests for background task progress tracking (in-memory dict)."""

    def test_progress_tracking_initialized(self):
        """Should initialize progress dict."""
        from src.audiobook_studio.api.templates import _apply_template_background

        # Clear any existing progress
        if hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress.clear()

        # Check progress dict exists
        assert hasattr(_apply_template_background, "progress")

    def test_progress_dict_operations(self):
        """Test progress dict basic operations."""
        from src.audiobook_studio.api.templates import _apply_template_background

        if hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress.clear()

        # Simulate progress tracking
        task_id = "test_123"
        _apply_template_background.progress[task_id] = {
            "processed": 5,
            "total": 10,
            "status": "running",
            "error": None,
            "current_paragraph_id": 42,
            "current_stage": "annotate"
        }

        progress = _apply_template_background.progress.get(task_id)
        assert progress is not None
        assert progress["processed"] == 5
        assert progress["total"] == 10
        assert progress["status"] == "running"
        assert progress["current_paragraph_id"] == 42
        assert progress["current_stage"] == "annotate"


# ─────────────────────────────────────────────────────────────────────────────
# Test: Error Handling (Endpoint level)
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplateErrorHandling:
    """Tests for error handling in template operations."""

    def test_confirm_template_db_error(self, mock_db_session, sample_feedback_record):
        """Should handle database commit errors."""
        sample_feedback_record.processed = False
        sample_feedback_record.promoted = False
        setup_first_query_mock(mock_db_session, return_record=sample_feedback_record)
        mock_db_session.commit.side_effect = Exception("Commit failed")

        response = client.post(
            "/api/projects/1/templates/1/confirm",
            json={"action": "confirm"}
        )

        # The endpoint catches exception and returns 500
        assert response.status_code == 500



# ─────────────────────────────────────────────────────────────────────────────
# Test: Progress Endpoint
# ─────────────────────────────────────────────────────────────────────────────

class TestTemplateProgressEndpoint:
    """Tests for GET /apply/{task_id}/progress endpoint."""

    def test_progress_endpoint_success(self, mock_db_session):
        """Should return progress for valid task_id."""
        from src.audiobook_studio.api.templates import _apply_template_background

        # Clear any existing progress
        if hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress.clear()
        else:
            _apply_template_background.progress = {}

        task_id = "test_progress_123"
        _apply_template_background.progress[task_id] = {
            "processed": 5,
            "total": 20,
            "status": "running",
            "error": None,
            "current_paragraph_id": 6,
            "current_stage": "annotate"
        }

        response = client.get(f"/api/projects/1/templates/apply/{task_id}/progress")

        assert response.status_code == 200
        data = response.json()
        assert data["processed"] == 5
        assert data["total"] == 20
        assert data["status"] == "running"
        assert data["current_paragraph_id"] == 6
        assert data["current_stage"] == "annotate"
        assert data["error"] is None

    def test_progress_endpoint_not_found(self, mock_db_session):
        """Should return 404 for unknown task_id."""
        from src.audiobook_studio.api.templates import _apply_template_background

        if hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress.clear()
        else:
            _apply_template_background.progress = {}

        response = client.get("/api/projects/1/templates/apply/unknown_task/progress")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"] == "Task not found"

    def test_progress_endpoint_completed(self, mock_db_session):
        """Should return completed progress."""
        from src.audiobook_studio.api.templates import _apply_template_background

        if hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress.clear()
        else:
            _apply_template_background.progress = {}

        task_id = "test_completed_456"
        _apply_template_background.progress[task_id] = {
            "processed": 20,
            "total": 20,
            "status": "completed",
            "error": None,
            "current_paragraph_id": 20,
            "current_stage": "quality"
        }

        response = client.get(f"/api/projects/1/templates/apply/{task_id}/progress")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["processed"] == data["total"]

    def test_progress_endpoint_failed(self, mock_db_session):
        """Should return failed progress with error."""
        from src.audiobook_studio.api.templates import _apply_template_background

        if hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress.clear()
        else:
            _apply_template_background.progress = {}

        task_id = "test_failed_789"
        _apply_template_background.progress[task_id] = {
            "processed": 5,
            "total": 20,
            "status": "failed",
            "error": "Database connection lost",
            "current_paragraph_id": 6,
            "current_stage": "edit"
        }

        response = client.get(f"/api/projects/1/templates/apply/{task_id}/progress")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "failed"
        assert data["error"] == "Database connection lost"
        assert data["current_paragraph_id"] == 6
        assert data["current_stage"] == "edit"

# ─────────────────────────────────────────────────────────────────────────────
# Run tests
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

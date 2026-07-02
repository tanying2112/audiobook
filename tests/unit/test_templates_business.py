"""Business logic tests for templates.py.

Tests the core template application functions:
- _apply_annotation_template
- _apply_edit_template
- _apply_routing_template
- _apply_quality_template
- _rerun_downstream_stages
- _feedback_to_template
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ===========================================================================
# _feedback_to_template conversion
# ===========================================================================


class TestFeedbackToTemplateConversion:
    """Test _feedback_to_template converts FeedbackRecord to TemplateItem."""

    def test_full_record_conversion(self):
        from src.audiobook_studio.api.templates import _feedback_to_template

        record = MagicMock()
        record.id = 42
        record.feedback_id = "fb-042"
        record.source = "human_edit"
        record.stage = "annotate"
        record.pattern_tags = ["dialogue_attribution", "emotion_fix"]
        record.diff_summary = "修正了张三的说话人"
        record.rationale = "情感不匹配"
        record.created_at = datetime(2025, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
        record.input_snapshot = {"text": "原文"}
        record.llm_output = {"emotion": "neutral"}
        record.corrected_output = {"emotion": "happy"}

        item = _feedback_to_template(record)
        assert item.id == 42
        assert item.feedback_id == "fb-042"
        assert item.source == "human_edit"
        assert item.stage == "annotate"
        assert item.pattern_tags == ["dialogue_attribution", "emotion_fix"]
        assert item.diff_summary == "修正了张三的说话人"
        assert item.rationale == "情感不匹配"
        assert "2025" in item.created_at
        assert item.input_snapshot == {"text": "原文"}
        assert item.corrected_output == {"emotion": "happy"}

    def test_none_pattern_tags_becomes_empty_list(self):
        from src.audiobook_studio.api.templates import _feedback_to_template

        record = MagicMock()
        record.id = 1
        record.feedback_id = "fb-1"
        record.source = "s"
        record.stage = "annotate"
        record.pattern_tags = None
        record.diff_summary = None
        record.rationale = "r"
        record.created_at = None
        record.input_snapshot = {}
        record.llm_output = {}
        record.corrected_output = {}

        item = _feedback_to_template(record)
        assert item.pattern_tags == []
        assert item.diff_summary is None
        # When created_at is None, it should use current time
        assert item.created_at is not None

    def test_empty_list_pattern_tags_stays_empty(self):
        from src.audiobook_studio.api.templates import _feedback_to_template

        record = MagicMock()
        record.id = 2
        record.feedback_id = "fb-2"
        record.source = "s"
        record.stage = "annotate"
        record.pattern_tags = []
        record.diff_summary = "d"
        record.rationale = "r"
        record.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        record.input_snapshot = {}
        record.llm_output = {}
        record.corrected_output = {}

        item = _feedback_to_template(record)
        assert item.pattern_tags == []


# ===========================================================================
# _apply_annotation_template
# ===========================================================================


class TestApplyAnnotationTemplateBusiness:
    """Test annotation template application with various corrected_output shapes."""

    def _make_para(self, **overrides):
        """Create a mock Paragraph with defaults."""
        pa = MagicMock()
        pa.id = 10
        pa.project_id = 5
        pa.chapter_id = 3
        pa.text = "原始段落文本"
        pa.edited_text = None
        pa.speaker_canonical_name = None
        pa.is_dialogue = False
        pa.emotion = None
        pa.emotion_intensity = None
        pa.speech_rate = None
        pa.pitch_shift_semitones = None
        pa.pause_before_ms = None
        pa.pause_after_ms = None
        pa.confidence = None
        pa.needs_sfx = False
        pa.sfx_tags = None
        pa.notes = None
        pa.edit_difficulty = None
        for k, v in overrides.items():
            setattr(pa, k, v)
        return pa

    def test_full_annotation_update(self):
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = MagicMock()
        pa = self._make_para()
        corrected = {
            "speaker_canonical_name": "林黛玉",
            "is_dialogue": True,
            "emotion": "sad",
            "emotion_intensity": 0.9,
            "speech_rate": 0.8,
            "pitch_shift_semitones": -2,
            "pause_before_ms": 500,
            "pause_after_ms": 800,
            "confidence": 0.95,
            "needs_sfx": True,
            "sfx_tags": ["wind"],
            "notes": "轻声细语",
            "difficulty": "A",
        }
        _apply_annotation_template(db, pa, corrected)

        assert pa.speaker_canonical_name == "林黛玉"
        assert pa.is_dialogue is True
        assert pa.emotion == "sad"
        assert pa.emotion_intensity == 0.9
        assert pa.speech_rate == 0.8
        assert pa.pitch_shift_semitones == -2
        assert pa.pause_before_ms == 500
        assert pa.pause_after_ms == 800
        assert pa.confidence == 0.95
        assert pa.needs_sfx is True
        assert pa.sfx_tags == ["wind"]
        assert pa.notes == "轻声细语"
        assert pa.edit_difficulty == "A"
        db.add.assert_called_with(pa)
        db.commit.assert_called_once()

    def test_partial_update_only_specified_fields(self):
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = MagicMock()
        pa = self._make_para(speaker_canonical_name="旁白")
        corrected = {"emotion": "angry"}
        _apply_annotation_template(db, pa, corrected)

        # Only emotion should change
        assert pa.emotion == "angry"
        # Others remain unchanged
        assert pa.speaker_canonical_name == "旁白"
        assert pa.is_dialogue is False

    def test_empty_corrected_output_no_changes(self):
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = MagicMock()
        pa = self._make_para()
        _apply_annotation_template(db, pa, {})
        # No fields changed, but db.add/commit still called
        db.add.assert_called_with(pa)
        db.commit.assert_called_once()

    def test_difficulty_sets_edit_difficulty(self):
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = MagicMock()
        pa = self._make_para()
        _apply_annotation_template(db, pa, {"difficulty": "B"})
        assert pa.edit_difficulty == "B"

    def test_unknown_fields_ignored(self):
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = MagicMock()
        pa = self._make_para()
        # corrected_output contains fields not in the mapped list
        _apply_annotation_template(db, pa, {"nonexistent_field": "value", "emotion": "tender"})
        assert pa.emotion == "tender"


# ===========================================================================
# _apply_edit_template
# ===========================================================================


class TestApplyEditTemplateBusiness:
    """Test edit template application creates TTSEdit and updates paragraph."""

    def _make_para(self):
        pa = MagicMock()
        pa.id = 20
        pa.project_id = 5
        pa.chapter_id = 3
        pa.text = "原始文本"
        pa.edited_text = "旧编辑文本"
        pa.edit_changes_made = None
        pa.edit_confidence = None
        pa.edit_rationale = None
        pa.edit_difficulty = None
        pa.edit_forbid_edit = None
        return pa

    def test_creates_tts_edit_with_all_fields(self):
        from src.audiobook_studio.api.templates import _apply_edit_template
        from src.audiobook_studio.models import TTSEdit

        db = MagicMock()
        pa = self._make_para()
        corrected = {
            "edited_text": "新编辑文本",
            "voice": "edge_zh-CN_female",
            "changes_made": ["去除了口语化表达"],
            "forbidden_content_removed": False,
            "confidence": 0.88,
            "rationale": "语气更正式",
            "difficulty": "B",
            "forbid_edit": False,
            "source": "template",
            "llm_model": "gpt-4o",
            "prompt_version": "v2",
        }

        _apply_edit_template(db, pa, corrected)

        # Verify db.add was called (once for TTSEdit, once for para update)
        assert db.add.call_count == 2
        assert db.commit.call_count == 2

        # Verify paragraph fields updated
        assert pa.edited_text == "新编辑文本"

    def test_fallback_to_original_text_when_no_edited_text(self):
        from src.audiobook_studio.api.templates import _apply_edit_template

        db = MagicMock()
        pa = self._make_para()
        pa.edited_text = None  # No previous edit
        corrected = {}  # No edited_text in corrected output

        _apply_edit_template(db, pa, corrected)
        # Should use pa.text as fallback
        assert pa.edited_text == "原始文本"

    def test_source_defaults_to_template(self):
        from src.audiobook_studio.api.templates import _apply_edit_template

        db = MagicMock()
        pa = self._make_para()
        corrected = {"edited_text": "更新"}
        _apply_edit_template(db, pa, corrected)
        assert db.add.call_count == 2  # TTSEdit + paragraph


# ===========================================================================
# _apply_routing_template
# ===========================================================================


class TestApplyRoutingTemplateBusiness:
    """Test routing template application creates Routing record and updates paragraph."""

    def _make_para(self):
        pa = MagicMock()
        pa.id = 30
        pa.project_id = 5
        pa.chapter_id = 3
        pa.routing_engine = None
        pa.routing_voice_id = None
        pa.routing_prosody_overrides = None
        pa.routing_fallback = None
        pa.routing_reasoning = None
        pa.routing_estimated_cost = None
        pa.routing_estimated_duration = None
        pa.actual_engine = None
        pa.actual_cost_usd = None
        pa.actual_duration_ms = None
        pa.status = None
        pa.voice = None
        pa.confidence = None
        return pa

    def test_creates_routing_record(self):
        from src.audiobook_studio.api.templates import _apply_routing_template

        db = MagicMock()
        pa = self._make_para()
        corrected = {
            "engine_choice": "kokoro",
            "voice_id": "kokoro_narrator_male",
            "fallback_engine": "edge",
            "reasoning": "男性角色匹配",
            "estimated_cost_usd": 0.005,
            "estimated_duration_ms": 8000,
            "status": "completed",
        }

        _apply_routing_template(db, pa, corrected)

        assert db.add.call_count == 2  # Routing + paragraph
        assert db.commit.call_count == 2
        assert pa.routing_engine == "kokoro"
        assert pa.routing_voice_id == "kokoro_narrator_male"
        assert pa.routing_fallback == "edge"
        assert pa.routing_reasoning == "男性角色匹配"
        assert pa.routing_estimated_cost == 0.005
        assert pa.routing_estimated_duration == 8000
        assert pa.status == "completed"

    def test_defaults_applied(self):
        from src.audiobook_studio.api.templates import _apply_routing_template

        db = MagicMock()
        pa = self._make_para()
        _apply_routing_template(db, pa, {})

        assert pa.routing_engine == "kokoro"  # default
        assert pa.routing_voice_id == "kokoro_narrator"  # default
        assert pa.routing_fallback == "edge"  # default

    def test_all_fields_set(self):
        from src.audiobook_studio.api.templates import _apply_routing_template

        db = MagicMock()
        pa = self._make_para()
        corrected = {
            "engine_choice": "edge",
            "voice_id": "edge_female",
            "prosody_overrides": {"rate": 1.2},
            "fallback_engine": "kokoro",
            "reasoning": "备选方案",
            "estimated_cost_usd": 0.001,
            "estimated_duration_ms": 3000,
            "actual_engine": "edge",
            "actual_cost_usd": 0.0008,
            "actual_duration_ms": 2800,
            "status": "completed",
            "voice": "edge_female_v2",
            "confidence": 0.92,
        }

        _apply_routing_template(db, pa, corrected)
        assert pa.routing_engine == "edge"
        assert pa.routing_voice_id == "edge_female"
        assert pa.routing_prosody_overrides == {"rate": 1.2}
        assert pa.actual_engine == "edge"
        assert pa.actual_cost_usd == 0.0008
        assert pa.actual_duration_ms == 2800
        assert pa.voice == "edge_female_v2"
        assert pa.confidence == 0.92


# ===========================================================================
# _apply_quality_template
# ===========================================================================


class TestApplyQualityTemplateBusiness:
    """Test quality template application creates Quality record and updates paragraph."""

    def _make_para(self):
        pa = MagicMock()
        pa.id = 40
        pa.project_id = 5
        pa.chapter_id = 3
        pa.quality_speaker_clarity = None
        pa.quality_emotion_match = None
        pa.quality_prosody_naturalness = None
        pa.quality_text_audio_alignment = None
        pa.quality_overall_score = None
        pa.quality_issues = None
        pa.quality_fix_suggestions = None
        pa.quality_needs_regeneration = None
        return pa

    def _make_tts_edit(self):
        edit = MagicMock()
        edit.id = 100
        return edit

    def test_creates_quality_record(self):
        from src.audiobook_studio.api.templates import _apply_quality_template

        db = MagicMock()
        pa = self._make_para()
        tts_edit = self._make_tts_edit()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = tts_edit

        corrected = {
            "speaker_clarity": 0.95,
            "emotion_match": 0.88,
            "prosody_naturalness": 0.92,
            "text_audio_alignment": 0.90,
            "overall_score": 0.91,
            "needs_regeneration": False,
            "judge_model": "gpt-4o",
            "issues": [],
            "fix_suggestions": [],
        }

        _apply_quality_template(db, pa, corrected)

        assert db.add.call_count == 2  # Quality + paragraph
        assert db.commit.call_count == 2
        assert pa.quality_speaker_clarity == 0.95
        assert pa.quality_emotion_match == 0.88
        assert pa.quality_prosody_naturalness == 0.92
        assert pa.quality_text_audio_alignment == 0.90
        assert pa.quality_overall_score == 0.91
        assert pa.quality_needs_regeneration is False

    def test_no_tts_edit_skips_quality_application(self):
        from src.audiobook_studio.api.templates import _apply_quality_template

        db = MagicMock()
        pa = self._make_para()
        # No TTSEdit found
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

        _apply_quality_template(db, pa, {"speaker_clarity": 0.9})

        # Should skip — no quality record created
        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_partial_quality_fields(self):
        from src.audiobook_studio.api.templates import _apply_quality_template

        db = MagicMock()
        pa = self._make_para()
        tts_edit = self._make_tts_edit()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = tts_edit

        _apply_quality_template(db, pa, {"overall_score": 0.75, "needs_regeneration": True})

        assert pa.quality_overall_score == 0.75
        assert pa.quality_needs_regeneration is True
        # Other fields remain None (not set)
        assert pa.quality_speaker_clarity is None


# ===========================================================================
# _rerun_downstream_stages
# ===========================================================================


class TestRerunDownstreamStages:
    """Test _rerun_downstream_stages maps stages correctly."""

    def test_annotate_triggers_edit_and_beyond(self):
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        db = MagicMock()
        para = MagicMock(id=1, chapter_id=1)
        with patch("src.audiobook_studio.pipeline.orchestrator.run_stage") as mock_run:
            _rerun_downstream_stages(db, 10, "annotate", [para])
            # Should call: edit, audio_postprocess, synthesize, quality
            assert mock_run.call_count == 4
            called_stages = [call.args[0] for call in mock_run.call_args_list]
            assert "edit" in called_stages
            assert "audio_postprocess" in called_stages
            assert "synthesize" in called_stages
            assert "quality" in called_stages

    def test_edit_for_tts_triggers_synthesize_and_quality(self):
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        db = MagicMock()
        para = MagicMock(id=1, chapter_id=1)
        with patch("src.audiobook_studio.pipeline.orchestrator.run_stage") as mock_run:
            _rerun_downstream_stages(db, 10, "edit_for_tts", [para])
            assert mock_run.call_count == 2
            called_stages = [call.args[0] for call in mock_run.call_args_list]
            assert "synthesize" in called_stages
            assert "quality" in called_stages

    def test_routing_triggers_synthesize_and_quality(self):
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        db = MagicMock()
        para = MagicMock(id=1, chapter_id=1)
        with patch("src.audiobook_studio.pipeline.orchestrator.run_stage") as mock_run:
            _rerun_downstream_stages(db, 10, "routing", [para])
            assert mock_run.call_count == 2

    def test_quality_triggers_nothing(self):
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        db = MagicMock()
        para = MagicMock(id=1, chapter_id=1)
        with patch("src.audiobook_studio.pipeline.orchestrator.run_stage") as mock_run:
            _rerun_downstream_stages(db, 10, "quality", [para])
            mock_run.assert_not_called()

    def test_unknown_stage_triggers_nothing(self):
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        db = MagicMock()
        para = MagicMock(id=1, chapter_id=1)
        with patch("src.audiobook_studio.pipeline.orchestrator.run_stage") as mock_run:
            _rerun_downstream_stages(db, 10, "unknown_stage", [para])
            mock_run.assert_not_called()

    def test_multiple_paragraphs_each_gets_all_stages(self):
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        db = MagicMock()
        paras = [MagicMock(id=i, chapter_id=1) for i in range(3)]
        with patch("src.audiobook_studio.pipeline.orchestrator.run_stage") as mock_run:
            _rerun_downstream_stages(db, 10, "annotate", paras)
            # 3 paragraphs × 4 stages = 12 calls
            assert mock_run.call_count == 12

    def test_failure_in_one_paragraph_does_not_abort_others(self):
        from src.audiobook_studio.api.templates import _rerun_downstream_stages

        db = MagicMock()
        para1 = MagicMock(id=1, chapter_id=1)
        para2 = MagicMock(id=2, chapter_id=1)

        with patch("src.audiobook_studio.pipeline.orchestrator.run_stage") as mock_run:
            call_count = [0]

            def side_effect(stage, db, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:  # First call (para1, edit) fails
                    raise RuntimeError("DB timeout")

            mock_run.side_effect = side_effect

            # Should not raise — errors are caught and logged
            _rerun_downstream_stages(db, 10, "annotate", [para1, para2])

            # para1 edit failed, but synthesize/quality for para1 + all 4 stages for para2 should still run
            # The function catches exceptions per stage per paragraph
            assert mock_run.call_count == 8  # 2 paras × 4 stages


# ===========================================================================
# Template application background task
# ===========================================================================


class TestApplyTemplateBackground:
    """Test _apply_template_background end-to-end flow."""

    def test_progress_tracking_lifecycle(self):
        """Background task tracks progress from running to completed."""
        from src.audiobook_studio.api.templates import _apply_annotation_template, _apply_template_background
        from src.audiobook_studio.models import FeedbackRecord as FR
        from src.audiobook_studio.models import Paragraph

        task_id = "test_task_001"

        # Create mock db session
        mock_db = MagicMock()

        # Mock template record (first query: FeedbackRecordModel)
        mock_template = MagicMock()
        mock_template.stage = "annotate"
        mock_template.corrected_output = {"emotion": "happy"}
        mock_template.processed = True
        mock_template.promoted = True

        # Mock paragraphs (second query: Paragraph)
        mock_para = MagicMock()
        mock_para.id = 1
        mock_para.project_id = 10
        mock_para.chapter_id = 1

        # The function makes two db.query() calls:
        # 1. db.query(FeedbackRecordModel).filter(...).first() → template
        # 2. db.query(Paragraph).filter(...).all() → paragraphs
        # Use side_effect to differentiate: first call returns template filter chain,
        # second call returns paragraph filter chain.
        mock_filter_result = MagicMock()
        mock_filter_result.first.return_value = mock_template
        mock_filter_result.all.return_value = [mock_para]
        mock_filter_result.order_by.return_value.all.return_value = [mock_para]

        mock_db.query.return_value.filter.return_value = mock_filter_result

        async def run():
            with patch("sqlalchemy.create_engine"):
                with patch("sqlalchemy.orm.sessionmaker", return_value=lambda: mock_db):
                    with patch("os.getenv", return_value="sqlite:///./test.db"):
                        with patch("src.audiobook_studio.api.templates._apply_annotation_template"):
                            with patch("src.audiobook_studio.api.templates._rerun_downstream_stages"):
                                await _apply_template_background(
                                    project_id=10,
                                    template_id=42,
                                    scope="all",
                                    chapter_ids=None,
                                    pattern_filter=None,
                                    task_id=task_id,
                                )

        _run_async(run())

        # Verify progress was tracked
        progress = _apply_template_background.progress.get(task_id)
        assert progress is not None
        assert progress["status"] == "completed"
        assert progress["total"] == 1
        assert progress["processed"] == 1

        # Cleanup
        del _apply_template_background.progress[task_id]

    def test_background_task_handles_template_not_found(self):
        """Background task sets status=failed when template not found."""
        from src.audiobook_studio.api.templates import _apply_template_background

        task_id = "test_task_002"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None  # No template

        async def run():
            with patch("sqlalchemy.create_engine"):
                with patch("sqlalchemy.orm.sessionmaker", return_value=lambda: mock_db):
                    with patch("os.getenv", return_value="sqlite:///./test.db"):
                        await _apply_template_background(
                            project_id=10,
                            template_id=999,
                            scope="all",
                            chapter_ids=None,
                            pattern_filter=None,
                            task_id=task_id,
                        )

        _run_async(run())

        progress = _apply_template_background.progress.get(task_id)
        assert progress is not None
        assert progress["status"] == "failed"
        assert "not found" in progress["error"].lower()

        # Cleanup
        del _apply_template_background.progress[task_id]

    def test_background_task_handles_unconfirmed_template(self):
        """Background task sets status=failed when template is not confirmed."""
        from src.audiobook_studio.api.templates import _apply_template_background

        task_id = "test_task_003"
        mock_db = MagicMock()
        mock_template = MagicMock()
        mock_template.processed = False  # Not confirmed
        mock_template.promoted = False
        mock_db.query.return_value.filter.return_value.first.return_value = mock_template

        async def run():
            with patch("sqlalchemy.create_engine"):
                with patch("sqlalchemy.orm.sessionmaker", return_value=lambda: mock_db):
                    with patch("os.getenv", return_value="sqlite:///./test.db"):
                        await _apply_template_background(
                            project_id=10,
                            template_id=42,
                            scope="all",
                            chapter_ids=None,
                            pattern_filter=None,
                            task_id=task_id,
                        )

        _run_async(run())

        progress = _apply_template_background.progress.get(task_id)
        assert progress is not None
        assert progress["status"] == "failed"
        assert "not confirmed" in progress["error"].lower()

        # Cleanup
        del _apply_template_background.progress[task_id]


def _run_async(coro):
    """Helper to run async functions in sync tests."""
    return asyncio.run(coro)

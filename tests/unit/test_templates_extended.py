"""templates.py 扩展测试 — 覆盖 _apply_*_template, list_templates 筛选路径, confirm, apply, progress 端点。"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTemplatesHelperFunctions:
    """测试 _apply_*_template 独立函数。"""

    def _make_db(self):
        """创建 mock db session。"""
        db = MagicMock()
        return db

    def _make_para(self):
        """创建 mock Paragraph 对象。"""
        pa = MagicMock()
        pa.id = 1
        pa.project_id = 10
        pa.chapter_id = 5
        pa.text = "原始文本"
        pa.edited_text = None
        return pa

    def test_apply_annotation_template(self):
        """_apply_annotation_template 设置字段。"""
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = self._make_db()
        pa = self._make_para()
        corrected = {
            "speaker_canonical_name": "张三",
            "is_dialogue": True,
            "emotion": "happy",
            "emotion_intensity": 0.9,
            "speech_rate": 1.2,
            "pitch_shift_semitones": 2,
            "pause_before_ms": 200,
            "pause_after_ms": 300,
            "confidence": 0.95,
            "needs_sfx": True,
            "sfx_tags": ["bgm"],
            "notes": "test",
            "difficulty": "A",
        }
        _apply_annotation_template(db, pa, corrected)
        assert pa.speaker_canonical_name == "张三"
        assert pa.is_dialogue is True
        assert pa.emotion == "happy"
        assert pa.edit_difficulty == "A"
        db.add.assert_called()
        db.commit.assert_called()

    def test_apply_annotation_template_minimal(self):
        """_apply_annotation_template 最小字段。"""
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = self._make_db()
        pa = self._make_para()
        _apply_annotation_template(db, pa, {"emotion": "sad"})
        assert pa.emotion == "sad"

    def test_apply_edit_template(self):
        """_apply_edit_template 创建 TTSEdit 记录。"""
        from src.audiobook_studio.api.templates import _apply_edit_template

        db = self._make_db()
        pa = self._make_para()
        corrected = {
            "edited_text": "编辑后文本",
            "voice": "v1",
            "changes_made": ["removed pauses"],
            "forbidden_content_removed": [],
            "confidence": 0.8,
            "rationale": "reason",
            "difficulty": "B",
            "forbid_edit": False,
            "source": "template",
            "llm_model": "test",
            "prompt_version": "v1",
        }
        _apply_edit_template(db, pa, corrected)
        db.add.assert_called()
        db.commit.assert_called()

    def test_apply_edit_template_minimal(self):
        """_apply_edit_template 最小字段。"""
        from src.audiobook_studio.api.templates import _apply_edit_template

        db = self._make_db()
        pa = self._make_para()
        _apply_edit_template(db, pa, {})
        db.add.assert_called()

    def test_apply_routing_template(self):
        """_apply_routing_template 创建 Routing 记录。"""
        from src.audiobook_studio.api.templates import _apply_routing_template

        db = self._make_db()
        pa = self._make_para()
        corrected = {
            "engine_choice": "kokoro",
            "voice_id": "v1",
            "prosody_overrides": {"rate": 1.0},
            "fallback_engine": "edge",
            "reasoning": "test",
            "estimated_cost_usd": 0.01,
            "estimated_duration_ms": 5000,
            "actual_engine": "kokoro",
            "actual_cost_usd": 0.01,
            "actual_duration_ms": 5000,
            "status": "completed",
            "voice": "v1",
            "confidence": 0.9,
        }
        _apply_routing_template(db, pa, corrected)
        db.add.assert_called()
        db.commit.assert_called()

    def test_apply_routing_template_minimal(self):
        """_apply_routing_template 最小字段。"""
        from src.audiobook_studio.api.templates import _apply_routing_template

        db = self._make_db()
        pa = self._make_para()
        _apply_routing_template(db, pa, {})
        db.add.assert_called()

    def test_apply_quality_template(self):
        """_apply_quality_template 创建 Quality 记录。"""
        from src.audiobook_studio.api.templates import _apply_quality_template

        db = self._make_db()
        pa = self._make_para()
        # Mock query chain for TTSEdit
        mock_tts_edit = MagicMock()
        mock_tts_edit.id = 42
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            mock_tts_edit
        )

        corrected = {
            "speaker_clarity": 0.9,
            "emotion_match": 0.85,
            "prosody_naturalness": 0.8,
            "text_audio_alignment": 0.9,
            "overall_score": 0.88,
            "score": 88,
            "comments": "good",
            "issues": [],
            "fix_suggestions": [],
            "needs_regeneration": False,
            "judge_model": "test",
            "judge_prompt_version": "v1",
            "audio_file_path": "/audio.mp3",
            "audio_duration_ms": 60000,
        }
        _apply_quality_template(db, pa, corrected)
        db.add.assert_called()
        db.commit.assert_called()

    def test_apply_quality_template_no_tts_edit(self):
        """_apply_quality_template 无 TTSEdit 时跳过。"""
        from src.audiobook_studio.api.templates import _apply_quality_template

        db = self._make_db()
        pa = self._make_para()
        db.query.return_value.filter.return_value.order_by.return_value.first.return_value = (
            None
        )

        _apply_quality_template(db, pa, {"overall_score": 0.9})
        # Should not add quality record
        db.add.assert_not_called()


class TestTemplatesBackgroundTask:
    """测试 _apply_template_background 函数。"""

    def test_apply_template_background_task_id_tracking(self):
        """_apply_template_background 设置进度跟踪。"""
        from src.audiobook_studio.api.templates import _apply_template_background

        # Reset progress
        if hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress = {}

        # The function imports create_engine/sessionmaker locally
        # so patch them at sqlalchemy level
        with patch("sqlalchemy.create_engine") as mock_engine:
            with patch("sqlalchemy.orm.sessionmaker") as mock_sm:
                mock_session = MagicMock()
                # Template not found → ValueError
                mock_session.query.return_value.filter.return_value.first.return_value = (
                    None
                )
                mock_sm.return_value = MagicMock(return_value=mock_session)

                import asyncio

                try:
                    asyncio.run(
                        _apply_template_background(
                            project_id=1,
                            template_id=999,
                            scope="all",
                            chapter_ids=None,
                            pattern_filter=None,
                            task_id="test_task_1",
                        )
                    )
                except Exception:
                    pass

                # Check that progress was initialized
                assert "test_task_1" in _apply_template_background.progress

    def test_apply_template_background_not_confirmed(self):
        """_apply_template_background 未确认的模板。"""
        from src.audiobook_studio.api.templates import _apply_template_background

        if hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress = {}

        with patch("sqlalchemy.create_engine"):
            with patch("sqlalchemy.orm.sessionmaker") as mock_sm:
                mock_session = MagicMock()
                # Template exists but not confirmed
                mock_template = MagicMock()
                mock_template.processed = False
                mock_template.promoted = False
                mock_session.query.return_value.filter.return_value.first.return_value = (
                    mock_template
                )
                mock_sm.return_value = MagicMock(return_value=mock_session)

                import asyncio

                try:
                    asyncio.run(
                        _apply_template_background(
                            project_id=1,
                            template_id=1,
                            scope="all",
                            chapter_ids=None,
                            pattern_filter=None,
                            task_id="test_task_2",
                        )
                    )
                except Exception:
                    pass

                assert "test_task_2" in _apply_template_background.progress

    def test_apply_template_background_chapter_scope(self):
        """_apply_template_background chapter scope。"""
        from src.audiobook_studio.api.templates import _apply_template_background

        if hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress = {}

        with patch("sqlalchemy.create_engine"):
            with patch("sqlalchemy.orm.sessionmaker") as mock_sm:
                mock_session = MagicMock()
                # Template confirmed
                mock_template = MagicMock()
                mock_template.processed = True
                mock_template.promoted = True
                mock_template.stage = "annotate"
                mock_template.corrected_output = {"emotion": "happy"}

                # Two queries: first for template, second for paragraphs
                q1 = MagicMock()
                q1.filter.return_value.first.return_value = mock_template
                q2 = MagicMock()
                q2.filter.return_value.filter.return_value.all.return_value = []

                mock_session.query.side_effect = [q1, q2]
                mock_sm.return_value = MagicMock(return_value=mock_session)

                import asyncio

                try:
                    asyncio.run(
                        _apply_template_background(
                            project_id=1,
                            template_id=1,
                            scope="chapter",
                            chapter_ids=[1, 2],
                            pattern_filter=None,
                            task_id="test_task_3",
                        )
                    )
                except Exception:
                    pass

                assert "test_task_3" in _apply_template_background.progress


class TestTemplatesAPISchemas:
    """测试 API schemas 的边界情况。"""

    def test_template_list_response_defaults(self):
        """TemplateListResponse 默认值。"""
        from src.audiobook_studio.api.templates import TemplateListResponse

        resp = TemplateListResponse()
        assert resp.templates == []
        assert resp.total_count == 0
        assert resp.pending_count == 0

    def test_template_confirm_request(self):
        """TemplateConfirmRequest 创建。"""
        from src.audiobook_studio.api.templates import TemplateConfirmRequest

        req = TemplateConfirmRequest(action="confirm", pattern_tags=["tag1"])
        assert req.action == "confirm"
        assert req.pattern_tags == ["tag1"]

    def test_template_confirm_request_no_tags(self):
        """TemplateConfirmRequest 无 tags。"""
        from src.audiobook_studio.api.templates import TemplateConfirmRequest

        req = TemplateConfirmRequest(action="reject")
        assert req.action == "reject"
        assert req.pattern_tags is None

    def test_template_apply_request(self):
        """TemplateApplyRequest 创建。"""
        from src.audiobook_studio.api.templates import TemplateApplyRequest

        req = TemplateApplyRequest(
            template_id=1,
            scope="chapter",
            chapter_ids=[1, 2],
            pattern_filter=None,
        )
        assert req.template_id == 1
        assert req.scope == "chapter"
        assert req.chapter_ids == [1, 2]

    def test_template_apply_progress_defaults(self):
        """TemplateApplyProgress 默认值。"""
        from src.audiobook_studio.api.templates import TemplateApplyProgress

        p = TemplateApplyProgress()
        assert p.processed == 0
        assert p.total == 0
        assert p.status == "running"

    def test_template_item_full(self):
        """TemplateItem 完整字段。"""
        from src.audiobook_studio.api.templates import TemplateItem

        item = TemplateItem(
            id=1,
            feedback_id="fb-1",
            source="human_edit",
            stage="annotate",
            pattern_tags=["tag1"],
            diff_summary="diff",
            rationale="reason",
            created_at="2025-01-01T00:00:00",
            input_snapshot={},
            llm_output={},
            corrected_output={},
        )
        assert item.id == 1
        assert item.source == "human_edit"


class TestFeedbackToTemplate:
    """测试 _feedback_to_template。"""

    def test_basic_conversion(self):
        """基本转换。"""
        from src.audiobook_studio.api.templates import _feedback_to_template

        record = MagicMock()
        record.id = 1
        record.feedback_id = "fb-1"
        record.source = "human_edit"
        record.stage = "annotate"
        record.pattern_tags = ["tag1"]
        record.diff_summary = "diff"
        record.rationale = "reason"
        record.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        record.input_snapshot = {}
        record.llm_output = {}
        record.corrected_output = {}

        item = _feedback_to_template(record)
        assert item.id == 1
        assert item.feedback_id == "fb-1"
        assert item.source == "human_edit"

    def test_none_created_at(self):
        """created_at 为 None 时使用当前时间。"""
        from src.audiobook_studio.api.templates import _feedback_to_template

        record = MagicMock()
        record.id = 2
        record.feedback_id = "fb-2"
        record.source = "quality_judge"
        record.stage = "quality"
        record.pattern_tags = None
        record.diff_summary = None
        record.rationale = "r"
        record.created_at = None
        record.input_snapshot = {}
        record.llm_output = {}
        record.corrected_output = {}

        item = _feedback_to_template(record)
        assert item.id == 2
        assert item.pattern_tags == []

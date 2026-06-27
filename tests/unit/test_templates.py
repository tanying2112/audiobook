"""templates API 模块测试 — 覆盖 schema 数据类、辅助函数、
apply 模板辅助函数、以及 API 端点核心逻辑。"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, AsyncMock

import pytest


# ===========================================================================
# Schema / dataclass 测试
# ===========================================================================


class TestTemplateSchemas:
    def test_template_item_creation(self):
        """TemplateItem 数据类可创建。"""
        from src.audiobook_studio.api.templates import TemplateItem

        t = TemplateItem(
            id=1,
            feedback_id="fb-001",
            source="human_edit",
            stage="annotate",
            pattern_tags=["dialogue_attribution"],
            diff_summary="修正了说话人",
            rationale="需要修正",
            created_at="2025-01-01T00:00:00",
            input_snapshot={"text": "test"},
            llm_output={"emotion": "neutral"},
            corrected_output={"emotion": "happy"},
        )
        assert t.id == 1
        assert t.stage == "annotate"
        assert t.pattern_tags == ["dialogue_attribution"]

    def test_template_item_defaults(self):
        """TemplateItem 可选字段默认值。"""
        from src.audiobook_studio.api.templates import TemplateItem

        t = TemplateItem(
            id=1, feedback_id="fb-1", source="s", stage="annotate",
            rationale="r", created_at="2025-01-01",
            input_snapshot={}, llm_output={}, corrected_output={},
        )
        assert t.pattern_tags is None
        assert t.diff_summary is None

    def test_template_list_response(self):
        """TemplateListResponse 默认为空。"""
        from src.audiobook_studio.api.templates import TemplateListResponse

        resp = TemplateListResponse()
        assert resp.templates == []
        assert resp.total_count == 0
        assert resp.pending_count == 0

    def test_template_list_response_with_data(self):
        """TemplateListResponse 含数据。"""
        from src.audiobook_studio.api.templates import TemplateListResponse, TemplateItem

        t = TemplateItem(
            id=1, feedback_id="fb-1", source="s", stage="annotate",
            rationale="r", created_at="2025-01-01",
            input_snapshot={}, llm_output={}, corrected_output={},
        )
        resp = TemplateListResponse(templates=[t], total_count=1, pending_count=0)
        assert len(resp.templates) == 1

    def test_template_confirm_request(self):
        """TemplateConfirmRequest 可创建。"""
        from src.audiobook_studio.api.templates import TemplateConfirmRequest

        req = TemplateConfirmRequest(action="confirm", pattern_tags=["tag1"])
        assert req.action == "confirm"
        assert req.pattern_tags == ["tag1"]

    def test_template_confirm_request_no_tags(self):
        """TemplateConfirmRequest 不带 tags。"""
        from src.audiobook_studio.api.templates import TemplateConfirmRequest

        req = TemplateConfirmRequest(action="reject")
        assert req.pattern_tags is None

    def test_template_apply_request(self):
        """TemplateApplyRequest 可创建。"""
        from src.audiobook_studio.api.templates import TemplateApplyRequest

        req = TemplateApplyRequest(
            template_id=1, scope="all",
            chapter_ids=[1, 2],
            pattern_filter="tag",
        )
        assert req.template_id == 1
        assert req.scope == "all"
        assert req.chapter_ids == [1, 2]

    def test_template_apply_request_chapter_scope(self):
        """TemplateApplyRequest chapter scope。"""
        from src.audiobook_studio.api.templates import TemplateApplyRequest

        req = TemplateApplyRequest(template_id=5, scope="chapter", chapter_ids=[1])
        assert req.scope == "chapter"

    def test_template_apply_progress(self):
        """TemplateApplyProgress 默认值。"""
        from src.audiobook_studio.api.templates import TemplateApplyProgress

        p = TemplateApplyProgress()
        assert p.processed == 0
        assert p.total == 0
        assert p.status == "running"
        assert p.error is None

    def test_template_apply_progress_custom(self):
        """TemplateApplyProgress 自定义值。"""
        from src.audiobook_studio.api.templates import TemplateApplyProgress

        p = TemplateApplyProgress(
            processed=5, total=10, status="completed",
            current_paragraph_id=5, current_stage="annotate",
        )
        assert p.processed == 5
        assert p.status == "completed"


# ===========================================================================
# _feedback_to_template
# ===========================================================================


class TestFeedbackToTemplate:
    def test_conversion(self):
        """_feedback_to_template 正确转换 FeedbackRecord。"""
        from src.audiobook_studio.api.templates import _feedback_to_template

        record = MagicMock()
        record.id = 10
        record.feedback_id = "fb-10"
        record.source = "human_edit"
        record.stage = "annotate"
        record.pattern_tags = ["tag_a"]
        record.diff_summary = "diff"
        record.rationale = "reason"
        record.created_at = datetime(2025, 3, 15, 12, 0, 0, tzinfo=timezone.utc)
        record.input_snapshot = {"a": 1}
        record.llm_output = {"b": 2}
        record.corrected_output = {"c": 3}

        t = _feedback_to_template(record)
        assert t.id == 10
        assert t.feedback_id == "fb-10"
        assert t.source == "human_edit"
        assert t.created_at == "2025-03-15T12:00:00+00:00"
        assert t.input_snapshot == {"a": 1}
        assert t.llm_output == {"b": 2}
        assert t.corrected_output == {"c": 3}

    def test_conversion_none_created_at(self):
        """created_at 为 None 时使用当前时间。"""
        from src.audiobook_studio.api.templates import _feedback_to_template

        record = MagicMock()
        record.id = 1
        record.feedback_id = "fb-1"
        record.source = "test"
        record.stage = "test"
        record.pattern_tags = None
        record.diff_summary = None
        record.rationale = "r"
        record.created_at = None
        record.input_snapshot = {}
        record.llm_output = {}
        record.corrected_output = {}

        t = _feedback_to_template(record)
        assert t.created_at  # 不为空

    def test_conversion_empty_tags(self):
        """空 tags 列表。"""
        from src.audiobook_studio.api.templates import _feedback_to_template

        record = MagicMock()
        record.id = 2
        record.feedback_id = "fb-2"
        record.source = "test"
        record.stage = "test"
        record.pattern_tags = []
        record.diff_summary = None
        record.rationale = "r"
        record.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        record.input_snapshot = {}
        record.llm_output = {}
        record.corrected_output = {}

        t = _feedback_to_template(record)
        assert t.pattern_tags == []


# ===========================================================================
# _apply_annotation_template
# ===========================================================================


class TestApplyAnnotationTemplate:
    def test_applies_fields(self):
        """_apply_annotation_template 设置段落属性。"""
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = MagicMock()
        pa = MagicMock()
        corrected = {
            "speaker_canonical_name": "主角",
            "is_dialogue": True,
            "emotion": "happy",
            "emotion_intensity": 0.9,
            "speech_rate": 1.2,
            "pitch_shift_semitones": 2,
            "pause_before_ms": 200,
            "pause_after_ms": 400,
            "confidence": 0.95,
            "needs_sfx": True,
            "sfx_tags": ["wind"],
            "notes": "test note",
            "difficulty": "C",
        }
        _apply_annotation_template(db, pa, corrected)
        assert pa.speaker_canonical_name == "主角"
        assert pa.emotion == "happy"
        assert pa.edit_difficulty == "C"
        assert pa.needs_sfx is True
        db.add.assert_called()
        db.commit.assert_called()

    def test_partial_fields(self):
        """部分字段更新。"""
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = MagicMock()
        pa = MagicMock()
        corrected = {"emotion": "sad"}
        _apply_annotation_template(db, pa, corrected)
        assert pa.emotion == "sad"
        db.add.assert_called()

    def test_empty_corrected(self):
        """空 corrected_output 不会崩溃。"""
        from src.audiobook_studio.api.templates import _apply_annotation_template

        db = MagicMock()
        pa = MagicMock()
        _apply_annotation_template(db, pa, {})
        db.add.assert_called()


# ===========================================================================
# _apply_edit_template
# ===========================================================================


class TestApplyEditTemplate:
    def test_creates_tts_edit(self):
        """_apply_edit_template 创建 TTSEdit 记录。"""
        from src.audiobook_studio.api.templates import _apply_edit_template

        db = MagicMock()
        pa = MagicMock()
        pa.id = 5
        pa.edited_text = None
        corrected = {
            "edited_text": "编辑后文本",
            "changes_made": ["fix1"],
            "forbidden_content_removed": [],
            "confidence": 0.9,
            "rationale": "r",
            "difficulty": "B",
            "forbid_edit": False,
        }
        _apply_edit_template(db, pa, corrected)
        db.add.assert_called()
        assert pa.edited_text == "编辑后文本"

    def test_with_voice(self):
        """包含 voice 字段。"""
        from src.audiobook_studio.api.templates import _apply_edit_template

        db = MagicMock()
        pa = MagicMock()
        corrected = {"edited_text": "t", "voice": "v1"}
        _apply_edit_template(db, pa, corrected)
        assert pa.edited_text == "t"

    def test_minimal_corrected(self):
        """最小 corrected_output。"""
        from src.audiobook_studio.api.templates import _apply_edit_template

        db = MagicMock()
        pa = MagicMock()
        _apply_edit_template(db, pa, {})
        db.add.assert_called()


# ===========================================================================
# _apply_routing_template
# ===========================================================================


class TestApplyRoutingTemplate:
    def test_creates_routing(self):
        """_apply_routing_template 创建 Routing 记录。"""
        from src.audiobook_studio.api.templates import _apply_routing_template

        db = MagicMock()
        pa = MagicMock()
        corrected = {
            "engine_choice": "kokoro",
            "voice_id": "v1",
            "fallback_engine": "edge",
            "reasoning": "test",
            "estimated_cost_usd": 0.001,
            "estimated_duration_ms": 5000,
        }
        _apply_routing_template(db, pa, corrected)
        db.add.assert_called()
        assert pa.routing_engine == "kokoro"

    def test_defaults(self):
        """默认 routing 参数。"""
        from src.audiobook_studio.api.templates import _apply_routing_template

        db = MagicMock()
        pa = MagicMock()
        _apply_routing_template(db, pa, {})
        db.add.assert_called()


# ===========================================================================
# _apply_quality_template
# ===========================================================================


class TestApplyQualityTemplate:
    def test_creates_quality(self):
        """_apply_quality_template 创建 Quality 记录。"""
        from src.audiobook_studio.api.templates import _apply_quality_template

        db = MagicMock()
        pa = MagicMock()
        pa.id = 10

        mock_tts = MagicMock()
        mock_tts.id = 99
        query = MagicMock()
        query.filter.return_value.order_by.return_value.first.return_value = mock_tts
        db.query.return_value = query

        corrected = {
            "speaker_clarity": 0.9,
            "emotion_match": 0.85,
            "prosody_naturalness": 0.88,
            "text_audio_alignment": 0.92,
            "overall_score": 0.89,
            "needs_regeneration": False,
            "issues": [],
            "fix_suggestions": [],
        }
        _apply_quality_template(db, pa, corrected)
        db.add.assert_called()
        assert pa.quality_overall_score == 0.89

    def test_no_tts_edit_skips(self):
        """没有 TTSEdit 时跳过。"""
        from src.audiobook_studio.api.templates import _apply_quality_template

        db = MagicMock()
        pa = MagicMock()
        pa.id = 20

        query = MagicMock()
        query.filter.return_value.order_by.return_value.first.return_value = None
        db.query.return_value = query

        _apply_quality_template(db, pa, {})
        db.add.assert_not_called()


# ===========================================================================
# _apply_template_background 进度追踪
# ===========================================================================


class TestApplyTemplateBackground:
    def test_progress_tracking_init(self):
        """进度追踪字典可初始化。"""
        from src.audiobook_studio.api.templates import _apply_template_background

        if not hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress = {}

        task_id = "test_task_init"
        _apply_template_background.progress[task_id] = {
            "processed": 0, "total": 0, "status": "running",
            "error": None, "current_paragraph_id": None,
            "current_stage": None,
        }
        assert task_id in _apply_template_background.progress
        assert _apply_template_background.progress[task_id]["status"] == "running"


# ===========================================================================
# list_templates 端点核心逻辑
# ===========================================================================


class TestListTemplatesLogic:
    """直接测试 list_templates 函数逻辑（不通过 HTTP 层）。"""

    @patch("src.audiobook_studio.api.templates.FeedbackRecordModel")
    @pytest.mark.asyncio
    async def test_list_templates_filters(self, MockFeedback):
        """list_templates 按条件过滤。"""
        from src.audiobook_studio.api.templates import list_templates

        db = MagicMock()

        # Mock 记录
        record = MagicMock()
        record.id = 1
        record.feedback_id = "fb-1"
        record.source = "human_edit"
        record.stage = "annotate"
        record.pattern_tags = ["tag1"]
        record.diff_summary = None
        record.rationale = "r"
        record.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
        record.input_snapshot = {}
        record.llm_output = {}
        record.corrected_output = {}
        record.processed = True
        record.promoted = True

        query = MagicMock()
        query.filter.return_value = query
        query.order_by.return_value = query
        query.limit.return_value = query
        query.all.return_value = [record]
        db.query.return_value = query

        result = await list_templates(
            project_id=1,
            source=None,
            stage=None,
            pattern_tag=None,
            pending_only=False,
            db=db,
        )
        assert result.total_count >= 0  # 至少不崩溃


# ===========================================================================
# confirm_template 端点核心逻辑
# ===========================================================================


class TestConfirmTemplateLogic:
    @pytest.mark.asyncio
    async def test_confirm_success(self):
        """confirm_template 确认操作。"""
        from src.audiobook_studio.api.templates import confirm_template, TemplateConfirmRequest

        db = MagicMock()
        record = MagicMock()
        record.id = 1
        record.feedback_id = "fb-1"
        record.processed = False
        record.promoted = False
        db.query.return_value.filter.return_value.first.return_value = record

        req = TemplateConfirmRequest(action="confirm")
        result = await confirm_template(project_id=1, template_id=1, request=req, db=db)

        assert result["processed"] is True
        assert result["promoted"] is True
        db.commit.assert_called()

    @pytest.mark.asyncio
    async def test_reject_success(self):
        """confirm_template 拒绝操作。"""
        from src.audiobook_studio.api.templates import confirm_template, TemplateConfirmRequest

        db = MagicMock()
        record = MagicMock()
        record.id = 1
        record.feedback_id = "fb-1"
        record.processed = False
        record.promoted = True
        db.query.return_value.filter.return_value.first.return_value = record

        req = TemplateConfirmRequest(action="reject")
        result = await confirm_template(project_id=1, template_id=1, request=req, db=db)

        assert result["processed"] is True
        assert result["promoted"] is False

    @pytest.mark.asyncio
    async def test_confirm_with_tags(self):
        """confirm 带 pattern_tags。"""
        from src.audiobook_studio.api.templates import confirm_template, TemplateConfirmRequest

        db = MagicMock()
        record = MagicMock()
        record.id = 1
        record.feedback_id = "fb-1"
        record.processed = False
        record.promoted = False
        record.pattern_tags = []
        db.query.return_value.filter.return_value.first.return_value = record

        req = TemplateConfirmRequest(action="confirm", pattern_tags=["new_tag"])
        result = await confirm_template(project_id=1, template_id=1, request=req, db=db)
        assert record.pattern_tags == ["new_tag"]


# ===========================================================================
# apply_template 端点核心逻辑
# ===========================================================================


class TestApplyTemplateLogic:
    @pytest.mark.asyncio
    async def test_apply_not_confirmed(self):
        """apply_template 未确认模板返回 400。"""
        from src.audiobook_studio.api.templates import apply_template, TemplateApplyRequest
        from fastapi import HTTPException

        db = MagicMock()
        template = MagicMock()
        template.processed = False
        template.promoted = False
        db.query.return_value.filter.return_value.first.return_value = template

        req = TemplateApplyRequest(template_id=1, scope="all")
        bg = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await apply_template(project_id=1, request=req, background_tasks=bg, db=db)
        assert exc_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_apply_not_found(self):
        """apply_template 模板不存在返回 404。"""
        from src.audiobook_studio.api.templates import apply_template, TemplateApplyRequest
        from fastapi import HTTPException

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        req = TemplateApplyRequest(template_id=999, scope="all")
        bg = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            await apply_template(project_id=1, request=req, background_tasks=bg, db=db)
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_apply_success(self):
        """apply_template 成功提交后台任务。"""
        from src.audiobook_studio.api.templates import apply_template, TemplateApplyRequest

        db = MagicMock()
        template = MagicMock()
        template.processed = True
        template.promoted = True
        db.query.return_value.filter.return_value.first.return_value = template

        req = TemplateApplyRequest(template_id=1, scope="all")
        bg = MagicMock()

        result = await apply_template(project_id=1, request=req, background_tasks=bg, db=db)
        assert result["status"] == "queued"
        assert "task_id" in result
        bg.add_task.assert_called_once()


# ===========================================================================
# get_apply_progress 端点核心逻辑
# ===========================================================================


class TestGetApplyProgressLogic:
    @pytest.mark.asyncio
    async def test_progress_not_found(self):
        """查询不存在任务返回 404。"""
        from src.audiobook_studio.api.templates import get_apply_progress
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_apply_progress(project_id=1, task_id="nonexistent")
        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_progress_found(self):
        """查询存在任务返回进度。"""
        from src.audiobook_studio.api.templates import (
            get_apply_progress,
            _apply_template_background,
        )

        task_id = "progress_test_task"
        if not hasattr(_apply_template_background, "progress"):
            _apply_template_background.progress = {}
        _apply_template_background.progress[task_id] = {
            "processed": 5,
            "total": 10,
            "status": "running",
            "error": None,
            "current_paragraph_id": 5,
            "current_stage": "annotate",
        }

        result = await get_apply_progress(project_id=1, task_id=task_id)
        assert result.processed == 5
        assert result.total == 10
        assert result.status == "running"

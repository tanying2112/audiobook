"""Manual Review Gate API — 人工终审门（TTS 合成前的人工编辑与确认）.

流水线 review 模式下位于 audio_postprocess 与 synthesize 之间暂停
（``api/auto_run.py::_enter_review_gate``），本路由补齐门所需的全部
人工侧操作，实现「客户最终控制」：

- 章节确认：approve / reset / approve-all（门的轮询只认 ``approved``，
  此前无任何端点写该字段 —— 本路由是唯一写入口）
- 路由预览：与合成共用 ``build_routing_input`` + ``make_tts_routing_decision``
  （所见即所合成，预览不会与合成漂移）
- 人工编辑：合成前设置与标注文本的 typed PATCH（编辑/选择/增补/润色），
  每次写入 ``TTSEdit`` 人工版本（source="human"）留审计；已确认章节被
  再次编辑时自动打回 ``pending_review`` 重新确认
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, get_args

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..exceptions import DomainError
from ..models.chapter import Chapter
from ..models.paragraph import Paragraph
from ..models.tts_edit import TTSEdit
from ..pipeline.synthesize import (
    _strip_image_placeholders,
    build_routing_input,
    make_tts_routing_decision,
)
from ..schemas.tts_routing import EngineChoice
from .dependencies import get_async_db
from .projects import ParagraphOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/review-gate", tags=["review-gate"])

# manual_engine 合法值 = 路由契约的 EngineChoice 全集（存库前校验，
# 防止非法引擎 ID 流到合成期才炸）
_VALID_MANUAL_ENGINES = frozenset(get_args(EngineChoice))


# ── Response schemas ─────────────────────────────────────────────────────────


class ReviewGateChapterStatus(BaseModel):
    """单章的终审状态."""

    chapter_id: int
    index: int
    title: Optional[str] = None
    review_status: Optional[str] = None  # None=未在审 | pending_review | approved
    paragraph_count: int = 0


class ReviewGateSummaryResponse(BaseModel):
    """整书终审门状态汇总."""

    project_id: int
    run_status: str = "not_started"  # auto-run 运行状态（awaiting_review=门激活中）
    chapters: List[ReviewGateChapterStatus]
    total_chapters: int = 0
    approved_chapters: int = 0
    pending_chapters: int = 0
    all_approved: bool = False


class ParagraphRoutingPreview(BaseModel):
    """单段合成路由预览（与合成同一份路由代码计算）."""

    paragraph_id: int
    paragraph_index: int
    effective_text: str = ""  # 合成将朗读的文本（edited_text 优先，插图块已剥离）
    engine_choice: Optional[str] = None
    voice_id: Optional[str] = None
    prosody_overrides: Optional[Dict[str, Any]] = None
    fallback_engine: Optional[str] = None
    reasoning: Optional[str] = None
    manual_voice_id: Optional[str] = None
    manual_engine: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None


class RoutingPreviewResponse(BaseModel):
    """整章路由预览."""

    chapter_id: int
    previews: List[ParagraphRoutingPreview]
    synthesized_count: int = 0
    skipped_count: int = 0


class ReviewParagraphEditRequest(BaseModel):
    """人工终审编辑请求：合成前设置与标注文本.

    语义约定：字段为 None = 不修改（哨兵）；要显式清空 manual_* 覆盖用
    clear_* 布尔开关；edited_text 允许空串（有意清空 → 合成跳过该段）。
    """

    model_config = ConfigDict(extra="forbid")

    # 环节④文本润色
    edited_text: Optional[str] = None
    # 环节③标注（合成前可人工修正）
    speaker_canonical_name: Optional[str] = None
    is_dialogue: Optional[bool] = None
    emotion: Optional[str] = None
    emotion_intensity: Optional[float] = Field(None, ge=0.0, le=1.0)
    speech_rate: Optional[float] = Field(None, gt=0.0, le=3.0)
    pitch_shift_semitones: Optional[int] = Field(None, ge=-12, le=12)
    pause_before_ms: Optional[int] = Field(None, ge=0, le=10000)
    pause_after_ms: Optional[int] = Field(None, ge=0, le=10000)
    needs_sfx: Optional[bool] = None
    sfx_tags: Optional[List[str]] = None
    notes: Optional[str] = None
    # 人工覆盖（manual overrides）
    manual_voice_id: Optional[str] = Field(None, max_length=255)
    clear_manual_voice_id: bool = False
    manual_engine: Optional[str] = Field(None, max_length=32)
    clear_manual_engine: bool = False
    # 编辑理由（写入 TTSEdit.rationale 审计）
    note: Optional[str] = None


class ReviewEditResponse(BaseModel):
    """人工编辑结果."""

    paragraph: ParagraphOut
    changes_made: List[str] = Field(default_factory=list)
    chapter_review_reset: bool = False  # True=该编辑把已确认章节打回待审
    tts_edit_version: Optional[int] = None


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _get_project_chapters(db: AsyncSession, project_id: int) -> List[Chapter]:
    result = await db.execute(
        select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.index)
    )
    return list(result.scalars().all())


async def _get_chapter(db: AsyncSession, project_id: int, chapter_id: int) -> Chapter:
    result = await db.execute(
        select(Chapter).where(Chapter.id == chapter_id, Chapter.project_id == project_id)
    )
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise DomainError(
            message="Chapter not found",
            error_code="NOT_FOUND",
            stage="review_gate",
            context={"project_id": project_id, "chapter_id": chapter_id},
        )
    return chapter


async def _build_summary(db: AsyncSession, project_id: int) -> ReviewGateSummaryResponse:
    """汇总：章节终审状态 + 段落数 + auto-run 运行状态."""
    chapters = await _get_project_chapters(db, project_id)
    counts_result = await db.execute(
        select(Paragraph.chapter_id, func.count(Paragraph.id))
        .where(Paragraph.project_id == project_id)
        .group_by(Paragraph.chapter_id)
    )
    count_map: Dict[Any, int] = {cid: cnt for cid, cnt in counts_result.all()}

    # 惰性导入避免与 auto_run 的模块级依赖相互牵扯；run 状态仅供前端展示
    from .auto_run import _active_runs

    run_info = _active_runs.get(project_id)
    run_status = run_info["status"] if run_info else "not_started"

    statuses = [
        ReviewGateChapterStatus(
            chapter_id=ch.id,
            index=ch.index,
            title=ch.title,
            review_status=ch.review_status,
            paragraph_count=count_map.get(ch.id, 0),
        )
        for ch in chapters
    ]
    approved = sum(1 for s in statuses if s.review_status == "approved")
    pending = sum(1 for s in statuses if s.review_status != "approved")
    return ReviewGateSummaryResponse(
        project_id=project_id,
        run_status=run_status,
        chapters=statuses,
        total_chapters=len(statuses),
        approved_chapters=approved,
        pending_chapters=pending,
        all_approved=bool(statuses) and approved == len(statuses),
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("", response_model=ReviewGateSummaryResponse)
async def get_review_gate_summary(
    project_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """终审门状态汇总（章节确认进度 + auto-run 状态）."""
    return await _build_summary(db, project_id)


@router.post("/chapters/{chapter_id}/approve", response_model=ReviewGateSummaryResponse)
async def approve_chapter(
    project_id: int,
    chapter_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """确认单章：review_status → approved.

    auto_run 的门轮询（每 2s）发现全部章节 approved 后自动放行合成，
    并广播 REVIEW_RELEASED。本端点是 review_status="approved" 的唯一写入口。
    """
    chapter = await _get_chapter(db, project_id, chapter_id)
    chapter.review_status = "approved"
    await db.commit()
    logger.info("Review gate: chapter %s approved (project %s)", chapter_id, project_id)
    return await _build_summary(db, project_id)


@router.post("/chapters/{chapter_id}/reset", response_model=ReviewGateSummaryResponse)
async def reset_chapter_approval(
    project_id: int,
    chapter_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """撤销单章确认：approved → pending_review（门未放行时重新回到待审）."""
    chapter = await _get_chapter(db, project_id, chapter_id)
    if chapter.review_status != "approved":
        raise DomainError(
            message="Chapter is not approved",
            error_code="CONFLICT",
            stage="review_gate",
            context={"project_id": project_id, "chapter_id": chapter_id, "review_status": chapter.review_status},
        )
    chapter.review_status = "pending_review"
    await db.commit()
    logger.info("Review gate: chapter %s approval reset (project %s)", chapter_id, project_id)
    return await _build_summary(db, project_id)


@router.post("/approve-all", response_model=ReviewGateSummaryResponse)
async def approve_all_chapters(
    project_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """整书确认：全部章节 → approved（门随即放行合成）."""
    chapters = await _get_project_chapters(db, project_id)
    for ch in chapters:
        ch.review_status = "approved"
    await db.commit()
    logger.info("Review gate: all %d chapters approved (project %s)", len(chapters), project_id)
    return await _build_summary(db, project_id)


@router.get("/chapters/{chapter_id}/routing-preview", response_model=RoutingPreviewResponse)
async def get_routing_preview(
    project_id: int,
    chapter_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """整章路由预览：每段将用什么引擎/音色/韵律合成.

    与合成共用 ``build_routing_input`` + ``make_tts_routing_decision``，
    预览即合成真相（含 edited_text 优先、人工覆盖、空文本跳过）。
    """
    chapter = await _get_chapter(db, project_id, chapter_id)
    result = await db.execute(
        select(Paragraph)
        .where(Paragraph.chapter_id == chapter.id, Paragraph.project_id == project_id)
        .order_by(Paragraph.index)
    )
    paragraphs = list(result.scalars().all())

    previews: List[ParagraphRoutingPreview] = []
    synthesized = 0
    skipped = 0
    for para in paragraphs:
        inp = build_routing_input(para, chapter, project_id)
        if inp is None:
            previews.append(
                ParagraphRoutingPreview(
                    paragraph_id=para.id,
                    paragraph_index=para.index,
                    skipped=True,
                    skip_reason="empty_text",
                    manual_voice_id=para.manual_voice_id,
                    manual_engine=para.manual_engine,
                )
            )
            skipped += 1
            continue

        # 与 SynthesizePipeline.run 相同的插图块剥离：剥离后为空 ⇒ 纯图片段
        speakable = _strip_image_placeholders(inp.text)
        if not speakable:
            previews.append(
                ParagraphRoutingPreview(
                    paragraph_id=para.id,
                    paragraph_index=para.index,
                    skipped=True,
                    skip_reason="image_only",
                    manual_voice_id=para.manual_voice_id,
                    manual_engine=para.manual_engine,
                )
            )
            skipped += 1
            continue

        decision = make_tts_routing_decision(inp)
        previews.append(
            ParagraphRoutingPreview(
                paragraph_id=para.id,
                paragraph_index=para.index,
                effective_text=speakable,
                engine_choice=decision.engine_choice,
                voice_id=decision.voice_id,
                prosody_overrides=decision.prosody_overrides,
                fallback_engine=decision.fallback_engine,
                reasoning=decision.reasoning,
                manual_voice_id=para.manual_voice_id,
                manual_engine=para.manual_engine,
            )
        )
        synthesized += 1

    return RoutingPreviewResponse(
        chapter_id=chapter.id,
        previews=previews,
        synthesized_count=synthesized,
        skipped_count=skipped,
    )


@router.patch("/chapters/{chapter_id}/paragraphs/{paragraph_id}", response_model=ReviewEditResponse)
async def review_edit_paragraph(
    project_id: int,
    chapter_id: int,
    paragraph_id: int,
    payload: ReviewParagraphEditRequest,
    db: AsyncSession = Depends(get_async_db),
):
    """人工编辑合成前设置与标注文本（编辑/选择/增补/润色）.

    - None=不修改；clear_manual_* 显式清除覆盖；edited_text="" 有意清空
    - 每次编辑写一条 TTSEdit 人工版本（source="human"）留审计
    - 已确认（approved）章节被编辑后自动打回 pending_review 重新确认
    """
    chapter = await _get_chapter(db, project_id, chapter_id)
    result = await db.execute(
        select(Paragraph).where(
            Paragraph.id == paragraph_id,
            Paragraph.project_id == project_id,
            Paragraph.chapter_id == chapter.id,
        )
    )
    para = result.scalar_one_or_none()
    if not para:
        raise DomainError(
            message="Paragraph not found",
            error_code="NOT_FOUND",
            stage="review_gate",
            context={"project_id": project_id, "chapter_id": chapter_id, "paragraph_id": paragraph_id},
        )

    if payload.manual_engine is not None and payload.manual_engine not in _VALID_MANUAL_ENGINES:
        raise DomainError(
            message=f"Invalid manual_engine '{payload.manual_engine}'",
            error_code="BAD_REQUEST",
            stage="review_gate",
            context={"valid_engines": sorted(_VALID_MANUAL_ENGINES)},
        )

    changes_made: List[str] = []

    # 逐字段应用（None=跳过）；manual_* 用 clear_* 开关显式清空
    simple_fields = (
        "edited_text",
        "speaker_canonical_name",
        "is_dialogue",
        "emotion",
        "emotion_intensity",
        "speech_rate",
        "pitch_shift_semitones",
        "pause_before_ms",
        "pause_after_ms",
        "needs_sfx",
        "sfx_tags",
        "notes",
    )
    values = payload.model_dump()
    for field in simple_fields:
        value = values.get(field)
        if value is None:
            continue
        if getattr(para, field) != value:
            setattr(para, field, value)
            changes_made.append(field)
    if values.get("manual_voice_id") is not None:
        if para.manual_voice_id != values["manual_voice_id"]:
            para.manual_voice_id = values["manual_voice_id"]
            changes_made.append("manual_voice_id")
    if payload.clear_manual_voice_id:
        para.manual_voice_id = None
        changes_made.append("manual_voice_id(cleared)")
    if values.get("manual_engine") is not None:
        if para.manual_engine != values["manual_engine"]:
            para.manual_engine = values["manual_engine"]
            changes_made.append("manual_engine")
    if payload.clear_manual_engine:
        para.manual_engine = None
        changes_made.append("manual_engine(cleared)")

    chapter_review_reset = False
    if changes_made:
        # 人工版本审计：新 TTSEdit 记录（version = 最新版本 + 1）
        last = await db.execute(
            select(TTSEdit.version)
            .where(TTSEdit.paragraph_id == para.id)
            .order_by(TTSEdit.version.desc())
            .limit(1)
        )
        last_version = last.scalar_one_or_none() or 0
        final_text = para.edited_text if para.edited_text is not None else para.text
        db.add(
            TTSEdit(
                project_id=project_id,
                chapter_id=chapter.id,
                paragraph_id=para.id,
                version=last_version + 1,
                edited_text=final_text,
                changes_made=list(changes_made),
                confidence=1.0,
                rationale=payload.note or "人工终审编辑 (manual review edit)",
                voice=para.manual_voice_id,
                source="human",
                created_at=datetime.now(timezone.utc),
            )
        )

        # 人工编辑过的段落回到「已编辑」态（合成前仍可继续改）
        para.status = "edited"

        # 客户最终控制语义：确认后内容又变了 ⇒ 打回待审重新确认
        if chapter.review_status == "approved":
            chapter.review_status = "pending_review"
            chapter_review_reset = True
            logger.info(
                "Review gate: chapter %s approval reset after paragraph %s edit",
                chapter.id,
                para.id,
            )

        await db.commit()
        await db.refresh(para)

    return ReviewEditResponse(
        paragraph=para,
        changes_made=changes_made,
        chapter_review_reset=chapter_review_reset,
        tts_edit_version=(last_version + 1) if changes_made else None,
    )

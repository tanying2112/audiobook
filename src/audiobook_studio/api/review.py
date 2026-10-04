"""Manual Review Gate API — 人工终审门（合成前编辑与确认）.

流水线在 audio_postprocess 完成后、synthesize 之前暂停（auto_run 的
mode="review"），客户在此对每段的标注文本与预合成设置进行编辑、选择、
增补、润色 —— 包括逐段 manual_engine / manual_voice_id 覆盖 —— 确认
（按章 approve / 整书 approve-all）后放行合成，实现「客户最终控制」。

路由优先级（合成时与预览一致）：manual_* > 角色绑定 > 自动能力选择。
预览与合成共用 pipeline.synthesize.build_routing_input / make_tts_routing_decision，
两处构造零漂移。
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, get_args

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..api.auto_run import AutoRunConfig, _active_runs, _run_auto_pipeline_blocking
from ..api.dependencies import get_async_db
from ..database import create_async_session
from ..exceptions import DomainError
from ..models.book import Project
from ..models.chapter import Chapter
from ..models.paragraph import Paragraph
from ..models.routing import Routing
from ..models.tts_edit import TTSEdit
from ..pipeline.checkpoint import CheckpointManager
from ..pipeline.synthesize import (
    _normalize_voice_id,
    _strip_image_placeholders,
    build_routing_input,
    make_tts_routing_decision,
)
from ..schemas.paragraph import EMOTION_TAGS
from ..schemas.tts_routing import EngineChoice

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/review-gate", tags=["review-gate"])

_VALID_ENGINES = set(get_args(EngineChoice))
_VALID_EMOTIONS = set(EMOTION_TAGS)


# ─────────────────────────────────────────────────────────────────────────────
# Request/Response Models
# ─────────────────────────────────────────────────────────────────────────────


class ReviewParagraphPatch(BaseModel):
    """终审段落编辑：润色文本 + 标注修正 + 逐段引擎/音色覆盖。

    extra=forbid：拼错的字段名必须 422 响亮失败，不允许静默丢弃。
    值域与 ParagraphAnnotation 一致（越界 422）；manual_engine 非法 → 400。
    """

    model_config = ConfigDict(extra="forbid")

    edited_text: Optional[str] = Field(default=None, description="润色后文本（\"\"=有意清空→跳过合成）")
    speaker_canonical_name: Optional[str] = None
    is_dialogue: Optional[bool] = None
    # emotion 必须命中合成期 ParagraphAnnotation 的 14 枚举 —— 保存入口
    # 同值域校验（422），否则坏值会在客户确认后、合成期炸掉（live E2E 实证）。
    emotion: Optional[str] = None

    @field_validator("emotion")
    @classmethod
    def _emotion_in_canonical_enum(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_EMOTIONS:
            raise ValueError(
                f"emotion must be one of {sorted(_VALID_EMOTIONS)}; got {v!r}"
            )
        return v
    emotion_intensity: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    speech_rate: Optional[float] = Field(default=None, ge=0.7, le=1.3)
    pitch_shift_semitones: Optional[int] = Field(default=None, ge=-5, le=5)
    pause_before_ms: Optional[int] = Field(default=None, ge=0, le=2000)
    pause_after_ms: Optional[int] = Field(default=None, ge=0, le=2000)
    needs_sfx: Optional[bool] = None
    sfx_tags: Optional[List[str]] = None
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    notes: Optional[str] = None
    note: Optional[str] = Field(default=None, description="追加备注（未显式给 notes 时附加到现有 notes）")
    # 客户最终控制：逐段强制引擎/音色（NULL=不覆盖，走自动路由）
    manual_engine: Optional[str] = None
    manual_voice_id: Optional[str] = None
    clear_manual_engine: bool = False
    clear_manual_voice_id: bool = False


class ChapterReviewEntry(BaseModel):
    chapter_id: int
    index: int
    title: Optional[str] = None
    review_status: Optional[str] = None  # NULL | pending_review | approved
    paragraph_count: int = 0


class ReviewGateSummary(BaseModel):
    project_id: int
    total_chapters: int
    approved_chapters: int
    pending_chapters: int
    all_approved: bool
    run_status: str = "not_started"
    chapters: List[ChapterReviewEntry] = Field(default_factory=list)


class RoutingPreviewItem(BaseModel):
    paragraph_id: int
    paragraph_index: int
    skipped: bool = False
    skip_reason: Optional[str] = None  # empty_text | image_only
    effective_text: str = ""
    engine_choice: Optional[str] = None
    voice_id: Optional[str] = None
    prosody_overrides: Optional[Dict[str, Any]] = None
    fallback_engine: Optional[str] = None
    reasoning: Optional[str] = None


class RoutingPreviewResponse(BaseModel):
    chapter_id: int
    synthesized_count: int
    skipped_count: int
    previews: List[RoutingPreviewItem]


class ReviewParagraphPatchResponse(BaseModel):
    changes_made: List[str]
    paragraph: Dict[str, Any]
    tts_edit_version: Optional[int] = None
    chapter_review_reset: bool = False


class ConfirmResponse(BaseModel):
    released: bool
    run_id: Optional[str] = None
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _live_run(project_id: int) -> Optional[Dict[str, Any]]:
    run = _active_runs.get(project_id)
    if run and run.get("status") in ("running", "paused", "awaiting_review"):
        return run
    return None


async def _get_chapter(db: AsyncSession, project_id: int, chapter_id: int) -> Chapter:
    result = await db.execute(select(Chapter).where(Chapter.id == chapter_id, Chapter.project_id == project_id))
    chapter = result.scalar_one_or_none()
    if not chapter:
        raise DomainError("Chapter not found", "NOT_FOUND", stage="review", context={"chapter_id": chapter_id})
    return chapter


async def _summary_payload(db: AsyncSession, project_id: int) -> ReviewGateSummary:
    """审核门摘要：全部由 DB 推导（重启后仍准确），run_status 来自内存。"""
    result = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.index))
    chapters = result.scalars().all()

    entries = [
        ChapterReviewEntry(
            chapter_id=ch.id,
            index=ch.index,
            title=ch.title,
            review_status=ch.review_status,
            paragraph_count=len(ch.paragraphs) if ch.paragraphs else 0,
        )
        for ch in chapters
    ]
    total = len(entries)
    approved = sum(1 for e in entries if e.review_status == "approved")

    run = _active_runs.get(project_id)
    run_status = run.get("status", "not_started") if run else "not_started"

    return ReviewGateSummary(
        project_id=project_id,
        total_chapters=total,
        approved_chapters=approved,
        pending_chapters=total - approved,
        all_approved=total > 0 and approved == total,
        run_status=run_status,
        chapters=entries,
    )


def _preview_for_paragraph(para: Paragraph, chapter: Chapter, project_id: int) -> RoutingPreviewItem:
    """单段路由预览：与合成路径共用 build_routing_input + make_tts_routing_decision。

    镜像 SynthesizePipeline.run 的文本规则：edited_text 优先、图片占位剥离。
    - edited_text == ""（有意清空）→ skip_reason="empty_text"
    - 剥离 [插图:...] 后为空但原文含插图块 → skip_reason="image_only"
    manual_engine / manual_voice_id 覆盖在自动决策之后应用（客户最终控制），
    音色随引擎重归一化（Edge ID → Kokoro ID 等），fallback 同步重算。
    """
    base = RoutingPreviewItem(paragraph_id=para.id, paragraph_index=para.index)

    raw_text = para.edited_text if para.edited_text is not None else (para.text or "")
    if para.edited_text is not None and para.edited_text == "":
        base.skipped = True
        base.skip_reason = "empty_text"
        return base

    effective = _strip_image_placeholders(raw_text)
    if not effective:
        base.skipped = True
        base.skip_reason = "image_only" if "[插图" in (raw_text or "") else "empty_text"
        base.effective_text = effective
        return base

    try:
        inp = build_routing_input(para, chapter, project_id)
    except Exception as e:
        logger.warning("build_routing_input failed for para %s: %s", para.id, e)
        base.skipped = True
        base.skip_reason = "empty_text"
        return base
    if inp is None:
        base.skipped = True
        base.skip_reason = "empty_text"
        return base

    # 与合成一致：进路由前剥离图片占位（pipeline.run 内同样就地剥离）
    inp.text = effective
    decision = make_tts_routing_decision(inp)

    engine = decision.engine_choice
    voice_id = decision.voice_id
    fallback = decision.fallback_engine
    reasoning = decision.reasoning

    if para.manual_engine or para.manual_voice_id:
        if para.manual_engine:
            engine = para.manual_engine  # type: ignore[assignment]
            reasoning = f"manual engine override → {engine}; " + reasoning
        if para.manual_voice_id:
            voice_id = para.manual_voice_id
            reasoning = f"manual voice override → {voice_id}; " + reasoning
        # 音色随（可能被覆盖的）引擎重归一化：Edge ID 喂给 Kokoro 会静默失败
        voice_id = _normalize_voice_id(voice_id, engine, strict=bool(para.manual_voice_id))
        fallback = "edge" if engine != "edge" else "kokoro"  # type: ignore[assignment]

    return RoutingPreviewItem(
        paragraph_id=para.id,
        paragraph_index=para.index,
        skipped=False,
        effective_text=effective,
        engine_choice=engine,
        voice_id=voice_id,
        prosody_overrides=decision.prosody_overrides,
        fallback_engine=fallback,
        reasoning=reasoning,
    )


async def _freeze_chapter_routing(db: AsyncSession, project_id: int, chapter: Chapter) -> None:
    """章节确认时把当前路由预览固化到 paragraph.routing_* + Routing 行 (customer_approved)。

    固化是「客户批准了什么」的审计快照：编排器合成仍按段落字段重算（结果一致），
    Celery 单段重生成直接读这些列 → 确认后的重生成采用客户批准的引擎/音色。
    预览失败（如引擎配置问题）不阻断确认 —— 记日志后继续（best-effort 审计）。
    """
    result = await db.execute(
        select(Paragraph).where(Paragraph.project_id == project_id, Paragraph.chapter_id == chapter.id)
    )
    for para in result.scalars().all():
        try:
            preview = _preview_for_paragraph(para, chapter, project_id)
        except Exception as e:
            logger.warning("routing freeze skipped for para %s: %s", para.id, e)
            continue
        para.routing_engine = preview.engine_choice or ("skip" if preview.skipped else None)
        para.routing_voice_id = preview.voice_id
        para.routing_prosody_overrides = preview.prosody_overrides
        para.routing_fallback = preview.fallback_engine
        para.routing_reasoning = preview.skip_reason if preview.skipped else preview.reasoning
        db.add(
            Routing(
                project_id=project_id,
                chapter_id=chapter.id,
                paragraph_id=para.id,
                engine_choice=preview.engine_choice or ("skip" if preview.skipped else None),
                voice_id=preview.voice_id,
                prosody_overrides=preview.prosody_overrides,
                fallback_engine=preview.fallback_engine,
                reasoning=preview.skip_reason if preview.skipped else preview.reasoning,
                status="customer_approved",
            )
        )


async def _preflight_checkpoints(project_id: int) -> None:
    """恢复路径预检：annotate/edit/audio_postprocess checkpoint 对每个非空段存在。

    缺失 → 400：防 checkpoint 文件丢失时 edit 阶段重跑毁掉客户编辑。
    """
    db = create_async_session()
    try:
        result = await db.execute(
            select(Paragraph, Chapter)
            .join(Chapter, Paragraph.chapter_id == Chapter.id)
            .where(Paragraph.project_id == project_id)
            .order_by(Chapter.index, Paragraph.index)
        )
        cp = CheckpointManager(project_id)
        missing: List[str] = []
        for para, chapter in result.all():
            if not (para.text or "").strip() and not (para.edited_text or "").strip():
                continue
            for stage in ("annotate", "edit", "audio_postprocess"):
                if not cp.is_stage_done(stage, chapter.index, para.index):
                    missing.append(f"ch{chapter.index} p{para.index} stage={stage}")
        if missing:
            raise DomainError(
                f"Missing checkpoints for {len(missing)} paragraph-stage(s): "
                + ", ".join(missing[:10])
                + ("..." if len(missing) > 10 else ""),
                "BAD_REQUEST",
                stage="review",
                context={"missing": missing},
            )
    finally:
        await db.close()


async def _release_or_recover(project_id: int, background_tasks: BackgroundTasks) -> ConfirmResponse:
    """门放行：活跃 run → 轮询 ≤2s 内发现全 approved 继续合成；死 run → 预检后拉起恢复 run。"""
    run = _live_run(project_id)
    if run:
        run_id = run["run_id"]
        logger.info("Review gate: live run %s will auto-release on next poll tick", run_id)
        return ConfirmResponse(released=True, run_id=run_id, message="Gate released; live run continuing to synthesize")

    await _preflight_checkpoints(project_id)

    run_id = f"autorun_recover_{project_id}_{int(datetime.now().timestamp())}"
    # Sentinel 竞争保护：先占位再 add_task，防并发 /confirm 重复拉起。
    # 恢复 run 走 mode="review"：checkpoint 跳过已完成阶段，门因全 approved
    # 而跳过 → 直达 synthesize。
    _active_runs[project_id] = {
        "run_id": run_id,
        "status": "running",
        "mode": "review",
        "config": AutoRunConfig().model_dump(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "current_stage": None,
        "completed_stages": [],
    }
    background_tasks.add_task(
        _run_auto_pipeline_blocking,
        project_id=project_id,
        run_id=run_id,
        config=AutoRunConfig(),
        pause_points=None,
        mode="review",
    )
    logger.info("Review gate: launched recovery run %s for project %s", run_id, project_id)
    return ConfirmResponse(
        released=True, run_id=run_id, message="Recovery run launched; gate skipped (all approved) → synthesize"
    )


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("", response_model=ReviewGateSummary)
async def get_review_gate_summary(project_id: int, db: AsyncSession = Depends(get_async_db)):
    """审核门摘要（章节确认状态 + 计数 + run_status）。

    不存在的项目返回空摘要而非 404（与列表端点语义一致）。
    """
    return await _summary_payload(db, project_id)


@router.post("/chapters/{chapter_id}/approve", response_model=ReviewGateSummary)
async def approve_chapter(project_id: int, chapter_id: int, db: AsyncSession = Depends(get_async_db)):
    """确认单章：置 approved + 固化当前路由预览（routing_* 列 + Routing 行）。"""
    chapter = await _get_chapter(db, project_id, chapter_id)
    if chapter.review_status != "approved":
        chapter.review_status = "approved"
        await _freeze_chapter_routing(db, project_id, chapter)
        await db.commit()
    return await _summary_payload(db, project_id)


@router.post("/chapters/{chapter_id}/reset", response_model=ReviewGateSummary)
async def reset_chapter_review(project_id: int, chapter_id: int, db: AsyncSession = Depends(get_async_db)):
    """把已确认章节打回待审（pending_review）。从未 approved 的章节 → 409。"""
    chapter = await _get_chapter(db, project_id, chapter_id)
    if chapter.review_status != "approved":
        raise DomainError(
            "Chapter is not approved; nothing to reset",
            "CONFLICT",
            stage="review",
            context={"chapter_id": chapter_id, "review_status": chapter.review_status},
        )
    chapter.review_status = "pending_review"
    await db.commit()
    return await _summary_payload(db, project_id)


@router.post("/approve-all", response_model=ReviewGateSummary)
async def approve_all_chapters(project_id: int, db: AsyncSession = Depends(get_async_db)):
    """整书确认：全部章节置 approved + 固化路由。活跃 run 的门轮询会自行放行。"""
    result = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.index))
    for ch in result.scalars().all():
        if ch.review_status != "approved":
            ch.review_status = "approved"
            await _freeze_chapter_routing(db, project_id, ch)
    await db.commit()
    return await _summary_payload(db, project_id)


@router.get("/chapters/{chapter_id}/routing-preview", response_model=RoutingPreviewResponse)
async def get_chapter_routing_preview(project_id: int, chapter_id: int, db: AsyncSession = Depends(get_async_db)):
    """章节逐段路由预览（与合成共用同一份路由代码；skip 段带原因）。"""
    chapter = await _get_chapter(db, project_id, chapter_id)
    result = await db.execute(
        select(Paragraph)
        .where(Paragraph.project_id == project_id, Paragraph.chapter_id == chapter_id)
        .order_by(Paragraph.index)
    )
    previews = [_preview_for_paragraph(p, chapter, project_id) for p in result.scalars().all()]
    skipped = sum(1 for p in previews if p.skipped)
    return RoutingPreviewResponse(
        chapter_id=chapter_id,
        synthesized_count=len(previews) - skipped,
        skipped_count=skipped,
        previews=previews,
    )


@router.patch("/chapters/{chapter_id}/paragraphs/{paragraph_id}", response_model=ReviewParagraphPatchResponse)
async def patch_review_paragraph(
    project_id: int,
    chapter_id: int,
    paragraph_id: int,
    payload: ReviewParagraphPatch,
    db: AsyncSession = Depends(get_async_db),
):
    """终审段落编辑：润色 edited_text + 标注修正 + manual_engine/voice 覆盖。

    - 逐字段 diff，仅实际变更计入 changes_made；全 no-op → 不写审计、不打回
    - edited_text 变更 → 追加 TTSEdit 版本行（source="human"）
    - 有效编辑 → paragraph.status="edited"；章节已 approved → 打回 pending_review
      并失效该段路由（Routing 行标 superseded）
    - manual_engine 非法 → 400；未知字段/越界 → 422（extra=forbid + 值域）
    """
    chapter = await _get_chapter(db, project_id, chapter_id)
    result = await db.execute(
        select(Paragraph).where(Paragraph.id == paragraph_id, Paragraph.chapter_id == chapter_id)
    )
    para = result.scalar_one_or_none()
    if not para:
        raise DomainError(
            "Paragraph not found in chapter",
            "NOT_FOUND",
            stage="review",
            context={"chapter_id": chapter_id, "paragraph_id": paragraph_id},
        )

    if payload.manual_engine is not None and payload.manual_engine not in _VALID_ENGINES:
        raise DomainError(
            f"Invalid manual_engine: {payload.manual_engine}",
            "BAD_REQUEST",
            stage="review",
            context={"valid_engines": sorted(_VALID_ENGINES)},
        )

    changes_made: List[str] = []
    data = payload.model_dump(exclude_unset=True)

    # clear_* 开关优先（显式清除覆盖，恢复自动路由）
    if payload.clear_manual_engine and para.manual_engine is not None:
        para.manual_engine = None
        changes_made.append("manual_engine")
    if payload.clear_manual_voice_id and para.manual_voice_id is not None:
        para.manual_voice_id = None
        changes_made.append("manual_voice_id")

    old_edited_text = para.edited_text
    for field, value in data.items():
        if field in ("clear_manual_engine", "clear_manual_voice_id", "note"):
            continue
        if getattr(para, field) != value:
            setattr(para, field, value)
            changes_made.append(field)

    # note（追加备注）：未显式给 notes 时附加到现有 notes
    if "note" in data and "notes" not in data and data["note"]:
        para.notes = (para.notes + "; " + data["note"]) if para.notes else data["note"]
        if "notes" not in changes_made:
            changes_made.append("notes")

    tts_edit_version: Optional[int] = None
    if "edited_text" in changes_made:
        result = await db.execute(
            select(TTSEdit).where(TTSEdit.paragraph_id == para.id).order_by(TTSEdit.version.desc())
        )
        last_edit = result.scalars().first()
        tts_edit_version = (last_edit.version + 1) if last_edit else 1
        db.add(
            TTSEdit(
                project_id=project_id,
                chapter_id=chapter_id,
                paragraph_id=para.id,
                version=tts_edit_version,
                edited_text=para.edited_text or "",
                changes_made=["human_review_edit"],
                source="human",
                rationale="人工终审编辑 (manual review edit)",
            )
        )

    chapter_review_reset = False
    if changes_made:
        para.status = "edited"  # 人工编辑后的段落状态
        if chapter.review_status == "approved":
            chapter.review_status = "pending_review"
            chapter_review_reset = True
            # 失效该段路由：Routing 行标 superseded + 清 routing_* 列
            result = await db.execute(
                select(Routing).where(Routing.paragraph_id == para.id, Routing.status != "superseded")
            )
            for r in result.scalars().all():
                r.status = "superseded"
            para.routing_engine = None
            para.routing_voice_id = None
            para.routing_prosody_overrides = None
            para.routing_fallback = None
            para.routing_reasoning = None
            para.routing_estimated_cost = 0.0
            para.routing_estimated_duration = 0
        await db.commit()
        await db.refresh(para)

    return ReviewParagraphPatchResponse(
        changes_made=changes_made,
        paragraph=para.to_full_dict(),
        tts_edit_version=tts_edit_version,
        chapter_review_reset=chapter_review_reset,
    )


@router.post("/confirm", response_model=ConfirmResponse)
async def confirm_and_release(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_async_db),
):
    """整书确认并放行：全部章节 approved → 活跃 run 轮询放行 / 死 run 拉起恢复 run。

    与 approve-all 的差别：本端点额外承担「死门恢复」—— run 已死（进程重启）
    时预检 checkpoint 后内部拉起恢复 run（不经 /auto-run/start，避开审核纪元重置）。
    """
    result = await db.execute(select(Chapter).where(Chapter.project_id == project_id).order_by(Chapter.index))
    chapters = result.scalars().all()
    for ch in chapters:
        if ch.review_status != "approved":
            ch.review_status = "approved"
            await _freeze_chapter_routing(db, project_id, ch)
    await db.commit()

    return await _release_or_recover(project_id, background_tasks)


@router.post("/abandon", response_model=ConfirmResponse)
async def abandon_review_gate(project_id: int, db: AsyncSession = Depends(get_async_db)):
    """放弃审核（仅死门可用）：清章节 review_status + project.status 离开 awaiting_review。

    run 存活时 → 409（应改用 /auto-run/cancel）。
    """
    run = _live_run(project_id)
    if run:
        raise DomainError(
            "Cannot abandon while run is alive; use /auto-run/cancel instead",
            "CONFLICT",
            stage="review",
            context={"project_id": project_id, "run_status": run.get("status")},
        )

    project = await db.get(Project, project_id)
    result = await db.execute(select(Chapter).where(Chapter.project_id == project_id))
    for ch in result.scalars().all():
        ch.review_status = None
    if project is not None and project.status == "awaiting_review":
        project.status = "draft"
        project.current_stage = None
    await db.commit()

    return ConfirmResponse(released=False, run_id=None, message="Review gate abandoned; project status reset")

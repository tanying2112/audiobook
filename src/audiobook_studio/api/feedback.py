"""Feedback API endpoints — 人工反馈收集与管理."""

from datetime import datetime, timezone
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from ..exceptions import NotFoundError

router = APIRouter(prefix="/feedback", tags=["feedback"])


# Request/Response models
class FeedbackCreate(BaseModel):
    """创建反馈请求."""

    source: str = Field(..., description="反馈来源: human_edit, quality_judge, user_rating")
    stage: str = Field(..., description="发生反馈的环节")
    book_id: str = Field(..., description="书籍 ID")
    paragraph_index: Optional[int] = None
    chapter_index: Optional[int] = None
    input_snapshot: dict[str, Any] = Field(..., description="输入数据快照")
    llm_output: dict[str, Any] = Field(..., description="LLM 输出")
    corrected_output: dict[str, Any] = Field(..., description="修正后的期望输出")
    rationale: str = Field(..., min_length=10, description="修改理由")


class FeedbackResponse(BaseModel):
    """反馈响应."""

    id: str
    timestamp: datetime
    source: str
    stage: str
    book_id: str
    paragraph_index: Optional[int]
    chapter_index: Optional[int]
    rationale: str
    diff_summary: str
    pattern_tags: List[str]
    contract_version: int


class FeedbackListResponse(BaseModel):
    """反馈列表响应."""

    items: List[FeedbackResponse]
    total: int


# In-memory storage (replace with DB in production)
_feedback_store: List[dict[str, Any]] = []


@router.post("/", response_model=FeedbackResponse)
async def create_feedback(feedback: FeedbackCreate):
    """提交人工反馈."""
    import uuid

    feedback_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Simple diff summary
    diff_summary = f"Modified {feedback.stage} output"
    pattern_tags = ["human_edit"]

    # Try to infer pattern tags from rationale
    rationale_lower = feedback.rationale.lower()
    if "emotion" in rationale_lower or "情感" in rationale_lower:
        pattern_tags.append("emotion_mismatch")
    if "speaker" in rationale_lower or "角色" in rationale_lower or "说话人" in rationale_lower:
        pattern_tags.append("speaker_error")
    if "speed" in rationale_lower or "语速" in rationale_lower:
        pattern_tags.append("wrong_speed")
    if "pitch" in rationale_lower or "音高" in rationale_lower:
        pattern_tags.append("wrong_pitch")

    fb = {
        "id": feedback_id,
        "timestamp": now,
        "source": feedback.source,
        "stage": feedback.stage,
        "book_id": feedback.book_id,
        "paragraph_index": feedback.paragraph_index,
        "chapter_index": feedback.chapter_index,
        "input_snapshot": feedback.input_snapshot,
        "llm_output": feedback.llm_output,
        "corrected_output": feedback.corrected_output,
        "rationale": feedback.rationale,
        "diff_summary": diff_summary,
        "pattern_tags": pattern_tags,
        "contract_version": 1,
    }
    # ① 先入库（feedback 存储）
    _feedback_store.append(fb)

    # ② 后入队：投喂 SOP 反思循环写库同时入队 collector（P0.1）。
    # 入队失败仅记录日志，绝不影响 feedback 响应（静默降级）。
    _feed_sop_collector_feedback(feedback, pattern_tags)

    return FeedbackResponse(**fb)


def _feed_sop_collector_feedback(feedback: FeedbackCreate, pattern_tags: list[str]) -> None:
    """把一条人工反馈映射为 SOP 纠错并投喂 CorrectionCollector。

    非阻塞：collector 不可用、project_id 不可解析、或入队失败时仅记录日志，
    绝不抛出（feedback 响应不受影响）。映射规则：
      - field ← pattern_tags 推断（emotion_mismatch→emotion，speaker_error→speaker_canonical_name，
        wrong_speed→speech_rate，wrong_pitch→pitch_shift_semitones，否则 fallback 'output'）
      - project_id ← int(book_id)（非整数则跳过投喂）
      - chapter_index/paragraph_index ← feedback 可选字段（默认 0）
      - original_value ← llm_output，corrected_value ← corrected_output
      - genre ← 'default'（对应 genre-agnostic 桶；真实 genre 由前端 WS/HTTP 路径带）
    """
    try:
        # book_id 未必是数字（历史兼容为 str），仅数字时投喂
        try:
            project_id = int(feedback.book_id)
        except (TypeError, ValueError):
            return

        tag_to_field = {
            "emotion_mismatch": "emotion",
            "speaker_error": "speaker_canonical_name",
            "wrong_speed": "speech_rate",
            "wrong_pitch": "pitch_shift_semitones",
        }
        field = next(
            (tag_to_field[tag] for tag in pattern_tags if tag in tag_to_field),
            "output",
        )

        # 采集器期望完整 dict；缺失字段用契约默认值补齐
        correction_dict = {
            "project_id": project_id,
            "chapter_index": feedback.chapter_index if feedback.chapter_index is not None else 0,
            "paragraph_index": feedback.paragraph_index if feedback.paragraph_index is not None else 0,
            "field": field,
            "original_value": feedback.llm_output,
            "corrected_value": feedback.corrected_output,
            "genre": "default",
            "context": {"stage": feedback.stage, "source": feedback.source, "rationale": feedback.rationale},
        }

        from ..pipeline.sop_reflection import get_correction_collector

        collector = get_correction_collector()
        collector.add_correction_dict(correction_dict)
    except Exception as exc:  # noqa: BLE001 — 入队失败绝不影响 feedback 主流程
        import logging

        logging.getLogger(__name__).warning(
            "feedback→SOP collector 投喂失败（静默降级，不影响反馈入库）: %s", exc
        )


@router.get("/", response_model=FeedbackListResponse)
async def list_feedback(
    book_id: Optional[str] = None,
    stage: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """获取反馈列表."""
    filtered = _feedback_store

    if book_id:
        filtered = [f for f in filtered if f["book_id"] == book_id]
    if stage:
        filtered = [f for f in filtered if f["stage"] == stage]
    if source:
        filtered = [f for f in filtered if f["source"] == source]

    total = len(filtered)
    items = filtered[offset : offset + limit]

    return FeedbackListResponse(items=[FeedbackResponse(**f) for f in items], total=total)


@router.get("/{feedback_id}", response_model=FeedbackResponse)
async def get_feedback(feedback_id: str):
    """获取单条反馈详情."""
    for f in _feedback_store:
        if f["id"] == feedback_id:
            return FeedbackResponse(**f)
    raise NotFoundError(resource="Feedback", identifier=feedback_id)


@router.get("/stats/summary")
async def get_feedback_stats(book_id: Optional[str] = None):
    """获取反馈统计摘要."""
    filtered = _feedback_store
    if book_id:
        filtered = [f for f in filtered if f["book_id"] == book_id]

    # Count by stage
    by_stage = {}
    for f in filtered:
        by_stage[f["stage"]] = by_stage.get(f["stage"], 0) + 1

    # Count by source
    by_source = {}
    for f in filtered:
        by_source[f["source"]] = by_source.get(f["source"], 0) + 1

    # Pattern tag frequency
    tag_freq = {}
    for f in filtered:
        for tag in f.get("pattern_tags", []):
            tag_freq[tag] = tag_freq.get(tag, 0) + 1

    return {
        "total_feedback": len(filtered),
        "by_stage": by_stage,
        "by_source": by_source,
        "top_pattern_tags": sorted(tag_freq.items(), key=lambda x: -x[1])[:10],
    }

"""Feedback API endpoints — 人工反馈收集与管理."""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/feedback", tags=["feedback"])


# Request/Response models
class FeedbackCreate(BaseModel):
    """创建反馈请求."""

    source: str = Field(
        ..., description="反馈来源: human_edit, quality_judge, user_rating"
    )
    stage: str = Field(..., description="发生反馈的环节")
    book_id: str = Field(..., description="书籍 ID")
    paragraph_index: Optional[int] = None
    chapter_index: Optional[int] = None
    input_snapshot: dict = Field(..., description="输入数据快照")
    llm_output: dict = Field(..., description="LLM 输出")
    corrected_output: dict = Field(..., description="修正后的期望输出")
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
_feedback_store: List[dict] = []


@router.post("/", response_model=FeedbackResponse)
async def create_feedback(feedback: FeedbackCreate):
    """提交人工反馈."""
    import uuid

    feedback_id = str(uuid.uuid4())
    now = datetime.utcnow()

    # Simple diff summary
    diff_summary = f"Modified {feedback.stage} output"
    pattern_tags = ["human_edit"]

    # Try to infer pattern tags from rationale
    rationale_lower = feedback.rationale.lower()
    if "emotion" in rationale_lower or "情感" in rationale_lower:
        pattern_tags.append("emotion_mismatch")
    if (
        "speaker" in rationale_lower
        or "角色" in rationale_lower
        or "说话人" in rationale_lower
    ):
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
    _feedback_store.append(fb)

    return FeedbackResponse(**fb)


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

    return FeedbackListResponse(
        items=[FeedbackResponse(**f) for f in items], total=total
    )


@router.get("/{feedback_id}", response_model=FeedbackResponse)
async def get_feedback(feedback_id: str):
    """获取单条反馈详情."""
    for f in _feedback_store:
        if f["id"] == feedback_id:
            return FeedbackResponse(**f)
    raise HTTPException(status_code=404, detail="Feedback not found")


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

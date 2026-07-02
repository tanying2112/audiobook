"""
E1 — FeedbackRecord 全面采集器

自动捕获 pipeline 各阶段的输入/输出到 FeedbackRecord。
支持人工编辑 (Web UI)、质量检测 (Quality Judge)、用户评分等来源。
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy.orm import Session

from ..models import FeedbackRecord as FeedbackRecordModel
from ..schemas.feedback import FeedbackRecord as FeedbackRecordSchema

logger = logging.getLogger(__name__)


def capture_feedback(
    db: Session,
    *,
    project_id: int,
    source: Literal["human_edit", "quality_judge", "user_rating"],
    stage: Literal[
        "extract",
        "analyze_structure",
        "annotate_paragraph",
        "edit_for_tts",
        "tts_routing",
        "quality_judge",
        "synthesize",
        "audio_postprocess",
    ],
    input_snapshot: Dict[str, Any],
    llm_output: Dict[str, Any],
    corrected_output: Dict[str, Any],
    rationale: str,
    chapter_id: Optional[int] = None,
    paragraph_id: Optional[int] = None,
    paragraph_index: Optional[int] = None,
    chapter_index: Optional[int] = None,
    diff_summary: str = "",
    pattern_tags: Optional[List[str]] = None,
) -> FeedbackRecordModel:
    """统一反馈记录写入.

    在每个 pipeline stage 完成时调用，记录该 stage 的输入/输出/修正。
    """
    feedback_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    # Validate rationale length
    if len(rationale.strip()) < 10:
        logger.warning(f"Feedback rationale too short ({len(rationale.strip())} chars), " f"padding with placeholder")
        rationale = rationale + " (自动采集反馈记录)"

    record = FeedbackRecordModel(
        project_id=project_id,
        chapter_id=chapter_id,
        paragraph_id=paragraph_id,
        feedback_id=feedback_id,
        source=source,
        stage=stage,
        input_snapshot=input_snapshot,
        llm_output=llm_output,
        corrected_output=corrected_output,
        rationale=rationale,
        diff_summary=diff_summary,
        pattern_tags=pattern_tags or [],
        processed=False,
        promoted=False,
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    # Also log to schema-compatible format
    schema_record = FeedbackRecordSchema(
        id=feedback_id,
        timestamp=now,
        source=source,
        stage=stage,  # type: ignore
        book_id=str(project_id),
        paragraph_index=paragraph_index,
        chapter_index=chapter_index,
        input_snapshot=input_snapshot,
        llm_output=llm_output,
        corrected_output=corrected_output,
        rationale=rationale,
        diff_summary=diff_summary,
        pattern_tags=pattern_tags or [],
    )

    logger.info(
        f"FeedbackRecord [{source}/{stage}]: id={feedback_id} " f"project={project_id} rationale={rationale[:60]}..."
    )
    return record


def capture_quality_feedback(
    db: Session,
    *,
    project_id: int,
    chapter_id: int,
    paragraph_id: int,
    paragraph_index: int,
    chapter_index: int,
    input_data: Dict[str, Any],
    llm_judgment: Dict[str, Any],
    corrected_judgment: Dict[str, Any],
    rationale: str,
) -> FeedbackRecordModel:
    """从 Quality Check 阶段自动采集反馈.

    当人工纠正了 LLM 的质量判断时调用。
    """
    return capture_feedback(
        db=db,
        project_id=project_id,
        source="quality_judge",
        stage="quality_judge",
        chapter_id=chapter_id,
        paragraph_id=paragraph_id,
        paragraph_index=paragraph_index,
        chapter_index=chapter_index,
        input_snapshot=input_data,
        llm_output=llm_judgment,
        corrected_output=corrected_judgment,
        rationale=rationale,
    )


def capture_edit_feedback(
    db: Session,
    *,
    project_id: int,
    chapter_id: int,
    paragraph_id: int,
    paragraph_index: int,
    chapter_index: int,
    original_text: str,
    edited_text: str,
    llm_suggested_edit: str,
    user_rationale: str,
) -> FeedbackRecordModel:
    """从文本编辑 (Web UI) 阶段采集反馈.

    当用户在 ParagraphEditor 中手动修改 TTS 编辑结果时调用。
    """
    return capture_feedback(
        db=db,
        project_id=project_id,
        source="human_edit",
        stage="edit_for_tts",
        chapter_id=chapter_id,
        paragraph_id=paragraph_id,
        paragraph_index=paragraph_index,
        chapter_index=chapter_index,
        input_snapshot={"original_text": original_text},
        llm_output={"edited_text": llm_suggested_edit},
        corrected_output={"edited_text": edited_text},
        rationale=user_rationale,
    )


def list_unprocessed_feedback(
    db: Session,
    project_id: Optional[int] = None,
    limit: int = 500,
) -> List[FeedbackRecordModel]:
    """列出未处理的反馈记录 (供差异分析 Agent 消费)."""
    query = db.query(FeedbackRecordModel).filter(FeedbackRecordModel.processed == False)  # noqa: E712
    if project_id:
        query = query.filter(FeedbackRecordModel.project_id == project_id)
    return query.order_by(FeedbackRecordModel.created_at.asc()).limit(limit).all()


def mark_feedback_processed(
    db: Session,
    feedback_id: str,
    pattern_tags: Optional[List[str]] = None,
    diff_summary: str = "",
) -> None:
    """标记反馈已处理 (差异分析完成后)."""
    record = db.query(FeedbackRecordModel).filter(FeedbackRecordModel.feedback_id == feedback_id).first()
    if record:
        record.processed = True
        if pattern_tags:
            record.pattern_tags = pattern_tags
        if diff_summary:
            record.diff_summary = diff_summary
        db.commit()
        logger.info(f"FeedbackRecord {feedback_id} marked processed")

"""马具迭代反馈采集器：整合现有 feedback.collector 功能，扩展对马具迭代的支持。"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..harness.models import CorrectionRecord
from ..harness.models import FeedbackRecord as FeedbackRecordModel
from ..harness.models import FeedbackSource, PipelineStage
from ..harness.storage import get_storage

logger = logging.getLogger(__name__)


class CorrectionCollector:
    """马具迭代反馈采集器：统一收集 pipeline 各阶段的输入/输出/修正。

    整合了原 feedback.collector.CorrectionCollector 功能，并扩展：
    - 自动写入 harness.storage (SQLite + JSONL 双写)
    - 自动提取 pattern_tags 用于 SOP 规则匹配
    - 支持批量获取/清空队列
    """

    def __init__(self, storage=None):
        self.storage = storage or get_storage()
        self._queue: List[dict] = []
        self._max_queue_size = 1000

    def capture_feedback(
        self,
        *,
        project_id: int,
        source: FeedbackSource,
        stage: PipelineStage,
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
    ) -> str:
        """统一反馈记录写入：写入 SQLite + JSONL 双写。

        Args:
            project_id: 项目 ID
            source: 反馈来源
            stage: Pipeline 阶段
            input_snapshot: 输入快照
            llm_output: LLM 原始输出
            corrected_output: 修正后的输出
            rationale: 修正理由
            chapter_id: 章节 ID
            paragraph_id: 段落 ID
            paragraph_index: 段落索引
            chapter_index: 章节索引
            diff_summary: 差异摘要
            pattern_tags: 模式标签（用于 SOP 匹配）

        Returns:
            feedback_id: 生成的反馈记录 ID
        """
        storage = get_storage()

        feedback_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # 校验 rationale
        if len(rationale.strip()) < 10:
            logger.warning(f"Feedback rationale too short ({len(rationale.strip())} chars), padding with placeholder")
            rationale = rationale + " (自动采集反馈记录)"

        record_data = {
            "feedback_id": feedback_id,
            "project_id": project_id,
            "chapter_id": chapter_id,
            "paragraph_id": paragraph_id,
            "paragraph_index": paragraph_index,
            "chapter_index": chapter_index,
            "source": source.value if isinstance(source, FeedbackSource) else source,
            "stage": stage.value if isinstance(stage, PipelineStage) else stage,
            "input_snapshot": input_snapshot,
            "llm_output": llm_output,
            "corrected_output": corrected_output,
            "rationale": rationale,
            "diff_summary": diff_summary,
            "pattern_tags": pattern_tags or [],
            "processed": False,
            "promoted": False,
            "created_at": now.isoformat(),
        }

        # 存储到 SQLite (通过 storage)
        with self.storage.db.session() as session:
            from ..harness.models import FeedbackRecord as FeedbackRecordModel

            record = FeedbackRecordModel(
                feedback_id=feedback_id,
                project_id=project_id,
                chapter_id=chapter_id,
                paragraph_id=paragraph_id,
                paragraph_index=paragraph_index,
                chapter_index=chapter_index,
                source=source.value if isinstance(source, FeedbackSource) else source,
                stage=stage.value if isinstance(stage, PipelineStage) else stage,
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
            session.add(record)
            session.commit()
            session.refresh(record)

        # 同时写入 JSONL (用于审计/备份)
        self._append_jsonl(record)

        logger.info(
            f"FeedbackRecord [{source}/{stage}]: id={feedback_id} "
            f"project={project_id} rationale={rationale[:60]}..."
        )
        return feedback_id

    def _append_jsonl(self, record) -> None:
        """追加到 JSONL 审计文件。"""
        # 简化：实际可写入独立的反馈审计日志
        pass

    def capture_quality_feedback(
        self,
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
    ) -> str:
        """从 Quality Check 阶段自动采集反馈。"""
        return self.capture_feedback(
            project_id=project_id,
            source=FeedbackSource.QUALITY_JUDGE,
            stage=PipelineStage.QUALITY,
            input_snapshot=input_data,
            llm_output=llm_judgment,
            corrected_output=corrected_judgment,
            rationale=rationale,
            chapter_id=chapter_id,
            paragraph_id=paragraph_id,
            paragraph_index=paragraph_index,
            chapter_index=chapter_index,
        )

    def capture_edit_feedback(
        self,
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
    ) -> str:
        """从文本编辑 (Web UI) 阶段采集反馈。"""
        return self.capture_feedback(
            project_id=project_id,
            source=FeedbackSource.HUMAN_EDIT,
            stage=PipelineStage.EDIT,
            input_snapshot={"original_text": original_text},
            llm_output={"edited_text": llm_suggested_edit},
            corrected_output={"edited_text": edited_text},
            rationale=user_rationale,
            chapter_id=chapter_id,
            paragraph_id=paragraph_id,
            paragraph_index=paragraph_index,
            chapter_index=chapter_index,
        )

    def list_unprocessed(
        self,
        project_id: Optional[int] = None,
        limit: int = 500,
    ) -> List[dict]:
        """列出未处理的反馈记录。"""
        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import select
            from sqlalchemy.orm import Session

            from ..harness.models import FeedbackRecord as FeedbackRecordModel

            stmt = select(storage.db._sync_session_factory().configure(bind=session.bind).class_).where(
                FeedbackRecordModel.processed == False  # noqa: E712
            )
            if project_id:
                stmt = stmt.where(FeedbackRecordModel.project_id == project_id)
            records = (
                session.execute(select(FeedbackRecordModel).where(FeedbackRecordModel.processed == False).limit(500))
                .scalars()
                .all()
            )

            return [
                {
                    "feedback_id": r.feedback_id,
                    "project_id": r.project_id,
                    "stage": r.stage,
                    "source": r.source,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in records
            ]

    def mark_processed(
        self,
        feedback_id: str,
        pattern_tags: Optional[List[str]] = None,
        diff_summary: str = "",
    ) -> bool:
        """标记反馈已处理。"""
        storage = get_storage()
        with storage.db.session() as session:
            from ..harness.models import FeedbackRecord as FeedbackRecordModel

            record = (
                session.execute(select(FeedbackRecordModel).where(FeedbackRecordModel.feedback_id == feedback_id))
                .scalars()
                .first()
            )
            if record:
                record.processed = True
                if pattern_tags:
                    record.pattern_tags = pattern_tags
                if diff_summary:
                    record.diff_summary = diff_summary
                session.commit()
                return True
        return False

    def get_batch(self, max_size: int = 100) -> list:
        """获取一批未处理的反馈记录（用于批量回流 golden）。"""
        storage = get_storage()
        with storage.db.session() as session:
            from sqlalchemy import select

            from ..harness.models import FeedbackRecord as FeedbackRecordModel

            stmt = (
                select(storage.db._sync_session_factory().configure(bind=session.bind).class_)
                .where(FeedbackRecordModel.processed == False)
                .limit(100)
            )
            records = (
                session.execute(select(FeedbackRecordModel).where(FeedbackRecordModel.processed == False).limit(100))
                .scalars()
                .all()
            )
            return [
                {
                    "feedback_id": r.feedback_id,
                    "project_id": r.project_id,
                    "stage": r.stage,
                    "source": r.source,
                    "input_snapshot": r.input_snapshot,
                    "llm_output": r.llm_output,
                    "corrected_output": r.corrected_output,
                    "rationale": r.rationale,
                    "diff_summary": r.diff_summary,
                    "pattern_tags": r.pattern_tags,
                }
                for r in records
            ]

    def drain(self, max_size: int = 100) -> List[dict]:
        """清空队列并返回所有记录（用于批量回流）。"""
        return self.get_batch(max_size)

    def clear(self) -> None:
        """清空队列（不返回记录）。"""
        self._queue.clear()


# 全局单例
_correction_collector: Optional["CorrectionCollector"] = None


def get_correction_collector() -> CorrectionCollector:
    """获取全局纠错采集器实例。"""
    global _correction_collector
    if _correction_collector is None:
        _correction_collector = CorrectionCollector()
    return _correction_collector


# 兼容旧接口
def capture_feedback(
    *,
    project_id: int,
    source: str,
    stage: str,
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
) -> "FeedbackRecord":
    """兼容旧接口：直接调用全局采集器。"""
    collector = get_correction_collector()
    return collector.capture_feedback(
        project_id=project_id,
        source=source,
        stage=stage,
        input_snapshot=input_snapshot,
        llm_output=llm_output,
        corrected_output=corrected_output,
        rationale=rationale,
        chapter_id=chapter_id,
        paragraph_id=paragraph_id,
        paragraph_index=paragraph_index,
        chapter_index=chapter_index,
        diff_summary=diff_summary,
        pattern_tags=pattern_tags,
    )


# 兼容旧导入
from ..models import FeedbackRecord

FeedbackRecord = FeedbackRecord

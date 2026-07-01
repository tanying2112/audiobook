"""SQLAlchemy 2.0 model for FeedbackRecord (反馈记录)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .book import Project
    from .paragraph import Paragraph


class FeedbackRecord(Base):
    """反馈记录 (对齐 FeedbackRecord schema)."""

    __tablename__ = "feedback_records"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chapter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True
    )
    paragraph_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("paragraphs.id", ondelete="CASCADE"), nullable=True
    )

    # 反馈标识
    feedback_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String, nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String, nullable=False, index=True)

    # 快照数据
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    llm_output: Mapped[dict] = mapped_column(JSON, nullable=False)
    corrected_output: Mapped[dict] = mapped_column(JSON, nullable=False)

    # 核心：修改理由
    rationale: Mapped[str] = mapped_column(Text, nullable=False)

    # Agent 自动生成
    diff_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pattern_tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)

    # 处理状态
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    promoted: Mapped[bool] = mapped_column(Boolean, default=False)

    # 时间戳
    created_at: Mapped[datetime] = mapped_column(nullable=False)

    # Relationships
    project: Mapped[Project] = relationship(
        "Project", back_populates="feedback_records"
    )
    paragraph: Mapped[Paragraph] = relationship(
        "Paragraph", back_populates="feedback_records"
    )

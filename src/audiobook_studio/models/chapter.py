"""SQLAlchemy 2.0 model for Chapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..orm_base import Base

if TYPE_CHECKING:
    from .audio_segment import AudioSegment
    from .book import Project
    from .paragraph import Paragraph


class Chapter(Base):
    """章节元数据 + 处理状态."""

    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)

    index: Mapped[int] = mapped_column(nullable=False, index=True)
    title: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    raw_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extracted_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    analyzed_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    annotated_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    edited_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    # Segmentation results (P0-3)
    segment_data: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    segment_strategy: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    segment_stats: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    segment_status: Mapped[str] = mapped_column(String, default="pending")

    # 处理状态
    status: Mapped[str] = mapped_column(String, default="pending")
    extract_status: Mapped[str] = mapped_column(String, default="pending")
    segment_status: Mapped[str] = mapped_column(String, default="pending")
    analyze_status: Mapped[str] = mapped_column(String, default="pending")
    annotate_status: Mapped[str] = mapped_column(String, default="pending")
    edit_status: Mapped[str] = mapped_column(String, default="pending")
    route_status: Mapped[str] = mapped_column(String, default="pending")
    synthesize_status: Mapped[str] = mapped_column(String, default="pending")
    quality_status: Mapped[str] = mapped_column(String, default="pending")

    # 成本追踪
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    token_count: Mapped[int] = mapped_column(nullable=False, default=0)
    tts_chars: Mapped[int] = mapped_column(nullable=False, default=0)

    # 时间戳
    started_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="chapters", lazy="selectin")
    paragraphs: Mapped[List[Paragraph]] = relationship(
        "Paragraph", back_populates="chapter", cascade="all, delete-orphan", lazy="selectin"
    )
    audio_segments: Mapped[List[AudioSegment]] = relationship(
        "AudioSegment", back_populates="chapter", cascade="all, delete-orphan", lazy="selectin"
    )

    # Composite indexes for query optimization (P2-5)
    __table_args__ = (
        # Common query: SELECT * FROM chapters WHERE project_id=? AND status=? ORDER BY index
        Index("ix_chapters_project_id_status_index", "project_id", "status", "index"),
        # Common query: SELECT * FROM chapters WHERE project_id=? AND index=?
        Index("ix_chapters_project_id_index", "project_id", "index"),
    )

    # Forbid lazy loading on detail endpoints that should use selectinload explicitly
    from sqlalchemy.orm import raiseload
    __raised_load_attrs__ = (raiseload("*"),)

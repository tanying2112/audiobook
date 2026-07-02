"""SQLAlchemy 2.0 model for Chapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

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
    analyzed_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    annotated_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    edited_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 处理状态
    status: Mapped[str] = mapped_column(String, default="pending")
    extract_status: Mapped[str] = mapped_column(String, default="pending")
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
    project: Mapped[Project] = relationship("Project", back_populates="chapters")
    paragraphs: Mapped[List[Paragraph]] = relationship(
        "Paragraph", back_populates="chapter", cascade="all, delete-orphan"
    )
    audio_segments: Mapped[List[AudioSegment]] = relationship(
        "AudioSegment", back_populates="chapter", cascade="all, delete-orphan"
    )

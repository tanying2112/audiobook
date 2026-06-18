"""SQLAlchemy 2.0 model for AudioSegment (音频片段)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .book import Project
    from .chapter import Chapter
    from .paragraph import Paragraph
    from .quality import Quality


class AudioSegment(Base):
    """音频片段 (对应每个段落的合成音频，支持增量合成)."""

    __tablename__ = "audio_segments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False
    )
    paragraph_id: Mapped[int] = mapped_column(
        ForeignKey("paragraphs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # 文件信息
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    format: Mapped[str] = mapped_column(String, default="mp3")
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sample_rate: Mapped[int] = mapped_column(Integer, default=24000)
    channels: Mapped[int] = mapped_column(Integer, default=1)

    # 合成信息
    engine: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    voice_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prosody_overrides: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    # 版本控制
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    parent_segment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("audio_segments.id"), nullable=True
    )

    # 质检关联
    quality_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("qualities.id", ondelete="SET NULL"), nullable=True
    )

    # 状态
    status: Mapped[str] = mapped_column(String, default="pending")

    # 时间戳
    created_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="audio_segments")
    chapter: Mapped[Chapter] = relationship("Chapter", back_populates="audio_segments")
    paragraph: Mapped[Paragraph] = relationship(
        "Paragraph",
        back_populates="audio_segment",
        uselist=False,
        foreign_keys="AudioSegment.paragraph_id",
    )
    quality: Mapped[Optional[Quality]] = relationship(
        "Quality", back_populates="audio_segment", uselist=False
    )

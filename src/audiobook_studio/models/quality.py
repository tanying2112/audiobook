"""SQLAlchemy 2.0 model for Quality (质检记录)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .audio_segment import AudioSegment
    from .paragraph import Paragraph
    from .tts_edit import TTSEdit


class Quality(Base):
    """质检记录 (对齐 QualityJudgment)."""

    __tablename__ = "qualities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    chapter_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    paragraph_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("paragraphs.id", ondelete="CASCADE"), nullable=True, index=True
    )
    tts_edit_id: Mapped[int] = mapped_column(ForeignKey("tts_edits.id", ondelete="CASCADE"), nullable=False)

    # 多维度评分 (0-1)
    speaker_clarity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    emotion_match: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    prosody_naturalness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    text_audio_alignment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    overall_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Simple CRUD API fields
    score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    comments: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # 问题列表
    issues: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    fix_suggestions: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    needs_regeneration: Mapped[bool] = mapped_column(Boolean, default=False)

    # Judge 信息
    judge_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    judge_prompt_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # 音频文件信息
    audio_file_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    audio_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # 时间戳
    created_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    paragraph: Mapped[Paragraph] = relationship("Paragraph", back_populates="quality_records")
    tts_edit: Mapped[TTSEdit] = relationship("TTSEdit", back_populates="quality_records")
    audio_segment: Mapped[Optional[AudioSegment]] = relationship(
        "AudioSegment", back_populates="quality", uselist=False
    )

    def to_schema(self):
        from ..schemas.quality import Quality as QualitySchema

        return QualitySchema(
            id=self.id,
            tts_edit_id=self.tts_edit_id,
            score=self.score or self.overall_score,
            comments=self.comments,
        )

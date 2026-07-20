"""SQLAlchemy 2.0 model for Paragraph (对齐 ParagraphAnnotation).

存储环节③输出的完整段落标注参数，支持增量合成。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .audio_segment import AudioSegment
    from .book import Project
    from .chapter import Chapter
    from .feedback_record import FeedbackRecord
    from .quality import Quality
    from .routing import Routing
    from .tts_edit import TTSEdit


class Paragraph(Base):
    """段落模型 (对齐 ParagraphAnnotation 字段)."""

    __tablename__ = "paragraphs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    chapter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Simple CRUD API backwards compat
    book_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    speaker: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # 基础字段
    index: Mapped[int] = mapped_column(nullable=False, index=True)
    chapter_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # 环节③标注字段
    speaker_canonical_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_dialogue: Mapped[bool] = mapped_column(Boolean, default=False)
    emotion: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    emotion_intensity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    speech_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    pitch_shift_semitones: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    needs_sfx: Mapped[bool] = mapped_column(Boolean, default=False)
    sfx_tags: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    pause_before_ms: Mapped[int] = mapped_column(Integer, default=0)
    pause_after_ms: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 环节④编辑后文本
    edited_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edit_changes_made: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    edit_forbidden_removed: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    edit_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    edit_rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    edit_difficulty: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    edit_forbid_edit: Mapped[bool] = mapped_column(Boolean, default=False)

    # 环节⑤路由决策
    routing_engine: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    routing_voice_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    routing_prosody_overrides: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    routing_fallback: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    routing_reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    routing_estimated_cost: Mapped[float] = mapped_column(Float, default=0.0)
    routing_estimated_duration: Mapped[int] = mapped_column(Integer, default=0)

    # 环节⑥质检
    quality_speaker_clarity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_emotion_match: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_prosody_naturalness: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_text_audio_alignment: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_overall_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quality_issues: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    quality_fix_suggestions: Mapped[Optional[list]] = mapped_column(JSON, default=list)
    quality_needs_regeneration: Mapped[bool] = mapped_column(Boolean, default=False)

    # 音频片段关联
    audio_segment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("audio_segments.id", ondelete="SET NULL"), nullable=True
    )

    # 状态
    status: Mapped[str] = mapped_column(String, default="pending")
    content_rating: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="paragraphs")
    chapter: Mapped[Chapter] = relationship("Chapter", back_populates="paragraphs")
    audio_segment: Mapped[Optional[AudioSegment]] = relationship(
        "AudioSegment",
        back_populates="paragraph",
        uselist=False,
        foreign_keys="AudioSegment.paragraph_id",
    )
    tts_edits: Mapped[List[TTSEdit]] = relationship("TTSEdit", back_populates="paragraph", cascade="all, delete-orphan")
    routings: Mapped[List[Routing]] = relationship("Routing", back_populates="paragraph", cascade="all, delete-orphan")
    quality_records: Mapped[List[Quality]] = relationship(
        "Quality", back_populates="paragraph", cascade="all, delete-orphan"
    )
    feedback_records: Mapped[List[FeedbackRecord]] = relationship(
        "FeedbackRecord", back_populates="paragraph", cascade="all, delete-orphan"
    )

    def to_schema(self):
        from ..schemas.paragraph import Paragraph as ParagraphSchema

        return ParagraphSchema(
            id=self.id,
            book_id=self.book_id or self.project_id,
            index=self.index,
            text=self.text,
            speaker=self.speaker or self.speaker_canonical_name,
        )

    def to_annotation_dict(self) -> dict:
        """Return annotation fields as a dict (aligned with ParagraphAnnotation schema)."""
        return {
            "speaker_canonical_name": self.speaker_canonical_name,
            "is_dialogue": self.is_dialogue,
            "emotion": self.emotion,
            "emotion_intensity": self.emotion_intensity,
            "speech_rate": self.speech_rate,
            "pitch_shift_semitones": self.pitch_shift_semitones,
            "needs_sfx": self.needs_sfx,
            "sfx_tags": self.sfx_tags or [],
            "pause_before_ms": self.pause_before_ms,
            "pause_after_ms": self.pause_after_ms,
            "confidence": self.confidence,
            "notes": self.notes,
        }

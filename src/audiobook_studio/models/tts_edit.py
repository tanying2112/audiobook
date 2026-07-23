"""SQLAlchemy 2.0 model for TTSEdit (编辑历史版本记录)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .paragraph import Paragraph
    from .quality import Quality


class TTSEdit(Base):
    """TTS 编辑历史 (每次编辑生成新版本)."""

    __tablename__ = "tts_edits"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    chapter_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    paragraph_id: Mapped[int] = mapped_column(ForeignKey("paragraphs.id", ondelete="CASCADE"), nullable=False)

    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    edited_text: Mapped[str] = mapped_column(Text, nullable=False)
    changes_made: Mapped[Optional[list[str]]] = mapped_column(JSON, default=list)
    forbidden_content_removed: Mapped[Optional[list[str]]] = mapped_column(JSON, default=list)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    rationale: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    difficulty: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    forbid_edit: Mapped[bool] = mapped_column(Boolean, default=False)
    voice: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # 来源追踪
    source: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prompt_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # 时间戳
    created_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    paragraph: Mapped[Paragraph] = relationship("Paragraph", back_populates="tts_edits")
    quality_records: Mapped[List[Quality]] = relationship(
        "Quality", back_populates="tts_edit", cascade="all, delete-orphan"
    )

    def to_schema(self):
        from ..schemas.tts_edit import TTSEdit as TTSEditSchema

        return TTSEditSchema(
            id=self.id,
            paragraph_id=self.paragraph_id,
            edited_text=self.edited_text,
            voice=self.voice,
        )

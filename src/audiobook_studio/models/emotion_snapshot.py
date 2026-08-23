"""SQLAlchemy 2.0 model for EmotionSnapshot (章节情感快照)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..orm_base import Base

if TYPE_CHECKING:
    from .book import Project


class EmotionSnapshot(Base):
    """章节情感快照."""

    __tablename__ = "emotion_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    chapter: Mapped[int] = mapped_column(nullable=False)
    dominant_emotion: Mapped[str] = mapped_column(String, nullable=False)
    intensity: Mapped[float] = mapped_column(nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="emotion_snapshots")

"""SQLAlchemy 2.0 model for Character (角色声音绑定)."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .book import Project


class Character(Base):
    """角色声音绑定 (全本唯一 canonical_name)."""

    __tablename__ = "characters"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    canonical_name: Mapped[str] = mapped_column(String, nullable=False, index=True)
    aliases: Mapped[Optional[List[str]]] = mapped_column(JSON, default=list)
    gender: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    age_range: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    suggested_voice_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    sample_quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="characters")

"""SQLAlchemy 2.0 model for ProjectSegment.

Text segments extracted from source files during Stage 1 (Extract).
Used for OCR results and content rating classification.
"""

from __future__ import annotations

import enum
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .project import Project


class ContentRating(str, enum.Enum):
    """Content rating categories for text segments."""

    CHILDREN = "儿童"
    GENERAL = "大众"
    YOUNG_ADULT = "青少年"
    ADULT = "成人"


class ProjectSegment(Base):
    """Text segment extracted from source file with metadata.

    Represents a logical unit of text (page, chapter section, etc.)
    with OCR metadata and content classification.
    """

    __tablename__ = "project_segments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    # Optional: link to specific chapter if already analyzed
    chapter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chapters.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Segment identification
    segment_index: Mapped[int] = mapped_column(nullable=False, index=True)
    source_page: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source_format: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # pdf, epub, image, etc.

    # Content
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # OCR metadata
    is_ocr: Mapped[bool] = mapped_column(default=False, nullable=False)
    ocr_confidence: Mapped[Optional[float]] = mapped_column(nullable=True)
    ocr_languages: Mapped[Optional[list[str]]] = mapped_column(JSON, default=list)

    # Content rating
    content_rating: Mapped[str] = mapped_column(
        SQLEnum(
            *[e.value for e in ContentRating],
            name="content_rating_enum",
            create_constraint=True,
        ),
        default=ContentRating.GENERAL.value,
        nullable=False,
    )

    # Language detection
    detected_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="segments")

    def __repr__(self):
        return (
            f"<ProjectSegment(project_id={self.project_id}, index={self.segment_index}, rating={self.content_rating})>"
        )

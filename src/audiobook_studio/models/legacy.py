"""Legacy SQLAlchemy 2.0 models for backward compatibility with existing CRUD API.

These models match the original simple Book/Paragraph/TTSEdit/Routing/Quality schemas
used by the existing API tests. Class names are prefixed with "Legacy" to avoid conflicts.
"""

from __future__ import annotations

from typing import List, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base


class LegacyBook(Base):
    """Legacy Book model for CRUD API tests."""

    __tablename__ = "legacy_books"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str] = mapped_column(String(2), nullable=False)
    isbn: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    paragraphs: Mapped[List[LegacyParagraph]] = relationship(
        "LegacyParagraph", back_populates="book", cascade="delete, delete-orphan"
    )

    def to_schema(self):
        from ..schemas.legacy import Book as BookSchema

        return BookSchema(
            id=self.id,
            title=self.title,
            author=self.author,
            language=self.language,
            isbn=self.isbn,
        )


class LegacyParagraph(Base):
    """Legacy Paragraph model for CRUD API tests."""

    __tablename__ = "legacy_paragraphs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("legacy_books.id"), nullable=False)
    index: Mapped[int] = mapped_column(nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    book: Mapped[LegacyBook] = relationship("LegacyBook", back_populates="paragraphs")
    tts_edits: Mapped[List[LegacyTTSEdit]] = relationship(
        "LegacyTTSEdit", back_populates="paragraph", cascade="delete, delete-orphan"
    )
    routings: Mapped[List[LegacyRouting]] = relationship(
        "LegacyRouting", back_populates="paragraph", cascade="delete, delete-orphan"
    )

    def to_schema(self):
        from ..schemas.legacy import Paragraph as ParagraphSchema

        return ParagraphSchema(
            id=self.id,
            book_id=self.book_id,
            index=self.index,
            text=self.text,
            speaker=self.speaker,
        )


class LegacyTTSEdit(Base):
    """Legacy TTSEdit model for CRUD API tests."""

    __tablename__ = "legacy_tts_edits"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    paragraph_id: Mapped[int] = mapped_column(ForeignKey("legacy_paragraphs.id", ondelete="CASCADE"), nullable=False)
    edited_text: Mapped[str] = mapped_column(Text, nullable=False)
    voice: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    paragraph: Mapped[LegacyParagraph] = relationship("LegacyParagraph", back_populates="tts_edits")
    quality: Mapped[Optional[LegacyQuality]] = relationship("LegacyQuality", back_populates="tts_edit", uselist=False)

    def to_schema(self):
        from ..schemas.legacy import TTSEdit as TTSEditSchema

        return TTSEditSchema(
            id=self.id,
            paragraph_id=self.paragraph_id,
            edited_text=self.edited_text,
            voice=self.voice,
        )


class LegacyRouting(Base):
    """Legacy Routing model for CRUD API tests."""

    __tablename__ = "legacy_routings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    paragraph_id: Mapped[int] = mapped_column(ForeignKey("legacy_paragraphs.id", ondelete="CASCADE"), nullable=False)
    voice: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # Relationships
    paragraph: Mapped[LegacyParagraph] = relationship("LegacyParagraph", back_populates="routings")

    def to_schema(self):
        from ..schemas.legacy import Routing as RoutingSchema

        return RoutingSchema(
            id=self.id,
            paragraph_id=self.paragraph_id,
            voice=self.voice,
            confidence=self.confidence,
        )


class LegacyQuality(Base):
    """Legacy Quality model for CRUD API tests."""

    __tablename__ = "legacy_qualities"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    tts_edit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("legacy_tts_edits.id"), nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    comments: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Relationships
    tts_edit: Mapped[Optional[LegacyTTSEdit]] = relationship("LegacyTTSEdit", back_populates="quality")

    def to_schema(self):
        from ..schemas.legacy import Quality as QualitySchema

        return QualitySchema(
            id=self.id,
            tts_edit_id=self.tts_edit_id,
            score=self.score,
            comments=self.comments,
        )

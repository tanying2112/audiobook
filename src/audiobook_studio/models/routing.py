"""SQLAlchemy 2.0 model for Routing (TTS 路由决策历史)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from ..schemas.routing import Routing as RoutingSchema

if TYPE_CHECKING:
    from .paragraph import Paragraph


class Routing(Base):
    """TTS 路由决策历史."""

    __tablename__ = "routings"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[Optional[int]] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    chapter_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    paragraph_id: Mapped[int] = mapped_column(ForeignKey("paragraphs.id", ondelete="CASCADE"), nullable=False)

    # HARNESS fields
    engine_choice: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    voice_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prosody_overrides: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    fallback_engine: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_duration_ms: Mapped[int] = mapped_column(Integer, default=0)

    # 实际执行结果
    actual_engine: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    actual_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, default="pending")

    # Simple CRUD API fields
    voice: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # 时间戳
    created_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    paragraph: Mapped[Paragraph] = relationship("Paragraph", back_populates="routings")

    def to_schema(self):
        return RoutingSchema(
            id=self.id,
            paragraph_id=self.paragraph_id,
            voice=self.voice or self.voice_id,
            confidence=self.confidence,
        )

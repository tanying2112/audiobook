"""SQLAlchemy models for Publish jobs and history."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .book import Project
    from .user import User


class PublishJob(Base):
    """Publish job tracking model for async publish operations."""

    __tablename__ = "publish_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        SQLEnum("pending", "running", "completed", "failed", name="publish_job_status"),
        nullable=False,
        default="pending",
        index=True,
    )
    target: Mapped[str] = mapped_column(String(50), nullable=False)  # audiobookshelf, podcast, etc.
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    result_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(timezone.utc), onupdate=datetime.now(timezone.utc)
    )

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="publish_jobs")
    user: Mapped["User"] = relationship("User", back_populates="publish_jobs")


class PublishHistory(Base):
    """Publish history for audit trail."""

    __tablename__ = "publish_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("publish_jobs.id"), nullable=True, index=True)
    target: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now(timezone.utc))

    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="publish_history")
    user: Mapped["User"] = relationship("User", back_populates="publish_history")

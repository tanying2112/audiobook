"""
Publish job state machine (Sprint 3, S3-1).

This model is the canonical production record for an async publish job. It
tracks the lifecycle of a publish operation (audiobookshelf / podcast-rss)
through an explicit state machine and records retry history so the frontend
can poll progress without depending on Celery's internals or Redis.

The legacy ``models.publish.PublishJob`` (table ``publish_jobs``) is kept for
backward compatibility; the two never collide (different table, different
status vocabulary).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..orm_base import Base


class PublishJobStatus(str, Enum):
    """Explicit publish job lifecycle states."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"

    @classmethod
    def is_terminal(cls, value: str) -> bool:
        return value in (cls.SUCCESS.value, cls.FAILED.value)

    @classmethod
    def is_active(cls, value: str) -> bool:
        return value in (cls.PENDING.value, cls.PROCESSING.value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _max_retries() -> int:
    # Kept as a function so tests / config can override the policy in one place.
    return 3


class PublishJobState(Base):
    """State-machine record for a single publish operation."""

    __tablename__ = "publish_job"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_publish_job_job_id"),
        UniqueConstraint("idempotency_key", name="uq_publish_job_idempotency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Public business key returned to the client for polling.
    job_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    # Comma-separated list of targets: audiobookshelf,podcast_rss
    target: Mapped[str] = mapped_column(String(128), nullable=False, default="audiobookshelf")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=PublishJobStatus.PENDING.value, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Whether the last attempt (or all) triggered an automatic retry.
    error_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    config_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    result_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    def __init__(self, **kwargs: Any) -> None:
        # Column ``default=`` only applies at INSERT (flush); set in-memory
        # defaults here so freshly constructed objects already carry the
        # correct state-machine starting point.
        status = kwargs.pop("status", None)
        retry_count = kwargs.pop("retry_count", None)
        progress = kwargs.pop("progress", None)
        super().__init__(**kwargs)
        if status is None:
            self.status = PublishJobStatus.PENDING.value
        if retry_count is None:
            self.retry_count = 0
        if progress is None:
            self.progress = 0.0

    # ------------------------------------------------------------------ #
    # Transition helpers (operate on the in-memory object; the repository
    # layer is responsible for committing).
    # ------------------------------------------------------------------ #
    def _append_error(self, error: Optional[str]) -> None:
        if not error:
            return
        ts = _now().isoformat()
        line = f"[{ts}] {error}"
        if self.error_log:
            # Keep the log bounded to avoid unbounded growth.
            lines = self.error_log.splitlines()
            self.error_log = "\n".join((lines + [line])[-20:])
        else:
            self.error_log = line

    def mark_processing(self) -> None:
        self.status = PublishJobStatus.PROCESSING.value
        if self.started_at is None:
            self.started_at = _now()
        self.updated_at = _now()

    def register_retry(self, error: Optional[str] = None) -> None:
        """Record an automatic retry: bump counter, stay active."""
        self.retry_count = (self.retry_count or 0) + 1
        self._append_error(error)
        self.status = PublishJobStatus.PROCESSING.value
        self.updated_at = _now()

    def mark_success(self, result: Any = None) -> None:
        self.status = PublishJobStatus.SUCCESS.value
        self.progress = 1.0
        if result is not None:
            try:
                self.result_json = json.dumps(result, default=str)
            except (TypeError, ValueError):
                self.result_json = str(result)
        if self.finished_at is None:
            self.finished_at = _now()
        self.updated_at = _now()

    def mark_failure(self, error: Optional[str] = None, result: Any = None) -> None:
        self.status = PublishJobStatus.FAILED.value
        self._append_error(error)
        if result is not None:
            try:
                self.result_json = json.dumps(result, default=str)
            except (TypeError, ValueError):
                self.result_json = str(result)
        if self.finished_at is None:
            self.finished_at = _now()
        self.updated_at = _now()

    # ------------------------------------------------------------------ #
    # Serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict:
        result = None
        if self.result_json:
            try:
                result = json.loads(self.result_json)
            except (TypeError, ValueError):
                result = self.result_json
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "user_id": self.user_id,
            "target": self.target,
            "status": self.status,
            "retry_count": self.retry_count,
            "progress": self.progress,
            "error_log": self.error_log,
            "result": result,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

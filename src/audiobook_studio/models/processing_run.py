"""SQLAlchemy 2.0 model for ProcessingRun (管线运行记录 + 版本追踪)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.dialects.sqlite import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .book import Project


class ProcessingRun(Base):
    """管线运行记录 (每次 pipeline run 的快照，支持版本追溯与回滚).

    对应 B7: 每次成功 pipeline run 保存 ProcessingConfig + prompt_template + golden_score
    作为 JSONL 行，支持 ``parent_run_id`` 实现版本追溯。
    """

    __tablename__ = "processing_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    parent_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("processing_runs.id"), nullable=True)

    # 运行快照
    config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # ProcessingConfig as JSON
    prompt_versions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # {stage: version} mapping
    stages_completed: Mapped[List[str]] = mapped_column(JSON, nullable=False, default=list)

    # 运行结果
    golden_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 版本标签 (用于 rollback CLI 识别)
    version_tag: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    commit_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 时间戳
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    completed_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)

    # Relationships
    project: Mapped[Project] = relationship("Project", back_populates="processing_runs")
    parent_run: Mapped[Optional[ProcessingRun]] = relationship(
        "ProcessingRun", remote_side="ProcessingRun.id", uselist=False
    )

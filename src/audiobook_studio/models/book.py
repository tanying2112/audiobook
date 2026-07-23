"""SQLAlchemy models for Book/Project and related entities.

对齐 HARNESS 规范的数据持久化模型:
- Book: 简单的书籍模型 (用于 CRUD API)
- Project: 书籍项目 (对应 BookAnalysisOutput)
- Character: 角色声音绑定 (CharacterVoiceBinding)
- EmotionSnapshot: 章节情感快照
- Chapter: 章节元数据
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .audio_segment import AudioSegment
    from .chapter import Chapter
    from .character import Character
    from .emotion_snapshot import EmotionSnapshot
    from .feedback_record import FeedbackRecord
    from .paragraph import Paragraph
    from .processing_run import ProcessingRun
    from .project_segment import ProjectSegment
    from .publish import PublishHistory, PublishJob
    from .user import ProjectPermission, User


class Book(Base):
    """简单的书籍模型 (用于 CRUD API 向后兼容)."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="en")
    isbn: Mapped[Optional[str]] = mapped_column(String, nullable=True, unique=True)

    def to_schema(self):
        from ..schemas.book import Book as BookSchema

        return BookSchema(
            id=self.id,
            title=self.title,
            author=self.author or "",
            language=self.language,
            isbn=self.isbn,
        )


class Project(Base):
    """书籍项目 (对应 BookAnalysisOutput - 上帝视角完整档案)."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)

    # BookMeta 字段
    title: Mapped[str] = mapped_column(String, nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    difficulty: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    language: Mapped[str] = mapped_column(String(2), nullable=False, default="zh")
    era: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    total_chapters_estimated: Mapped[Optional[int]] = mapped_column(nullable=True)

    # 全局文风备注
    global_style_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    story_line_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # 状态追踪
    status: Mapped[str] = mapped_column(String, default="draft")
    current_stage: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    # 成本追踪
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    cost_limit_per_book: Mapped[float] = mapped_column(Float, default=20.0)
    cost_limit_per_chapter: Mapped[float] = mapped_column(Float, default=5.0)

    # 时间戳
    created_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    updated_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    completed_at: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # ── Relationships ──
    characters: Mapped[List[Character]] = relationship(
        "Character", back_populates="project", cascade="all, delete-orphan"
    )
    emotion_snapshots: Mapped[List[EmotionSnapshot]] = relationship(
        "EmotionSnapshot", back_populates="project", cascade="all, delete-orphan"
    )
    chapters: Mapped[List[Chapter]] = relationship("Chapter", back_populates="project", cascade="all, delete-orphan")
    feedback_records: Mapped[List[FeedbackRecord]] = relationship(
        "FeedbackRecord", back_populates="project", cascade="all, delete-orphan"
    )
    paragraphs: Mapped[List[Paragraph]] = relationship(
        "Paragraph", back_populates="project", cascade="all, delete-orphan"
    )
    audio_segments: Mapped[List[AudioSegment]] = relationship(
        "AudioSegment", back_populates="project", cascade="all, delete-orphan"
    )
    processing_runs: Mapped[List[ProcessingRun]] = relationship(
        "ProcessingRun", back_populates="project", cascade="all, delete-orphan"
    )
    permissions: Mapped[List[ProjectPermission]] = relationship("ProjectPermission", back_populates="project")
    segments: Mapped[List["ProjectSegment"]] = relationship(
        "ProjectSegment", back_populates="project", cascade="all, delete-orphan"
    )
    publish_jobs: Mapped[List["PublishJob"]] = relationship(
        "PublishJob", back_populates="project", cascade="all, delete-orphan"
    )
    publish_history: Mapped[List["PublishHistory"]] = relationship(
        "PublishHistory", back_populates="project", cascade="all, delete-orphan"
    )

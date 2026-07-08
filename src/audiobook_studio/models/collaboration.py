"""Collaboration models for Audiobook Studio.

SQLAlchemy 2.0 ORM models for team collaboration features:
- TeamMember: Team member profiles
- Comment: Comments/suggestions/questions on tasks/files
- Task: Task management with status, assignee, dependencies
- ApprovalRequest: Approval workflows for artifacts
- ApprovalResponse: Individual approver responses
- ChangeRecord: Audit trail of all changes
"""

import enum
from datetime import datetime, timezone
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Table, Text
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base

if TYPE_CHECKING:
    from .user import User


# Association table for task dependencies (many-to-many)
task_dependencies = Table(
    "task_dependencies",
    Base.metadata,
    Column("task_id", Integer, ForeignKey("tasks.id"), primary_key=True),
    Column("depends_on_task_id", Integer, ForeignKey("tasks.id"), primary_key=True),
)

# Association table for approval request approvers (many-to-many)
approval_approvers = Table(
    "approval_approvers",
    Base.metadata,
    Column("approval_request_id", Integer, ForeignKey("approval_requests.id"), primary_key=True),
    Column("approver_id", Integer, ForeignKey("team_members.id"), primary_key=True),
)


class CommentType(str, enum.Enum):
    """Comment type enumeration."""

    COMMENT = "comment"
    SUGGESTION = "suggestion"
    QUESTION = "question"
    ISSUE = "issue"


class TaskStatus(str, enum.Enum):
    """Task status enumeration."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    DONE = "done"
    ARCHIVED = "archived"


class ApprovalStatus(str, enum.Enum):
    """Approval status enumeration."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    NEEDS_CHANGES = "needs_changes"


class ChangeType(str, enum.Enum):
    """Change type enumeration."""

    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    MOVE = "move"


class TeamMember(Base):
    """Team member profile model."""

    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # translator, editor, narrator, proofreader, manager
    is_active: Mapped[bool] = mapped_column(default=True)
    # Optional link to auth User (nullable: a team member may not have a login account)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, unique=True, index=True
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    skills: Mapped[List[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default="[]"
    )  # JSON array
    languages: Mapped[List[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default="[]"
    )  # JSON array
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    comments: Mapped[List["Comment"]] = relationship(
        "Comment", foreign_keys="Comment.author_id", back_populates="author"
    )
    assigned_tasks: Mapped[List["Task"]] = relationship(
        "Task", foreign_keys="Task.assignee_id", back_populates="assignee"
    )
    reported_tasks: Mapped[List["Task"]] = relationship(
        "Task", foreign_keys="Task.reporter_id", back_populates="reporter"
    )
    approval_requests: Mapped[List["ApprovalRequest"]] = relationship("ApprovalRequest", back_populates="requester")
    approval_responses: Mapped[List["ApprovalResponse"]] = relationship("ApprovalResponse", back_populates="approver")
    change_records: Mapped[List["ChangeRecord"]] = relationship("ChangeRecord", back_populates="changed_by_member")


class Comment(Base):
    """Comment model for collaboration."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    comment_type: Mapped[CommentType] = mapped_column(SQLEnum(CommentType), nullable=False, index=True)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("team_members.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    # Optional associations
    task_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    line_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Reply relationship
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("comments.id"), nullable=True, index=True)
    # Resolution
    resolved: Mapped[bool] = mapped_column(default=False)
    resolved_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("team_members.id"), nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    author: Mapped["TeamMember"] = relationship("TeamMember", foreign_keys=[author_id], back_populates="comments")
    resolved_by_member: Mapped[Optional["TeamMember"]] = relationship("TeamMember", foreign_keys=[resolved_by])
    task: Mapped[Optional["Task"]] = relationship("Task", back_populates="comments")
    parent: Mapped[Optional["Comment"]] = relationship("Comment", remote_side=[id], backref="replies")


class Task(Base):
    """Task model for collaboration."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[TaskStatus] = mapped_column(SQLEnum(TaskStatus), default=TaskStatus.TODO, nullable=False, index=True)
    assignee_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("team_members.id"), nullable=True, index=True
    )
    reporter_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("team_members.id"), nullable=True, index=True
    )
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    tags: Mapped[List[str]] = mapped_column(
        MutableList.as_mutable(JSON), default=list, server_default="[]"
    )  # JSON array
    priority: Mapped[int] = mapped_column(default=1)  # 1-5, 5 highest
    estimated_hours: Mapped[Optional[float]] = mapped_column(nullable=True)
    actual_hours: Mapped[Optional[float]] = mapped_column(nullable=True)
    project_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("projects.id"), nullable=True, index=True)
    parent_task_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    assignee: Mapped[Optional["TeamMember"]] = relationship(
        "TeamMember", foreign_keys=[assignee_id], back_populates="assigned_tasks"
    )
    reporter: Mapped[Optional["TeamMember"]] = relationship(
        "TeamMember", foreign_keys=[reporter_id], back_populates="reported_tasks"
    )
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="task")
    subtasks: Mapped[List["Task"]] = relationship(
        "Task", back_populates="parent_task", foreign_keys="[Task.parent_task_id]"
    )
    parent_task: Mapped[Optional["Task"]] = relationship(
        "Task", back_populates="subtasks", remote_side=[id], foreign_keys="[Task.parent_task_id]"
    )
    depends_on: Mapped[List["Task"]] = relationship(
        "Task",
        secondary=task_dependencies,
        primaryjoin=id == task_dependencies.c.task_id,
        secondaryjoin=id == task_dependencies.c.depends_on_task_id,
        backref="dependents",
    )
    approval_requests: Mapped[List["ApprovalRequest"]] = relationship("ApprovalRequest", back_populates="task")


class ApprovalRequest(Base):
    """Approval request model for collaboration workflows."""

    __tablename__ = "approval_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    requester_id: Mapped[int] = mapped_column(Integer, ForeignKey("team_members.id"), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        SQLEnum(ApprovalStatus), default=ApprovalStatus.PENDING, nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
    # Optional associations
    task_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    artifact_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Approval requirements
    required_approvals: Mapped[int] = mapped_column(default=1)
    auto_approve_if_unstoppable: Mapped[bool] = mapped_column(default=False)

    # Relationships
    requester: Mapped["TeamMember"] = relationship("TeamMember", back_populates="approval_requests")
    task: Mapped[Optional["Task"]] = relationship("Task", back_populates="approval_requests")
    approvers: Mapped[List["TeamMember"]] = relationship(
        "TeamMember",
        secondary=approval_approvers,
        backref="approval_requests_to_approve",
    )
    responses: Mapped[List["ApprovalResponse"]] = relationship(
        "ApprovalResponse", back_populates="approval_request", cascade="all, delete-orphan"
    )


class ApprovalResponse(Base):
    """Approval response model for individual approver responses."""

    __tablename__ = "approval_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    approval_request_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("approval_requests.id"), nullable=False, index=True
    )
    approver_id: Mapped[int] = mapped_column(Integer, ForeignKey("team_members.id"), nullable=False, index=True)
    status: Mapped[ApprovalStatus] = mapped_column(SQLEnum(ApprovalStatus), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    commented_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    approval_request: Mapped["ApprovalRequest"] = relationship("ApprovalRequest", back_populates="responses")
    approver: Mapped["TeamMember"] = relationship("TeamMember", back_populates="approval_responses")


class ChangeRecord(Base):
    """Change record model for audit trail."""

    __tablename__ = "change_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    change_type: Mapped[ChangeType] = mapped_column(SQLEnum(ChangeType), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # task, comment, approval_request, etc.
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    changed_by: Mapped[int] = mapped_column(Integer, ForeignKey("team_members.id"), nullable=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    old_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    new_state: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    related_change_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("change_records.id"), nullable=True)

    # Relationships
    changed_by_member: Mapped["TeamMember"] = relationship("TeamMember", back_populates="change_records")
    related_change: Mapped[Optional["ChangeRecord"]] = relationship(
        "ChangeRecord", remote_side=[id], backref="followup_changes"
    )

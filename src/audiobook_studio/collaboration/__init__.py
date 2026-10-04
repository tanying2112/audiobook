# Audiobook Studio - Collaboration Module
"""Team collaboration features: comments, tasks, approvals, change history."""

from .team_collaboration import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ChangeRecord,
    ChangeType,
    CollaborationManager,
    Comment,
    CommentType,
    Task,
    TaskStatus,
    TeamMember,
)

__all__ = [
    "CollaborationManager",
    "TeamMember",
    "Comment",
    "CommentType",
    "Task",
    "TaskStatus",
    "ApprovalRequest",
    "ApprovalResponse",
    "ApprovalStatus",
    "ChangeRecord",
    "ChangeType",
]

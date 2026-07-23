"""Tests for team_collaboration module."""

import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project path for imports


def test_collaboration_imports():
    """Test that team_collaboration module can be imported."""
    from src.audiobook_studio.collaboration.team_collaboration import (
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

    assert CommentType is not None
    assert TaskStatus is not None
    assert ApprovalStatus is not None
    assert ChangeType is not None
    assert TeamMember is not None
    assert Comment is not None
    assert Task is not None
    assert ApprovalRequest is not None
    assert ApprovalResponse is not None
    assert ChangeRecord is not None
    assert CollaborationManager is not None


class TestEnums:
    """Tests for enumeration types."""

    def test_comment_type_values(self):
        """Test CommentType enum values."""
        from src.audiobook_studio.collaboration.team_collaboration import CommentType

        assert CommentType.COMMENT.value == "comment"
        assert CommentType.SUGGESTION.value == "suggestion"
        assert CommentType.QUESTION.value == "question"
        assert CommentType.ISSUE.value == "issue"

    def test_task_status_values(self):
        """Test TaskStatus enum values."""
        from src.audiobook_studio.collaboration.team_collaboration import TaskStatus

        assert TaskStatus.TODO.value == "todo"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.REVIEW.value == "review"
        assert TaskStatus.DONE.value == "done"
        assert TaskStatus.ARCHIVED.value == "archived"

    def test_approval_status_values(self):
        """Test ApprovalStatus enum values."""
        from src.audiobook_studio.collaboration.team_collaboration import ApprovalStatus

        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.NEEDS_CHANGES.value == "needs_changes"

    def test_change_type_values(self):
        """Test ChangeType enum values."""
        from src.audiobook_studio.collaboration.team_collaboration import ChangeType

        assert ChangeType.CREATE.value == "create"
        assert ChangeType.UPDATE.value == "update"
        assert ChangeType.DELETE.value == "delete"
        assert ChangeType.MOVE.value == "move"


class TestDataclasses:
    """Tests for dataclass types."""

    def test_team_member_creation(self):
        """Test creating a TeamMember."""
        from src.audiobook_studio.collaboration.team_collaboration import TeamMember

        member = TeamMember(
            id="user-1",
            name="Test User",
            email="test@example.com",
            role="translator",
        )
        assert member.id == "user-1"
        assert member.name == "Test User"
        assert member.is_active is True
        assert member.skills == []
        assert member.languages == []

    def test_comment_creation(self):
        """Test creating a Comment."""
        from src.audiobook_studio.collaboration.team_collaboration import Comment, CommentType

        comment = Comment(
            id="comment-1",
            content="This needs review",
            author_id="user-1",
            comment_type=CommentType.SUGGESTION,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert comment.id == "comment-1"
        assert comment.content == "This needs review"
        assert comment.comment_type == CommentType.SUGGESTION
        assert comment.resolved is False

    def test_task_creation(self):
        """Test creating a Task."""
        from src.audiobook_studio.collaboration.team_collaboration import Task, TaskStatus

        task = Task(
            id="task-1",
            title="Translate chapter 1",
            description="Translate the first chapter",
            status=TaskStatus.TODO,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert task.id == "task-1"
        assert task.status == TaskStatus.TODO
        assert task.priority == 1
        assert task.tags == []

    def test_approval_request_creation(self):
        """Test creating an ApprovalRequest."""
        from src.audiobook_studio.collaboration.team_collaboration import ApprovalRequest, ApprovalStatus

        request = ApprovalRequest(
            id="approval-1",
            title="Review translation",
            description="Please review the translation",
            requester_id="user-1",
            approver_ids=["user-2", "user-3"],
            status=ApprovalStatus.PENDING,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert request.id == "approval-1"
        assert request.required_approvals == 1
        assert len(request.approver_ids) == 2

    def test_change_record_creation(self):
        """Test creating a ChangeRecord."""
        from src.audiobook_studio.collaboration.team_collaboration import ChangeRecord, ChangeType

        record = ChangeRecord(
            id="change-1",
            change_type=ChangeType.UPDATE,
            entity_type="task",
            entity_id="task-1",
            changed_by="user-1",
            changed_at=datetime.now(),
            description="Updated task status",
        )
        assert record.id == "change-1"
        assert record.change_type == ChangeType.UPDATE
        assert record.description == "Updated task status"


class TestCollaborationManager:
    """Tests for CollaborationManager."""

    def test_manager_creation(self, tmp_path):
        """Test creating a CollaborationManager."""
        from src.audiobook_studio.collaboration.team_collaboration import CollaborationManager

        manager = CollaborationManager(storage_path=tmp_path)
        assert manager.team_members == {}
        assert manager.comments == {}
        assert manager.tasks == {}
        assert manager.approval_requests == {}
        assert manager.change_history == []

    def test_add_team_member(self, tmp_path):
        """Test adding a team member."""
        from src.audiobook_studio.collaboration.team_collaboration import CollaborationManager, TeamMember

        manager = CollaborationManager(storage_path=tmp_path)
        member = TeamMember(
            id="user-1",
            name="Test User",
            email="test@example.com",
            role="translator",
        )

        member_id = manager.add_team_member(member)
        assert member_id == "user-1"
        assert "user-1" in manager.team_members
        assert len(manager.change_history) == 1

    def test_add_comment(self, tmp_path):
        """Test adding a comment."""
        from src.audiobook_studio.collaboration.team_collaboration import CollaborationManager, Comment, CommentType

        manager = CollaborationManager(storage_path=tmp_path)
        comment = Comment(
            id="comment-1",
            content="Test comment",
            author_id="user-1",
            comment_type=CommentType.COMMENT,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        comment_id = manager.add_comment(comment)
        assert comment_id == "comment-1"
        assert "comment-1" in manager.comments

    def test_add_task(self, tmp_path):
        """Test adding a task."""
        from src.audiobook_studio.collaboration.team_collaboration import CollaborationManager, Task, TaskStatus

        manager = CollaborationManager(storage_path=tmp_path)
        task = Task(
            id="task-1",
            title="Test task",
            description="Test description",
            status=TaskStatus.TODO,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        task_id = manager.add_task(task)
        assert task_id == "task-1"
        assert "task-1" in manager.tasks
        assert len(manager.change_history) == 1

    def test_update_task_status(self, tmp_path):
        """Test updating task status."""
        from src.audiobook_studio.collaboration.team_collaboration import CollaborationManager, Task, TaskStatus

        manager = CollaborationManager(storage_path=tmp_path)
        task = Task(
            id="task-1",
            title="Test task",
            description="Test description",
            status=TaskStatus.TODO,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        manager.add_task(task)

        result = manager.update_task_status("task-1", TaskStatus.IN_PROGRESS, "user-1")
        assert result is True
        assert manager.tasks["task-1"].status == TaskStatus.IN_PROGRESS

    def test_update_task_status_not_found(self, tmp_path):
        """Test updating non-existent task."""
        from src.audiobook_studio.collaboration.team_collaboration import CollaborationManager, TaskStatus

        manager = CollaborationManager(storage_path=tmp_path)
        result = manager.update_task_status("nonexistent", TaskStatus.DONE, "user-1")
        assert result is False

"""Tests for collaboration API models."""

import pytest
from datetime import datetime


class TestCollabModels:
    """Tests for collaboration Pydantic models."""

    def test_comment_base(self):
        from src.audiobook_studio.api.collab import CommentBase

        comment = CommentBase(
            content="Test comment",
            comment_type="comment",
            task_id=1,
            file_path="test.py",
            line_number=10,
            parent_id=None
        )
        assert comment.content == "Test comment"
        assert comment.comment_type == "comment"
        assert comment.task_id == 1
        assert comment.file_path == "test.py"
        assert comment.line_number == 10

    def test_comment_create(self):
        from src.audiobook_studio.api.collab import CommentCreate

        comment = CommentCreate(
            content="New comment",
            comment_type="suggestion"
        )
        assert comment.content == "New comment"
        assert comment.comment_type == "suggestion"

    def test_comment_response(self):
        from src.audiobook_studio.api.collab import CommentResponse

        comment = CommentResponse(
            id=1,
            author_id="user1",
            content="Response",
            comment_type="comment",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        assert comment.id == 1
        assert comment.author_id == "user1"
        assert comment.resolved is False

    def test_task_base(self):
        from src.audiobook_studio.api.collab import TaskBase

        task = TaskBase(
            title="Test Task",
            description="Task description",
            status="todo",
            assignee_id="user1",
            reporter_id="user2",
            tags=["tag1"],
            priority=3,
            project_id="proj1"
        )
        assert task.title == "Test Task"
        assert task.status == "todo"
        assert task.priority == 3
        assert task.tags == ["tag1"]

    def test_task_create(self):
        from src.audiobook_studio.api.collab import TaskCreate

        task = TaskCreate(
            title="New Task",
            description="Description",
            status="in_progress"
        )
        assert task.title == "New Task"
        assert task.status == "in_progress"

    def test_task_response(self):
        from src.audiobook_studio.api.collab import TaskResponse

        task = TaskResponse(
            id=1,
            title="Task",
            description="Desc",
            status="done",
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        assert task.id == 1
        assert task.status == "done"

    def test_approval_request_base(self):
        from src.audiobook_studio.api.collab import ApprovalRequestBase

        approval = ApprovalRequestBase(
            title="Approval",
            description="Need approval",
            approver_ids=["user1", "user2"],
            task_id=1,
            artifact_path="/path/to/artifact",
            required_approvals=2
        )
        assert approval.title == "Approval"
        assert approval.approver_ids == ["user1", "user2"]
        assert approval.required_approvals == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
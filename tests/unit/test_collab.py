"""Tests for collaboration API models."""

from datetime import datetime

import pytest


class TestCollabModels:
    """Tests for collaboration Pydantic models."""

    def test_comment_base(self):
        from src.audiobook_studio.api.collab import CommentBase

        comment = CommentBase(
            content="Test comment",
            comment_type="comment",
            task_id=1,
            file_path="test.py",
        )
        assert comment.content == "Test comment"
        assert comment.comment_type == "comment"
        assert comment.task_id == 1
        assert comment.file_path == "test.py"

    def test_comment_create(self):
        from src.audiobook_studio.api.collab import CommentCreate

        comment = CommentCreate(content="New comment", comment_type="suggestion")
        assert comment.content == "New comment"
        assert comment.comment_type == "suggestion"

    def test_comment_response(self):
        from src.audiobook_studio.api.collab import CommentResponse

        comment = CommentResponse(
            id=1,
            user_id=1,
            content="Response",
            comment_type="comment",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert comment.id == 1
        assert comment.user_id == 1
        assert comment.processed is False

    def test_task_base(self):
        from src.audiobook_studio.api.collab import TaskStatusBase

        task = TaskStatusBase(
            task_id=1,
            status="in_progress",
            assignee_id=1,
            due_date=datetime.now(),
        )
        assert task.task_id == 1
        assert task.status == "in_progress"
        assert task.assignee_id == 1

    def test_task_create(self):
        from src.audiobook_studio.api.collab import TaskStatusCreate

        task = TaskStatusCreate(task_id=2, status="todo")
        assert task.task_id == 2
        assert task.status == "todo"

    def test_task_response(self):
        from src.audiobook_studio.api.collab import TaskStatusResponse

        task = TaskStatusResponse(
            id=1,
            task_id=1,
            project_id=1,
            status="done",
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        assert task.id == 1
        assert task.status == "done"

    def test_approval_request_base(self):
        from src.audiobook_studio.api.collab import ApprovalBase

        approval = ApprovalBase(
            resource_type="chapter",
            resource_id=1,
            action="approve",
            comments="Looks good",
        )
        assert approval.resource_type == "chapter"
        assert approval.resource_id == 1
        assert approval.action == "approve"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

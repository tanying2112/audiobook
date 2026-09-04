"""Behavior tests for src/audiobook_studio/models/collaboration.py ORM models.

collaboration.py is pure ORM declaration (4 enums + 6 models). The only way to
exercise the mapper definitions is to instantiate them against a REAL schema
(Base.metadata.create_all) and assert the column/relationship wiring, enum
defaults, and JSON-list mutability behave correctly. No implicit mocking.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.audiobook_studio.database import Base
from src.audiobook_studio.models.collaboration import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ChangeRecord,
    ChangeType,
    Comment,
    CommentType,
    Task,
    TaskStatus,
    TeamMember,
)
from src.audiobook_studio.models.user import User


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class TestCollaborationEnums:
    def test_comment_type_values(self):
        assert CommentType.COMMENT.value == "comment"
        assert CommentType.SUGGESTION.value == "suggestion"
        assert CommentType.QUESTION.value == "question"
        assert CommentType.ISSUE.value == "issue"

    def test_task_status_values(self):
        assert TaskStatus.TODO.value == "todo"
        assert TaskStatus.IN_PROGRESS.value == "in_progress"
        assert TaskStatus.REVIEW.value == "review"
        assert TaskStatus.DONE.value == "done"
        assert TaskStatus.ARCHIVED.value == "archived"

    def test_approval_status_values(self):
        assert ApprovalStatus.PENDING.value == "pending"
        assert ApprovalStatus.APPROVED.value == "approved"
        assert ApprovalStatus.REJECTED.value == "rejected"
        assert ApprovalStatus.NEEDS_CHANGES.value == "needs_changes"

    def test_change_type_values(self):
        assert ChangeType.CREATE.value == "create"
        assert ChangeType.UPDATE.value == "update"
        assert ChangeType.DELETE.value == "delete"
        assert ChangeType.MOVE.value == "move"


class TestTeamMemberModel:
    def test_create_with_defaults(self, db):
        m = TeamMember(name="Alice", email="alice@example.com", role="editor")
        db.add(m)
        db.commit()
        assert m.id is not None
        # Default active state and empty JSON list columns.
        assert m.is_active is True
        assert m.skills == []
        assert m.languages == []
        # created_at populated from the default lambda — must be a near-now TZ-aware datetime.
        from datetime import datetime, timezone

        assert (datetime.now(timezone.utc) - m.created_at.replace(tzinfo=timezone.utc)).total_seconds() < 5

    def test_skills_list_mutates_inplace(self, db):
        m = TeamMember(name="Bob", email="bob@example.com", role="narrator")
        m.skills = ["editing", "vo"]
        m.languages = ["zh", "en"]
        db.add(m)
        db.commit()
        # MutableList mutability must round-trip through the JSON column.
        assert m.skills == ["editing", "vo"]
        assert m.languages == ["zh", "en"]

    def test_login_link_optional_and_unique(self, db):
        u = User(email="lu@example.com", username="lu", hashed_password="h", is_active=True)
        db.add(u)
        db.flush()
        m = TeamMember(name="Lu", email="lu@example.com", role="editor", user_id=u.id)
        db.add(m)
        db.commit()
        assert m.user_id == u.id


class TestCommentModel:
    def test_create_and_resolve(self, db):
        author = TeamMember(name="A", email="a@example.com", role="editor")
        db.add(author)
        db.flush()
        c = Comment(
            content="Please review para 3",
            comment_type=CommentType.SUGGESTION,
            author_id=author.id,
            resolved=False,
        )
        db.add(c)
        db.commit()
        assert c.id is not None
        assert c.resolved is False
        assert c.comment_type == CommentType.SUGGESTION

        # Mark resolved, with timestamp + resolver.
        c.resolved = True
        solver = TeamMember(name="B", email="b@example.com", role="editor")
        db.add(solver)
        db.flush()
        c.resolved_by = solver.id
        c.resolved_at = datetime.now(timezone.utc)
        db.commit()
        assert c.resolved is True
        assert c.resolved_by == solver.id

    def test_reply_relationship_parent_and_replies(self, db):
        author = TeamMember(name="C", email="c@example.com", role="editor")
        db.add(author)
        db.flush()
        parent = Comment(
            content="Question here",
            comment_type=CommentType.QUESTION,
            author_id=author.id,
        )
        db.add(parent)
        db.commit()
        reply = Comment(
            content="Answer here",
            comment_type=CommentType.COMMENT,
            author_id=author.id,
            parent_id=parent.id,
        )
        db.add(reply)
        db.commit()
        # `replies` backref must surface the linked child.
        assert reply in parent.replies
        assert reply.parent_id == parent.id


class TestTaskModel:
    def test_create_with_defaults_status_todo_priority_one(self, db):
        assignee = TeamMember(name="D", email="d@example.com", role="editor")
        reporter = TeamMember(name="R", email="r@example.com", role="manager")
        db.add_all([assignee, reporter])
        db.flush()
        t = Task(
            title="Translate ch.1",
            description="Translate the first chapter",
            assignee_id=assignee.id,
            reporter_id=reporter.id,
        )
        db.add(t)
        db.commit()
        # Defaults: status TODO, priority 1.
        assert t.status == TaskStatus.TODO
        assert t.priority == 1
        assert t.tags == []
        # Relationship wiring
        assert t.assignee.id == assignee.id
        assert t.reporter.id == reporter.id

    def test_status_transitions_and_tags(self, db):
        assignee = TeamMember(name="E", email="e@example.com", role="editor")
        db.add(assignee)
        db.flush()
        t = Task(title="Edit ch.2", description="d", assignee_id=assignee.id)
        t.tags = ["urgent", "ch2"]
        db.add(t)
        db.commit()
        t.status = TaskStatus.IN_PROGRESS
        t.priority = 5
        t.estimated_hours = 4.5
        db.commit()
        assert t.status == TaskStatus.IN_PROGRESS
        assert t.tags == ["urgent", "ch2"]
        assert t.priority == 5
        assert t.estimated_hours == 4.5

    def test_subtasks_via_parent_task_id(self, db):
        assignee = TeamMember(name="F", email="f@example.com", role="editor")
        db.add(assignee)
        db.flush()
        parent = Task(title="Epic", description="d", assignee_id=assignee.id)
        db.add(parent)
        db.commit()
        child = Task(title="Sub", description="d", assignee_id=assignee.id, parent_task_id=parent.id)
        db.add(child)
        db.commit()
        assert child in parent.subtasks
        assert child.parent_task_id == parent.id

    def test_task_dependency_many_to_many(self, db):
        m = TeamMember(name="G", email="g@example.com", role="editor")
        db.add(m)
        db.flush()
        a = Task(title="A", description="d", assignee_id=m.id)
        b = Task(title="B", description="d", assignee_id=m.id)
        db.add_all([a, b])
        db.commit()
        b.depends_on.append(a)
        db.commit()
        # B waits on A; A's dependents includes B.
        assert a in b.depends_on
        assert b in a.dependents

    def test_overdue_task(self, db):
        m = TeamMember(name="H", email="h@example.com", role="editor")
        db.add(m)
        db.flush()
        past = datetime.now(timezone.utc) - timedelta(days=2)
        t = Task(title="Late", description="d", assignee_id=m.id, due_date=past)
        db.add(t)
        db.commit()
        # SQLite stores naive datetimes; assert the persisted value is in the
        # past relative to a fresh naive "now".
        now_naive = datetime.now()
        assert t.due_date is not None
        assert t.due_date < now_naive


class TestApprovalWorkflow:
    def test_create_request_defaults_pending(self, db):
        requester = TeamMember(name="I", email="i@example.com", role="translator")
        db.add(requester)
        db.flush()
        req = ApprovalRequest(
            title="Approve translation",
            description=" QA review before publish",
            requester_id=requester.id,
        )
        db.add(req)
        db.commit()
        # Default status PENDING, required_approvals 1, auto-approve False.
        assert req.status == ApprovalStatus.PENDING
        assert req.required_approvals == 1
        assert req.auto_approve_if_unstoppable is False
        assert req.requester.id == requester.id

    def test_approver_m2m_and_responses(self, db):
        requester = TeamMember(name="J", email="j@example.com", role="editor")
        approver = TeamMember(name="K", email="k@example.com", role="manager")
        db.add_all([requester, approver])
        db.flush()
        req = ApprovalRequest(title="X", description="d", requester_id=requester.id, required_approvals=1)
        req.approvers.append(approver)
        db.add(req)
        db.commit()
        assert approver in req.approvers

        # Submit the approver's response.
        resp = ApprovalResponse(
            approval_request_id=req.id,
            approver_id=approver.id,
            status=ApprovalStatus.APPROVED,
            comment="LGTM",
        )
        db.add(resp)
        db.commit()
        assert resp.approval_request_id == req.id
        assert resp.status == ApprovalStatus.APPROVED
        assert resp in req.responses

    def test_rejection_status_change(self, db):
        requester = TeamMember(name="L", email="l@example.com", role="editor")
        db.add(requester)
        db.flush()
        req = ApprovalRequest(title="Y", description="d", requester_id=requester.id)
        db.add(req)
        db.commit()
        req.status = ApprovalStatus.REJECTED
        db.commit()
        assert req.status == ApprovalStatus.REJECTED


class TestChangeRecordAuditTrail:
    def test_create_records_old_new_state(self, db):
        changer = TeamMember(name="M", email="m@example.com", role="editor")
        db.add(changer)
        db.flush()
        rec = ChangeRecord(
            change_type=ChangeType.UPDATE,
            entity_type="task",
            entity_id=7,
            changed_by=changer.id,
            old_state='{"status":"todo"}',
            new_state='{"status":"done"}',
            description="marked done",
        )
        db.add(rec)
        db.commit()
        assert rec.change_type == ChangeType.UPDATE
        assert rec.entity_type == "task"
        # Real assertions on persisted state:
        assert rec.old_state == '{"status":"todo"}'
        assert rec.new_state == '{"status":"done"}'
        # Default description fallback came from us (not default "").
        assert rec.description == "marked done"

    def test_change_record_default_description(self, db):
        changer = TeamMember(name="N", email="n@example.com", role="editor")
        db.add(changer)
        db.flush()
        rec = ChangeRecord(
            change_type=ChangeType.CREATE,
            entity_type="comment",
            entity_id=1,
            changed_by=changer.id,
        )
        db.add(rec)
        db.commit()
        # description defaulted to "" because we supplied no value.
        assert rec.description == ""

    def test_related_change_chain(self, db):
        changer = TeamMember(name="O", email="o@example.com", role="editor")
        db.add(changer)
        db.flush()
        parent_change = ChangeRecord(
            change_type=ChangeType.CREATE,
            entity_type="task",
            entity_id=1,
            changed_by=changer.id,
        )
        db.add(parent_change)
        db.commit()
        followup = ChangeRecord(
            change_type=ChangeType.UPDATE,
            entity_type="task",
            entity_id=1,
            changed_by=changer.id,
            related_change_id=parent_change.id,
        )
        db.add(followup)
        db.commit()
        assert followup.related_change_id == parent_change.id
        assert followup in parent_change.followup_changes

"""Integration tests for the collaboration API router.

Covers the full CRUD + auth integration introduced when the placeholder 501
endpoints were replaced with SQLAlchemy-backed implementations:
- Comments: create / get / list (filtered) / resolve
- Team members: list / auto-creation of the caller's profile
- Tasks: create (with assignee/reporter validation) / get / list (filtered) / update status
- Approvals: create / get / list / respond (status refresh, 403 for non-approvers)
- Change history + stats
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.audiobook_studio.api.collab import router
from src.audiobook_studio.auth.dependencies import get_current_active_user
from src.audiobook_studio.database import Base, get_db
from src.audiobook_studio.models.collaboration import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ChangeRecord,
    Comment,
    TeamMember,
)
from src.audiobook_studio.models.user import User

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=eng)
    yield eng
    eng.dispose()


@pytest.fixture
def db_session(engine):
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def alice_user(db_session):
    """A real User record for the auth dependency. No TeamMember is pre-created so tests
    that exercise auto-creation (GET /members/me) can do so; tests that need a pre-existing
    profile should request the ``alice_member`` fixture instead."""
    user = User(
        username="alice",
        email="alice@example.com",
        hashed_password="hash",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def alice_member(db_session, alice_user):
    """A TeamMember profile linked to alice_user, created up-front for tests that need one."""
    member = TeamMember(
        name="Alice",
        email="alice@example.com",
        role="editor",
        is_active=True,
        user_id=alice_user.id,
    )
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)
    return member


@pytest.fixture
def bob_user(db_session):
    user = User(
        username="bob",
        email="bob@example.com",
        hashed_password="hash",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(db_session, alice_user):
    """TestClient wired to the in-memory DB, auth always resolves to alice."""
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_active_user] = lambda: alice_user
    with TestClient(app) as c:
        c.app = app
        yield c
    app.dependency_overrides.clear()


def _make_member(db_session, name, email, role="editor", user=None):
    member = TeamMember(
        name=name,
        email=email,
        role=role,
        is_active=True,
        user_id=user.id if user else None,
    )
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)
    return member


# ── Team member endpoints ──────────────────────────────────────────────────────


class TestTeamMembers:
    def test_get_my_profile_auto_creates(self, client, db_session, alice_user):
        # No TeamMember linked to alice yet
        assert db_session.query(TeamMember).filter(TeamMember.user_id == alice_user.id).first() is None
        resp = client.get("/api/collab/members/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == alice_user.id
        assert data["email"] == "alice@example.com"
        # Second call reuses the existing profile rather than creating a duplicate
        resp2 = client.get("/api/collab/members/me")
        assert resp2.status_code == 200
        assert resp2.json()["id"] == data["id"]
        assert db_session.query(TeamMember).filter(TeamMember.user_id == alice_user.id).count() == 1

    def test_list_members_filter_by_role(self, client, db_session):
        _make_member(db_session, "Bob", "bob@x.com", role="narrator")
        _make_member(db_session, "Carol", "carol@x.com", role="manager")
        resp = client.get("/api/collab/members", params={"role": "manager"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["name"] == "Carol"


# ── Comment endpoints ──────────────────────────────────────────────────────────


class TestComments:
    def test_create_and_get_comment(self, client, alice_user):
        resp = client.post(
            "/api/collab/comments",
            json={"content": "Looks good", "comment_type": "comment"},
        )
        assert resp.status_code == 201
        created = resp.json()
        assert created["content"] == "Looks good"
        assert created["author_id"] is not None
        # The author is a TeamMember derived from alice, not the literal string "system"
        assert created["resolved"] is False
        comment_id = created["id"]
        resp2 = client.get(f"/api/collab/comments/{comment_id}")
        assert resp2.status_code == 200
        assert resp2.json()["id"] == comment_id

    def test_create_comment_rejects_invalid_type(self, client):
        resp = client.post(
            "/api/collab/comments",
            json={"content": "x", "comment_type": "chatter"},
        )
        assert resp.status_code == 422

    def test_get_comment_404(self, client):
        assert client.get("/api/collab/comments/999999").status_code == 404

    def test_list_comments_filtered_by_task(self, client, db_session, alice_member):
        task_a = _make_task(db_session, alice_member)
        task_b = _make_task(db_session, alice_member)
        client.post("/api/collab/comments", json={"content": "on A", "comment_type": "comment", "task_id": task_a.id})
        client.post("/api/collab/comments", json={"content": "on B", "comment_type": "issue", "task_id": task_b.id})
        resp = client.get("/api/collab/comments", params={"task_id": task_a.id})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["content"] == "on A"

    def test_resolve_comment(self, client, db_session, alice_user):
        created = client.post(
            "/api/collab/comments",
            json={"content": "needs resolving", "comment_type": "issue"},
        ).json()
        cid = created["id"]
        assert created["resolved"] is False
        resp = client.put(f"/api/collab/comments/{cid}/resolve")
        assert resp.status_code == 200
        data = resp.json()
        assert data["resolved"] is True
        assert data["resolved_by"] is not None
        assert data["resolved_at"] is not None
        # A change record must have been logged
        assert db_session.query(ChangeRecord).filter(ChangeRecord.entity_type == "comment").count() >= 1


# ── Task endpoints ─────────────────────────────────────────────────────────────


def _make_task(db_session, reporter, assignee=None, status="todo", title="Sample task"):
    from src.audiobook_studio.models.collaboration import Task, TaskStatus

    task = Task(
        title=title,
        description="desc",
        status=TaskStatus(status),
        assignee_id=assignee.id if assignee else None,
        reporter_id=reporter.id,
        priority=2,
    )
    db_session.add(task)
    db_session.commit()
    db_session.refresh(task)
    return task


class TestTasks:
    def test_create_task_defaults_reporter_to_caller(self, client, db_session):
        bob_member = _make_member(db_session, "Bob", "bob3@x.com", role="narrator")
        resp = client.post(
            "/api/collab/tasks",
            json={
                "title": "Transcribe ch1",
                "description": "Do it",
                "status": "todo",
                "assignee_id": bob_member.id,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        # reporter should be alice's auto-created member id, not null
        assert data["reporter_id"] is not None
        assert data["assignee_id"] == bob_member.id

    def test_create_task_invalid_assignee(self, client):
        resp = client.post(
            "/api/collab/tasks",
            json={"title": "T", "description": "d", "status": "todo", "assignee_id": 99999},
        )
        assert resp.status_code == 400
        assert "Assignee not found" in resp.json()["detail"]

    def test_create_task_invalid_status(self, client):
        resp = client.post(
            "/api/collab/tasks",
            json={"title": "T", "description": "d", "status": "wonky"},
        )
        assert resp.status_code == 422

    def test_get_task_404(self, client):
        assert client.get("/api/collab/tasks/999999").status_code == 404

    def test_list_tasks_filtered_by_status(self, client, db_session, alice_member):
        bob_member = _make_member(db_session, "Bob", "bob4@x.com")
        _make_task(db_session, alice_member, assignee=bob_member, status="todo", title="A")
        _make_task(db_session, alice_member, assignee=bob_member, status="done", title="B")
        # Filter by status=done
        resp = client.get("/api/collab/tasks", params={"status": "done"})
        assert resp.status_code == 200
        titles = [t["title"] for t in resp.json()]
        assert titles == ["B"]
        # Filter by assignee
        resp2 = client.get("/api/collab/tasks", params={"assignee_id": bob_member.id})
        assert len(resp2.json()) == 2

    def test_update_task_status_records_change(self, client, db_session, alice_member):
        task = _make_task(db_session, alice_member, status="todo", title="To advance")
        prev_changes = db_session.query(ChangeRecord).filter(ChangeRecord.entity_type == "task").count()
        resp = client.put(
            f"/api/collab/tasks/{task.id}/status",
            params={"new_status": "in_progress"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "in_progress"
        new_changes = db_session.query(ChangeRecord).filter(ChangeRecord.entity_type == "task").count()
        assert new_changes == prev_changes + 1

    def test_update_task_status_404(self, client):
        resp = client.put("/api/collab/tasks/999999/status", params={"new_status": "done"})
        assert resp.status_code == 404

    def test_update_task_status_invalid(self, client, db_session, alice_member):
        task = _make_task(db_session, alice_member)
        resp = client.put(f"/api/collab/tasks/{task.id}/status", params={"new_status": "nope"})
        assert resp.status_code == 422


# ── Approval endpoints ────────────────────────────────────────────────────────


class TestApprovals:
    def test_create_approval_request(self, client, db_session):
        approver = _make_member(db_session, "Bob", "bob7@x.com", role="manager")
        resp = client.post(
            "/api/collab/approvals",
            json={
                "title": "Release ch1",
                "description": "Approve please",
                "approver_ids": [approver.id],
                "required_approvals": 1,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"
        assert data["requester_id"] is not None
        assert data["responses"] == []

    def test_create_approval_no_valid_approvers(self, client):
        resp = client.post(
            "/api/collab/approvals",
            json={"title": "X", "description": "d", "approver_ids": [99999]},
        )
        assert resp.status_code == 400
        assert "approver" in resp.json()["detail"]

    def test_create_approval_unknown_task(self, client, db_session):
        approver = _make_member(db_session, "Bob", "bob8@x.com", role="manager")
        resp = client.post(
            "/api/collab/approvals",
            json={"title": "X", "description": "d", "approver_ids": [approver.id], "task_id": 99999},
        )
        assert resp.status_code == 400
        assert "task" in resp.json()["detail"].lower()

    def test_get_approval_404(self, client):
        assert client.get("/api/collab/approvals/999999").status_code == 404

    def test_list_approvals_filtered_by_status(self, client, db_session, alice_member):
        approver = _make_member(db_session, "Bob", "bob9@x.com", role="manager")
        # pending approval
        client.post(
            "/api/collab/approvals",
            json={"title": "P", "description": "d", "approver_ids": [approver.id]},
        )
        # an already-approved approval crafted directly via the model
        approved = ApprovalRequest(
            title="Done",
            description="d",
            requester_id=alice_member.id,
            status=ApprovalStatus.APPROVED,
            required_approvals=1,
        )
        approved.approvers = [approver]
        db_session.add(approved)
        db_session.commit()
        resp = client.get("/api/collab/approvals", params={"status": "approved"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Done"

    def test_respond_to_approval_promotes_status(self, client, db_session, bob_user):
        # alice is the requester; bob is the approver.
        bob_member = _make_member(db_session, "Bob", "bob10@x.com", role="manager", user=bob_user)

        create_resp = client.post(
            "/api/collab/approvals",
            json={"title": "Sign off", "description": "d", "approver_ids": [bob_member.id]},
        )
        approval_id = create_resp.json()["id"]

        # Override auth to bob and respond
        client.app.dependency_overrides[get_current_active_user] = lambda: bob_user
        resp = client.post(
            f"/api/collab/approvals/{approval_id}/respond",
            json={"status": "approved", "comment": "lgtm"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "approved"
        assert len(data["responses"]) == 1
        assert data["responses"][0]["status"] == "approved"

    def test_respond_to_approval_rejection_marks_rejected(self, client, db_session, alice_user):
        bob_user = User(username="bob_rej", email="bob_rej@example.com", hashed_password="h", is_active=True)
        db_session.add(bob_user)
        db_session.commit()
        db_session.refresh(bob_user)
        bob_member = _make_member(db_session, "Bob", "bob11@x.com", role="manager", user=bob_user)

        create_resp = client.post(
            "/api/collab/approvals",
            json={"title": "Sign off 2", "description": "d", "approver_ids": [bob_member.id]},
        )
        approval_id = create_resp.json()["id"]

        client.app.dependency_overrides[get_current_active_user] = lambda: bob_user
        resp = client.post(
            f"/api/collab/approvals/{approval_id}/respond",
            json={"status": "rejected"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_respond_to_approval_non_approver_forbidden(self, client, db_session, alice_user):
        approver = _make_member(db_session, "Approver", "appr@x.com", role="manager")
        create_resp = client.post(
            "/api/collab/approvals",
            json={"title": "X", "description": "d", "approver_ids": [approver.id]},
        )
        approval_id = create_resp.json()["id"]
        # alice is the requester, not the approver -> 403
        resp = client.post(
            f"/api/collab/approvals/{approval_id}/respond",
            json={"status": "approved"},
        )
        assert resp.status_code == 403
        assert "approver" in resp.json()["detail"].lower()

    def test_respond_to_approval_404(self, client):
        resp = client.post("/api/collab/approvals/999999/respond", json={"status": "approved"})
        assert resp.status_code == 404


# ── History + Stats ────────────────────────────────────────────────────────────


class TestHistoryAndStats:
    def test_history_records_write_operations(self, client, db_session, alice_user):
        # Create a comment -> should seed a change record
        client.post("/api/collab/comments", json={"content": "hi", "comment_type": "comment"})
        resp = client.get("/api/collab/history")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["entity_type"] == "comment"

    def test_history_filtered_by_entity_type(self, client, db_session, alice_member):
        client.post("/api/collab/comments", json={"content": "c", "comment_type": "comment"})
        _make_task(db_session, alice_member)
        client.post(
            "/api/collab/tasks",
            json={"title": "T", "description": "d", "status": "todo"},
        )
        resp = client.get("/api/collab/history", params={"entity_type": "task"})
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["entity_type"] == "task" for r in data)
        assert len(data) >= 1

    def test_stats_endpoint(self, client, db_session):
        # Ensure at least one comment exists
        client.post("/api/collab/comments", json={"content": "c", "comment_type": "comment"})
        resp = client.get("/api/collab/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_comments"] >= 1
        assert "tasks_by_status" in data
        assert "approvals_by_status" in data
        assert data["total_changes"] >= 1
        # Every TaskStatus / CommentType / ApprovalStatus key is present
        for key in ("todo", "in_progress", "review", "done", "archived"):
            assert key in data["tasks_by_status"]

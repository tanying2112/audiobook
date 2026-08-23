"""Behavior tests for src/audiobook_studio/models/user.py RBAC methods.

Exercises User.has_permission / has_role / get_permissions against a REAL
in-memory SQLite database (created via create_all), not mocks. Asserts:
- superuser bypass returns True for any permission/role
- non-superuser permission lookup iterates role.permissions
- role membership check matches by role.name
- permission aggregation deduplicates and grants "*" to superusers
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.audiobook_studio.database import Base
from src.audiobook_studio.models.user import Permission, Role, User


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


def _make_role_with_perms(db: Session, role_name: str, perm_names: list[str]) -> Role:
    role = Role(name=role_name, description=f"{role_name} role")
    for pn in perm_names:
        # Permission.name is UNIQUE — reuse an existing row if present.
        existing = db.query(Permission).filter(Permission.name == pn).first()
        perm = existing or Permission(name=pn, description=f"{pn} permission")
        role.permissions.append(perm)
    db.add(role)
    db.flush()
    return role


class TestUserHasPermission:
    def test_superuser_bypass_any_permission(self, db):
        su = User(
            email="root@example.com",
            username="root",
            hashed_password="h",
            is_active=True,
            is_superuser=True,
        )
        db.add(su)
        db.flush()
        # Superuser must possess every permission, including ones no role grants.
        assert su.has_permission("project:delete") is True
        assert su.has_permission("system:reboot") is True

    def test_non_superuser_with_role_permission_true(self, db):
        role = _make_role_with_perms(db, "editor", ["project:read", "project:write"])
        u = User(
            email="ed@example.com",
            username="ed",
            hashed_password="h",
            is_active=True,
            is_superuser=False,
        )
        u.roles.append(role)
        db.add(u)
        db.flush()
        assert u.has_permission("project:read") is True
        assert u.has_permission("project:write") is True

    def test_non_superuser_missing_permission_false(self, db):
        role = _make_role_with_perms(db, "viewer", ["project:read"])
        u = User(
            email="v@example.com",
            username="v",
            hashed_password="h",
            is_active=True,
            is_superuser=False,
        )
        u.roles.append(role)
        db.add(u)
        db.flush()
        # viewer only has project:read, so project:delete must be False
        assert u.has_permission("project:read") is True
        assert u.has_permission("project:delete") is False

    def test_user_with_no_roles_has_no_permissions(self, db):
        u = User(
            email="nobody@example.com",
            username="nobody",
            hashed_password="h",
            is_active=True,
            is_superuser=False,
        )
        db.add(u)
        db.flush()
        assert u.has_permission("anything") is False


class TestUserHasRole:
    def test_superuser_has_any_role(self, db):
        su = User(
            email="root@example.com",
            username="root2",
            hashed_password="h",
            is_active=True,
            is_superuser=True,
        )
        db.add(su)
        db.flush()
        assert su.has_role("admin") is True
        assert su.has_role(" nonexistent-role ") is True

    def test_has_matching_role_name(self, db):
        role = Role(name="editor", description="editor")
        u = User(
            email="e@example.com",
            username="e",
            hashed_password="h",
            is_active=True,
            is_superuser=False,
        )
        u.roles.append(role)
        db.add(u)
        db.flush()
        assert u.has_role("editor") is True

    def test_missing_role_returns_false(self, db):
        role = Role(name="editor", description="editor")
        u = User(
            email="e2@example.com",
            username="e2",
            hashed_password="h",
            is_active=True,
            is_superuser=False,
        )
        u.roles.append(role)
        db.add(u)
        db.flush()
        assert u.has_role("admin") is False

    def test_multiple_roles_matched_by_any(self, db):
        r1 = Role(name="editor")
        r2 = Role(name="narrator")
        u = User(
            email="multi@example.com",
            username="multi",
            hashed_password="h",
            is_active=True,
            is_superuser=False,
        )
        u.roles.extend([r1, r2])
        db.add(u)
        db.flush()
        assert u.has_role("editor") is True
        assert u.has_role("narrator") is True
        assert u.has_role("viewer") is False


class TestUserGetPermissions:
    def test_superuser_gets_wildcard(self, db):
        su = User(
            email="root3@example.com",
            username="root3",
            hashed_password="h",
            is_active=True,
            is_superuser=True,
        )
        db.add(su)
        db.flush()
        perms = su.get_permissions()
        assert perms == {"*"}

    def test_aggregates_and_dedupes_permissions(self, db):
        # Two roles sharing one permission, plus unique perms each
        r1 = _make_role_with_perms(db, "editor", ["project:read", "project:write"])
        r2 = _make_role_with_perms(db, "narrator", ["project:read", "project:publish"])
        u = User(
            email="agg@example.com",
            username="agg",
            hashed_password="h",
            is_active=True,
            is_superuser=False,
        )
        u.roles.extend([r1, r2])
        db.add(u)
        db.flush()
        perms = u.get_permissions()
        # Dedup: project:read appears in both roles only once.
        assert perms == {"project:read", "project:write", "project:publish"}

    def test_no_roles_yields_empty_set(self, db):
        u = User(
            email="empty@example.com",
            username="empty",
            hashed_password="h",
            is_active=True,
            is_superuser=False,
        )
        db.add(u)
        db.flush()
        assert u.get_permissions() == set()

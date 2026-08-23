"""Behavior tests for src/audiobook_studio/auth/rbac.py seeding + helpers.

The existing test_rbac.py exercises RBACManager with a mocked DB and is
explicitly scoped to permission/role assignment logic. init_rbac(), the two
read-side helpers (get_user_project_permissions / get_user_projects), and the
legacy decorator/standalone helpers were uncovered. These tests run init_rbac
against a REAL in-memory SQLite (created via Base.metadata.create_all) and
assert the seeding is real, idempotent, and that the read helpers return real
data — no implicit mocking of the production path.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.audiobook_studio.auth.models import PermissionName, RoleName
from src.audiobook_studio.auth.rbac import (
    RBACManager,
    check_permission,
    get_rbac_manager,
    init_rbac,
)
from src.audiobook_studio.database import Base
from src.audiobook_studio.models.user import Permission, ProjectPermission, Role, User


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


class TestInitRbac:
    def test_seed_creates_all_permissions_and_roles(self, db):
        init_rbac(db)
        # Every PermissionName enum value must exist as a DB row.
        perm_names = {p.name for p in db.query(Permission).all()}
        assert perm_names == {pn.value for pn in PermissionName}
        role_names = {r.name for r in db.query(Role).all()}
        assert role_names == {rn.value for rn in RoleName}

    def test_seed_admin_has_every_permission(self, db):
        init_rbac(db)
        admin = db.query(Role).filter(Role.name == RoleName.ADMIN.value).first()
        admin_perm_set = {p.name for p in admin.permissions}
        # Admin gets *all* PermissionName values.
        assert admin_perm_set == {pn.value for pn in PermissionName}

    def test_seed_project_owner_permissions_subset(self, db):
        init_rbac(db)
        owner = db.query(Role).filter(Role.name == RoleName.PROJECT_OWNER.value).first()
        owner_perms = {p.name for p in owner.permissions}
        # Owner must hold core project perms and is NOT granted admin-only ones.
        assert PermissionName.PROJECT_CREATE.value in owner_perms
        assert PermissionName.PROJECT_DELETE.value in owner_perms
        # A representative admin-only perm distinct from owner: ADMIN_USERS.
        assert PermissionName.ADMIN_USERS.value not in owner_perms

    def test_seed_editor_permissions_subset(self, db):
        init_rbac(db)
        editor = db.query(Role).filter(Role.name == RoleName.EDITOR.value).first()
        editor_perms = {p.name for p in editor.permissions}
        assert PermissionName.PARAGRAPH_ANNOTATE.value in editor_perms
        assert PermissionName.PARAGRAPH_EDIT.value in editor_perms
        assert PermissionName.PROJECT_DELETE.value not in editor_perms

    def test_init_rbac_is_idempotent(self, db):
        init_rbac(db)
        perm_count_1 = db.query(Permission).count()
        role_count_1 = db.query(Role).count()
        # Second invocation must not duplicate rows.
        init_rbac(db)
        assert db.query(Permission).count() == perm_count_1
        assert db.query(Role).count() == role_count_1
        # Admin still has exactly the full permission set (not 2× assignment).
        admin = db.query(Role).filter(Role.name == RoleName.ADMIN.value).first()
        admin_perm_names = {p.name for p in admin.permissions}
        assert len(admin_perm_names) == len(list(PermissionName))


class TestRbacUserPermissionHelpers:
    def test_get_user_project_permissions_returns_rows(self, db):
        init_rbac(db)
        user = User(
            email="p@example.com", username="p", hashed_password="h", is_active=True
        )
        db.add(user)
        db.flush()
        pp = ProjectPermission(
            user_id=user.id, project_id=42, role="editor"
        )
        db.add(pp)
        db.commit()

        rbac = RBACManager(db)
        perms = rbac.get_user_project_permissions(user.id)
        assert len(perms) == 1
        assert perms[0].project_id == 42
        assert perms[0].role == "editor"

    def test_get_user_projects_returns_role_map(self, db):
        init_rbac(db)
        user = User(
            email="p2@example.com", username="p2", hashed_password="h", is_active=True
        )
        db.add(user)
        db.flush()
        db.add_all(
            [
                ProjectPermission(user_id=user.id, project_id=42, role="editor"),
                ProjectPermission(user_id=user.id, project_id=7, role="viewer"),
            ]
        )
        db.commit()

        rbac = RBACManager(db)
        projects = rbac.get_user_projects(user.id)
        assert {(p["project_id"], p["role"]) for p in projects} == {(42, "editor"), (7, "viewer")}
        # No perms for an unknown user -> empty list, not None.
        assert rbac.get_user_projects(999999) == []

    def test_user_has_permission_uses_real_seeded_roles(self, db):
        init_rbac(db)
        user = User(
            email="e@example.com", username="e", hashed_password="h", is_active=True
        )
        editor = db.query(Role).filter(Role.name == RoleName.EDITOR.value).first()
        user.roles = [editor]
        db.add(user)
        db.commit()

        rbac = RBACManager(db)
        # Editor was seeded with paragraph:edit -> must have that permission.
        assert rbac.user_has_permission(user, PermissionName.PARAGRAPH_EDIT) is True
        # Seeded editor lacks project:delete.
        assert rbac.user_has_permission(user, PermissionName.PROJECT_DELETE) is False


class TestLegacyConvenienceHelpers:
    def test_check_permission_uses_rbac_manager(self, db):
        init_rbac(db)
        user = User(
            email="x@example.com", username="x", hashed_password="h", is_active=True
        )
        admin = db.query(Role).filter(Role.name == RoleName.ADMIN.value).first()
        user.roles = [admin]
        db.add(user)
        db.commit()

        # Standalone check_permission must reflect real RBAC.
        assert check_permission(user, PermissionName.PROJECT_READ, db) is True
        assert check_permission(user, PermissionName.ADMIN_USERS, db) is True

    def test_get_rbac_manager_returns_manager_binds_same_db(self, db):
        rbac = get_rbac_manager(db)
        assert isinstance(rbac, RBACManager)
        assert rbac.db is db

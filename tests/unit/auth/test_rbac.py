"""Unit tests for src/audiobook_studio/auth/rbac.py — RBACManager.

All tests use mocked DB sessions and model objects. No real database connections.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.auth.models import PermissionName, RoleName
from src.audiobook_studio.auth.rbac import (
    RBACManager,
    check_permission,
    get_rbac_manager,
    require_permission,
    require_project_permission,
    require_role,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_user(
    id=1,
    username="testuser",
    email="test@example.com",
    is_superuser=False,
    is_active=True,
    roles=None,
    hashed_password="hashed",
):
    user = MagicMock()
    user.id = id
    user.username = username
    user.email = email
    user.is_superuser = is_superuser
    user.is_active = is_active
    user.hashed_password = hashed_password
    user.roles = roles or []
    user.has_role = lambda name: is_superuser or any(
        r.name == (name.value if hasattr(name, "value") else name) for r in user.roles
    )
    return user


def _make_role(id=1, name="admin", description="Admin role", permissions=None):
    role = MagicMock()
    role.id = id
    role.name = name
    role.description = description
    role.permissions = permissions or []
    return role


def _make_permission(id=1, name="project:read", description="Read projects"):
    perm = MagicMock()
    perm.id = id
    perm.name = name
    perm.description = description
    return perm


def _make_project_permission(id=1, user_id=1, project_id=10, role="editor"):
    pp = MagicMock()
    pp.id = id
    pp.user_id = user_id
    pp.project_id = project_id
    pp.role = role
    return pp


def _make_rbac(db_mock=None):
    if db_mock is None:
        db_mock = MagicMock()
    return RBACManager(db_mock)


# ── User Management ──────────────────────────────────────────────────────────


class TestCreateUser:
    @patch("src.audiobook_studio.auth.rbac.hash_password", return_value="hashed_pw")
    def test_create_user_success(self, mock_hash):
        rbac = _make_rbac()
        user = rbac.create_user("a@b.com", "alice", "password123", full_name="Alice")
        rbac.db.add.assert_called_once()
        rbac.db.commit.assert_called_once()
        rbac.db.refresh.assert_called_once()
        mock_hash.assert_called_once_with("password123")

    @patch("src.audiobook_studio.auth.rbac.hash_password", return_value="hashed_pw")
    def test_create_superuser(self, mock_hash):
        rbac = _make_rbac()
        user = rbac.create_user("a@b.com", "admin", "pw", is_superuser=True)
        added_user = rbac.db.add.call_args[0][0]
        assert added_user.is_superuser is True


class TestGetUser:
    def test_get_user_found(self):
        rbac = _make_rbac()
        mock_user = _make_user(id=5)
        rbac.db.query.return_value.filter.return_value.first.return_value = mock_user
        result = rbac.get_user(5)
        assert result == mock_user

    def test_get_user_not_found(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        result = rbac.get_user(999)
        assert result is None


class TestGetUserByUsername:
    def test_found(self):
        rbac = _make_rbac()
        mock_user = _make_user(username="bob")
        rbac.db.query.return_value.filter.return_value.first.return_value = mock_user
        assert rbac.get_user_by_username("bob") == mock_user

    def test_not_found(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        assert rbac.get_user_by_username("nobody") is None


class TestGetUserByEmail:
    def test_found(self):
        rbac = _make_rbac()
        mock_user = _make_user(email="x@y.com")
        rbac.db.query.return_value.filter.return_value.first.return_value = mock_user
        assert rbac.get_user_by_email("x@y.com") == mock_user

    def test_not_found(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        assert rbac.get_user_by_email("no@no.com") is None


class TestAuthenticateUser:
    @patch("src.audiobook_studio.auth.rbac.verify_password", return_value=True)
    def test_success(self, mock_verify):
        rbac = _make_rbac()
        mock_user = _make_user(hashed_password="hashed")
        rbac.db.query.return_value.filter.return_value.first.return_value = mock_user
        result = rbac.authenticate_user("testuser", "correct")
        assert result == mock_user
        mock_verify.assert_called_once_with("correct", "hashed")

    def test_user_not_found(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        result = rbac.authenticate_user("nobody", "pw")
        assert result is None

    @patch("src.audiobook_studio.auth.rbac.verify_password", return_value=False)
    def test_wrong_password(self, mock_verify):
        rbac = _make_rbac()
        mock_user = _make_user()
        rbac.db.query.return_value.filter.return_value.first.return_value = mock_user
        result = rbac.authenticate_user("testuser", "wrong")
        assert result is None


class TestUpdateUser:
    def test_update_fields(self):
        rbac = _make_rbac()
        user = _make_user()
        rbac.update_user(user, full_name="New Name", email="new@b.com")
        rbac.db.commit.assert_called_once()
        rbac.db.refresh.assert_called_once_with(user)

    def test_update_ignores_unknown_field(self):
        rbac = _make_rbac()
        user = _make_user()
        rbac.update_user(user, nonexistent_field="value")
        rbac.db.commit.assert_called_once()


class TestDeleteUser:
    def test_delete_existing(self):
        rbac = _make_rbac()
        user = _make_user()
        rbac.db.query.return_value.filter.return_value.first.return_value = user
        assert rbac.delete_user(1) is True
        rbac.db.delete.assert_called_once_with(user)
        rbac.db.commit.assert_called_once()

    def test_delete_nonexistent(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        assert rbac.delete_user(999) is False


# ── Role Management ──────────────────────────────────────────────────────────


class TestRoleManagement:
    def test_create_role(self):
        rbac = _make_rbac()
        role = rbac.create_role(RoleName.ADMIN, description="Admin")
        rbac.db.add.assert_called_once()
        rbac.db.commit.assert_called_once()

    def test_get_role_found(self):
        rbac = _make_rbac()
        mock_role = _make_role(name="admin")
        rbac.db.query.return_value.filter.return_value.first.return_value = mock_role
        assert rbac.get_role(RoleName.ADMIN) == mock_role

    def test_get_role_not_found(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        assert rbac.get_role(RoleName.ADMIN) is None

    def test_get_all_roles(self):
        rbac = _make_rbac()
        roles = [_make_role(id=1), _make_role(id=2)]
        rbac.db.query.return_value.all.return_value = roles
        assert rbac.get_all_roles() == roles

    def test_delete_role_existing(self):
        rbac = _make_rbac()
        role = _make_role()
        rbac.db.query.return_value.filter.return_value.first.return_value = role
        assert rbac.delete_role(1) is True
        rbac.db.delete.assert_called_once_with(role)

    def test_delete_role_nonexistent(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        assert rbac.delete_role(999) is False


# ── Permission Management ────────────────────────────────────────────────────


class TestPermissionManagement:
    def test_create_permission(self):
        rbac = _make_rbac()
        perm = rbac.create_permission(PermissionName.PROJECT_READ)
        rbac.db.add.assert_called_once()
        rbac.db.commit.assert_called_once()

    def test_get_permission_found(self):
        rbac = _make_rbac()
        mock_perm = _make_permission(name="project:read")
        rbac.db.query.return_value.filter.return_value.first.return_value = mock_perm
        assert rbac.get_permission(PermissionName.PROJECT_READ) == mock_perm

    def test_get_permission_not_found(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        assert rbac.get_permission(PermissionName.PROJECT_READ) is None

    def test_get_all_permissions(self):
        rbac = _make_rbac()
        perms = [_make_permission(id=1), _make_permission(id=2)]
        rbac.db.query.return_value.all.return_value = perms
        assert rbac.get_all_permissions() == perms


# ── Role-Permission Assignment ───────────────────────────────────────────────


class TestAssignPermissionToRole:
    def test_success(self):
        rbac = _make_rbac()
        role = _make_role(permissions=[])
        perm = _make_permission()
        with patch.object(rbac, "get_role", return_value=role):
            with patch.object(rbac, "get_permission", return_value=perm):
                assert rbac.assign_permission_to_role(RoleName.ADMIN, PermissionName.PROJECT_READ) is True
        assert perm in role.permissions
        rbac.db.commit.assert_called_once()

    def test_already_assigned(self):
        rbac = _make_rbac()
        perm = _make_permission()
        role = _make_role(permissions=[perm])
        with patch.object(rbac, "get_role", return_value=role):
            with patch.object(rbac, "get_permission", return_value=perm):
                assert rbac.assign_permission_to_role(RoleName.ADMIN, PermissionName.PROJECT_READ) is True
        # commit not called because perm was already in role
        rbac.db.commit.assert_not_called()

    def test_role_not_found(self):
        rbac = _make_rbac()
        with patch.object(rbac, "get_role", return_value=None):
            with patch.object(rbac, "get_permission", return_value=_make_permission()):
                assert rbac.assign_permission_to_role(RoleName.ADMIN, PermissionName.PROJECT_READ) is False

    def test_perm_not_found(self):
        rbac = _make_rbac()
        with patch.object(rbac, "get_role", return_value=_make_role()):
            with patch.object(rbac, "get_permission", return_value=None):
                assert rbac.assign_permission_to_role(RoleName.ADMIN, PermissionName.PROJECT_READ) is False


class TestRemovePermissionFromRole:
    def test_success(self):
        rbac = _make_rbac()
        perm = _make_permission()
        role = _make_role(permissions=[perm])
        with patch.object(rbac, "get_role", return_value=role):
            with patch.object(rbac, "get_permission", return_value=perm):
                assert rbac.remove_permission_from_role(RoleName.ADMIN, PermissionName.PROJECT_READ) is True
        assert perm not in role.permissions
        rbac.db.commit.assert_called_once()

    def test_not_assigned(self):
        rbac = _make_rbac()
        perm = _make_permission()
        role = _make_role(permissions=[])
        with patch.object(rbac, "get_role", return_value=role):
            with patch.object(rbac, "get_permission", return_value=perm):
                assert rbac.remove_permission_from_role(RoleName.ADMIN, PermissionName.PROJECT_READ) is True
        rbac.db.commit.assert_not_called()

    def test_role_not_found(self):
        rbac = _make_rbac()
        with patch.object(rbac, "get_role", return_value=None):
            with patch.object(rbac, "get_permission", return_value=_make_permission()):
                assert rbac.remove_permission_from_role(RoleName.ADMIN, PermissionName.PROJECT_READ) is False

    def test_perm_not_found(self):
        rbac = _make_rbac()
        with patch.object(rbac, "get_role", return_value=_make_role()):
            with patch.object(rbac, "get_permission", return_value=None):
                assert rbac.remove_permission_from_role(RoleName.ADMIN, PermissionName.PROJECT_READ) is False


# ── User-Role Assignment ─────────────────────────────────────────────────────


class TestAssignRoleToUser:
    def test_success(self):
        rbac = _make_rbac()
        user = _make_user(roles=[])
        role = _make_role()
        with patch.object(rbac, "get_user", return_value=user):
            with patch.object(rbac, "get_role", return_value=role):
                assert rbac.assign_role_to_user(1, RoleName.ADMIN) is True
        assert role in user.roles
        rbac.db.commit.assert_called_once()

    def test_already_assigned(self):
        rbac = _make_rbac()
        role = _make_role()
        user = _make_user(roles=[role])
        with patch.object(rbac, "get_user", return_value=user):
            with patch.object(rbac, "get_role", return_value=role):
                assert rbac.assign_role_to_user(1, RoleName.ADMIN) is True
        rbac.db.commit.assert_not_called()

    def test_user_not_found(self):
        rbac = _make_rbac()
        with patch.object(rbac, "get_user", return_value=None):
            with patch.object(rbac, "get_role", return_value=_make_role()):
                assert rbac.assign_role_to_user(999, RoleName.ADMIN) is False

    def test_role_not_found(self):
        rbac = _make_rbac()
        with patch.object(rbac, "get_user", return_value=_make_user()):
            with patch.object(rbac, "get_role", return_value=None):
                assert rbac.assign_role_to_user(1, RoleName.ADMIN) is False


class TestRemoveRoleFromUser:
    def test_success(self):
        rbac = _make_rbac()
        role = _make_role()
        user = _make_user(roles=[role])
        with patch.object(rbac, "get_user", return_value=user):
            with patch.object(rbac, "get_role", return_value=role):
                assert rbac.remove_role_from_user(1, RoleName.ADMIN) is True
        assert role not in user.roles
        rbac.db.commit.assert_called_once()

    def test_not_assigned(self):
        rbac = _make_rbac()
        role = _make_role()
        user = _make_user(roles=[])
        with patch.object(rbac, "get_user", return_value=user):
            with patch.object(rbac, "get_role", return_value=role):
                assert rbac.remove_role_from_user(1, RoleName.ADMIN) is True
        rbac.db.commit.assert_not_called()

    def test_user_not_found(self):
        rbac = _make_rbac()
        with patch.object(rbac, "get_user", return_value=None):
            with patch.object(rbac, "get_role", return_value=_make_role()):
                assert rbac.remove_role_from_user(999, RoleName.ADMIN) is False

    def test_role_not_found(self):
        rbac = _make_rbac()
        with patch.object(rbac, "get_user", return_value=_make_user()):
            with patch.object(rbac, "get_role", return_value=None):
                assert rbac.remove_role_from_user(1, RoleName.ADMIN) is False


class TestGetUserRoles:
    def test_user_found(self):
        rbac = _make_rbac()
        roles = [_make_role(id=1), _make_role(id=2)]
        user = _make_user(roles=roles)
        with patch.object(rbac, "get_user", return_value=user):
            assert rbac.get_user_roles(1) == roles

    def test_user_not_found(self):
        rbac = _make_rbac()
        with patch.object(rbac, "get_user", return_value=None):
            assert rbac.get_user_roles(999) == []


# ── Permission Checking ──────────────────────────────────────────────────────


class TestUserHasPermission:
    def test_superuser_always_has_permission(self):
        rbac = _make_rbac()
        user = _make_user(is_superuser=True)
        assert rbac.user_has_permission(user, PermissionName.PROJECT_READ) is True

    def test_user_with_matching_role_permission(self):
        rbac = _make_rbac()
        perm = _make_permission(name="project:read")
        role = _make_role(permissions=[perm])
        user = _make_user(roles=[role])
        assert rbac.user_has_permission(user, PermissionName.PROJECT_READ) is True

    def test_user_without_permission(self):
        rbac = _make_rbac()
        perm = _make_permission(name="project:delete")
        role = _make_role(permissions=[perm])
        user = _make_user(roles=[role])
        assert rbac.user_has_permission(user, PermissionName.PROJECT_READ) is False

    def test_user_with_no_roles(self):
        rbac = _make_rbac()
        user = _make_user(roles=[])
        assert rbac.user_has_permission(user, PermissionName.PROJECT_READ) is False


class TestUserHasAnyPermission:
    def test_has_one_of(self):
        rbac = _make_rbac()
        perm = _make_permission(name="project:read")
        role = _make_role(permissions=[perm])
        user = _make_user(roles=[role])
        assert rbac.user_has_any_permission(user, [PermissionName.PROJECT_READ, PermissionName.PROJECT_DELETE]) is True

    def test_has_none(self):
        rbac = _make_rbac()
        user = _make_user(roles=[])
        assert rbac.user_has_any_permission(user, [PermissionName.PROJECT_READ, PermissionName.PROJECT_DELETE]) is False


class TestUserHasAllPermissions:
    def test_has_all(self):
        rbac = _make_rbac()
        perm1 = _make_permission(name="project:read")
        perm2 = _make_permission(name="project:delete")
        role = _make_role(permissions=[perm1, perm2])
        user = _make_user(roles=[role])
        assert rbac.user_has_all_permissions(user, [PermissionName.PROJECT_READ, PermissionName.PROJECT_DELETE]) is True

    def test_missing_one(self):
        rbac = _make_rbac()
        perm = _make_permission(name="project:read")
        role = _make_role(permissions=[perm])
        user = _make_user(roles=[role])
        assert (
            rbac.user_has_all_permissions(user, [PermissionName.PROJECT_READ, PermissionName.PROJECT_DELETE]) is False
        )


class TestGetUserPermissions:
    def test_superuser_gets_wildcard(self):
        rbac = _make_rbac()
        user = _make_user(is_superuser=True)
        assert rbac.get_user_permissions(user) == {"*"}

    def test_normal_user_gets_role_perms(self):
        rbac = _make_rbac()
        perm1 = _make_permission(name="project:read")
        perm2 = _make_permission(name="project:write")
        role = _make_role(permissions=[perm1, perm2])
        user = _make_user(roles=[role])
        result = rbac.get_user_permissions(user)
        assert result == {"project:read", "project:write"}

    def test_user_with_no_roles(self):
        rbac = _make_rbac()
        user = _make_user(roles=[])
        assert rbac.get_user_permissions(user) == set()


# ── Project-Level Permissions ────────────────────────────────────────────────


class TestGrantProjectPermission:
    def test_grant_new(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        perm = rbac.grant_project_permission(1, 10, RoleName.EDITOR)
        rbac.db.add.assert_called_once()
        rbac.db.commit.assert_called_once()

    def test_grant_existing_updates(self):
        rbac = _make_rbac()
        existing = _make_project_permission(role="viewer")
        rbac.db.query.return_value.filter.return_value.first.return_value = existing
        perm = rbac.grant_project_permission(1, 10, RoleName.EDITOR)
        assert existing.role == RoleName.EDITOR.value
        rbac.db.commit.assert_called_once()


class TestRevokeProjectPermission:
    def test_revoke_existing(self):
        rbac = _make_rbac()
        perm = _make_project_permission()
        rbac.db.query.return_value.filter.return_value.first.return_value = perm
        assert rbac.revoke_project_permission(1, 10) is True
        rbac.db.delete.assert_called_once_with(perm)

    def test_revoke_nonexistent(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        assert rbac.revoke_project_permission(1, 10) is False


class TestGetProjectPermission:
    def test_found(self):
        rbac = _make_rbac()
        perm = _make_project_permission()
        rbac.db.query.return_value.filter.return_value.first.return_value = perm
        assert rbac.get_project_permission(1, 10) == perm

    def test_not_found(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.first.return_value = None
        assert rbac.get_project_permission(1, 10) is None


class TestCheckProjectAccess:
    def test_superuser_always_allowed(self):
        rbac = _make_rbac()
        user = _make_user(is_superuser=True)
        assert rbac.check_project_access(user, 10, RoleName.VIEWER) is True

    def test_project_permission_sufficient(self):
        rbac = _make_rbac()
        user = _make_user(is_superuser=False)
        proj_perm = _make_project_permission(role="editor")
        with patch.object(rbac, "get_project_permission", return_value=proj_perm):
            assert rbac.check_project_access(user, 10, RoleName.VIEWER) is True

    def test_project_permission_insufficient(self):
        rbac = _make_rbac()
        user = _make_user(is_superuser=False)
        proj_perm = _make_project_permission(role="viewer")
        with patch.object(rbac, "get_project_permission", return_value=proj_perm):
            assert rbac.check_project_access(user, 10, RoleName.ADMIN) is False

    def test_no_project_permission_but_global_admin(self):
        rbac = _make_rbac()
        admin_role = _make_role(name="admin")
        user = _make_user(is_superuser=False, roles=[admin_role])
        with patch.object(rbac, "get_project_permission", return_value=None):
            assert rbac.check_project_access(user, 10, RoleName.VIEWER) is True

    def test_no_project_permission_but_global_owner(self):
        rbac = _make_rbac()
        owner_role = _make_role(name="project_owner")
        user = _make_user(is_superuser=False, roles=[owner_role])
        with patch.object(rbac, "get_project_permission", return_value=None):
            assert rbac.check_project_access(user, 10, RoleName.VIEWER) is True

    def test_no_permission_at_all(self):
        rbac = _make_rbac()
        user = _make_user(is_superuser=False, roles=[])
        with patch.object(rbac, "get_project_permission", return_value=None):
            assert rbac.check_project_access(user, 10, RoleName.VIEWER) is False


class TestGetUserProjects:
    def test_returns_projects(self):
        rbac = _make_rbac()
        perms = [
            _make_project_permission(project_id=10, role="editor"),
            _make_project_permission(project_id=20, role="viewer"),
        ]
        rbac.db.query.return_value.filter.return_value.all.return_value = perms
        result = rbac.get_user_projects(1)
        assert len(result) == 2
        assert result[0]["project_id"] == 10
        assert result[0]["role"] == "editor"

    def test_no_projects(self):
        rbac = _make_rbac()
        rbac.db.query.return_value.filter.return_value.all.return_value = []
        assert rbac.get_user_projects(1) == []


# ── Convenience Functions ────────────────────────────────────────────────────


class TestGetRbacManager:
    def test_with_db(self):
        db = MagicMock()
        mgr = get_rbac_manager(db)
        assert isinstance(mgr, RBACManager)
        assert mgr.db is db

    @patch("src.audiobook_studio.auth.rbac.RBACManager")
    def test_without_db(self, MockRBAC):
        MockRBAC.return_value = "mock_mgr"
        result = get_rbac_manager(None)
        assert result == "mock_mgr"


class TestCheckPermission:
    @patch("src.audiobook_studio.auth.rbac.RBACManager")
    def test_delegates_to_rbac(self, MockRBAC):
        mock_rbac = MagicMock()
        mock_rbac.user_has_permission.return_value = True
        MockRBAC.return_value = mock_rbac
        db = MagicMock()
        user = _make_user()
        result = check_permission(user, PermissionName.PROJECT_READ, db)
        assert result is True
        mock_rbac.user_has_permission.assert_called_once_with(user, PermissionName.PROJECT_READ)


class TestRequirePermission:
    def test_decorator_returns_wrapper(self):
        @require_permission(PermissionName.PROJECT_READ)
        async def my_func():
            return "ok"

        assert callable(my_func)

    @pytest.mark.asyncio
    async def test_wrapper_calls_original(self):
        @require_permission(PermissionName.PROJECT_READ)
        async def my_func():
            return "ok"

        result = await my_func()
        assert result == "ok"


class TestRequireRole:
    def test_decorator_returns_wrapper(self):
        @require_role(RoleName.ADMIN)
        async def my_func():
            return "ok"

        assert callable(my_func)

    @pytest.mark.asyncio
    async def test_wrapper_calls_original(self):
        @require_role(RoleName.ADMIN)
        async def my_func():
            return "ok"

        result = await my_func()
        assert result == "ok"


class TestRequireProjectPermission:
    def test_decorator_returns_wrapper(self):
        @require_project_permission(RoleName.EDITOR)
        async def my_func():
            return "ok"

        assert callable(my_func)

    @pytest.mark.asyncio
    async def test_wrapper_calls_original(self):
        @require_project_permission(RoleName.EDITOR)
        async def my_func():
            return "ok"

        result = await my_func()
        assert result == "ok"

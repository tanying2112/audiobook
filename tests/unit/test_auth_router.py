"""Tests for auth router and JWT handler.

Tests cover login, registration, token refresh, and user management
endpoints with proper authentication.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from jose import jwt

from src.audiobook_studio.auth.jwt_handler import JWTHandler
from src.audiobook_studio.auth.models import PermissionName, RoleName, TokenData
from src.audiobook_studio.main import app
from src.audiobook_studio.models import Permission, Role, User


@pytest.fixture
def client():
    """Test client."""
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_db():
    """Mock database session."""
    with patch("src.audiobook_studio.auth.router.get_db") as mock:
        db = MagicMock()
        mock.return_value = iter([db])
        yield db


@pytest.fixture
def mock_user():
    """Mock user."""
    user = MagicMock(spec=User)
    user.id = 1
    user.username = "testuser"
    user.email = "test@example.com"
    user.hashed_password = "hashed_password"
    user.full_name = "Test User"
    user.is_active = True
    user.is_superuser = False
    user.created_at = datetime.now(timezone.utc)
    user.roles = []
    user.project_permissions = []
    return user


@pytest.fixture
def mock_role():
    """Mock role."""
    role = MagicMock(spec=Role)
    role.name = RoleName.USER
    return role


@pytest.fixture
def mock_permission():
    """Mock permission."""
    perm = MagicMock(spec=Permission)
    perm.name = PermissionName.PROJECT_READ
    return perm


# Mock RBAC manager
@pytest.fixture
def mock_rbac():
    """Mock RBAC manager."""
    with patch("src.audiobook_studio.auth.router.get_rbac_manager") as mock:
        rbac = MagicMock()
        mock.return_value = rbac
        yield rbac


# Mock JWT handler
@pytest.fixture
def mock_jwt():
    """Mock JWT handler functions."""
    with patch("src.audiobook_studio.auth.router.jwt_handler") as mock:
        yield mock


# Mock verify_password - patch where it's actually called (in rbac module)
@pytest.fixture
def mock_verify_password():
    """Mock verify_password function - patch at rbac module where it's called."""
    with patch("src.audiobook_studio.auth.rbac.verify_password") as mock:
        yield mock


# Mock hash_password
@pytest.fixture
def mock_hash_password():
    """Mock hash_password function."""
    with patch("src.audiobook_studio.auth.jwt_handler.hash_password") as mock:
        yield mock


class TestAuthRouter:
    """Tests for auth router endpoints."""

    def test_login_success(self, client, mock_rbac, mock_user, mock_verify_password, mock_jwt):
        """Test successful login returns access and refresh tokens."""
        mock_rbac.authenticate_user.return_value = mock_user
        mock_jwt.create_token_pair.return_value = {
            "access_token": "access_token",
            "refresh_token": "refresh_token",
            "token_type": "bearer",
            "expires_in": 1800,
        }

        response = client.post("/api/auth/login", data={"username": "testuser", "password": "testpass"})

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    def test_login_invalid_credentials(self, client, mock_rbac):
        """Test login with invalid credentials returns 401."""
        mock_rbac.authenticate_user.return_value = None

        response = client.post("/api/auth/login", data={"username": "nonexistent", "password": "wrongpass"})

        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    def test_login_invalid_password(self, client, mock_rbac, mock_user, mock_verify_password):
        """Test login with wrong password returns 401."""
        mock_verify_password.return_value = False
        mock_rbac.get_user_by_username.return_value = mock_user
        mock_rbac.authenticate_user.return_value = None

        response = client.post("/api/auth/login", data={"username": "testuser", "password": "wrongpass"})

        assert response.status_code == 401
        assert "incorrect" in response.json()["detail"].lower()

    def test_refresh_token_success(self, client, mock_jwt):
        """Test successful token refresh."""
        mock_jwt.decode_token.return_value = {
            "sub": "1",
            "username": "testuser",
            "roles": ["user"],
            "permissions": ["project:read"],
        }
        mock_jwt.refresh_access_token.return_value = "new_access_token"
        mock_jwt.create_refresh_token.return_value = "new_refresh_token"

        response = client.post("/api/auth/refresh", json={"refresh_token": "valid_refresh_token"})

        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "new_access_token"
        assert data["token_type"] == "bearer"

    def test_refresh_token_invalid(self, client, mock_jwt):
        """Test refresh with invalid token returns 401."""
        mock_jwt.decode_token.return_value = None
        mock_jwt.refresh_access_token.return_value = None

        response = client.post("/api/auth/refresh", json={"refresh_token": "invalid_token"})

        assert response.status_code == 401

    @patch("src.audiobook_studio.auth.router.get_current_superuser")
    def test_register_success(self, mock_get_superuser, client, mock_rbac, mock_hash_password, mock_user):
        """Test successful user registration."""
        mock_get_superuser.return_value = mock_user
        mock_user.is_superuser = True
        mock_rbac.get_user_by_username.return_value = None
        mock_rbac.get_user_by_email.return_value = None

        # Create a mock new user
        new_user = MagicMock()
        new_user.id = 2
        new_user.username = "newuser"
        new_user.email = "new@example.com"
        new_user.is_active = True
        new_user.created_at = datetime.now(timezone.utc)
        new_user.is_superuser = False
        new_user.roles = []
        new_user.project_permissions = []

        mock_rbac.create_user.return_value = new_user
        mock_hash_password.return_value = "hashed_password"

        response = client.post(
            "/api/auth/register", json={"username": "newuser", "email": "new@example.com", "password": "password123"}
        )

        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["email"] == "new@example.com"

    @patch("src.audiobook_studio.auth.router.get_current_superuser")
    def test_register_duplicate_username(self, mock_get_superuser, client, mock_rbac, mock_user):
        """Test registration with existing username returns 400."""
        mock_rbac.get_user_by_username.return_value = mock_user

        response = client.post(
            "/api/auth/register",
            json={"username": "testuser", "email": "different@example.com", "password": "password123"},
        )

        assert response.status_code == 400
        assert "username" in response.json()["detail"].lower()

    @patch("src.audiobook_studio.auth.router.get_current_superuser")
    def test_register_duplicate_email(self, mock_get_superuser, client, mock_rbac, mock_user):
        """Test registration with existing email returns 400."""
        mock_get_superuser.return_value = mock_user
        mock_rbac.get_user_by_email.return_value = mock_user

        response = client.post(
            "/api/auth/register",
            json={"username": "differentuser", "email": "test@example.com", "password": "password123"},
        )

        assert response.status_code == 400
        assert "email" in response.json()["detail"].lower()


class TestAuthMe:
    """Tests for /api/auth/me endpoint."""

    @patch("src.audiobook_studio.auth.router.get_current_active_user")
    def test_get_current_user_success(self, mock_get_user, client, mock_user):
        """Test getting current user info."""
        mock_get_user.return_value = mock_user

        response = client.get("/api/auth/me")

        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"

    @patch("src.audiobook_studio.auth.router.get_current_active_user")
    def test_update_current_user_success(self, mock_get_user, client, mock_user, mock_db):
        """Test updating current user info."""
        mock_get_user.return_value = mock_user

        # Need to patch get_db for the update
        with patch("src.audiobook_studio.auth.router.get_db") as mock_get_db:
            mock_db2 = MagicMock()
            mock_get_db.return_value = iter([mock_db2])
            mock_db2.commit = MagicMock()
            mock_db2.refresh = MagicMock()

            response = client.put("/api/auth/me", json={"full_name": "Updated Name", "email": "updated@example.com"})

        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Updated Name"
        assert data["email"] == "updated@example.com"


class TestAuthRoles:
    """Tests for role management endpoints."""

    @patch("src.audiobook_studio.auth.router.get_current_superuser")
    def test_create_role_success(self, mock_get_superuser, client, mock_user, mock_db):
        """Test creating a role (superuser only)."""
        mock_get_superuser.return_value = mock_user
        mock_user.is_superuser = True

        with patch("src.audiobook_studio.auth.router.get_db") as mock_get_db:
            mock_db2 = MagicMock()
            mock_get_db.return_value = iter([mock_db2])
            mock_db2.query.return_value.filter.return_value.first.return_value = None

            new_role = MagicMock()
            new_role.id = 1
            new_role.name = RoleName.EDITOR
            new_role.description = "Editor role"
            new_role.created_at = datetime.now(timezone.utc)

            mock_db2.add = MagicMock()
            mock_db2.commit = MagicMock()
            mock_db2.refresh = MagicMock(side_effect=lambda r: setattr(r, "id", 1))

            response = client.post("/api/auth/roles", json={"name": "editor", "description": "Editor role"})

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "editor"

    @patch("src.audiobook_studio.auth.router.get_current_superuser")
    def test_list_roles_success(self, mock_get_superuser, client, mock_user, mock_db):
        """Test listing roles."""
        mock_get_superuser.return_value = mock_user
        mock_user.is_superuser = True

        mock_role = MagicMock()
        mock_role.id = 1
        mock_role.name = RoleName.USER
        mock_role.description = "Basic user"
        mock_role.created_at = datetime.now(timezone.utc)

        with patch("src.audiobook_studio.auth.router.get_db") as mock_get_db:
            mock_db2 = MagicMock()
            mock_get_db.return_value = iter([mock_db2])
            mock_db2.query.return_value.all.return_value = [mock_role]

            response = client.get("/api/auth/roles")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "user"


class TestAuthUsers:
    """Tests for user management endpoints."""

    @patch("src.audiobook_studio.auth.router.get_current_superuser")
    def test_list_users_success(self, mock_get_superuser, client, mock_user, mock_db):
        """Test listing users (superuser only)."""
        mock_get_superuser.return_value = mock_user
        mock_user.is_superuser = True

        mock_user2 = MagicMock()
        mock_user2.id = 2
        mock_user2.username = "user2"
        mock_user2.email = "user2@example.com"
        mock_user2.is_active = True
        mock_user2.created_at = datetime.now(timezone.utc)
        mock_user2.is_superuser = False

        with patch("src.audiobook_studio.auth.router.get_db") as mock_get_db:
            mock_db2 = MagicMock()
            mock_get_db.return_value = iter([mock_db2])
            mock_db2.query.return_value.all.return_value = [mock_user, mock_user2]

            response = client.get("/api/auth/users")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


class TestAuthPermissions:
    """Tests for permission management endpoints."""

    @patch("src.audiobook_studio.auth.router.get_current_superuser")
    def test_assign_role_to_user(self, mock_get_superuser, client, mock_user, mock_db):
        """Test assigning role to user."""
        mock_get_superuser.return_value = mock_user
        mock_user.is_superuser = True

        with patch("src.audiobook_studio.auth.router.get_db") as mock_get_db:
            mock_db2 = MagicMock()
            mock_get_db.return_value = iter([mock_db2])
            mock_db2.query.return_value.filter.return_value.first.return_value = mock_user

            response = client.post("/api/auth/users/1/roles/editor")

        assert response.status_code == 200
        data = response.json()
        assert "success" in data or "message" in data


class TestJWTHandler:
    """Tests for JWTHandler class."""

    def test_create_access_token(self):
        """Test creating an access token."""
        handler = JWTHandler()
        token = handler.create_access_token(user_id=1, username="testuser")

        assert isinstance(token, str)
        assert len(token) > 0

        # Verify token can be decoded
        payload = handler.decode_token(token)
        assert payload["sub"] == "1"
        assert payload["username"] == "testuser"

    def test_create_refresh_token(self):
        """Test creating a refresh token."""
        handler = JWTHandler()
        token = handler.create_refresh_token(user_id=1, username="testuser")

        assert isinstance(token, str)
        assert len(token) > 0

        payload = handler.decode_token(token)
        assert payload["sub"] == "1"
        assert payload["type"] == "refresh"

    def test_decode_expired_token(self):
        """Test decoding expired token raises error."""
        handler = JWTHandler()

        # Create an expired token manually
        expired_payload = {"sub": "1", "exp": datetime.now(timezone.utc) - timedelta(hours=1), "type": "access"}
        expired_token = jwt.encode(expired_payload, handler.secret_key, algorithm=handler.algorithm)

        with pytest.raises(Exception):
            handler.decode_token(expired_token)

    def test_decode_invalid_token(self):
        """Test decoding invalid token raises error."""
        handler = JWTHandler()

        with pytest.raises(Exception):
            handler.decode_token("invalid.token.here")

    def test_token_type_validation(self):
        """Test token type validation."""
        handler = JWTHandler()

        # Create a refresh token
        refresh_token = handler.create_refresh_token(user_id=1, username="testuser")

        # Try to use it as access token - should still decode but we check type
        payload = handler.decode_token(refresh_token)
        assert payload["type"] == "refresh"

        access_token = handler.create_access_token(user_id=1, username="testuser")
        payload = handler.decode_token(access_token)
        assert payload["type"] == "access"

    def test_create_token_pair(self):
        """Test creating token pair returns both tokens."""
        handler = JWTHandler()
        tokens = handler.create_token_pair(user_id=1, username="testuser", roles=["user"], permissions=["project:read"])

        assert "access_token" in tokens
        assert "refresh_token" in tokens
        assert tokens["token_type"] == "bearer"
        assert "expires_in" in tokens

    def test_refresh_access_token(self):
        """Test refreshing access token from refresh token."""
        handler = JWTHandler()

        refresh_token = handler.create_refresh_token(user_id=1, username="testuser")
        new_access = handler.refresh_access_token(refresh_token)

        assert isinstance(new_access, str)
        assert len(new_access) > 0

        payload = handler.decode_token(new_access)
        assert payload["type"] == "access"

    def test_refresh_access_token_invalid(self):
        """Test refreshing with invalid token returns None."""
        handler = JWTHandler()

        result = handler.refresh_access_token("invalid.token.here")
        assert result is None


class TestTokenData:
    """Tests for TokenData model."""

    def test_token_data_creation(self):
        """Test TokenData can be created with required fields."""
        token_data = TokenData(username="testuser", user_id=1)
        assert token_data.username == "testuser"
        assert token_data.user_id == 1
        assert token_data.roles == []
        assert token_data.permissions == []

    def test_token_data_with_roles(self):
        """Test TokenData with roles and permissions."""
        token_data = TokenData(
            username="admin", user_id=1, roles=["admin"], permissions=["project:read", "project:write"]
        )
        assert token_data.roles == ["admin"]
        assert token_data.permissions == ["project:read", "project:write"]


class TestAuthModels:
    """Tests for auth models."""

    def test_role_name_values(self):
        """Test RoleName enum values."""
        assert RoleName.ADMIN.value == "admin"
        assert RoleName.PROJECT_OWNER.value == "project_owner"
        assert RoleName.EDITOR.value == "editor"
        assert RoleName.VIEWER.value == "viewer"
        assert RoleName.CONTRIBUTOR.value == "contributor"

    def test_permission_name_values(self):
        """Test PermissionName enum values."""
        assert PermissionName.PROJECT_READ.value == "project:read"
        assert PermissionName.PROJECT_UPDATE.value == "project:update"
        assert PermissionName.PROJECT_CREATE.value == "project:create"
        assert PermissionName.PROJECT_DELETE.value == "project:delete"


class TestAuthDependencies:
    """Tests for auth dependency functions."""

    @patch("src.audiobook_studio.auth.dependencies.get_current_user")
    def test_get_current_active_user_active(self, mock_get_user, mock_user):
        """Test get_current_active_user returns user if active."""
        import asyncio

        from src.audiobook_studio.auth.dependencies import get_current_active_user

        mock_user.is_active = True
        mock_get_user.return_value = mock_user

        async def test():
            result = await get_current_active_user(current_user=mock_user)
            assert result == mock_user

        asyncio.run(test())

    @patch("src.audiobook_studio.auth.dependencies.get_current_user")
    def test_get_current_active_user_inactive(self, mock_get_user, mock_user):
        """Test get_current_active_user raises for inactive user."""
        import asyncio

        from fastapi import HTTPException

        from src.audiobook_studio.auth.dependencies import get_current_active_user

        mock_user.is_active = False
        mock_get_user.return_value = mock_user

        async def test():
            try:
                await get_current_active_user(current_user=mock_user)
                assert False, "Should have raised HTTPException"
            except HTTPException as e:
                assert e.status_code == 400
                assert "inactive" in e.detail.lower()

        asyncio.run(test())

    @patch("src.audiobook_studio.auth.dependencies.get_current_active_user")
    def test_get_current_superuser_success(self, mock_get_active, mock_user):
        """Test get_current_superuser returns user if superuser."""
        import asyncio

        from src.audiobook_studio.auth.dependencies import get_current_superuser

        mock_user.is_superuser = True
        mock_get_active.return_value = mock_user

        async def test():
            result = await get_current_superuser(current_user=mock_user)
            assert result == mock_user

        asyncio.run(test())

    @patch("src.audiobook_studio.auth.dependencies.get_current_active_user")
    def test_get_current_superuser_not_superuser(self, mock_get_active, mock_user):
        """Test get_current_superuser raises for non-superuser."""
        import asyncio

        from fastapi import HTTPException

        from src.audiobook_studio.auth.dependencies import get_current_superuser

        mock_user.is_superuser = False
        mock_get_active.return_value = mock_user

        async def test():
            try:
                await get_current_superuser(current_user=mock_user)
                assert False, "Should have raised HTTPException"
            except HTTPException as e:
                assert e.status_code == 403
                assert "superuser" in e.detail.lower()

        asyncio.run(test())

    def test_require_permission(self):
        """Test require_permission dependency."""
        from src.audiobook_studio.auth.dependencies import require_permission
        from src.audiobook_studio.auth.models import PermissionName

        dep = require_permission(PermissionName.PROJECT_READ)
        assert dep is not None

    def test_require_role(self):
        """Test require_role dependency."""
        from src.audiobook_studio.auth.dependencies import require_role
        from src.audiobook_studio.auth.models import RoleName

        dep = require_role(RoleName.ADMIN)
        assert dep is not None

    def test_require_project_permission(self):
        """Test require_project_permission dependency."""
        from src.audiobook_studio.auth.dependencies import require_project_permission

        dep = require_project_permission(RoleName.EDITOR)
        assert dep is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

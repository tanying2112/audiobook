"""Tests for auth router endpoints - FastAPI integration tests."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.audiobook_studio.auth.router import router
from src.audiobook_studio.database import Base, get_db
from src.audiobook_studio.auth.dependencies import get_current_active_user, get_current_superuser, require_permission
from src.audiobook_studio.models.user import User as UserModel
from src.audiobook_studio.auth.models import PermissionName


# Test database fixture
@pytest.fixture
def test_db():
    """Create a test database with StaticPool for thread-safe in-memory SQLite."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # Critical for TestClient thread safety
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def client(test_db):
    """Create test client with test database."""
    app = FastAPI()
    app.include_router(router, prefix="/api")

    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_rbac_manager():
    """Mock RBAC manager for testing."""
    with patch("src.audiobook_studio.auth.router.get_rbac_manager") as mock:
        rbac = MagicMock()
        mock.return_value = rbac
        yield rbac


@pytest.fixture
def mock_jwt_handler():
    """Mock JWT handler for testing."""
    with patch("src.audiobook_studio.auth.router.jwt_handler") as mock:
        yield mock


class TestLoginEndpoint:
    """Tests for /api/auth/login endpoint."""

    def test_login_success(self, client, mock_rbac_manager, mock_jwt_handler):
        """Test successful login returns tokens."""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.is_active = True
        mock_role = MagicMock()
        mock_role.name = "admin"
        mock_user.roles = [mock_role]
        mock_rbac_manager.authenticate_user.return_value = mock_user
        mock_rbac_manager.get_user_permissions.return_value = {"project:read", "project:write"}
        
        mock_jwt_handler.create_token_pair.return_value = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "token_type": "bearer",
            "expires_in": 1800
        }

        response = client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "correct_password"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 1800

    def test_login_invalid_password(self, client, mock_rbac_manager):
        """Test login with wrong password."""
        mock_rbac_manager.authenticate_user.return_value = None
        
        response = client.post(
            "/api/auth/login",
            data={"username": "testuser", "password": "wrong_password"}
        )
        
        assert response.status_code == 401
        assert "Incorrect username or password" in response.json()["detail"]

    def test_login_user_not_found(self, client, mock_rbac_manager):
        """Test login with non-existent user."""
        mock_rbac_manager.authenticate_user.return_value = None
        
        response = client.post(
            "/api/auth/login",
            data={"username": "nonexistent", "password": "password"}
        )
        
        assert response.status_code == 401

    def test_login_inactive_user(self, client, mock_rbac_manager):
        """Test login with inactive user."""
        mock_user = MagicMock()
        mock_user.is_active = False
        mock_rbac_manager.authenticate_user.return_value = mock_user
        
        response = client.post(
            "/api/auth/login",
            data={"username": "inactive", "password": "password"}
        )
        
        assert response.status_code == 400
        assert "Inactive user" in response.json()["detail"]

    def test_login_missing_credentials(self, client):
        """Test login with missing credentials."""
        response = client.post("/api/auth/login", data={})
        assert response.status_code == 422


class TestRefreshTokenEndpoint:
    """Tests for /api/auth/refresh endpoint."""

    def test_refresh_token_success(self, client, mock_jwt_handler):
        """Test successful token refresh."""
        mock_jwt_handler.refresh_access_token.return_value = "new_access_token"
        mock_jwt_handler.decode_token.return_value = {
            "sub": "1",
            "username": "testuser",
            "roles": ["admin"],
            "permissions": ["project:read"]
        }
        mock_jwt_handler.create_refresh_token.return_value = "new_refresh_token"
        mock_jwt_handler.access_token_expire_minutes = 30

        response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": "valid_refresh_token"}
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["access_token"] == "new_access_token"
        assert data["refresh_token"] == "new_refresh_token"
        assert data["expires_in"] == 1800

    def test_refresh_token_invalid(self, client, mock_jwt_handler):
        """Test refresh with invalid token."""
        mock_jwt_handler.refresh_access_token.return_value = None
        
        response = client.post(
            "/api/auth/refresh",
            json={"refresh_token": "invalid_token"}
        )
        
        assert response.status_code == 401
        assert "Invalid or expired refresh token" in response.json()["detail"]

    def test_refresh_token_missing(self, client):
        """Test refresh without token."""
        response = client.post("/api/auth/refresh", json={})
        assert response.status_code == 422


class TestRegisterEndpoint:
    """Tests for /api/auth/register endpoint (admin only)."""

    def test_register_success(self, client, mock_rbac_manager):
        """Test successful user registration."""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "newuser"
        mock_user.email = "new@example.com"
        mock_user.full_name = "New User"
        mock_user.is_active = True
        mock_user.is_superuser = False
        mock_user.roles = []
        mock_user.hashed_password = "hashed"
        mock_rbac_manager.get_user_by_username.return_value = None
        mock_rbac_manager.get_user_by_email.return_value = None
        mock_rbac_manager.create_user.return_value = mock_user

        app = client.app
        def mock_superuser():
            user = MagicMock()
            user.is_superuser = True
            user.id = 1
            return user
        app.dependency_overrides[get_current_superuser] = mock_superuser
        
        response = client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "password123",
                "full_name": "New User"
            }
        )
        
        if get_current_superuser in app.dependency_overrides:
            del app.dependency_overrides[get_current_superuser]
        
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "newuser"
        assert data["email"] == "new@example.com"

    def test_register_duplicate_username(self, client, mock_rbac_manager):
        """Test registration with existing username."""
        mock_rbac_manager.get_user_by_username.return_value = MagicMock()
        mock_rbac_manager.get_user_by_email.return_value = None

        app = client.app
        def mock_superuser():
            user = MagicMock()
            user.is_superuser = True
            return user
        app.dependency_overrides[get_current_superuser] = mock_superuser
        
        response = client.post(
            "/api/auth/register",
            json={
                "username": "existing",
                "email": "new@example.com",
                "password": "password123"
            }
        )
        
        if get_current_superuser in app.dependency_overrides:
            del app.dependency_overrides[get_current_superuser]
        
        assert response.status_code == 400
        assert "Username already registered" in response.json()["detail"]

    def test_register_duplicate_email(self, client, mock_rbac_manager):
        """Test registration with existing email."""
        mock_rbac_manager.get_user_by_username.return_value = None
        mock_rbac_manager.get_user_by_email.return_value = MagicMock()

        app = client.app
        def mock_superuser():
            user = MagicMock()
            user.is_superuser = True
            return user
        app.dependency_overrides[get_current_superuser] = mock_superuser
        
        response = client.post(
            "/api/auth/register",
            json={
                "username": "newuser",
                "email": "existing@example.com",
                "password": "password123"
            }
        )
        
        if get_current_superuser in app.dependency_overrides:
            del app.dependency_overrides[get_current_superuser]
        
        assert response.status_code == 400
        assert "Email already registered" in response.json()["detail"]


class TestCurrentUserEndpoints:
    """Tests for /api/auth/me endpoints."""

    def test_read_current_user(self, client, mock_rbac_manager):
        """Test getting current user profile."""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.email = "test@example.com"
        mock_user.full_name = "Test User"
        mock_user.is_active = True
        mock_user.is_superuser = False
        mock_role = MagicMock()
        mock_role.name = "admin"
        mock_user.roles = [mock_role]
        mock_user.hashed_password = "hashed"
        mock_user.created_at = "2024-01-01T00:00:00"
        
        mock_rbac_manager.get_user_permissions.return_value = {"project:read"}
        mock_rbac_manager.get_user_project_permissions.return_value = []

        app = client.app
        def mock_active_user():
            return mock_user
        app.dependency_overrides[get_current_active_user] = mock_active_user
        
        with patch("src.audiobook_studio.auth.router.UserOut.from_orm") as mock_from_orm:
            mock_user_out = MagicMock()
            mock_user_out.id = 1
            mock_user_out.username = "testuser"
            mock_user_out.email = "test@example.com"
            mock_user_out.full_name = "Test User"
            mock_user_out.is_active = True
            mock_user_out.is_superuser = False
            mock_user_out.roles = ["admin"]
            mock_user_out.project_permissions = []
            mock_user_out.created_at = "2024-01-01T00:00:00"
            mock_user_out.model_dump.return_value = {
                "id": 1,
                "username": "testuser",
                "email": "test@example.com",
                "full_name": "Test User",
                "is_active": True,
                "is_superuser": False,
                "roles": ["admin"],
                "project_permissions": [],
                "created_at": "2024-01-01T00:00:00"
            }
            mock_from_orm.return_value = mock_user_out
            
            response = client.get("/api/auth/me")
        
        if get_current_active_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_active_user]
        
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["email"] == "test@example.com"

    def test_update_current_user(self, client, mock_rbac_manager):
        """Test updating current user profile."""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.email = "test@example.com"
        mock_user.full_name = "Updated Name"
        mock_user.is_active = True
        mock_user.is_superuser = False
        mock_user.roles = []
        mock_user.hashed_password = "hashed"
        
        mock_rbac_manager.update_user.return_value = mock_user

        app = client.app
        def mock_active_user():
            return mock_user
        app.dependency_overrides[get_current_active_user] = mock_active_user
        
        response = client.put(
            "/api/auth/me",
            json={"full_name": "Updated Name"}
        )
        
        if get_current_active_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_active_user]
        
        assert response.status_code == 200
        data = response.json()
        assert data["full_name"] == "Updated Name"


class TestAdminUserEndpoints:
    """Tests for admin user management endpoints."""

    def test_list_users(self, test_db, mock_rbac_manager):
        """Test listing all users (admin)."""
        # Create real user objects in test_db
        user1 = UserModel(
            id=1, username="user1", email="u1@test.com", full_name="User 1",
            is_active=True, is_superuser=False, hashed_password="hash"
        )
        user2 = UserModel(
            id=2, username="user2", email="u2@test.com", full_name="User 2",
            is_active=True, is_superuser=False, hashed_password="hash"
        )
        test_db.add_all([user1, user2])
        test_db.commit()

        # Create a fresh app without the client fixture's get_db override
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from src.audiobook_studio.database import get_db
        
        app = FastAPI()
        app.include_router(router, prefix="/api")
        
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users" and route.methods == {"GET"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        app.dependency_overrides[get_db] = lambda: test_db
        
        with TestClient(app) as client:
            response = client.get("/api/auth/users")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        if get_db in app.dependency_overrides:
            del app.dependency_overrides[get_db]
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_get_user(self, client, mock_rbac_manager):
        """Test getting user by ID (admin)."""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.email = "test@example.com"
        mock_user.full_name = "Test User"
        mock_user.is_active = True
        mock_user.is_superuser = False
        mock_user.roles = []
        mock_user.hashed_password = "hashed"
        mock_rbac_manager.get_user.return_value = mock_user

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}" and route.methods == {"GET"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.get("/api/auth/users/1")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"

    def test_get_user_not_found(self, client, mock_rbac_manager):
        """Test getting non-existent user."""
        mock_rbac_manager.get_user.return_value = None

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}" and route.methods == {"GET"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.get("/api/auth/users/999")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]


class TestRoleEndpoints:
    """Tests for role management endpoints."""

    def test_create_role(self, client, mock_rbac_manager):
        """Test creating a new role."""
        mock_role = MagicMock()
        mock_role.id = 1
        mock_role.name = "admin"
        mock_role.description = "Admin role"
        mock_rbac_manager.create_role.return_value = mock_role

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/roles" and route.methods == {"POST"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.post(
            "/api/auth/roles",
            params={"name": "admin", "description": "Admin role"}
        )
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "admin"

    def test_list_roles(self, client, mock_rbac_manager):
        """Test listing all roles."""
        mock_roles = [
            MagicMock(id=1, name="admin", description="Admin", permissions=[]),
            MagicMock(id=2, name="editor", description="Editor", permissions=[]),
        ]
        mock_rbac_manager.get_all_roles.return_value = mock_roles

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/roles" and route.methods == {"GET"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.get("/api/auth/roles")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_assign_permission_to_role(self, client, mock_rbac_manager):
        """Test assigning permission to role."""
        mock_rbac_manager.assign_permission_to_role.return_value = True

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/roles/{role_name}/permissions" and route.methods == {"POST"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.post(
            "/api/auth/roles/admin/permissions",
            params={"permission_name": "project:read"}
        )
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        assert "assigned to role" in response.json()["message"]


class TestInitRBACEndpoint:
    """Test for /api/auth/init-rbac endpoint."""

    def test_initialize_rbac(self, client):
        """Test RBAC initialization."""
        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/init-rbac" and route.methods == {"POST"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        with patch("src.audiobook_studio.auth.rbac.init_rbac") as mock_init:
            response = client.post("/api/auth/init-rbac")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        assert "RBAC initialized successfully" in response.json()["message"]


class TestAuthEdgeCases:
    """Test edge cases and error conditions."""

    def test_login_with_special_characters(self, client, mock_rbac_manager, mock_jwt_handler):
        """Test login with special characters in username."""
        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "test@user"
        mock_user.is_active = True
        mock_user.roles = []
        mock_rbac_manager.authenticate_user.return_value = mock_user
        mock_rbac_manager.get_user_permissions.return_value = set()
        mock_jwt_handler.create_token_pair.return_value = {
            "access_token": "token", "refresh_token": "refresh",
            "token_type": "bearer", "expires_in": 1800
        }

        response = client.post(
            "/api/auth/login",
            data={"username": "test@user", "password": "pass!@#$%"}
        )
        
        assert response.status_code == 200


class TestAdminUserEndpointsExtended:
    """Additional tests for admin user management endpoints to boost coverage."""

    def test_update_user_success(self, client, mock_rbac_manager):
        """Test updating user by admin."""
        from src.audiobook_studio.auth.models import UserOut
        from datetime import datetime

        mock_user = MagicMock()
        mock_user.id = 1
        mock_user.username = "testuser"
        mock_user.email = "test@example.com"
        mock_user.full_name = "Updated Name"
        mock_user.is_active = True
        mock_user.is_superuser = False
        mock_user.roles = []
        mock_user.hashed_password = "hashed"
        mock_rbac_manager.get_user.return_value = mock_user
        mock_rbac_manager.update_user.return_value = mock_user

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user

        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}" and route.methods == {"PUT"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break

        app.dependency_overrides[admin_dep] = mock_admin_user

        # Create a real UserOut instance instead of mocking from_orm
        user_out = UserOut(
            id=1,
            username="testuser",
            email="test@example.com",
            full_name="Updated Name",
            is_active=True,
            is_superuser=False,
            roles=[],
            project_permissions=[],
            created_at=datetime(2024, 1, 1, 0, 0, 0),
        )
        with patch("src.audiobook_studio.auth.router.UserOut.from_orm", return_value=user_out) as mock_from_orm:

            response = client.put(
                "/api/auth/users/1",
                json={"full_name": "Updated Name"}
            )

        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]

        assert response.status_code == 200

    def test_update_user_not_found(self, client, mock_rbac_manager):
        """Test updating non-existent user."""
        mock_rbac_manager.get_user.return_value = None

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}" and route.methods == {"PUT"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.put(
            "/api/auth/users/999",
            json={"full_name": "Updated Name"}
        )
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]

    def test_delete_user_success(self, client, mock_rbac_manager):
        """Test deleting user by admin."""
        mock_rbac_manager.delete_user.return_value = True

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            user.id = 2  # Different from user being deleted
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}" and route.methods == {"DELETE"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.delete("/api/auth/users/1")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        assert "deleted successfully" in response.json()["message"]

    def test_delete_user_self(self, client, mock_rbac_manager):
        """Test admin cannot delete themselves."""
        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            user.id = 1  # Same as user being deleted
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}" and route.methods == {"DELETE"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.delete("/api/auth/users/1")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 400
        assert "Cannot delete yourself" in response.json()["detail"]

    def test_delete_user_not_found(self, client, mock_rbac_manager):
        """Test deleting non-existent user."""
        mock_rbac_manager.delete_user.return_value = False

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            user.id = 2
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}" and route.methods == {"DELETE"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.delete("/api/auth/users/999")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]


class TestRoleEndpointsExtended:
    """Additional tests for role management endpoints."""

    def test_assign_permission_to_role_not_found(self, client, mock_rbac_manager):
        """Test assigning permission to non-existent role."""
        mock_rbac_manager.assign_permission_to_role.return_value = False

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user

        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/roles/{role_name}/permissions" and route.methods == {"POST"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break

        app.dependency_overrides[admin_dep] = mock_admin_user

        # Use valid enum value but mock returns False (simulates not found)
        response = client.post(
            "/api/auth/roles/admin/permissions",
            params={"permission_name": "project:read"}
        )

        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]

        assert response.status_code == 400
        assert "Role or permission not found" in response.json()["detail"]


class TestUserRoleEndpoints:
    """Tests for user role assignment endpoints."""

    def test_assign_role_to_user_success(self, client, mock_rbac_manager):
        """Test assigning role to user."""
        mock_rbac_manager.assign_role_to_user.return_value = True

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}/roles/{role_name}" and route.methods == {"POST"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.post(
            "/api/auth/users/1/roles/admin",
        )
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        assert "assigned to user" in response.json()["message"]

    def test_assign_role_to_user_not_found(self, client, mock_rbac_manager):
        """Test assigning role to non-existent user/role."""
        mock_rbac_manager.assign_role_to_user.return_value = False

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user

        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}/roles/{role_name}" and route.methods == {"POST"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break

        app.dependency_overrides[admin_dep] = mock_admin_user

        # Use valid enum value but mock returns False (simulates not found)
        response = client.post(
            "/api/auth/users/999/roles/admin",
        )

        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]

        assert response.status_code == 400
        assert "User or role not found" in response.json()["detail"]

    def test_remove_role_from_user_success(self, client, mock_rbac_manager):
        """Test removing role from user."""
        mock_rbac_manager.remove_role_from_user.return_value = True

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}/roles/{role_name}" and route.methods == {"DELETE"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.delete("/api/auth/users/1/roles/admin")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        assert "removed from user" in response.json()["message"]

    def test_remove_role_from_user_not_found(self, client, mock_rbac_manager):
        """Test removing non-existent role from user."""
        mock_rbac_manager.remove_role_from_user.return_value = False

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user

        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/users/{user_id}/roles/{role_name}" and route.methods == {"DELETE"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break

        app.dependency_overrides[admin_dep] = mock_admin_user

        # Use valid enum value but mock returns False (simulates not found)
        response = client.delete("/api/auth/users/999/roles/admin")

        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]

        assert response.status_code == 400
        assert "User or role not found" in response.json()["detail"]


class TestProjectPermissionEndpoints:
    """Tests for project permission endpoints."""

    def test_grant_project_permission(self, client, mock_rbac_manager):
        """Test granting project permission."""
        mock_perm = MagicMock()
        mock_perm.id = 1
        mock_perm.user_id = 1
        mock_perm.project_id = 1
        mock_perm.role = "editor"
        mock_rbac_manager.grant_project_permission.return_value = mock_perm

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/projects/{project_id}/permissions" and route.methods == {"POST"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.post(
            "/api/auth/projects/1/permissions",
            params={"user_id": 1, "role": "editor"}
        )
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        data = response.json()
        assert data["project_id"] == 1
        assert data["user_id"] == 1
        assert data["role"] == "editor"

    def test_revoke_project_permission_success(self, client, mock_rbac_manager):
        """Test revoking project permission."""
        mock_rbac_manager.revoke_project_permission.return_value = True

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/projects/{project_id}/permissions/{user_id}" and route.methods == {"DELETE"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.delete("/api/auth/projects/1/permissions/1")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 200
        assert "revoked" in response.json()["message"]

    def test_revoke_project_permission_not_found(self, client, mock_rbac_manager):
        """Test revoking non-existent project permission."""
        mock_rbac_manager.revoke_project_permission.return_value = False

        app = client.app
        def mock_admin_user():
            user = MagicMock()
            user.is_superuser = True
            user.is_active = True
            return user
        
        admin_dep = None
        for route in router.routes:
            if route.path == "/auth/projects/{project_id}/permissions/{user_id}" and route.methods == {"DELETE"}:
                for dep in route.dependant.dependencies:
                    if "permission_checker" in str(dep.call):
                        admin_dep = dep.call
                        break
        
        app.dependency_overrides[admin_dep] = mock_admin_user
        
        response = client.delete("/api/auth/projects/1/permissions/999")
        
        if admin_dep in app.dependency_overrides:
            del app.dependency_overrides[admin_dep]
        
        assert response.status_code == 404
        assert "Permission not found" in response.json()["detail"]


class TestListProjectPermissions:
    """Tests for listing project permissions."""

    def test_list_project_permissions_success(self, client, test_db, mock_rbac_manager):
        """Test listing project permissions with access."""
        from src.audiobook_studio.models.user import User as UserModel, ProjectPermission
        from datetime import datetime, timezone

        mock_rbac_manager.check_project_access.return_value = True

        # Create test users in the database
        user1 = UserModel(
            id=1,
            username="user1",
            email="user1@example.com",
            hashed_password="hash",
            is_active=True,
            is_superuser=False,
        )
        user2 = UserModel(
            id=2,
            username="user2",
            email="user2@example.com",
            hashed_password="hash",
            is_active=True,
            is_superuser=False,
        )
        test_db.add_all([user1, user2])
        test_db.commit()

        # Create project permissions in the database
        perm1 = ProjectPermission(user_id=1, project_id=1, role="editor")
        perm2 = ProjectPermission(user_id=2, project_id=1, role="viewer")
        test_db.add_all([perm1, perm2])
        test_db.commit()

        app = client.app
        def mock_active_user():
            user = MagicMock()
            user.id = 1
            user.is_active = True
            return user
        app.dependency_overrides[get_current_active_user] = mock_active_user

        response = client.get("/api/auth/projects/1/permissions")

        if get_current_active_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_active_user]

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_list_project_permissions_access_denied(self, client, mock_rbac_manager):
        """Test listing project permissions without access."""
        mock_rbac_manager.check_project_access.return_value = False

        app = client.app
        def mock_active_user():
            user = MagicMock()
            user.id = 1
            user.is_active = True
            return user
        app.dependency_overrides[get_current_active_user] = mock_active_user
        
        response = client.get("/api/auth/projects/1/permissions")
        
        if get_current_active_user in app.dependency_overrides:
            del app.dependency_overrides[get_current_active_user]
        
        assert response.status_code == 403
        assert "Access denied" in response.json()["detail"]

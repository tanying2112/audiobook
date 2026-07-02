"""Tests for auth dependencies - FastAPI dependency injection tests."""

import pytest
from datetime import timedelta
from unittest.mock import MagicMock, patch
from fastapi import FastAPI, HTTPException
from fastapi.security import SecurityScopes
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from jose import JWTError

from src.audiobook_studio.auth.dependencies import (
    get_current_user,
    get_current_active_user,
    get_current_superuser,
    require_permission,
    require_role,
    require_project_permission,
    get_rbac_manager,
    authenticate_user,
    oauth2_scheme,
)
from src.audiobook_studio.auth.jwt_handler import jwt_handler
from src.audiobook_studio.auth.models import PermissionName, RoleName, TokenData
from src.audiobook_studio.auth.rbac import RBACManager
from src.audiobook_studio.database import Base, get_db
from src.audiobook_studio.models.user import User as UserModel


# Test database fixture with StaticPool for thread safety
@pytest.fixture
def test_db():
    """Create a test database with StaticPool for thread-safe in-memory SQLite."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
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
def mock_user():
    """Create a mock user."""
    user = MagicMock(spec=UserModel)
    user.id = 1
    user.username = "testuser"
    user.email = "test@example.com"
    user.full_name = "Test User"
    user.is_active = True
    user.is_superuser = False
    user.hashed_password = "hashed_password"
    user.roles = []
    user.created_at = "2024-01-01T00:00:00"
    return user


@pytest.fixture
def mock_superuser():
    """Create a mock superuser."""
    user = MagicMock(spec=UserModel)
    user.id = 1
    user.username = "admin"
    user.email = "admin@example.com"
    user.full_name = "Admin User"
    user.is_active = True
    user.is_superuser = True
    user.hashed_password = "hashed_password"
    user.roles = [MagicMock(name="admin")]
    user.created_at = "2024-01-01T00:00:00"
    return user


@pytest.fixture
def mock_rbac_manager():
    """Mock RBAC manager."""
    with patch("src.audiobook_studio.auth.dependencies.RBACManager") as mock:
        rbac = MagicMock()
        mock.return_value = rbac
        yield rbac


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_get_current_user_success(self, test_db, mock_user, mock_rbac_manager):
        """Test successful user retrieval from valid token."""
        # Create a valid token
        token = jwt_handler.create_token_pair(
            user_id=1,
            username="testuser",
            roles=["admin"],
            permissions=["project:read", "project:write"]
        )["access_token"]
        
        # Mock the database query to return our user
        with patch.object(test_db, 'query') as mock_query:
            mock_query.return_value.filter.return_value.first.return_value = mock_user
            
            # Call the dependency
            security_scopes = SecurityScopes(scopes=[])
            result = await get_current_user(
                security_scopes=security_scopes,
                token=token,
                db=test_db
            )
            
            assert result == mock_user
            mock_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_current_user_invalid_token(self, test_db):
        """Test rejection of invalid token."""
        security_scopes = SecurityScopes(scopes=[])
        
        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                security_scopes=security_scopes,
                token="invalid.token.here",
                db=test_db
            )
        
        assert exc_info.value.status_code == 401
        assert "Could not validate credentials" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_user_expired_token(self, test_db):
        """Test rejection of expired token."""
        # Create an expired token (we can't easily create one, so mock decode)
        with patch.object(jwt_handler, 'decode_token', side_effect=JWTError("Expired")):
            security_scopes = SecurityScopes(scopes=[])
            
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    security_scopes=security_scopes,
                    token="expired.token.here",
                    db=test_db
                )
            
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_missing_user(self, test_db, mock_rbac_manager):
        """Test rejection when user not found in database."""
        token = jwt_handler.create_token_pair(
            user_id=999,
            username="nonexistent",
            roles=[],
            permissions=[]
        )["access_token"]
        
        with patch.object(test_db, 'query') as mock_query:
            mock_query.return_value.filter.return_value.first.return_value = None
            
            security_scopes = SecurityScopes(scopes=[])
            
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    security_scopes=security_scopes,
                    token=token,
                    db=test_db
                )
            
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_current_user_scope_check_fail(self, test_db, mock_user):
        """Test scope check failure."""
        token = jwt_handler.create_token_pair(
            user_id=1,
            username="testuser",
            roles=[],
            permissions=["project:read"]  # Missing admin scope
        )["access_token"]
        
        with patch.object(test_db, 'query') as mock_query:
            mock_query.return_value.filter.return_value.first.return_value = mock_user
            
            security_scopes = SecurityScopes(scopes=["admin"])
            
            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(
                    security_scopes=security_scopes,
                    token=token,
                    db=test_db
                )
            
            assert exc_info.value.status_code == 403
            assert "Not enough permissions" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_get_current_user_scope_check_pass_with_role(self, test_db, mock_user):
        """Test scope check passes with admin role."""
        token = jwt_handler.create_token_pair(
            user_id=1,
            username="testuser",
            roles=["admin"],
            permissions=["project:read"]
        )["access_token"]
        
        with patch.object(test_db, 'query') as mock_query:
            mock_query.return_value.filter.return_value.first.return_value = mock_user
            
            security_scopes = SecurityScopes(scopes=["admin"])
            
            result = await get_current_user(
                security_scopes=security_scopes,
                token=token,
                db=test_db
            )
            
            assert result == mock_user


class TestGetCurrentActiveUser:
    """Tests for get_current_active_user dependency."""

    @pytest.mark.asyncio
    async def test_get_current_active_user_success(self, mock_user):
        """Test active user passes through."""
        result = await get_current_active_user(current_user=mock_user)
        assert result == mock_user

    @pytest.mark.asyncio
    async def test_get_current_active_user_inactive(self, mock_user):
        """Test inactive user raises 400."""
        mock_user.is_active = False
        
        with pytest.raises(HTTPException) as exc_info:
            await get_current_active_user(current_user=mock_user)
        
        assert exc_info.value.status_code == 400
        assert "Inactive user" in exc_info.value.detail


class TestGetCurrentSuperuser:
    """Tests for get_current_superuser dependency."""

    @pytest.mark.asyncio
    async def test_get_current_superuser_success(self, mock_superuser):
        """Test superuser passes through."""
        result = await get_current_superuser(current_user=mock_superuser)
        assert result == mock_superuser

    @pytest.mark.asyncio
    async def test_get_current_superuser_not_superuser(self, mock_user):
        """Test non-superuser raises 403."""
        with pytest.raises(HTTPException) as exc_info:
            await get_current_superuser(current_user=mock_user)
        
        assert exc_info.value.status_code == 403
        assert "Superuser access required" in exc_info.value.detail


class TestRequirePermission:
    """Tests for require_permission dependency factory."""

    @pytest.mark.asyncio
    async def test_require_permission_granted(self, test_db, mock_user, mock_rbac_manager):
        """Test permission granted when user has permission."""
        mock_rbac_manager.user_has_permission.return_value = True
        
        permission_dep = require_permission(PermissionName.PROJECT_READ)
        result = await permission_dep(current_user=mock_user, db=test_db)
        
        assert result == mock_user
        mock_rbac_manager.user_has_permission.assert_called_once_with(mock_user, PermissionName.PROJECT_READ)

    @pytest.mark.asyncio
    async def test_require_permission_denied(self, test_db, mock_user, mock_rbac_manager):
        """Test permission denied raises 403."""
        mock_rbac_manager.user_has_permission.return_value = False
        
        permission_dep = require_permission(PermissionName.ADMIN_USERS)
        
        with pytest.raises(HTTPException) as exc_info:
            await permission_dep(current_user=mock_user, db=test_db)
        
        assert exc_info.value.status_code == 403
        assert "Permission denied" in exc_info.value.detail


class TestRequireRole:
    """Tests for require_role dependency factory."""

    @pytest.mark.asyncio
    async def test_require_role_granted(self, mock_user):
        """Test role granted when user has role."""
        mock_user.has_role.return_value = True
        
        role_dep = require_role(RoleName.ADMIN)
        result = await role_dep(current_user=mock_user)
        
        assert result == mock_user
        mock_user.has_role.assert_called_once_with(RoleName.ADMIN)

    @pytest.mark.asyncio
    async def test_require_role_denied(self, mock_user):
        """Test role denied raises 403."""
        mock_user.has_role.return_value = False
        
        role_dep = require_role(RoleName.ADMIN)
        
        with pytest.raises(HTTPException) as exc_info:
            await role_dep(current_user=mock_user)
        
        assert exc_info.value.status_code == 403
        assert "Role required" in exc_info.value.detail


class TestRequireProjectPermission:
    """Tests for require_project_permission dependency factory."""

    @pytest.mark.asyncio
    async def test_require_project_permission_granted(self, test_db, mock_user, mock_rbac_manager):
        """Test project permission granted."""
        mock_rbac_manager.check_project_access.return_value = True
        
        project_perm_dep = require_project_permission(RoleName.EDITOR)
        result = await project_perm_dep(project_id=1, current_user=mock_user, db=test_db)
        
        assert result == mock_user
        mock_rbac_manager.check_project_access.assert_called_once_with(mock_user, 1, RoleName.EDITOR)

    @pytest.mark.asyncio
    async def test_require_project_permission_denied(self, test_db, mock_user, mock_rbac_manager):
        """Test project permission denied raises 403."""
        mock_rbac_manager.check_project_access.return_value = False
        
        project_perm_dep = require_project_permission(RoleName.ADMIN)
        
        with pytest.raises(HTTPException) as exc_info:
            await project_perm_dep(project_id=1, current_user=mock_user, db=test_db)
        
        assert exc_info.value.status_code == 403
        assert "Project access denied" in exc_info.value.detail


class TestGetRBACManager:
    """Tests for get_rbac_manager dependency."""

    def test_get_rbac_manager(self, test_db):
        """Test RBAC manager creation."""
        rbac = get_rbac_manager(db=test_db)
        assert isinstance(rbac, RBACManager)
        assert rbac.db == test_db


class TestAuthenticateUser:
    """Tests for authenticate_user dependency."""

    @pytest.mark.asyncio
    async def test_authenticate_user_success(self, test_db, mock_user, mock_rbac_manager):
        """Test successful authentication."""
        mock_rbac_manager.authenticate_user.return_value = mock_user
        
        form_data = MagicMock()
        form_data.username = "testuser"
        form_data.password = "correct_password"
        
        result = await authenticate_user(form_data=form_data, db=test_db)
        
        assert result == mock_user
        mock_rbac_manager.authenticate_user.assert_called_once_with("testuser", "correct_password")

    @pytest.mark.asyncio
    async def test_authenticate_user_failure(self, test_db, mock_rbac_manager):
        """Test failed authentication raises 401."""
        mock_rbac_manager.authenticate_user.return_value = None
        
        form_data = MagicMock()
        form_data.username = "testuser"
        form_data.password = "wrong_password"
        
        with pytest.raises(HTTPException) as exc_info:
            await authenticate_user(form_data=form_data, db=test_db)
        
        assert exc_info.value.status_code == 401
        assert "Incorrect username or password" in exc_info.value.detail


class TestOAuth2Scheme:
    """Tests for OAuth2 scheme configuration."""

    def test_oauth2_scheme_config(self):
        """Test OAuth2 scheme is properly configured."""
        assert oauth2_scheme.model.flows.password.tokenUrl == "/api/auth/login"
        scopes = oauth2_scheme.model.flows.password.scopes
        assert "admin" in scopes
        assert "project:read" in scopes
        assert "project:write" in scopes
        assert "golden:contribute" in scopes


class TestDependencyIntegration:
    """Integration tests using TestClient."""

    @pytest.fixture
    def app(self, test_db):
        """Create test app with auth router."""
        from src.audiobook_studio.auth.router import router
        
        app = FastAPI()
        app.include_router(router, prefix="/api")
        
        def override_get_db():
            try:
                yield test_db
            finally:
                pass
        
        app.dependency_overrides[get_db] = override_get_db
        return app

    @pytest.mark.asyncio
    async def test_protected_endpoint_requires_auth(self, app, test_db):
        """Test that protected endpoints require authentication."""
        client = TestClient(app)
        
        # Try to access /api/auth/me without auth
        response = client.get("/api/auth/me")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_admin_endpoint_requires_admin(self, app, test_db, mock_user):
        """Test admin endpoint requires admin permission."""
        client = TestClient(app)
        
        # Mock get_current_active_user to return regular user
        from src.audiobook_studio.auth.dependencies import get_current_active_user
        
        def mock_active_user():
            return mock_user
        
        app.dependency_overrides[get_current_active_user] = mock_active_user
        
        try:
            response = client.get("/api/auth/users")
            # Should fail with 403 because user is not admin
            assert response.status_code == 403
        finally:
            if get_current_active_user in app.dependency_overrides:
                del app.dependency_overrides[get_current_active_user]

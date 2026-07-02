"""Authentication and Authorization module for Audiobook Studio.

Provides JWT-based authentication with Role-Based Access Control (RBAC)
and project-level permission isolation.
"""

# Dependencies
from .dependencies import authenticate_user, get_current_active_user, get_current_superuser, get_current_user
from .dependencies import get_rbac_manager as get_rbac_dep
from .dependencies import require_permission, require_project_permission, require_role

# JWT handler
from .jwt_handler import (
    JWTHandler,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

# Pydantic models for API
from .models import (
    PermissionBase,
    PermissionName,
    PermissionOut,
    ProjectPermissionBase,
    ProjectPermissionCreate,
    ProjectPermissionOut,
    RoleBase,
    RoleCreate,
    RoleName,
    RoleOut,
    Token,
    TokenData,
    UserBase,
    UserCreate,
    UserOut,
    UserUpdate,
)

# RBAC
from .rbac import RBACManager, get_rbac_manager

__all__ = [
    # Models
    "UserBase",
    "UserCreate",
    "UserUpdate",
    "UserOut",
    "RoleName",
    "PermissionName",
    "RoleBase",
    "RoleCreate",
    "RoleOut",
    "PermissionBase",
    "PermissionOut",
    "ProjectPermissionBase",
    "ProjectPermissionCreate",
    "ProjectPermissionOut",
    "Token",
    "TokenData",
    # JWT
    "JWTHandler",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "verify_password",
    # RBAC
    "RBACManager",
    "get_rbac_manager",
    # Dependencies
    "get_current_user",
    "get_current_active_user",
    "get_current_superuser",
    "require_permission",
    "require_role",
    "require_project_permission",
    "get_rbac_dep",
    "authenticate_user",
]

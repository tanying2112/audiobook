"""Authentication API router for Audiobook Studio.

Provides endpoints for login, registration, token refresh, and user management.
"""

from datetime import timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from src.audiobook_studio.auth.dependencies import (
    authenticate_user,
    get_current_active_user,
    get_current_superuser,
    get_current_user,
    require_permission,
    require_role,
    _invalidate_user_cache,
)
from src.audiobook_studio.auth.jwt_handler import jwt_handler

# Pydantic models
from src.audiobook_studio.auth.models import (
    PermissionName,
    ProjectPermissionOut,
    RoleName,
    Token,
    UserCreate,
    UserOut,
    UserUpdate,
)
from src.audiobook_studio.auth.rbac import RBACManager, get_rbac_manager
from src.audiobook_studio.database import get_db

# SQLAlchemy models
from src.audiobook_studio.models.user import ProjectPermission as ProjectPermissionModel
from src.audiobook_studio.models.user import User as UserModel

router = APIRouter(prefix="/auth", tags=["authentication"])


# Request/Response models
class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class MessageResponse(BaseModel):
    message: str


# Auth endpoints
@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate user and return access/refresh tokens."""
    rbac = get_rbac_manager(db)
    user = rbac.authenticate_user(form_data.username, form_data.password)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    # Get user permissions from roles
    permissions = rbac.get_user_permissions(user)
    roles = [role.name for role in user.roles]

    tokens = jwt_handler.create_token_pair(
        user_id=user.id,
        username=user.username,
        roles=roles,
        permissions=list(permissions),
    )

    return TokenResponse(**tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """Refresh access token using refresh token."""
    new_access_token = jwt_handler.refresh_access_token(request.refresh_token)

    if not new_access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Decode refresh token to get user info
    payload = jwt_handler.decode_token(request.refresh_token)
    user_id = int(payload.get("sub", 0))
    username = payload.get("username", "")
    roles = payload.get("roles", [])
    permissions = payload.get("permissions", [])

    new_refresh_token = jwt_handler.create_refresh_token(user_id, username)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=jwt_handler.access_token_expire_minutes * 60,
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: UserModel = Depends(get_current_superuser),
):
    """Register a new user (admin only)."""
    rbac = get_rbac_manager(db)

    # Check if user already exists
    if rbac.get_user_by_username(user_data.username):
        raise HTTPException(status_code=400, detail="Username already registered")

    if rbac.get_user_by_email(user_data.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    user = rbac.create_user(
        email=user_data.email,
        username=user_data.username,
        password=user_data.password,
        full_name=user_data.full_name,
    )

    # Construct UserOut manually to avoid from_attributes issues with roles relationship
    user_data_dict = {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at,
        "roles": [role.name for role in user.roles],
        "project_permissions": [],
    }
    return UserOut.model_validate(user_data_dict)


@router.get("/me", response_model=UserOut)
async def read_current_user(
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get current user profile."""
    rbac = get_rbac_manager(db)
    permissions = rbac.get_user_permissions(current_user)
    roles = [role.name for role in current_user.roles]
    project_perms = rbac.get_user_project_permissions(current_user.id)

    # Convert project permissions to output format
    project_perms_out = []
    for p in project_perms:
        project_perms_out.append(
            ProjectPermissionOut(
                id=p.id,
                user_id=p.user_id,
                project_id=p.project_id,
                role=p.role,
                created_at=p.created_at,
                granted_by=p.granted_by,
                username=current_user.username,
            )
        )

    # Construct UserOut manually to avoid from_attributes issues with roles relationship
    user_data = {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "full_name": current_user.full_name,
        "is_active": current_user.is_active,
        "is_superuser": current_user.is_superuser,
        "created_at": current_user.created_at,
        "roles": roles,
        "project_permissions": project_perms_out,
    }
    return UserOut.model_validate(user_data)


@router.put("/me", response_model=UserOut)
async def update_current_user(
    user_update: UserUpdate,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Update current user profile."""
    rbac = get_rbac_manager(db)

    update_data = user_update.model_dump(exclude_unset=True)
    user = rbac.update_user(current_user, **update_data)

    # Invalidate cache after update
    await _invalidate_user_cache(current_user.id)

    # Construct UserOut manually to avoid from_attributes issues with roles relationship
    user_data = {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at,
        "roles": [role.name for role in user.roles],
        "project_permissions": [],
    }
    return UserOut.model_validate(user_data)


# Admin endpoints
@router.get("/users", response_model=List[UserOut])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """List all users (admin only)."""
    users = db.query(UserModel).offset(skip).limit(limit).all()
    return [
        UserOut.model_validate(
            {
                "id": u.id,
                "email": u.email,
                "username": u.username,
                "full_name": u.full_name,
                "is_active": u.is_active,
                "is_superuser": u.is_superuser,
                "created_at": u.created_at,
                "roles": [role.name for role in u.roles],
                "project_permissions": [],
            }
        )
        for u in users
    ]


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(
    user_id: int,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """Get user by ID (admin only)."""
    rbac = get_rbac_manager(db)
    user = rbac.get_user(user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Construct UserOut manually to avoid from_attributes issues with roles relationship
    user_data = {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "created_at": user.created_at,
        "roles": [role.name for role in user.roles],
        "project_permissions": [],
    }
    return UserOut.model_validate(user_data)


@router.put("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: int,
    user_update: UserUpdate,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """Update user (admin only)."""
    rbac = get_rbac_manager(db)
    user = rbac.get_user(user_id)

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = user_update.model_dump(exclude_unset=True)
    user = rbac.update_user(user, **update_data)

    # Invalidate cache after update
    await _invalidate_user_cache(user_id)

    return UserOut.from_orm(user)


@router.delete("/users/{user_id}", response_model=MessageResponse)
async def delete_user(
    user_id: int,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """Delete user (admin only)."""
    rbac = get_rbac_manager(db)

    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    success = rbac.delete_user(user_id)
    if not success:
        raise HTTPException(status_code=404, detail="User not found")

    # Invalidate cache after delete
    await _invalidate_user_cache(user_id)

    return MessageResponse(message="User deleted successfully")


# Role management endpoints
@router.post("/roles", response_model=dict)
async def create_role(
    name: RoleName,
    description: Optional[str] = None,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """Create a new role (admin only)."""
    rbac = get_rbac_manager(db)
    role = rbac.create_role(name, description)
    return {"id": role.id, "name": role.name, "description": role.description}


@router.get("/roles", response_model=List[dict[str, Any]])
async def list_roles(
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """List all roles (admin only)."""
    rbac = get_rbac_manager(db)
    roles = rbac.get_all_roles()
    return [
        {
            "id": r.id,
            "name": r.name,
            "description": r.description,
            "permissions": [p.name for p in r.permissions],
        }
        for r in roles
    ]


@router.post("/roles/{role_name}/permissions", response_model=dict)
async def assign_permission_to_role(
    role_name: RoleName,
    permission_name: PermissionName,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """Assign permission to role (admin only)."""
    rbac = get_rbac_manager(db)
    success = rbac.assign_permission_to_role(role_name, permission_name)

    if not success:
        raise HTTPException(status_code=400, detail="Role or permission not found")

    return {"message": f"Permission {permission_name.value} assigned to role {role_name.value}"}


# User role assignment
@router.post("/users/{user_id}/roles/{role_name}", response_model=dict)
async def assign_role_to_user(
    user_id: int,
    role_name: RoleName,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """Assign role to user (admin only)."""
    rbac = get_rbac_manager(db)
    success = rbac.assign_role_to_user(user_id, role_name)

    if not success:
        raise HTTPException(status_code=400, detail="User or role not found")

    return {"message": f"Role {role_name.value} assigned to user {user_id}"}


@router.delete("/users/{user_id}/roles/{role_name}", response_model=dict)
async def remove_role_from_user(
    user_id: int,
    role_name: RoleName,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """Remove role from user (admin only)."""
    rbac = get_rbac_manager(db)
    success = rbac.remove_role_from_user(user_id, role_name)

    if not success:
        raise HTTPException(status_code=400, detail="User or role not found")

    return {"message": f"Role {role_name.value} removed from user {user_id}"}


# Project permission endpoints
@router.post("/projects/{project_id}/permissions", response_model=dict)
async def grant_project_permission(
    project_id: int,
    user_id: int,
    role: RoleName,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """Grant project permission to user (admin only)."""
    rbac = get_rbac_manager(db)
    perm = rbac.grant_project_permission(user_id, project_id, role)

    return {
        "id": perm.id,
        "user_id": perm.user_id,
        "project_id": perm.project_id,
        "role": perm.role,
    }


@router.delete("/projects/{project_id}/permissions/{user_id}", response_model=dict)
async def revoke_project_permission(
    project_id: int,
    user_id: int,
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_USERS)),
    db: Session = Depends(get_db),
):
    """Revoke project permission from user (admin only)."""
    rbac = get_rbac_manager(db)
    success = rbac.revoke_project_permission(user_id, project_id)

    if not success:
        raise HTTPException(status_code=404, detail="Permission not found")

    return {"message": "Project permission revoked"}


@router.get("/projects/{project_id}/permissions", response_model=List[dict[str, Any]])
async def list_project_permissions(
    project_id: int,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """List all permissions for a project (user must have project access)."""
    rbac = get_rbac_manager(db)

    # Check if user has access to this project
    if not rbac.check_project_access(current_user, project_id, RoleName.VIEWER):
        raise HTTPException(status_code=403, detail="Access denied to this project")

    # Get all project permissions
    from src.audiobook_studio.models.user import ProjectPermission

    project_perms = db.query(ProjectPermission).filter(ProjectPermission.project_id == project_id).all()

    result = []
    for p in project_perms:
        user = rbac.get_user(p.user_id)
        result.append(
            {
                "user_id": p.user_id,
                "username": user.username if user else "unknown",
                "role": p.role,
            }
        )

    return result


# Initialize RBAC (admin only)
@router.post("/init-rbac", response_model=MessageResponse)
async def initialize_rbac(
    current_user: UserModel = Depends(require_permission(PermissionName.ADMIN_SYSTEM)),
    db: Session = Depends(get_db),
):
    """Initialize default RBAC roles and permissions (admin only)."""
    from src.audiobook_studio.auth.rbac import init_rbac

    init_rbac(db)
    return MessageResponse(message="RBAC initialized successfully")

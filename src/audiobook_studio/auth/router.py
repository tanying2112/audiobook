from ..config.settings import Settings

"""Authentication API router for Audiobook Studio.

Provides endpoints for login, registration, token refresh, and user management.
"""

import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Auth dependencies
from src.audiobook_studio.auth.dependencies import (
    _invalidate_user_cache,
    get_current_active_user,
    get_current_user_optional,
    require_permission,
)

# Rate limiting (in-memory, simple implementation)
# Rate limiting (in-memory, simple implementation)
from src.audiobook_studio.config import get_settings

# Rate limiter (in-memory, simple token bucket per IP)
_rate_limit_store: Dict[str, List[float]] = defaultdict(list)


def check_rate_limit(
    request: Request,
    limit: int = 10,
    window_seconds: int = 60,
) -> bool:
    """Simple in-memory rate limiter. Returns True if allowed, False if rate limited."""
    settings = get_settings()
    if not settings.RATE_LIMIT_ENABLED:
        return True

    client_ip = request.client.host if request.client else "unknown"
    now = time.time()
    key = f"{request.url.path}:{client_ip}"

    # Clean old entries
    window_start = time.time() - window_seconds
    _rate_limit_store[key] = [t for t in _rate_limit_store[key] if t > window_start]

    if len(_rate_limit_store[key]) >= limit:
        return False

    _rate_limit_store[key].append(now)
    return True


def check_auth_rate_limit(request: Request) -> None:
    """Rate limit for auth endpoints. Raises HTTPException if rate limited."""
    settings = get_settings()
    if not settings.RATE_LIMIT_ENABLED:
        return

    # Stricter limits for auth endpoints
    limit = 5  # 5 requests
    window_seconds = 300  # per 5 minutes

    if not check_rate_limit(request, limit=limit, window_seconds=window_seconds):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": "300"},
        )


from src.audiobook_studio.auth.jwt_handler import jwt_handler

# Pydantic models
from src.audiobook_studio.auth.models import (
    PermissionName,
    ProjectPermissionOut,
    ResendVerificationRequest,
    RoleName,
    UserCreate,
    UserOut,
    UserUpdate,
    VerifyEmailRequest,
    VerifyEmailResponse,
)
from src.audiobook_studio.auth.rbac import get_rbac_manager
from src.audiobook_studio.database import get_db

# SQLAlchemy models
from src.audiobook_studio.models.user import AuditLog as AuditLogModel
from src.audiobook_studio.models.user import User as UserModel


def record_audit_log(
    db: Session,
    event_type: str,
    user: Optional[UserModel] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    details: Optional[dict] = None,
) -> AuditLogModel:
    """Record an audit log entry."""
    log = AuditLogModel(
        event_type=event_type,
        user_id=user.id if user else None,
        username=user.username if user else None,
        details=details or {},
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


router = APIRouter(prefix="/auth", tags=["authentication"])


def _user_out_payload(
    user: Any,  # noqa: ANN401 - accepts UserModel (or any object exposing the same attrs)
    roles: Optional[List[str]] = None,
    project_permissions: Optional[List[ProjectPermissionOut]] = None,
) -> Dict[str, Any]:
    """Build the ``UserOut`` payload for a user row.

    Centralised on purpose: every endpoint used to inline its own dict, so adding a
    column to ``UserOut`` (e.g. ``is_email_verified``) silently 500'd every endpoint
    that forgot to map it. Optional attributes are type-checked before being passed
    through so a partially-populated object cannot inject an invalid type.
    """
    is_verified = getattr(user, "is_email_verified", False)
    verified_at = getattr(user, "email_verified_at", None)
    return {
        "id": user.id,
        "email": user.email,
        "username": user.username,
        "full_name": user.full_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "is_email_verified": is_verified if isinstance(is_verified, bool) else False,
        "created_at": user.created_at,
        "email_verified_at": verified_at if isinstance(verified_at, datetime) else None,
        "roles": list(roles) if roles else [],
        "project_permissions": list(project_permissions) if project_permissions else [],
    }


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
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    """Authenticate user and return access/refresh tokens."""
    # Rate limiting for login
    check_auth_rate_limit(request)

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

    # Record audit log for successful login
    record_audit_log(db, "user_login", user=user)

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
    payload.get("roles", [])
    payload.get("permissions", [])

    new_refresh_token = jwt_handler.create_refresh_token(user_id, username)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=jwt_handler.access_token_expire_minutes * 60,
    )


def _registration_allowed(
    settings: "Settings",
    user_data: UserCreate,
    current_user: Optional[UserModel],
) -> "tuple[bool, Optional[str]]":
    """Decide whether registration is permitted under AUTH_REGISTRATION_MODE.

    - ``open``: anyone may self-register.
    - ``invite``: a valid invite code (REGISTRATION_INVITE_CODES) or an admin
      bootstrap is required; otherwise registration is denied.
    - any other mode (e.g. ``approval``): only an admin may bootstrap accounts.
    """
    mode = settings.AUTH_REGISTRATION_MODE
    if mode == "open":
        return True, None
    if mode == "invite":
        allowed = [c.strip() for c in (settings.REGISTRATION_INVITE_CODES or "").split(",") if c.strip()]
        if user_data.invite_code and user_data.invite_code in allowed:
            return True, None
        if current_user is not None and getattr(current_user, "is_superuser", False):
            return True, None
        return False, "Registration requires a valid invite code (AUTH_REGISTRATION_MODE=invite)."
    # approval / any other mode: only an admin may bootstrap accounts.
    if current_user is not None and getattr(current_user, "is_superuser", False):
        return True, None
    return False, f"Registration not allowed in '{mode}' mode. Contact administrator."


import secrets

# ... (keep existing imports)


def generate_verification_token() -> str:
    """Generate a secure email verification token."""
    return secrets.token_urlsafe(32)


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    request: Request,
    user_data: UserCreate,
    db: Session = Depends(get_db),
    current_user: Optional[UserModel] = Depends(get_current_user_optional),
):
    """Register a new user.

    Behavior depends on AUTH_REGISTRATION_MODE setting:
    - "open": Anyone can register (default)
    - "invite": Requires valid invite code
    - "approval": Requires admin approval after registration
    """
    # Rate limiting for registration
    check_auth_rate_limit(request)

    settings = get_settings()
    allowed, reason = _registration_allowed(settings, user_data, current_user)
    if not allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=reason)

    rbac = get_rbac_manager(db)

    # Check if user already exists
    if rbac.get_user_by_username(user_data.username):
        raise HTTPException(status_code=400, detail="Username already registered")

    if rbac.get_user_by_email(user_data.email):
        raise HTTPException(status_code=400, detail="Email already registered")

    # Generate email verification token (expires in 24 hours)
    verification_token = generate_verification_token()
    datetime.now(timezone.utc) + timedelta(hours=24)

    user = rbac.create_user(
        email=user_data.email,
        username=user_data.username,
        password=user_data.password,
        full_name=user_data.full_name,
        is_email_verified=False,
        email_verification_token=verification_token,
        email_verification_token_expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )

    # TODO: Send verification email (best-effort)
    # await send_verification_email(user.email, verification_token)

    # Record audit log for registration
    record_audit_log(db, "user_register", user=user)

    # Construct UserOut manually to avoid from_attributes issues with roles relationship
    return UserOut.model_validate(_user_out_payload(user, roles=[role.name for role in user.roles]))


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    request: VerifyEmailRequest,
    db: Session = Depends(get_db),
):
    """Verify user's email address with token."""
    get_rbac_manager(db)
    user = db.query(UserModel).filter(UserModel.email_verification_token == request.token).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired verification token")

    if user.is_email_verified:
        return VerifyEmailResponse(message="Email already verified", verified=True)

    if user.email_verification_token_expires_at and user.email_verification_token_expires_at < datetime.now(
        timezone.utc
    ):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification token has expired")

    user.is_email_verified = True
    user.email_verified_at = datetime.now(timezone.utc)
    user.email_verification_token = None
    user.email_verification_token_expires_at = None
    db.commit()

    return VerifyEmailResponse(message="Email verified successfully", verified=True)


@router.post("/resend-verification", response_model=VerifyEmailResponse)
async def resend_verification(
    request: ResendVerificationRequest,
    db: Session = Depends(get_db),
):
    """Resend email verification link."""
    rbac = get_rbac_manager(db)
    user = rbac.get_user_by_email(request.email)

    if not user:
        # Don't reveal if email exists
        return VerifyEmailResponse(message="If the email exists, a verification link has been sent", verified=False)

    if user.is_email_verified:
        return VerifyEmailResponse(message="Email already verified", verified=True)

    # Generate new token
    generate_verification_token()
    user.email_verification_token = generate_verification_token()
    user.email_verification_token_expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    db.commit()

    # TODO: Send verification email (best-effort)
    # await send_verification_email(user.email, user.email_verification_token)

    return VerifyEmailResponse(message="If the email exists, a verification link has been sent", verified=False)


@router.get("/me", response_model=UserOut)
async def read_current_user(
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Get current user profile."""
    rbac = get_rbac_manager(db)
    rbac.get_user_permissions(current_user)
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
    return UserOut.model_validate(_user_out_payload(current_user, roles=roles, project_permissions=project_perms_out))


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
    return UserOut.model_validate(_user_out_payload(user, roles=[role.name for role in user.roles]))


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
    return [UserOut.model_validate(_user_out_payload(u, roles=[role.name for role in u.roles])) for u in users]


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
    return UserOut.model_validate(_user_out_payload(user, roles=[role.name for role in user.roles]))


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

    # Same payload builder as the other endpoints (``from_orm`` is deprecated and
    # also tripped over the roles relationship).
    return UserOut.model_validate(_user_out_payload(user, roles=[role.name for role in user.roles]))


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

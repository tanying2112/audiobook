"""FastAPI dependencies for authentication and authorization."""

from typing import List, Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import (
    OAuth2PasswordBearer,
    OAuth2PasswordRequestForm,
    SecurityScopes,
)
from jose import JWTError
from sqlalchemy.orm import Session

from src.audiobook_studio.auth.jwt_handler import jwt_handler

# Pydantic models from auth/models.py
from src.audiobook_studio.auth.models import PermissionName, RoleName, TokenData
from src.audiobook_studio.auth.rbac import RBACManager
from src.audiobook_studio.database import get_db

# SQLAlchemy models from models/user.py
from src.audiobook_studio.models.user import User

# OAuth2 scheme for token authentication
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/auth/login",
    scopes={
        "admin": "Full system access",
        "project:read": "Read project data",
        "project:write": "Write project data",
        "golden:contribute": "Contribute to golden dataset",
    },
)


async def get_current_user(
    security_scopes: SecurityScopes,
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Get current authenticated user from JWT token."""
    authenticate_value = (
        f'Bearer scope="{security_scopes.scope_str}"'
        if security_scopes.scopes
        else "Bearer"
    )

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": authenticate_value},
    )

    try:
        payload = jwt_handler.decode_token(token)
        user_id: int = int(payload.get("sub", 0))
        username: str = payload.get("username", "")
        roles: List[str] = payload.get("roles", [])
        permissions: List[str] = payload.get("permissions", [])

        if user_id == 0:
            raise credentials_exception

        token_data = TokenData(
            username=username,
            user_id=user_id,
            roles=roles,
            permissions=permissions,
        )
    except JWTError:
        raise credentials_exception
    except Exception:
        raise credentials_exception

    user = db.query(User).filter(User.id == token_data.user_id).first()
    if user is None:
        raise credentials_exception

    # Check scopes if required
    for scope in security_scopes.scopes:
        if (
            scope not in token_data.permissions
            and scope != "admin" not in token_data.roles
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Not enough permissions. Required: {scope}",
                headers={"WWW-Authenticate": authenticate_value},
            )

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Get current active user."""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user


async def get_current_superuser(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Get current superuser."""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Superuser access required",
        )
    return current_user


# Permission-based dependencies
def require_permission(permission: PermissionName):
    """Dependency to require a specific permission."""

    async def permission_checker(
        current_user: User = Depends(get_current_active_user),
        db: Session = Depends(get_db),
    ) -> User:
        rbac = RBACManager(db)
        if not rbac.user_has_permission(current_user, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value} required",
            )
        return current_user

    return permission_checker


def require_role(role: RoleName):
    """Dependency to require a specific role."""

    async def role_checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if not current_user.has_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role required: {role.value}",
            )
        return current_user

    return role_checker


def require_project_permission(required_role: RoleName):
    """Dependency to require project-level permission."""

    async def project_permission_checker(
        project_id: int,
        current_user: User = Depends(get_current_active_user),
        db: Session = Depends(get_db),
    ) -> User:
        rbac = RBACManager(db)
        if not rbac.check_project_access(current_user, project_id, required_role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Project access denied: {required_role.value} role required",
            )
        return current_user

    return project_permission_checker


# Optional: dependency to get RBAC manager
def get_rbac_manager(db: Session = Depends(get_db)) -> RBACManager:
    """Get RBAC manager instance."""
    return RBACManager(db)


# Token creation endpoint helper
async def authenticate_user(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
) -> User:
    """Authenticate user and return user object."""
    rbac = RBACManager(db)
    user = rbac.authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

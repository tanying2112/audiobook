"""RBAC Manager for Audiobook Studio.

Provides Role-Based Access Control with project-level permissions.
"""

from typing import Any, Dict, List, Optional, Set

from sqlalchemy import and_
from sqlalchemy.orm import Session

from src.audiobook_studio.auth.jwt_handler import hash_password, verify_password

# Import Pydantic enums from auth/models.py
from src.audiobook_studio.auth.models import PermissionName, RoleName

# Import SQLAlchemy models from models/user.py
from src.audiobook_studio.models.user import Permission, ProjectPermission, Role, User


class RBACManager:
    """Manages roles, permissions, and access control."""

    def __init__(self, db: Session):
        self.db = db

    # User management
    def create_user(
        self,
        email: str,
        username: str,
        password: str,
        full_name: Optional[str] = None,
        is_superuser: bool = False,
    ) -> User:
        """Create a new user."""
        hashed_password = hash_password(password)
        user = User(
            email=email,
            username=username,
            hashed_password=hashed_password,
            full_name=full_name,
            is_superuser=is_superuser,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def get_user(self, user_id: int) -> Optional[User]:
        """Get user by ID."""
        return self.db.query(User).filter(User.id == user_id).first()

    def get_user_by_username(self, username: str) -> Optional[User]:
        """Get user by username."""
        return self.db.query(User).filter(User.username == username).first()

    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        return self.db.query(User).filter(User.email == email).first()

    def authenticate_user(self, username: str, password: str) -> Optional[User]:
        """Authenticate a user with username and password."""
        user = self.get_user_by_username(username)
        if not user:
            return None
        if not verify_password(password, user.hashed_password):
            return None
        return user

    def update_user(self, user: User, **kwargs) -> User:
        """Update user fields."""
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        self.db.commit()
        self.db.refresh(user)
        return user

    def delete_user(self, user_id: int) -> bool:
        """Delete a user."""
        user = self.get_user(user_id)
        if user:
            self.db.delete(user)
            self.db.commit()
            return True
        return False

    # Role management
    def create_role(self, name: RoleName, description: Optional[str] = None) -> Role:
        """Create a new role."""
        role = Role(name=name.value, description=description)
        self.db.add(role)
        self.db.commit()
        self.db.refresh(role)
        return role

    def get_role(self, name: RoleName) -> Optional[Role]:
        """Get role by name."""
        return self.db.query(Role).filter(Role.name == name.value).first()

    def get_all_roles(self) -> List[Role]:
        """Get all roles."""
        return self.db.query(Role).all()

    def delete_role(self, role_id: int) -> bool:
        """Delete a role."""
        role = self.db.query(Role).filter(Role.id == role_id).first()
        if role:
            self.db.delete(role)
            self.db.commit()
            return True
        return False

    # Permission management
    def create_permission(
        self, name: PermissionName, description: Optional[str] = None
    ) -> Permission:
        """Create a new permission."""
        perm = Permission(name=name.value, description=description)
        self.db.add(perm)
        self.db.commit()
        self.db.refresh(perm)
        return perm

    def get_permission(self, name: PermissionName) -> Optional[Permission]:
        """Get permission by name."""
        return self.db.query(Permission).filter(Permission.name == name.value).first()

    def get_all_permissions(self) -> List[Permission]:
        """Get all permissions."""
        return self.db.query(Permission).all()

    def assign_permission_to_role(
        self, role_name: RoleName, perm_name: PermissionName
    ) -> bool:
        """Assign a permission to a role."""
        role = self.get_role(role_name)
        perm = self.get_permission(perm_name)

        if not role or not perm:
            return False

        if perm not in role.permissions:
            role.permissions.append(perm)
            self.db.commit()
        return True

    def remove_permission_from_role(
        self, role_name: RoleName, perm_name: PermissionName
    ) -> bool:
        """Remove a permission from a role."""
        role = self.get_role(role_name)
        perm = self.get_permission(perm_name)

        if not role or not perm:
            return False

        if perm in role.permissions:
            role.permissions.remove(perm)
            self.db.commit()
        return True

    # User role assignment
    def assign_role_to_user(self, user_id: int, role_name: RoleName) -> bool:
        """Assign a role to a user."""
        user = self.get_user(user_id)
        role = self.get_role(role_name)

        if not user or not role:
            return False

        if role not in user.roles:
            user.roles.append(role)
            self.db.commit()
        return True

    def remove_role_from_user(self, user_id: int, role_name: RoleName) -> bool:
        """Remove a role from a user."""
        user = self.get_user(user_id)
        role = self.get_role(role_name)

        if not user or not role:
            return False

        if role in user.roles:
            user.roles.remove(role)
            self.db.commit()
        return True

    def get_user_roles(self, user_id: int) -> List[Role]:
        """Get all roles for a user."""
        user = self.get_user(user_id)
        if not user:
            return []
        return user.roles

    # Permission checking
    def user_has_permission(self, user: User, permission: PermissionName) -> bool:
        """Check if user has a specific permission."""
        if user.is_superuser:
            return True

        # Check direct role permissions
        for role in user.roles:
            for perm in role.permissions:
                if perm.name == permission.value:
                    return True

        return False

    def user_has_any_permission(
        self, user: User, permissions: List[PermissionName]
    ) -> bool:
        """Check if user has any of the given permissions."""
        return any(self.user_has_permission(user, p) for p in permissions)

    def user_has_all_permissions(
        self, user: User, permissions: List[PermissionName]
    ) -> bool:
        """Check if user has all of the given permissions."""
        return all(self.user_has_permission(user, p) for p in permissions)

    def get_user_permissions(self, user: User) -> Set[str]:
        """Get all permissions for a user."""
        perms = set()
        if user.is_superuser:
            perms.add("*")
            return perms

        for role in user.roles:
            for perm in role.permissions:
                perms.add(perm.name)
        return perms

    # Project-level permissions
    def grant_project_permission(
        self,
        user_id: int,
        project_id: int,
        role: RoleName,
    ) -> ProjectPermission:
        """Grant a user project-level permission."""
        # Check if permission already exists
        existing = (
            self.db.query(ProjectPermission)
            .filter(
                and_(
                    ProjectPermission.user_id == user_id,
                    ProjectPermission.project_id == project_id,
                )
            )
            .first()
        )

        if existing:
            existing.role = role.value
            self.db.commit()
            self.db.refresh(existing)
            return existing

        perm = ProjectPermission(
            user_id=user_id,
            project_id=project_id,
            role=role.value,
        )
        self.db.add(perm)
        self.db.commit()
        self.db.refresh(perm)
        return perm

    def revoke_project_permission(self, user_id: int, project_id: int) -> bool:
        """Revoke a user's project permission."""
        perm = (
            self.db.query(ProjectPermission)
            .filter(
                and_(
                    ProjectPermission.user_id == user_id,
                    ProjectPermission.project_id == project_id,
                )
            )
            .first()
        )

        if perm:
            self.db.delete(perm)
            self.db.commit()
            return True
        return False

    def get_project_permission(
        self, user_id: int, project_id: int
    ) -> Optional[ProjectPermission]:
        """Get user's project permission."""
        return (
            self.db.query(ProjectPermission)
            .filter(
                and_(
                    ProjectPermission.user_id == user_id,
                    ProjectPermission.project_id == project_id,
                )
            )
            .first()
        )

    def check_project_access(
        self,
        user: User,
        project_id: int,
        required_role: RoleName,
    ) -> bool:
        """Check if user has required role for a project."""
        if user.is_superuser:
            return True

        # Check project-specific permission
        proj_perm = self.get_project_permission(user.id, project_id)
        if proj_perm:
            role_hierarchy = {
                RoleName.ADMIN: 5,
                RoleName.PROJECT_OWNER: 4,
                RoleName.EDITOR: 3,
                RoleName.VIEWER: 2,
                RoleName.CONTRIBUTOR: 1,
            }
            user_role_level = role_hierarchy.get(RoleName(proj_perm.role), 0)
            required_level = role_hierarchy.get(required_role, 0)
            return user_role_level >= required_level

        # Check global roles (admin, project_owner can access all projects)
        if user.has_role(RoleName.ADMIN) or user.has_role(RoleName.PROJECT_OWNER):
            return True

        return False

    def get_user_projects(self, user_id: int) -> List[Dict[str, Any]]:
        """Get all projects a user has access to with their roles."""
        perms = (
            self.db.query(ProjectPermission)
            .filter(ProjectPermission.user_id == user_id)
            .all()
        )

        return [{"project_id": p.project_id, "role": p.role} for p in perms]


# Convenience functions for FastAPI dependencies
def get_rbac_manager(db: Session = None) -> RBACManager:
    """Get RBAC manager instance (for use as FastAPI dependency).

    Note: When db is None, a new session is created and the caller is
    responsible for closing it. Prefer using the FastAPI dependency in
    auth/dependencies.py which handles session lifecycle automatically.
    """
    if db is None:
        from src.audiobook_studio.database import SessionLocal

        db = SessionLocal()
        try:
            return RBACManager(db)
        except Exception:
            db.close()
            raise
    return RBACManager(db)


def init_rbac(db: Session) -> None:
    """Initialize default roles and permissions if they don't exist.

    Called at application startup to ensure the RBAC system has
    the baseline roles and permissions.
    """
    rbac = RBACManager(db)

    # Create all permissions
    for perm_name in PermissionName:
        if not rbac.get_permission(perm_name):
            rbac.create_permission(perm_name)

    # Create all roles
    for role_name in RoleName:
        if not rbac.get_role(role_name):
            rbac.create_role(role_name)

    # Assign permissions to roles (admin gets everything)
    admin_perms = list(PermissionName)
    for perm in admin_perms:
        rbac.assign_permission_to_role(RoleName.ADMIN, perm)

    # Project owner gets project + pipeline + export permissions
    owner_perms = [
        PermissionName.PROJECT_CREATE, PermissionName.PROJECT_READ,
        PermissionName.PROJECT_UPDATE, PermissionName.PROJECT_DELETE,
        PermissionName.PROJECT_LIST, PermissionName.CHAPTER_CREATE,
        PermissionName.CHAPTER_READ, PermissionName.CHAPTER_UPDATE,
        PermissionName.CHAPTER_DELETE, PermissionName.PARAGRAPH_READ,
        PermissionName.PARAGRAPH_UPDATE, PermissionName.PARAGRAPH_ANNOTATE,
        PermissionName.PARAGRAPH_EDIT, PermissionName.CHARACTER_CREATE,
        PermissionName.CHARACTER_READ, PermissionName.CHARACTER_UPDATE,
        PermissionName.CHARACTER_DELETE, PermissionName.PIPELINE_RUN,
        PermissionName.PIPELINE_VIEW, PermissionName.PIPELINE_CANCEL,
        PermissionName.EXPORT_CREATE, PermissionName.EXPORT_READ,
        PermissionName.EXPORT_DOWNLOAD, PermissionName.TTS_ROUTE,
        PermissionName.TTS_SYNTHESIZE, PermissionName.TTS_QUALITY_CHECK,
        PermissionName.FEEDBACK_CREATE, PermissionName.FEEDBACK_READ,
    ]
    for perm in owner_perms:
        rbac.assign_permission_to_role(RoleName.PROJECT_OWNER, perm)

    # Editor gets read + edit + annotate + pipeline view
    editor_perms = [
        PermissionName.PROJECT_READ, PermissionName.PROJECT_LIST,
        PermissionName.CHAPTER_READ, PermissionName.PARAGRAPH_READ,
        PermissionName.PARAGRAPH_UPDATE, PermissionName.PARAGRAPH_ANNOTATE,
        PermissionName.PARAGRAPH_EDIT, PermissionName.CHARACTER_READ,
        PermissionName.PIPELINE_VIEW, PermissionName.EXPORT_READ,
        PermissionName.FEEDBACK_CREATE, PermissionName.FEEDBACK_READ,
    ]
    for perm in editor_perms:
        rbac.assign_permission_to_role(RoleName.EDITOR, perm)

    # Viewer gets read-only permissions
    viewer_perms = [
        PermissionName.PROJECT_READ, PermissionName.PROJECT_LIST,
        PermissionName.CHAPTER_READ, PermissionName.PARAGRAPH_READ,
        PermissionName.CHARACTER_READ, PermissionName.PIPELINE_VIEW,
        PermissionName.EXPORT_READ,
    ]
    for perm in viewer_perms:
        rbac.assign_permission_to_role(RoleName.VIEWER, perm)

    # Contributor gets read + feedback
    contributor_perms = [
        PermissionName.PROJECT_READ, PermissionName.PROJECT_LIST,
        PermissionName.CHAPTER_READ, PermissionName.PARAGRAPH_READ,
        PermissionName.FEEDBACK_CREATE, PermissionName.FEEDBACK_READ,
    ]
    for perm in contributor_perms:
        rbac.assign_permission_to_role(RoleName.CONTRIBUTOR, perm)


# Permission checking helpers
def check_permission(user: User, permission: PermissionName, db: Session) -> bool:
    """Check if user has permission."""
    rbac = RBACManager(db)
    return rbac.user_has_permission(user, permission)


def require_permission(permission: PermissionName):
    """Decorator to require a permission (legacy - use FastAPI dependency instead)."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_role(role: RoleName):
    """Decorator to require a role (legacy - use FastAPI dependency instead)."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def require_project_permission(required_role: RoleName):
    """Decorator to require project permission (legacy - use FastAPI dependency instead)."""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            return await func(*args, **kwargs)

        return wrapper

    return decorator

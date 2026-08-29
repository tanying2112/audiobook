"""Pydantic models for authentication API (request/response models)."""

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class RoleName(str, Enum):
    """System roles."""

    ADMIN = "admin"
    PROJECT_OWNER = "project_owner"
    EDITOR = "editor"
    VIEWER = "viewer"
    CONTRIBUTOR = "contributor"


class PermissionName(str, Enum):
    """System permissions."""

    PROJECT_CREATE = "project:create"
    PROJECT_READ = "project:read"
    PROJECT_UPDATE = "project:update"
    PROJECT_DELETE = "project:delete"
    PROJECT_LIST = "project:list"
    CHAPTER_CREATE = "chapter:create"
    CHAPTER_READ = "chapter:read"
    CHAPTER_UPDATE = "chapter:update"
    CHAPTER_DELETE = "chapter:delete"
    PARAGRAPH_READ = "paragraph:read"
    PARAGRAPH_UPDATE = "paragraph:update"
    PARAGRAPH_ANNOTATE = "paragraph:annotate"
    PARAGRAPH_EDIT = "paragraph:edit"
    CHARACTER_CREATE = "character:create"
    CHARACTER_READ = "character:read"
    CHARACTER_UPDATE = "character:update"
    CHARACTER_DELETE = "character:delete"
    TTS_ROUTE = "tts:route"
    TTS_SYNTHESIZE = "tts:synthesize"
    TTS_QUALITY_CHECK = "tts:quality_check"
    EXPORT_CREATE = "export:create"
    EXPORT_READ = "export:read"
    EXPORT_DOWNLOAD = "export:download"
    GOLDEN_CONTRIBUTE = "golden:contribute"
    GOLDEN_REVIEW = "golden:review"
    GOLDEN_APPROVE = "golden:approve"
    GOLDEN_MANAGE = "golden:manage"
    ADMIN_USERS = "admin:users"
    ADMIN_SYSTEM = "admin:system"
    ADMIN_CONFIG = "admin:config"
    ADMIN_MONITORING = "admin:monitoring"
    PIPELINE_RUN = "pipeline:run"
    PIPELINE_VIEW = "pipeline:view"
    PIPELINE_CANCEL = "pipeline:cancel"
    TEMPLATE_CREATE = "template:create"
    TEMPLATE_READ = "template:read"
    TEMPLATE_APPLY = "template:apply"
    FEEDBACK_CREATE = "feedback:create"
    FEEDBACK_READ = "feedback:read"
    FEEDBACK_PROCESS = "feedback:process"
    AUTH_VERIFY_EMAIL = "auth:verify_email"
    AUTH_INVITE_CREATE = "auth:invite_create"
    AUTH_AUDIT_READ = "auth:audit_read"


# Pydantic models for API
class UserBase(BaseModel):
    email: EmailStr
    username: str = Field(..., min_length=3, max_length=100)
    full_name: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=100)
    invite_code: Optional[str] = Field(
        default=None,
        description="Invite code required when AUTH_REGISTRATION_MODE=invite",
    )


class UserUpdate(BaseModel):
    email: Optional[EmailStr] = None
    full_name: Optional[str] = None
    is_active: Optional[bool] = None
    model_config = ConfigDict(from_attributes=True)


class UserOut(UserBase):
    id: int
    is_active: bool
    is_superuser: bool
    # Defaults to False so a caller that cannot resolve the flag (legacy row, or a
    # payload built before the column existed) degrades to "unverified" instead of
    # raising a 500 on serialization.
    is_email_verified: bool = False
    # created_at can be None on freshly-constructed/persisted users at runtime,
    # so keep it optional rather than a required datetime (was a 500 on /me).
    created_at: Optional[datetime] = None
    email_verified_at: Optional[datetime] = None
    roles: List[str] = []
    project_permissions: List["ProjectPermissionOut"] = []
    model_config = ConfigDict(from_attributes=True)


class RoleBase(BaseModel):
    name: RoleName
    description: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class RoleCreate(RoleBase):
    permission_names: List[str] = []


class RoleOut(RoleBase):
    id: int
    created_at: datetime
    permissions: List["PermissionOut"] = []
    model_config = ConfigDict(from_attributes=True)


class PermissionBase(BaseModel):
    name: PermissionName
    description: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class PermissionOut(PermissionBase):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProjectPermissionBase(BaseModel):
    project_id: int
    role: RoleName
    model_config = ConfigDict(from_attributes=True)


class ProjectPermissionCreate(ProjectPermissionBase):
    user_id: int


class ProjectPermissionOut(ProjectPermissionBase):
    id: int
    user_id: int
    created_at: datetime
    granted_by: Optional[int] = None
    username: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class TokenData(BaseModel):
    username: Optional[str] = None
    user_id: Optional[int] = None
    roles: List[str] = []
    permissions: List[str] = []


# Email verification
class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class VerifyEmailResponse(BaseModel):
    message: str
    verified: bool = False


# Invite code management
class InviteCodeCreate(BaseModel):
    code: str = Field(..., min_length=8, max_length=64)
    description: Optional[str] = None
    max_uses: int = Field(default=1, ge=1)
    expires_in_days: Optional[int] = Field(default=30, ge=1)


class InviteCodeOut(BaseModel):
    id: int
    code: str
    description: Optional[str] = None
    max_uses: int
    used_count: int
    expires_at: Optional[datetime] = None
    created_at: datetime
    created_by: int
    model_config = ConfigDict(from_attributes=True)


# Audit log
class AuditLogEntry(BaseModel):
    id: int
    event_type: str
    user_id: Optional[int] = None
    username: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    details: dict = {}
    timestamp: datetime
    model_config = ConfigDict(from_attributes=True)


class AuditLogFilter(BaseModel):
    event_type: Optional[str] = None
    user_id: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


# Forward references
UserOut.model_rebuild()
RoleOut.model_rebuild()
PermissionOut.model_rebuild()
ProjectPermissionOut.model_rebuild()

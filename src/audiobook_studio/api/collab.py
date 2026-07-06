"""FastAPI router for team collaboration features.

Implements commenting, approval, task status, and change history for team collaboration.
All write endpoints use the authenticated user (TeamMember linked via user_id) as the actor.
"""

import json
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from ..auth.dependencies import get_current_active_user
from ..database import get_db
from ..models.collaboration import (
    ApprovalRequest,
    ApprovalResponse,
    ApprovalStatus,
    ChangeRecord,
    ChangeType,
    Comment,
    CommentType,
    Task,
    TaskStatus,
    TeamMember,
)
from ..models.user import User

router = APIRouter(prefix="/collab", tags=["collaboration"])


def get_or_create_team_member(user: User, db: Session) -> TeamMember:
    """Get the TeamMember linked to the auth User, creating a default profile if absent.

    Bridges the auth User and team profile systems. A User without a TeamMember yet
    gets a minimal profile derived from their account so they can author collaboration
    artifacts immediately.
    """
    member = db.query(TeamMember).filter(TeamMember.user_id == user.id).first()
    if member is not None:
        return member
    member = TeamMember(
        name=user.full_name or user.username,
        email=user.email,
        role="editor",
        is_active=user.is_active,
        user_id=user.id,
    )
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


def _record_change(
    db: Session,
    change_type: ChangeType,
    entity_type: str,
    entity_id: int,
    actor: TeamMember,
    old_state: Optional[object] = None,
    new_state: Optional[object] = None,
    description: str = "",
) -> ChangeRecord:
    """Persist a ChangeRecord audit-trail entry."""
    record = ChangeRecord(
        change_type=change_type,
        entity_type=entity_type,
        entity_id=entity_id,
        changed_by=actor.id,
        old_state=json.dumps(old_state, default=str) if old_state is not None else None,
        new_state=json.dumps(new_state, default=str) if new_state is not None else None,
        description=description or f"{change_type.value} {entity_type} {entity_id}",
    )
    db.add(record)
    return record


# ── Pydantic models for collaboration features ──────────────────────────────


class TeamMemberResponse(BaseModel):
    id: int
    name: str
    email: str
    role: str
    is_active: bool
    user_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class CommentBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    comment_type: str = Field(..., description="comment, suggestion, question, or issue")
    task_id: Optional[int] = None
    file_path: Optional[str] = None
    line_number: Optional[int] = None
    parent_id: Optional[int] = None  # For replies to other comments


class CommentCreate(CommentBase):
    pass


class CommentResponse(CommentBase):
    id: int
    author_id: int
    created_at: datetime
    updated_at: datetime
    resolved: bool = False
    resolved_by: Optional[int] = None
    resolved_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class TaskBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., max_length=2000)
    status: str = Field(default="todo", description="todo, in_progress, review, done, or archived")
    assignee_id: Optional[int] = None
    reporter_id: Optional[int] = None
    tags: List[str] = Field(default_factory=list)
    priority: int = Field(default=1, ge=1, le=5)  # 1-5, 5 being highest priority
    estimated_hours: Optional[float] = Field(None, ge=0)
    project_id: Optional[int] = None
    parent_task_id: Optional[int] = None  # For subtasks
    depends_on: List[int] = Field(default_factory=list)  # Predecessor task IDs


class TaskCreate(TaskBase):
    pass


class TaskResponse(TaskBase):
    id: int
    created_at: datetime
    updated_at: datetime
    actual_hours: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class ApprovalRequestBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., max_length=2000)
    task_id: Optional[int] = None
    artifact_path: Optional[str] = None  # Path to artifact being reviewed
    required_approvals: int = Field(default=1, ge=1)
    auto_approve_if_unstoppable: bool = Field(default=False)


class ApprovalRequestCreate(ApprovalRequestBase):
    approver_ids: List[int] = Field(..., min_length=1)


class ApprovalResponseOut(BaseModel):
    approver_id: int
    status: str
    comment: Optional[str] = None
    commented_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ApprovalRequestResponse(ApprovalRequestBase):
    id: int
    requester_id: int
    approver_ids: List[int] = Field(default_factory=list)
    status: str = Field(..., description="pending, approved, rejected, or needs_changes")
    created_at: datetime
    updated_at: datetime
    responses: List[ApprovalResponseOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)

    @field_validator("approver_ids", mode="before")
    @classmethod
    def _extract_approver_ids(cls, v):
        # When serializing from the ORM, the attribute is the `approvers`
        # relationship (list of TeamMember); pull the ids out of it.
        if v is None:
            return []
        if isinstance(v, list):
            return [getattr(m, "id", m) for m in v]
        return v


class ApprovalResponseCreate(BaseModel):
    status: str = Field(..., description="pending, approved, rejected, or needs_changes")
    comment: Optional[str] = None


# ── Helpers for enum validation ──────────────────────────────────────────────


def _parse_comment_type(value: str) -> CommentType:
    try:
        return CommentType(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid comment_type. Must be one of: {[t.value for t in CommentType]}",
        )


def _parse_task_status(value: str) -> TaskStatus:
    try:
        return TaskStatus(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Must be one of: {[t.value for t in TaskStatus]}",
        )


def _parse_approval_status(value: str) -> ApprovalStatus:
    try:
        return ApprovalStatus(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid status. Must be one of: {[t.value for t in ApprovalStatus]}",
        )


# ── Comment endpoints ────────────────────────────────────────────────────────


@router.post("/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
def create_comment(
    comment: CommentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """创建新评论"""
    author = get_or_create_team_member(current_user, db)
    ct = _parse_comment_type(comment.comment_type)
    db_comment = Comment(
        content=comment.content,
        comment_type=ct,
        author_id=author.id,
        task_id=comment.task_id,
        file_path=comment.file_path,
        line_number=comment.line_number,
        parent_id=comment.parent_id,
    )
    db.add(db_comment)
    db.commit()
    db.refresh(db_comment)
    _record_change(
        db,
        ChangeType.CREATE,
        "comment",
        db_comment.id,
        author,
        new_state={"content": db_comment.content, "comment_type": ct.value},
    )
    db.commit()
    return db_comment


@router.get("/comments/{comment_id}", response_model=CommentResponse)
def get_comment(comment_id: int, db: Session = Depends(get_db)):
    """获取特定评论"""
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.get("/comments", response_model=List[CommentResponse])
def list_comments(
    task_id: Optional[int] = None,
    file_path: Optional[str] = None,
    resolved: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    """列出评论，可按任务、文件或解决状态过滤"""
    query = db.query(Comment)
    if task_id is not None:
        query = query.filter(Comment.task_id == task_id)
    if file_path is not None:
        query = query.filter(Comment.file_path == file_path)
    if resolved is not None:
        query = query.filter(Comment.resolved == resolved)
    return query.order_by(Comment.created_at.desc()).all()


@router.put("/comments/{comment_id}/resolve", response_model=CommentResponse)
def resolve_comment(
    comment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """解决评论"""
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    actor = get_or_create_team_member(current_user, db)
    old_state = {"resolved": comment.resolved, "resolved_by": comment.resolved_by}
    comment.resolved = True
    comment.resolved_by = actor.id
    comment.resolved_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(comment)
    _record_change(
        db,
        ChangeType.UPDATE,
        "comment",
        comment.id,
        actor,
        old_state=old_state,
        new_state={"resolved": True, "resolved_by": actor.id},
        description=f"Resolved comment {comment.id}",
    )
    db.commit()
    return comment


# ── Team member endpoints ─────────────────────────────────────────────────────


@router.get("/members", response_model=List[TeamMemberResponse])
def list_team_members(
    role: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """列出团队成员，可按角色过滤"""
    query = db.query(TeamMember)
    if role is not None:
        query = query.filter(TeamMember.role == role)
    return query.order_by(TeamMember.id).all()


@router.get("/members/me", response_model=TeamMemberResponse)
def get_my_member_profile(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """获取当前用户的团队成员档案"""
    return get_or_create_team_member(current_user, db)


# ── Task endpoints ───────────────────────────────────────────────────────────


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    task: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """创建新任务"""
    actor = get_or_create_team_member(current_user, db)
    task_status = _parse_task_status(task.status)
    # Validate assignee/reporter if provided
    if task.assignee_id is not None and not db.query(TeamMember).filter(TeamMember.id == task.assignee_id).first():
        raise HTTPException(status_code=400, detail="Assignee not found")
    if task.reporter_id is not None and not db.query(TeamMember).filter(TeamMember.id == task.reporter_id).first():
        raise HTTPException(status_code=400, detail="Reporter not found")
    # If reporter not specified, default to the creator
    reporter_id = task.reporter_id if task.reporter_id is not None else actor.id
    db_task = Task(
        title=task.title,
        description=task.description,
        status=task_status,
        assignee_id=task.assignee_id,
        reporter_id=reporter_id,
        tags=task.tags,
        priority=task.priority,
        estimated_hours=task.estimated_hours,
        project_id=task.project_id,
        parent_task_id=task.parent_task_id,
    )
    db.add(db_task)
    db.commit()
    db.refresh(db_task)
    # Apply dependencies (many-to-many) after the task has an id
    if task.depends_on:
        deps = db.query(Task).filter(Task.id.in_(task.depends_on)).all()
        db_task.depends_on = deps
        db.commit()
        db.refresh(db_task)
    _record_change(
        db,
        ChangeType.CREATE,
        "task",
        db_task.id,
        actor,
        new_state={"title": db_task.title, "status": task_status.value},
    )
    db.commit()
    return db_task


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db)):
    """获取特定任务"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("/tasks", response_model=List[TaskResponse])
def list_tasks(
    assignee_id: Optional[int] = None,
    status: Optional[str] = None,
    priority: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """列出任务，可按负责人、状态或优先级过滤"""
    query = db.query(Task)
    if assignee_id is not None:
        query = query.filter(Task.assignee_id == assignee_id)
    if status is not None:
        task_status = _parse_task_status(status)
        query = query.filter(Task.status == task_status)
    if priority is not None:
        query = query.filter(Task.priority == priority)
    return query.order_by(Task.created_at.desc()).all()


@router.put("/tasks/{task_id}/status", response_model=TaskResponse)
def update_task_status(
    task_id: int,
    new_status: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """更新任务状态"""
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    actor = get_or_create_team_member(current_user, db)
    old_status = task.status
    new_status_enum = _parse_task_status(new_status)
    old_state = {"status": old_status.value}
    task.status = new_status_enum
    db.commit()
    db.refresh(task)
    _record_change(
        db,
        ChangeType.UPDATE,
        "task",
        task.id,
        actor,
        old_state=old_state,
        new_state={"status": new_status_enum.value},
        description=f"Task '{task.title}' status: {old_status.value} -> {new_status_enum.value}",
    )
    db.commit()
    return task


# ── Approval endpoints ───────────────────────────────────────────────────────


def _refresh_approval_status(db: Session, approval: ApprovalRequest) -> None:
    """Recompute overall approval status from individual responses (mirrors team_collaboration logic)."""
    approved = sum(1 for r in approval.responses if r.status == ApprovalStatus.APPROVED)
    rejected = sum(1 for r in approval.responses if r.status == ApprovalStatus.REJECTED)
    needs_changes = sum(1 for r in approval.responses if r.status == ApprovalStatus.NEEDS_CHANGES)
    if rejected > 0:
        approval.status = ApprovalStatus.REJECTED
    elif approved >= approval.required_approvals and rejected == 0:
        approval.status = ApprovalStatus.APPROVED
    elif needs_changes > 0:
        approval.status = ApprovalStatus.NEEDS_CHANGES
    else:
        approval.status = ApprovalStatus.PENDING


@router.post(
    "/approvals",
    response_model=ApprovalRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_approval_request(
    approval: ApprovalRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """创建新审批请求"""
    actor = get_or_create_team_member(current_user, db)
    approvers = db.query(TeamMember).filter(TeamMember.id.in_(approval.approver_ids)).all()
    if not approvers:
        raise HTTPException(status_code=400, detail="No valid approvers found")
    if len(approvers) != len(approval.approver_ids):
        raise HTTPException(status_code=400, detail="Some approvers were not found")
    if approval.task_id is not None and not db.query(Task).filter(Task.id == approval.task_id).first():
        raise HTTPException(status_code=400, detail="Referenced task not found")
    db_approval = ApprovalRequest(
        title=approval.title,
        description=approval.description,
        requester_id=actor.id,
        status=ApprovalStatus.PENDING,
        task_id=approval.task_id,
        artifact_path=approval.artifact_path,
        required_approvals=approval.required_approvals,
        auto_approve_if_unstoppable=approval.auto_approve_if_unstoppable,
        approvers=approvers,
    )
    db.add(db_approval)
    db.commit()
    db.refresh(db_approval)
    _record_change(
        db,
        ChangeType.CREATE,
        "approval_request",
        db_approval.id,
        actor,
        new_state={"title": db_approval.title, "status": ApprovalStatus.PENDING.value},
    )
    db.commit()
    return db_approval


@router.get("/approvals/{approval_id}", response_model=ApprovalRequestResponse)
def get_approval_request(approval_id: int, db: Session = Depends(get_db)):
    """获取特定审批请求"""
    approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    return approval


@router.get("/approvals", response_model=List[ApprovalRequestResponse])
def list_approval_requests(
    task_id: Optional[int] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """列出审批请求，可按任务或状态过滤"""
    query = db.query(ApprovalRequest)
    if task_id is not None:
        query = query.filter(ApprovalRequest.task_id == task_id)
    if status is not None:
        approval_status = _parse_approval_status(status)
        query = query.filter(ApprovalRequest.status == approval_status)
    return query.order_by(ApprovalRequest.created_at.desc()).all()


@router.post("/approvals/{approval_id}/respond", response_model=ApprovalRequestResponse)
def respond_to_approval(
    approval_id: int,
    response: ApprovalResponseCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    """响应审批请求"""
    approval = db.query(ApprovalRequest).filter(ApprovalRequest.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval request not found")
    actor = get_or_create_team_member(current_user, db)
    if actor.id not in [a.id for a in approval.approvers]:
        raise HTTPException(status_code=403, detail="Not an assigned approver for this request")
    new_status = _parse_approval_status(response.status)
    # Replace any prior response by the same approver
    existing = (
        db.query(ApprovalResponse)
        .filter(
            ApprovalResponse.approval_request_id == approval.id,
            ApprovalResponse.approver_id == actor.id,
        )
        .first()
    )
    if existing is not None:
        db.delete(existing)
        db.commit()
    approval_response = ApprovalResponse(
        approval_request_id=approval.id,
        approver_id=actor.id,
        status=new_status,
        comment=response.comment,
    )
    db.add(approval_response)
    db.commit()
    db.refresh(approval)
    old_overall = approval.status
    _refresh_approval_status(db, approval)
    db.commit()
    db.refresh(approval)
    _record_change(
        db,
        ChangeType.UPDATE,
        "approval_request",
        approval.id,
        actor,
        old_state={"status": old_overall.value},
        new_state={"status": approval.status.value, "responder": actor.id},
        description=f"Approver {actor.id} responded {new_status.value} to '{approval.title}'",
    )
    db.commit()
    db.refresh(approval)
    return approval


# ── Change history endpoints ──────────────────────────────────────────────────


@router.get("/history", response_model=List[dict])
def get_change_history(
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    """获取变更历史，可按实体类型/ID过滤"""
    query = db.query(ChangeRecord)
    if entity_type is not None:
        query = query.filter(ChangeRecord.entity_type == entity_type)
    if entity_id is not None:
        query = query.filter(ChangeRecord.entity_id == entity_id)
    records = query.order_by(ChangeRecord.changed_at.desc()).limit(limit).all()
    return [r.to_dict() for r in records]


# ── Statistics endpoints ────────────────────────────────────────────────────


@router.get("/stats", response_model=dict)
def get_collaboration_stats(db: Session = Depends(get_db)):
    """获取协作统计信息"""
    tasks_by_status = {}
    for s in TaskStatus:
        tasks_by_status[s.value] = db.query(Task).filter(Task.status == s).count()
    comments_by_type = {}
    for ct in CommentType:
        comments_by_type[ct.value] = db.query(Comment).filter(Comment.comment_type == ct).count()
    approvals_by_status = {}
    for s in ApprovalStatus:
        approvals_by_status[s.value] = db.query(ApprovalRequest).filter(ApprovalRequest.status == s).count()
    return {
        "team_members": db.query(TeamMember).count(),
        "active_members": db.query(TeamMember).filter(TeamMember.is_active.is_(True)).count(),
        "total_tasks": db.query(Task).count(),
        "tasks_by_status": tasks_by_status,
        "total_comments": db.query(Comment).count(),
        "comments_by_type": comments_by_type,
        "resolved_comments": db.query(Comment).filter(Comment.resolved.is_(True)).count(),
        "total_approval_requests": db.query(ApprovalRequest).count(),
        "approvals_by_status": approvals_by_status,
        "total_changes": db.query(ChangeRecord).count(),
    }

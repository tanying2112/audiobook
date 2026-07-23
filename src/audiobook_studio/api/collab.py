"""FastAPI router for team collaboration features.

Implements commenting, approval, task status, and change history for team collaboration.
"""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.feedback_record import FeedbackRecord as CollaborationRecord
from ..schemas.feedback import FeedbackRecord as CollaborationRecordSchema
from .dependencies import get_async_db

router = APIRouter(prefix="/collab", tags=["collaboration"])


# Pydantic models for collaboration features
class CommentBase(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    comment_type: str = Field(..., description="comment, suggestion, question, or issue")
    task_id: Optional[int] = None
    file_path: Optional[str] = None


class CommentCreate(CommentBase):
    pass


class CommentUpdate(BaseModel):
    content: Optional[str] = Field(None, min_length=1, max_length=2000)
    comment_type: Optional[str] = None
    task_id: Optional[int] = None
    file_path: Optional[str] = None
    processed: Optional[bool] = None


class CommentResponse(CommentBase):
    id: int
    project_id: Optional[int] = None
    user_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    processed: bool = False

    model_config = ConfigDict(from_attributes=True)


class CommentListResponse(BaseModel):
    comments: List[CommentResponse]
    total: int
    processed: int
    pending: int


# ── API Endpoints ────────────────────────────────────────────────────────────


@router.get("/comments", response_model=CommentListResponse)
async def list_comments(
    project_id: Optional[int] = None,
    user_id: Optional[int] = None,
    comment_type: Optional[str] = None,
    processed: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_async_db),
):
    """List comments with optional filters."""
    query = select(CollaborationRecord)

    if project_id is not None:
        query = query.where(CollaborationRecord.project_id == project_id)
    if user_id is not None:
        query = query.where(CollaborationRecord.user_id == user_id)
    if comment_type is not None:
        query = query.where(CollaborationRecord.type == comment_type)
    if processed is not None:
        query = query.where(CollaborationRecord.processed == processed)

    # Get total count
    count_query = query
    total_result = await db.execute(count_query)
    total = len(total_result.scalars().all())

    # Get processed count
    processed_query = query.where(CollaborationRecord.processed is True)
    processed_result = await db.execute(processed_query)
    processed_count = len(processed_result.scalars().all())

    # Get paginated results
    query = query.offset(skip).limit(limit).order_by(CollaborationRecord.created_at.desc())
    result = await db.execute(query)
    comments = result.scalars().all()

    return CommentListResponse(
        comments=[CommentResponse.model_validate(c) for c in comments],
        total=total,
        processed=processed_count,
        pending=total - processed_count,
    )


@router.post("/comments", response_model=CommentResponse, status_code=status.HTTP_201_CREATED)
async def create_comment(
    comment: CommentCreate,
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new comment."""
    db_comment = CollaborationRecord(
        type=comment.comment_type,
        content=comment.content,
        task_id=comment.task_id,
        project_id=None,  # Will be set from context if available
        user_id=None,  # Will be set from auth if available
        processed=False,
    )
    db.add(db_comment)
    await db.commit()
    await db.refresh(db_comment)
    return CommentResponse.model_validate(db_comment)


@router.get("/comments/{comment_id}", response_model=CommentResponse)
async def get_comment(
    comment_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """Get a specific comment by ID."""
    result = await db.execute(select(CollaborationRecord).where(CollaborationRecord.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return CommentResponse.model_validate(comment)


@router.put("/comments/{comment_id}", response_model=CommentResponse)
async def update_comment(
    comment_id: int,
    comment_update: CommentUpdate,
    db: AsyncSession = Depends(get_async_db),
):
    """Update a comment."""
    result = await db.execute(select(CollaborationRecord).where(CollaborationRecord.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    update_data = comment_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(comment, field, value)

    await db.commit()
    await db.refresh(comment)
    return CommentResponse.model_validate(comment)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """Delete a comment."""
    result = await db.execute(select(CollaborationRecord).where(CollaborationRecord.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    await db.delete(comment)
    await db.commit()
    return None


@router.post("/comments/{comment_id}/process", response_model=CommentResponse)
async def process_comment(
    comment_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """Mark a comment as processed."""
    result = await db.execute(select(CollaborationRecord).where(CollaborationRecord.id == comment_id))
    comment = result.scalar_one_or_none()
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")

    comment.processed = True
    await db.commit()
    await db.refresh(comment)
    return CommentResponse.model_validate(comment)


# ── Task Status endpoints ─────────────────────────────────────────────────────


class TaskStatusBase(BaseModel):
    task_id: int
    status: str = Field(..., description="pending, in_progress, review, completed, blocked")
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None


class TaskStatusCreate(TaskStatusBase):
    pass


class TaskStatusUpdate(BaseModel):
    status: Optional[str] = None
    assignee_id: Optional[int] = None
    due_date: Optional[datetime] = None


class TaskStatusResponse(TaskStatusBase):
    id: int
    project_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("/tasks", response_model=List[TaskStatusResponse])
async def list_task_statuses(
    project_id: Optional[int] = None,
    status: Optional[str] = None,
    assignee_id: Optional[int] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_async_db),
):
    """List task statuses with optional filters."""
    # Note: Using CollaborationRecord as a generic table for now
    # In production, this would be a separate TaskStatus model
    query = select(CollaborationRecord).where(CollaborationRecord.type == "task_status")

    if project_id is not None:
        query = query.where(CollaborationRecord.project_id == project_id)
    if status is not None:
        query = query.where(CollaborationRecord.content.contains(f'"status": "{status}"'))
    if assignee_id is not None:
        query = query.where(CollaborationRecord.user_id == assignee_id)

    query = query.offset(skip).limit(limit).order_by(CollaborationRecord.created_at.desc())
    result = await db.execute(query)
    tasks = result.scalars().all()

    return [TaskStatusResponse.model_validate(t) for t in tasks]


@router.post("/tasks", response_model=TaskStatusResponse, status_code=status.HTTP_201_CREATED)
async def create_task_status(
    task: TaskStatusCreate,
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new task status entry."""
    import json

    db_task = CollaborationRecord(
        type="task_status",
        content=json.dumps(
            {
                "task_id": task.task_id,
                "status": task.status,
                "assignee_id": task.assignee_id,
                "due_date": task.due_date.isoformat() if task.due_date else None,
            }
        ),
        project_id=0,  # Would be set from context
        user_id=task.assignee_id,
        processed=False,
    )
    db.add(db_task)
    await db.commit()
    await db.refresh(db_task)
    return TaskStatusResponse.model_validate(db_task)


# ── Approval workflow endpoints ───────────────────────────────────────────────


class ApprovalBase(BaseModel):
    resource_type: str = Field(..., description="chapter, paragraph, audio_segment, project")
    resource_id: int
    action: str = Field(..., description="approve, reject, request_changes")
    comments: Optional[str] = None


class ApprovalCreate(ApprovalBase):
    pass


class ApprovalResponse(ApprovalBase):
    id: int
    user_id: int
    status: str = Field(..., description="pending, approved, rejected, changes_requested")
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("/approvals", response_model=List[ApprovalResponse])
async def list_approvals(
    project_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_async_db),
):
    """List approvals with optional filters."""
    query = select(CollaborationRecord).where(CollaborationRecord.type == "approval")

    if project_id is not None:
        query = query.where(CollaborationRecord.project_id == project_id)
    if resource_type is not None:
        query = query.where(CollaborationRecord.content.contains(f'"resource_type": "{resource_type}"'))
    if resource_id is not None:
        query = query.where(CollaborationRecord.content.contains(f'"resource_id": {resource_id}'))
    if status is not None:
        query = query.where(CollaborationRecord.content.contains(f'"status": "{status}"'))

    query = query.offset(skip).limit(limit).order_by(CollaborationRecord.created_at.desc())
    result = await db.execute(query)
    approvals = result.scalars().all()

    return [ApprovalResponse.model_validate(a) for a in approvals]


@router.post("/approvals", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED)
async def create_approval(
    approval: ApprovalCreate,
    db: AsyncSession = Depends(get_async_db),
):
    """Create a new approval request."""
    import json

    db_approval = CollaborationRecord(
        type="approval",
        content=json.dumps(
            {
                "resource_type": approval.resource_type,
                "resource_id": approval.resource_id,
                "action": approval.action,
                "comments": approval.comments,
                "status": "pending",
            }
        ),
        project_id=0,  # Would be set from context
        user_id=0,  # Would be set from auth
        processed=False,
    )
    db.add(db_approval)
    await db.commit()
    await db.refresh(db_approval)
    return ApprovalResponse.model_validate(db_approval)


class ApprovalDecision(BaseModel):
    decision: str = Field(..., description="approve, reject, or request_changes")
    comments: Optional[str] = None


@router.post("/approvals/{approval_id}/decide", response_model=ApprovalResponse)
async def decide_approval(
    approval_id: int,
    payload: ApprovalDecision,
    db: AsyncSession = Depends(get_async_db),
):
    """Make a decision on an approval request."""
    result = await db.execute(select(CollaborationRecord).where(CollaborationRecord.id == approval_id))
    approval = result.scalar_one_or_none()
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")

    import json

    content = json.loads(approval.content) if approval.content else {}
    content["status"] = payload.decision
    content["decision_comments"] = payload.comments
    content["decided_at"] = datetime.now(timezone.utc).isoformat()

    approval.content = json.dumps(content)
    approval.processed = True
    await db.commit()
    await db.refresh(approval)
    return ApprovalResponse.model_validate(approval)


# ── Change History endpoints ───────────────────────────────────────────────────


class ChangeHistoryBase(BaseModel):
    resource_type: str
    resource_id: int
    change_type: str = Field(..., description="create, update, delete, move, reorder")
    field_name: Optional[str] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    user_id: Optional[int] = None


class ChangeHistoryCreate(ChangeHistoryBase):
    pass


class ChangeHistoryResponse(ChangeHistoryBase):
    id: int
    project_id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


@router.get("/history", response_model=List[ChangeHistoryResponse])
async def list_change_history(
    project_id: Optional[int] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    change_type: Optional[str] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_async_db),
):
    """List change history with optional filters."""
    query = select(CollaborationRecord).where(CollaborationRecord.type == "change_history")

    if project_id is not None:
        query = query.where(CollaborationRecord.project_id == project_id)
    if resource_type is not None:
        query = query.where(CollaborationRecord.content.contains(f'"resource_type": "{resource_type}"'))
    if resource_id is not None:
        query = query.where(CollaborationRecord.content.contains(f'"resource_id": {resource_id}'))
    if change_type is not None:
        query = query.where(CollaborationRecord.content.contains(f'"change_type": "{change_type}"'))

    query = query.offset(skip).limit(limit).order_by(CollaborationRecord.created_at.desc())
    result = await db.execute(query)
    changes = result.scalars().all()

    return [ChangeHistoryResponse.model_validate(c) for c in changes]


@router.post("/history", response_model=ChangeHistoryResponse, status_code=status.HTTP_201_CREATED)
async def record_change(
    change: ChangeHistoryCreate,
    db: AsyncSession = Depends(get_async_db),
):
    """Record a change in the history."""
    import json

    db_change = CollaborationRecord(
        type="change_history",
        content=json.dumps(change.model_dump()),
        project_id=0,  # Would be set from context
        user_id=change.user_id,
        processed=True,  # History entries are always processed
    )
    db.add(db_change)
    await db.commit()
    await db.refresh(db_change)
    return ChangeHistoryResponse.model_validate(db_change)

"""
Publish job state-machine API (Sprint 3, S3-1).

Thin HTTP layer over the durable ``PublishJob`` record and the Celery publish
tasks. The frontend triggers a publish via ``POST /api/publish/start`` (which
returns a ``job_id``) and then polls ``GET /api/publish/{job_id}/status`` to
render the live state machine (PENDING -> PROCESSING -> SUCCESS/FAILED).
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth.dependencies import get_current_active_user
from ..database import get_async_session
from ..models.book import Project
from ..models.publish_job import PublishJobStatus
from ..models.user import User
from ..tasks import publish_job_repo as job_repo
from ..tasks.publish_tasks import publish_audiobookshelf_async, publish_project_async

router = APIRouter(prefix="/publish", tags=["publish-job"])


# ─────────────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────────────
class PublishStartRequest(BaseModel):
    """Request to start an async publish job."""

    project_id: int = Field(..., description="Project to publish")
    destinations: List[str] = Field(
        default_factory=lambda: ["audiobookshelf"],
        description="Targets: audiobookshelf, podcast_rss",
    )
    audiobookshelf_config: Optional[Dict[str, Any]] = None
    podcast_config: Optional[Dict[str, Any]] = None
    idempotency_key: Optional[str] = None


class PublishStartResponse(BaseModel):
    job_id: str
    status: str
    project_id: int


class PublishStatusResponse(BaseModel):
    job_id: str
    project_id: int
    user_id: Optional[int] = None
    target: str
    status: str
    retry_count: int
    progress: float
    error_log: Optional[str] = None
    result: Optional[Any] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    updated_at: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────
@router.post("/start", response_model=PublishStartResponse)
async def start_publish(
    req: PublishStartRequest,
    db=Depends(get_async_session),
    current_user: User = Depends(get_current_active_user),
) -> PublishStartResponse:
    """Create a durable publish job and dispatch it to Celery (exponential backoff)."""
    project = await db.get(Project, req.project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project {req.project_id} not found")

    destinations = req.destinations or ["audiobookshelf"]
    job = await job_repo.create_publish_job(
        project_id=req.project_id,
        target=",".join(destinations),
        user_id=getattr(current_user, "id", None),
        idempotency_key=req.idempotency_key,
        config={
            "audiobookshelf": req.audiobookshelf_config or {},
            "podcast_rss": req.podcast_config or {},
        },
    )
    if job is None:
        # Best-effort persistence failed; still try to dispatch so the pipeline runs.
        job_id = req.idempotency_key or f"publish_{req.project_id}"
    else:
        job_id = job.job_id

    # Dispatch the Celery task (idempotent job_id keeps the record linked).
    publish_project_async.delay(
        project_id=req.project_id,
        destinations=destinations,
        audiobookshelf_config=req.audiobookshelf_config,
        podcast_config=req.podcast_config,
        job_id=job_id,
    )

    return PublishStartResponse(
        job_id=job_id,
        status=PublishJobStatus.PENDING.value,
        project_id=req.project_id,
    )


@router.get("/{job_id}/status", response_model=PublishStatusResponse)
async def get_publish_job_status(
    job_id: str,
    _: User = Depends(get_current_active_user),
) -> PublishStatusResponse:
    """Poll the live state of a publish job."""
    job = await job_repo.get_publish_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Publish job {job_id} not found")
    data = job.to_dict()
    return PublishStatusResponse(**data)

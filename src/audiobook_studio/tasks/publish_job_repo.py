"""
Repository for the publish-job state machine (S3-1).

All functions are best-effort: if the database is unavailable (e.g. tests that
do not spin up a real engine, or a degraded runtime), they log and return a
graceful default instead of raising. This keeps the publish pipeline working
even when the durable job record cannot be written.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy import select

from ..database import AsyncSessionLocal
from ..models.publish_job import PublishJobState, PublishJobStatus

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_config(config: Any) -> Optional[str]:
    if config is None:
        return None
    try:
        return json.dumps(config, default=str)
    except (TypeError, ValueError):
        return str(config)


async def create_publish_job(
    project_id: int,
    target: str,
    job_id: Optional[str] = None,
    user_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
    config: Any = None,
) -> Optional[PublishJobState]:
    """Create a PENDING publish job. Returns the existing object if the
    ``job_id`` (or ``idempotency_key``) already exists, otherwise inserts.
    Returns None on failure.
    """
    try:
        async with AsyncSessionLocal() as db:
            if job_id is not None:
                existing = await db.execute(
                    select(PublishJobState).where(PublishJobState.job_id == job_id)
                )
                found = existing.scalar_one_or_none()
                if found is not None:
                    return found
            if idempotency_key is not None:
                existing = await db.execute(
                    select(PublishJobState).where(
                        PublishJobState.idempotency_key == idempotency_key
                    )
                )
                found = existing.scalar_one_or_none()
                if found is not None:
                    return found
            job = PublishJobState(
                job_id=job_id
                or f"publish_{project_id}_{int(_now().timestamp() * 1000)}",
                project_id=project_id,
                user_id=user_id,
                target=target,
                idempotency_key=idempotency_key,
                config_json=_safe_config(config),
                status=PublishJobStatus.PENDING.value,
            )
            db.add(job)
            await db.commit()
            await db.refresh(job)
            return job
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("create_publish_job failed (job not persisted): %s", exc)
        return None


async def get_publish_job(job_id: str) -> Optional[PublishJobState]:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PublishJobState).where(PublishJobState.job_id == job_id)
            )
            return result.scalar_one_or_none()
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("get_publish_job failed for %s: %s", job_id, exc)
        return None


async def _update(job_id: str, mutate: Callable[[PublishJobState], None]) -> Optional[PublishJobState]:
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PublishJobState).where(PublishJobState.job_id == job_id)
            )
            job = result.scalar_one_or_none()
            if job is None:
                return None
            mutate(job)
            job.updated_at = _now()
            await db.commit()
            await db.refresh(job)
            return job
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("publish_job update failed for %s: %s", job_id, exc)
        return None


async def mark_processing(job_id: str) -> Optional[PublishJobState]:
    return await _update(job_id, lambda j: j.mark_processing())


async def register_retry(job_id: str, error: Optional[str] = None) -> Optional[PublishJobState]:
    return await _update(job_id, lambda j: j.register_retry(error))


async def mark_success(job_id: str, result: Any = None) -> Optional[PublishJobState]:
    return await _update(job_id, lambda j: j.mark_success(result))


async def mark_failure(
    job_id: str, error: Optional[str] = None, result: Any = None
) -> Optional[PublishJobState]:
    return await _update(job_id, lambda j: j.mark_failure(error, result))

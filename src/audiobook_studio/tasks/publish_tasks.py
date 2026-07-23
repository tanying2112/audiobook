"""
Celery tasks for publish operations with Redis/DB state persistence.

Provides async publish execution with progress tracking via Celery states
and persistent job state stored in Redis (primary) with DB fallback.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from celery import states as celery_states

from ..celery_app import celery_app
from ..database import AsyncSessionLocal
from ..models.book import Project

logger = logging.getLogger(__name__)

PENDING = celery_states.PENDING
STARTED = celery_states.STARTED
SUCCESS = celery_states.SUCCESS
FAILURE = celery_states.FAILURE
RETRY = celery_states.RETRY

# Redis key prefixes for job state persistence
PUBLISH_JOB_KEY_PREFIX = "publish:job:"
PUBLISH_JOB_TTL = 86400 * 7  # 7 days TTL


async def _get_redis():
    """Get Redis client from connection pool."""
    from ..config.settings import get_settings

    settings = get_settings()
    import redis.asyncio as redis

    return redis.from_url(
        settings.REDIS_URL,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        decode_responses=True,
    )


async def _persist_job_state(job_id: str, state: Dict[str, Any]) -> None:
    """Persist job state to Redis with TTL."""
    try:
        redis = await _get_redis()
        key = f"{PUBLISH_JOB_KEY_PREFIX}{job_id}"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        await redis.setex(key, PUBLISH_JOB_TTL, json.dumps(state))
        await redis.aclose()
    except Exception as e:
        logger.warning(f"Failed to persist job state to Redis: {e}")
        # Could add DB fallback here if needed


async def _get_job_state(job_id: str) -> Optional[Dict[str, Any]]:
    """Get job state from Redis."""
    try:
        redis = await _get_redis()
        key = f"{PUBLISH_JOB_KEY_PREFIX}{job_id}"
        data = await redis.get(key)
        await redis.aclose()
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Failed to get job state from Redis: {e}")
    return None


async def _persist_job_state_db(job_id: str, project_id: int, state: Dict[str, Any], db_session=None) -> None:
    """Persist job state to database as fallback."""
    try:
        if db_session is None:
            async with AsyncSessionLocal() as db:
                await _persist_job_state_db(job_id, project_id, state, db)
            return

        # Try to import the model if it exists
        try:
            from sqlalchemy import select

            from ..models.publish import PublishJob

            result = await db_session.execute(select(PublishJob).where(PublishJob.job_id == job_id))
            job = result.scalar_one_or_none()

            if job:
                job.status = state.get("status", "pending")
                job.results = state.get("results", {})
                job.error = state.get("error")
                job.completed_at = state.get("completed_at")
                job.updated_at = datetime.now(timezone.utc)
            else:
                job = PublishJob(
                    job_id=job_id,
                    project_id=project_id,
                    status=state.get("status", "pending"),
                    destinations=state.get("destinations", []),
                    results=state.get("results", {}),
                    error=state.get("error"),
                    created_at=state.get("created_at", datetime.now(timezone.utc)),
                    completed_at=state.get("completed_at"),
                )
                db_session.add(job)

            await db_session.commit()
        except ImportError:
            # PublishJob model doesn't exist, skip DB persistence
            pass
        except Exception as e:
            logger.warning(f"Failed to persist job state to DB: {e}")
    except Exception as e:
        logger.warning(f"DB fallback persistence failed: {e}")


async def _run_publish_async(
    job_id: str,
    project_id: int,
    destinations: list[str],
    audiobookshelf_config: Optional[dict] = None,
    podcast_config: Optional[dict] = None,
) -> Dict[str, Any]:
    """Run publish operation asynchronously."""
    # Initialize job state
    job_state = {
        "job_id": job_id,
        "project_id": project_id,
        "status": "publishing",
        "destinations": destinations,
        "results": {},
        "error": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": None,
    }
    await _persist_job_state(job_id, job_state)

    results = {}
    all_success = True

    # Import local functions to avoid circular imports
    from ..api.publish import _generate_podcast_rss, _publish_to_audiobookshelf

    # Publish to Audiobookshelf
    if "audiobookshelf" in destinations:
        try:
            result = await _publish_to_audiobookshelf(
                project_id=project_id,
                config=audiobookshelf_config or {},
            )
            results["audiobookshelf"] = {
                "success": True,
                "book_url": result.get("book_url"),
                "item_id": result.get("item_id"),
                "uploaded_files": result.get("uploaded_files", 0),
                "total_size_bytes": result.get("total_size_bytes", 0),
            }
        except Exception as e:
            logger.error(f"Audiobookshelf publish failed: {e}")
            results["audiobookshelf"] = {
                "success": False,
                "error": str(e),
            }
            all_success = False

    # Generate Podcast RSS
    if "podcast_rss" in destinations:
        try:
            result = await _generate_podcast_rss(
                project_id=project_id,
                config=podcast_config or {},
            )
            results["podcast_rss"] = {
                "success": True,
                "rss_url": result.get("rss_url"),
                "episode_count": result.get("episode_count", 0),
            }
        except Exception as e:
            logger.error(f"Podcast RSS generation failed: {e}")
            results["podcast_rss"] = {
                "success": False,
                "error": str(e),
            }
            all_success = False

    # Update final state
    job_state["results"] = results
    job_state["completed_at"] = datetime.now(timezone.utc).isoformat()
    job_state["status"] = "completed" if all_success else "failed"
    if not all_success:
        errors = [r.get("error") for r in results.values() if r.get("error")]
        job_state["error"] = "; ".join(errors)

    await _persist_job_state(job_id, job_state)

    # Also persist to DB
    await _persist_job_state_db(job_id, project_id, job_state)

    return job_state


@celery_app.task(
    bind=True,
    name="src.audiobook_studio.tasks.publish_tasks.publish_project_async",
    max_retries=3,
    default_retry_delay=60,
)
def publish_project_async(
    self,
    project_id: int,
    destinations: list[str],
    audiobookshelf_config: Optional[dict] = None,
    podcast_config: Optional[dict] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async task to publish a completed project to destinations.

    Args:
        project_id: Project ID to publish
        destinations: List of destinations ["audiobookshelf", "podcast_rss"]
        audiobookshelf_config: Audiobookshelf server config
        podcast_config: Podcast RSS feed config
        job_id: Optional job ID (generated if not provided)

    Returns:
        Dict with job_id, status, results, error
    """
    task_id = self.request.id
    job_id = job_id or f"publish_{project_id}_{int(datetime.now().timestamp())}"
    logger.info(f"[{task_id}] Starting publish for project {project_id}, job {job_id}")

    try:
        import asyncio

        result = asyncio.run(
            _run_publish_async(
                job_id=job_id,
                project_id=project_id,
                destinations=destinations,
                audiobookshelf_config=audiobookshelf_config,
                podcast_config=podcast_config,
            )
        )

        response = {
            "job_id": job_id,
            "task_id": task_id,
            "status": result["status"],
            "results": result.get("results", {}),
            "error": result.get("error"),
            "project_id": project_id,
        }

        logger.info(f"[{task_id}] Publish completed: {result['status']}")
        return response

    except Exception as e:
        logger.exception(f"[{task_id}] Publish failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {
            "job_id": job_id,
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "project_id": project_id,
        }


@celery_app.task(
    bind=True,
    name="src.audiobook_studio.tasks.publish_tasks.publish_audiobookshelf_async",
    max_retries=3,
    default_retry_delay=60,
)
def publish_audiobookshelf_async(
    self,
    project_id: int,
    config: Dict[str, Any],
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async task to publish to Audiobookshelf only.

    Args:
        project_id: Project ID to publish
        config: Audiobookshelf configuration
        job_id: Optional job ID

    Returns:
        Dict with job_id, status, book_url, item_id, etc.
    """
    task_id = self.request.id
    job_id = job_id or f"abs_{project_id}_{int(datetime.now().timestamp())}"
    logger.info(f"[{task_id}] Starting Audiobookshelf publish for project {project_id}")

    try:
        import asyncio

        async def _run():
            job_state = {
                "job_id": job_id,
                "project_id": project_id,
                "status": "publishing",
                "destinations": ["audiobookshelf"],
                "results": {},
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": None,
            }
            await _persist_job_state(job_id, job_state)

            try:
                result = await publish_to_audiobookshelf(
                    project_id=project_id,
                    config=config,
                )
                job_state["results"]["audiobookshelf"] = {
                    "success": True,
                    "book_url": result.get("book_url"),
                    "item_id": result.get("item_id"),
                    "uploaded_files": result.get("uploaded_files", 0),
                    "total_size_bytes": result.get("total_size_bytes", 0),
                }
                job_state["status"] = "completed"
            except Exception as e:
                logger.error(f"Audiobookshelf publish failed: {e}")
                job_state["results"]["audiobookshelf"] = {
                    "success": False,
                    "error": str(e),
                }
                job_state["status"] = "failed"
                job_state["error"] = str(e)

            job_state["completed_at"] = datetime.now(timezone.utc).isoformat()
            await _persist_job_state(job_id, job_state)
            await _persist_job_state_db(job_id, project_id, job_state)
            return job_state

        result = asyncio.run(_run())

        response = {
            "job_id": job_id,
            "task_id": task_id,
            "status": result["status"],
            "results": result.get("results", {}),
            "error": result.get("error"),
            "project_id": project_id,
        }

        logger.info(f"[{task_id}] Audiobookshelf publish completed: {result['status']}")
        return response

    except Exception as e:
        logger.exception(f"[{task_id}] Audiobookshelf publish failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {
            "job_id": job_id,
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "project_id": project_id,
        }


@celery_app.task(
    bind=True,
    name="src.audiobook_studio.tasks.publish_tasks.generate_podcast_rss_async",
    max_retries=3,
    default_retry_delay=30,
)
def generate_podcast_rss_async(
    self,
    project_id: int,
    config: Dict[str, Any],
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Async task to generate Podcast RSS feed.

    Args:
        project_id: Project ID
        config: Podcast RSS configuration
        job_id: Optional job ID

    Returns:
        Dict with job_id, status, rss_url, episode_count
    """
    task_id = self.request.id
    job_id = job_id or f"rss_{project_id}_{int(datetime.now().timestamp())}"
    logger.info(f"[{task_id}] Starting Podcast RSS generation for project {project_id}")

    try:
        import asyncio

        from ..publish.podcast import generate_podcast_rss

        async def _run():
            job_state = {
                "job_id": job_id,
                "project_id": project_id,
                "status": "generating",
                "destinations": ["podcast_rss"],
                "results": {},
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": None,
            }
            await _persist_job_state(job_id, job_state)

            try:
                result = await generate_podcast_rss(
                    project_id=project_id,
                    config=config,
                )
                job_state["results"]["podcast_rss"] = {
                    "success": True,
                    "rss_url": result.get("rss_url"),
                    "episode_count": result.get("episode_count", 0),
                }
                job_state["status"] = "completed"
            except Exception as e:
                logger.error(f"Podcast RSS generation failed: {e}")
                job_state["results"]["podcast_rss"] = {
                    "success": False,
                    "error": str(e),
                }
                job_state["status"] = "failed"
                job_state["error"] = str(e)

            job_state["completed_at"] = datetime.now(timezone.utc).isoformat()
            await _persist_job_state(job_id, job_state)
            await _persist_job_state_db(job_id, project_id, job_state)
            return job_state

        result = asyncio.run(_run())

        response = {
            "job_id": job_id,
            "task_id": task_id,
            "status": result["status"],
            "results": result.get("results", {}),
            "error": result.get("error"),
            "project_id": project_id,
        }

        logger.info(f"[{task_id}] Podcast RSS generation completed: {result['status']}")
        return response

    except Exception as e:
        logger.exception(f"[{task_id}] Podcast RSS generation failed: {e}")
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        return {
            "job_id": job_id,
            "task_id": task_id,
            "status": "failed",
            "error": str(e),
            "project_id": project_id,
        }


@celery_app.task(name="src.audiobook_studio.tasks.publish_tasks.get_publish_status")
def get_publish_status(job_id: str) -> Dict[str, Any]:
    """
    Get the status of a publish job by job ID.

    Checks Redis first, falls back to Celery result backend.

    Args:
        job_id: Publish job ID

    Returns:
        Dict with job_id, state, results, error
    """
    import asyncio

    async def _get_status():
        # Try Redis first (persisted state)
        state = await _get_job_state(job_id)
        if state:
            return {
                "job_id": job_id,
                "state": state.get("status", "unknown"),
                "results": state.get("results", {}),
                "error": state.get("error"),
                "created_at": state.get("created_at"),
                "completed_at": state.get("completed_at"),
                "source": "redis",
            }

        # Fallback: try to get from Celery result backend if we have a task ID
        # Job IDs are like "publish_123_1234567890" or "abs_123_1234567890"
        # But we don't have a direct mapping from job_id to task_id
        # So just return not found
        return {
            "job_id": job_id,
            "state": "not_found",
            "results": {},
            "error": "Job not found in Redis or Celery backend",
            "source": "none",
        }

    return asyncio.run(_get_status())


@celery_app.task(name="src.audiobook_studio.tasks.publish_tasks.get_publish_history")
def get_publish_history(project_id: int) -> Dict[str, Any]:
    """
    Get publish history for a project.

    Queries Redis for all job keys matching the project.

    Args:
        project_id: Project ID

    Returns:
        Dict with project_id and list of history items
    """
    import asyncio

    async def _get_history():
        try:
            redis = await _get_redis()
            pattern = f"{PUBLISH_JOB_KEY_PREFIX}*"
            keys = []
            async for key in redis.scan_iter(match=pattern, count=100):
                keys.append(key)

            history = []
            for key in keys:
                data = await redis.get(key)
                if data:
                    job = json.loads(data)
                    if job.get("project_id") == project_id:
                        history.append(
                            {
                                "job_id": job.get("job_id"),
                                "status": job.get("status"),
                                "destinations": job.get("destinations", []),
                                "created_at": job.get("created_at"),
                                "completed_at": job.get("completed_at"),
                            }
                        )

            await redis.aclose()

            # Sort by created_at descending
            history.sort(key=lambda x: x.get("created_at", ""), reverse=True)

            return {"project_id": project_id, "history": history}
        except Exception as e:
            logger.warning(f"Failed to get publish history from Redis: {e}")
            return {"project_id": project_id, "history": [], "error": str(e)}

    return asyncio.run(_get_history())


# Export all
__all__ = [
    "publish_project_async",
    "publish_audiobookshelf_async",
    "generate_podcast_rss_async",
    "get_publish_status",
    "get_publish_history",
]

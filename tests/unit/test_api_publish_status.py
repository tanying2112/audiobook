"""Tests for the S3-1 publish-job status/start HTTP endpoints.

The endpoints are exercised directly (not via TestClient) with the DB session
and Celery dispatch mocked, so no broker/Redis/network is touched.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.audiobook_studio.api import publish_job as publish_job_api
from src.audiobook_studio.models.publish_job import PublishJobState, PublishJobStatus


def _fake_job(status=PublishJobStatus.SUCCESS, result=None):
    job = PublishJobState(job_id="publish_1_xyz", project_id=1, target="audiobookshelf")
    if status == PublishJobStatus.SUCCESS:
        job.mark_success(result or {"rss_url": "http://x/rss"})
    elif status == PublishJobStatus.FAILED:
        job.mark_failure("boom")
    elif status == PublishJobStatus.PROCESSING:
        job.mark_processing()
    else:
        job.mark_processing()  # PENDING stays PENDING; call processing for realism
    return job


@pytest.mark.asyncio
async def test_start_publish_creates_job_and_dispatches_celery():
    req = publish_job_api.PublishStartRequest(
        project_id=1, destinations=["audiobookshelf"]
    )
    db = MagicMock()
    db.get = AsyncMock(return_value=MagicMock())  # project exists
    user = MagicMock()
    user.id = 7

    with patch.object(
        publish_job_api.job_repo, "create_publish_job", new=AsyncMock(return_value=_fake_job())
    ) as m_create, patch.object(
        publish_job_api.publish_project_async, "delay"
    ) as m_delay:
        resp = await publish_job_api.start_publish(req, db=db, current_user=user)

        assert resp.job_id == "publish_1_xyz"
        assert resp.status == PublishJobStatus.PENDING.value
        assert resp.project_id == 1
        m_create.assert_awaited_once()
        m_delay.assert_called_once()
        # the durable job_id is propagated to the Celery task for status linkage
        assert m_delay.call_args.kwargs["job_id"] == "publish_1_xyz"
        assert m_delay.call_args.kwargs["project_id"] == 1


@pytest.mark.asyncio
async def test_start_publish_404_when_project_missing():
    req = publish_job_api.PublishStartRequest(project_id=999)
    db = MagicMock()
    db.get = AsyncMock(return_value=None)
    user = MagicMock()
    with pytest.raises(HTTPException) as exc:
        await publish_job_api.start_publish(req, db=db, current_user=user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_status_endpoint_returns_state():
    user = MagicMock()
    with patch.object(
        publish_job_api.job_repo, "get_publish_job", new=AsyncMock(return_value=_fake_job())
    ):
        resp = await publish_job_api.get_publish_job_status("publish_1_xyz", _=user)
        assert resp.job_id == "publish_1_xyz"
        assert resp.status == PublishJobStatus.SUCCESS.value
        assert resp.result["rss_url"] == "http://x/rss"
        assert resp.retry_count == 0


@pytest.mark.asyncio
async def test_status_endpoint_failed_state():
    user = MagicMock()
    with patch.object(
        publish_job_api.job_repo,
        "get_publish_job",
        new=AsyncMock(return_value=_fake_job(status=PublishJobStatus.FAILED)),
    ):
        resp = await publish_job_api.get_publish_job_status("publish_1_xyz", _=user)
        assert resp.status == PublishJobStatus.FAILED.value
        assert "boom" in (resp.error_log or "")


@pytest.mark.asyncio
async def test_status_endpoint_404_when_missing():
    user = MagicMock()
    with patch.object(
        publish_job_api.job_repo, "get_publish_job", new=AsyncMock(return_value=None)
    ):
        with pytest.raises(HTTPException) as exc:
            await publish_job_api.get_publish_job_status("nope", _=user)
        assert exc.value.status_code == 404

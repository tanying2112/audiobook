"""Tests for S3-1 publish-job state machine integration in Celery tasks.

Focus: exponential backoff policy and the durable state-machine transitions
(PENDING -> PROCESSING -> SUCCESS / FAILED) around a single publish attempt.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.tasks import publish_tasks


def test_exponential_backoff_grows_and_caps():
    assert publish_tasks.exponential_backoff_countdown(0) == 5
    assert publish_tasks.exponential_backoff_countdown(1) == 10
    assert publish_tasks.exponential_backoff_countdown(2) == 20
    assert publish_tasks.exponential_backoff_countdown(3) == 40
    # capped at EXPONENTIAL_BACKOFF_MAX_SECONDS (300)
    assert publish_tasks.exponential_backoff_countdown(6) == 300
    assert publish_tasks.exponential_backoff_countdown(100) == 300


@pytest.mark.asyncio
async def test_state_machine_success_marks_processing_then_success():
    self = MagicMock()
    self.request.retries = 0
    self.max_retries = 3
    with patch("src.audiobook_studio.tasks.publish_tasks.mark_processing") as m_proc, patch(
        "src.audiobook_studio.tasks.publish_tasks.mark_success"
    ) as m_succ, patch(
        "src.audiobook_studio.tasks.publish_tasks.register_retry"
    ) as m_retry, patch(
        "src.audiobook_studio.tasks.publish_tasks.mark_failure"
    ) as m_fail:
        async def run_coro():
            return {"status": "completed"}

        result = await publish_tasks._run_publish_job_state_machine(
            self, "j1", 1, run_coro
        )
        assert result["status"] == "completed"
        m_proc.assert_awaited_once()
        m_succ.assert_awaited_once()
        m_retry.assert_not_awaited()
        m_fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_state_machine_retry_reraises_and_registers():
    self = MagicMock()
    self.request.retries = 0
    self.max_retries = 3
    with patch("src.audiobook_studio.tasks.publish_tasks.mark_processing"), patch(
        "src.audiobook_studio.tasks.publish_tasks.register_retry"
    ) as m_retry, patch("src.audiobook_studio.tasks.publish_tasks.mark_success"), patch(
        "src.audiobook_studio.tasks.publish_tasks.mark_failure"
    ):
        async def run_coro():
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await publish_tasks._run_publish_job_state_machine(self, "j1", 1, run_coro)
        m_retry.assert_awaited_once()


@pytest.mark.asyncio
async def test_state_machine_exhausted_retries_marks_failure():
    self = MagicMock()
    self.request.retries = 3  # exhausted
    self.max_retries = 3
    with patch("src.audiobook_studio.tasks.publish_tasks.mark_processing"), patch(
        "src.audiobook_studio.tasks.publish_tasks.mark_success"
    ) as m_succ, patch("src.audiobook_studio.tasks.publish_tasks.register_retry") as m_retry, patch(
        "src.audiobook_studio.tasks.publish_tasks.mark_failure"
    ) as m_fail:
        async def run_coro():
            raise RuntimeError("boom")

        result = await publish_tasks._run_publish_job_state_machine(
            self, "j1", 1, run_coro
        )
        assert result["status"] == "failed"
        m_succ.assert_not_awaited()
        m_retry.assert_not_awaited()  # exhausted -> no more register_retry
        m_fail.assert_awaited_once()


def test_publish_project_async_uses_exponential_backoff_on_retry():
    """When the run raises, the task must re-queue with an exponential countdown."""
    mock_self = MagicMock()
    mock_self.request.id = "task_123"
    mock_self.request.retries = 1
    mock_self.max_retries = 3
    test_exception = Exception("Temporary failure")
    captured = {}

    def _retry(**kwargs):
        captured.update(kwargs)
        raise kwargs.get("exc", test_exception)

    mock_self.retry.side_effect = _retry

    with patch("asyncio.run") as mock_run:
        mock_run.side_effect = test_exception
        with pytest.raises(Exception):
            publish_tasks.publish_project_async(
                mock_self, project_id=1, destinations=["audiobookshelf"]
            )
        assert mock_self.retry.called
        # retries=1 -> countdown = 5 * 2**1 = 10
        assert captured.get("countdown") == publish_tasks.exponential_backoff_countdown(1)
        assert captured.get("countdown") == 10


def test_publish_audiobookshelf_async_uses_exponential_backoff_on_retry():
    mock_self = MagicMock()
    mock_self.request.id = "task_123"
    mock_self.request.retries = 2
    mock_self.max_retries = 3
    test_exception = Exception("ABS down")
    captured = {}

    def _retry(**kwargs):
        captured.update(kwargs)
        raise kwargs.get("exc", test_exception)

    mock_self.retry.side_effect = _retry
    with patch("asyncio.run") as mock_run:
        mock_run.side_effect = test_exception
        with pytest.raises(Exception):
            publish_tasks.publish_audiobookshelf_async(
                mock_self, project_id=1, config={"server_url": "x"}
            )
        assert mock_self.retry.called
        # retries=2 -> countdown = 5 * 2**2 = 20
        assert captured.get("countdown") == 20


def test_generate_podcast_rss_async_uses_exponential_backoff_on_retry():
    mock_self = MagicMock()
    mock_self.request.id = "task_123"
    mock_self.request.retries = 0
    mock_self.max_retries = 3
    test_exception = Exception("RSS gen failed")
    captured = {}

    def _retry(**kwargs):
        captured.update(kwargs)
        raise kwargs.get("exc", test_exception)

    mock_self.retry.side_effect = _retry
    with patch("asyncio.run") as mock_run:
        mock_run.side_effect = test_exception
        with pytest.raises(Exception):
            publish_tasks.generate_podcast_rss_async(
                mock_self, project_id=1, config={"title": "x"}
            )
        assert mock_self.retry.called
        assert captured.get("countdown") == 5

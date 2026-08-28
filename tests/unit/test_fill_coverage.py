import asyncio
from unittest import mock

import pytest

import audiobook_studio.tasks.publish_tasks as PT
import audiobook_studio.utils.redis_pool as RP


def test_redis_pool():
    cfg = {
        "url": "redis://localhost:6379/0",
        "max_connections": 5,
        "socket_keepalive": True,
        "retry_on_timeout": True,
        "pool_size": 5,
    }
    async_pool = mock.MagicMock()
    async_pool.disconnect = mock.AsyncMock()
    sync_pool = mock.MagicMock()
    with (
        mock.patch("audiobook_studio.config.get_unified_redis_config", return_value=cfg),
        mock.patch("redis.asyncio.ConnectionPool.from_url", return_value=async_pool),
        mock.patch("redis.ConnectionPool.from_url", return_value=sync_pool),
    ):
        pool = RP.get_redis_pool()
        assert pool is async_pool
        assert RP.get_redis_pool() is pool  # singleton
        RP.reset_redis_pool()
        r = asyncio.run(RP.get_redis())
        assert r is not None
        sr = RP.get_sync_redis()
        assert sr is not None
        RP.reset_redis_pool()


def test_publish_tasks_backoff():
    assert PT.exponential_backoff_countdown(0) >= 0
    assert PT.exponential_backoff_countdown(3) > PT.exponential_backoff_countdown(0)
    assert PT.exponential_backoff_countdown(10) >= 0


def test_publish_status_shape():
    status = PT.get_publish_status("missing")
    assert isinstance(status, dict)
    assert "state" in status and "job_id" in status
    history = PT.get_publish_history(1)
    assert isinstance(history, dict)

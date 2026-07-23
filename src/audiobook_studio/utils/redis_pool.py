"""Redis connection pool singleton (PERF-003).

Provides a single shared async ConnectionPool so all callers reuse connections
rather than creating new pools per call.  Config is driven by Settings.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_pool: Optional["ConnectionPool"] = None


def get_redis_pool() -> "ConnectionPool":
    """Return the singleton async Redis ConnectionPool, creating it on first call.

    Pool parameters (max_connections, socket_keepalive, retry_on_timeout) are
    read from the application Settings once at creation time.
    """
    global _pool
    if _pool is not None:
        return _pool

    from redis.asyncio import ConnectionPool

    from ..config import get_settings

    s = get_settings()
    _pool = ConnectionPool.from_url(
        s.REDIS_URL,
        max_connections=s.REDIS_MAX_CONNECTIONS,
        socket_keepalive=s.REDIS_SOCKET_KEEPALIVE,
        retry_on_timeout=s.REDIS_RETRY_ON_TIMEOUT,
        decode_responses=True,
    )
    logger.info(
        f"Redis pool created: max_connections={s.REDIS_MAX_CONNECTIONS}, "
        f"pool_size={s.REDIS_POOL_SIZE}, keepalive={s.REDIS_SOCKET_KEEPALIVE}s"
    )
    return _pool


def reset_redis_pool() -> None:
    """Close and reset the singleton pool (useful for testing)."""
    global _pool
    if _pool is not None:
        _pool.disconnect()
        _pool = None
        logger.debug("Redis pool closed and reset")


async def get_redis() -> "Redis":
    """Return an async Redis client backed by the shared pool."""
    from redis.asyncio import Redis

    pool = get_redis_pool()
    return Redis(connection_pool=pool)


def get_sync_redis() -> "Redis":
    """Return a sync Redis client (for Celery / sync workers) backed by a sync pool."""
    from redis import ConnectionPool as SyncConnectionPool
    from redis import Redis as SyncRedis

    from ..config import get_settings

    s = get_settings()
    sync_pool = SyncConnectionPool.from_url(
        s.REDIS_URL,
        max_connections=s.REDIS_MAX_CONNECTIONS,
        socket_keepalive=s.REDIS_SOCKET_KEEPALIVE,
        retry_on_timeout=s.REDIS_RETRY_ON_TIMEOUT,
        decode_responses=True,
    )
    return SyncRedis(connection_pool=sync_pool)
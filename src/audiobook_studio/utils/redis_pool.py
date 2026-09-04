"""Redis connection pool singleton (PERF-003).

Provides a single shared async ConnectionPool so all callers reuse connections
rather than creating new pools per call.  Config is driven by UnifiedConfig.
"""

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from redis import Redis as SyncRedis
    from redis.asyncio import ConnectionPool, Redis

logger = logging.getLogger(__name__)

_pool: Optional["ConnectionPool"] = None


def get_redis_pool() -> "ConnectionPool":
    """Return the singleton async Redis ConnectionPool, creating it on first call.

    Pool parameters (max_connections, socket_keepalive, retry_on_timeout) are
    read from the UnifiedConfig once at creation time.
    """
    global _pool
    if _pool is not None:
        return _pool

    from redis.asyncio import ConnectionPool

    from ..config import get_unified_redis_config

    redis_config = get_unified_redis_config()
    _pool = ConnectionPool.from_url(
        redis_config["url"],
        max_connections=redis_config["max_connections"],
        socket_keepalive=redis_config["socket_keepalive"],
        retry_on_timeout=redis_config["retry_on_timeout"],
        decode_responses=True,
    )
    logger.info(
        f"Redis pool created: max_connections={redis_config['max_connections']}, "
        f"pool_size={redis_config['pool_size']}, keepalive={redis_config['socket_keepalive']}s"
    )
    return _pool


def reset_redis_pool() -> None:
    """Close and reset the singleton pool (useful for testing)."""
    global _pool
    if _pool is not None:
        import asyncio

        asyncio.run(_pool.disconnect())
        _pool = None
        logger.debug("Redis pool closed and reset")


async def get_redis() -> "Redis":
    """Return an async Redis client backed by the shared pool."""
    from redis.asyncio import Redis

    pool = get_redis_pool()
    return Redis(connection_pool=pool)


def get_sync_redis() -> "SyncRedis":
    """Return a sync Redis client (for Celery / sync workers) backed by a sync pool."""
    from redis import ConnectionPool as SyncConnectionPool
    from redis import Redis as SyncRedis

    from ..config import get_unified_redis_config

    redis_config = get_unified_redis_config()
    sync_pool = SyncConnectionPool.from_url(
        redis_config["url"],
        max_connections=redis_config["max_connections"],
        socket_keepalive=redis_config["socket_keepalive"],
        retry_on_timeout=redis_config["retry_on_timeout"],
        decode_responses=True,
    )
    return SyncRedis(connection_pool=sync_pool)

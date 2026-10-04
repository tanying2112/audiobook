# PERF-003: Redis 连接池调优

## 严重级别
**P1 - Medium** (并发稳定性)

## 问题描述
`src/audiobook_studio/api/upload.py:150` `redis.ConnectionPool.from_url()` 无 `max_connections`、`socket_keepalive`、`retry_on_timeout` 配置。高并发上传时连接耗尽、Keep-Alive 失效导致 `ConnectionResetError`。

## 修复方案
1. `config/settings.py` 新增：
   ```python
   REDIS_POOL_SIZE: int = Field(default=20, alias="REDIS_POOL_SIZE")
   REDIS_SOCKET_KEEPALIVE: int = Field(default=30, alias="REDIS_SOCKET_KEEPALIVE")
   REDIS_RETRY_ON_TIMEOUT: bool = Field(default=True, alias="REDIS_RETRY_ON_TIMEOUT")
   REDIS_MAX_CONNECTIONS: int = Field(default=50, alias="REDIS_MAX_CONNECTIONS")
   ```
2. 单例连接池模块 `src/audiobook_studio/utils/redis_pool.py`：
   ```python
   from redis.asyncio import ConnectionPool
   from src.audiobook_studio.config import get_settings
   
   _pool: ConnectionPool | None = None
   
   def get_redis_pool() -> ConnectionPool:
       global _pool
       if _pool is None:
           s = get_settings()
           _pool = ConnectionPool.from_url(
               s.REDIS_URL,
               max_connections=s.REDIS_MAX_CONNECTIONS,
               socket_keepalive=s.REDIS_SOCKET_KEEPALIVE,
               retry_on_timeout=s.REDIS_RETRY_ON_TIMEOUT,
               decode_responses=True,
           )
       return _pool
   ```
3. 所有 `redis.from_url()` / `ConnectionPool.from_url()` 替换为 `get_redis_pool()`

## 验收标准
- [ ] Locust 并发 100 上传：连接复用率 > 90% (`redis-cli info clients`)
- [ ] 无 `ConnectionResetError` / `ConnectionPool exhausted` 错误
- [ ] 连接池指标暴露 `/metrics` (redis_active_connections, redis_idle_connections)

## 关联文件
- `src/audiobook_studio/config/settings.py`
- 新建 `src/audiobook_studio/utils/redis_pool.py`
- `src/audiobook_studio/api/upload.py`
- `src/audiobook_studio/celery_app.py`
- `src/audiobook_studio/tasks/*.py`
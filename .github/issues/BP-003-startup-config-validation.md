# BP-003: 启动时配置探活 (DB/Redis/模型路径)

## 严重级别
**P1 - Medium** (可靠性 / 故障快速失败)

## 问题描述
`config/settings.py` 仅校验 `JWT_SECRET_KEY` 和 `CORS`，缺失：
- `DATABASE_URL` 连通性 (`engine.connect()`)
- `REDIS_URL` ping (`redis.ping()`)
- `KOKORO_MODEL_PATH` / `VOXCPM2_MODEL_PATH` 文件存在性
- `OPENAI_API_KEY` 等 LLM 密钥格式基础校验

容器启动成功但依赖不可用，导致 `/health` 通过但业务 500。

## 修复方案
1. `settings.validate_runtime_dependencies()` 新增异步校验方法
2. `main.py` `lifespan` 中 `await settings.validate_runtime_dependencies()`
3. 区分 `liveness` (进程活) vs `readiness` (依赖就绪)：
   - `/health/live` → 进程存活
   - `/health/ready` → 依赖就绪（含模型加载完成）
4. 失败时结构化日志 + 明确退出码

## 验收标准
- [ ] `docker run` 无 DB 时 10s 内退出，日志含 `DATABASE_URL connect failed`
- [ ] `/health/live` 200，`/health/ready` 503 (依赖未就绪)
- [ ] 模型文件缺失时 `/health/ready` 返回 `model_not_found` 错误码
- [ ] `pytest tests/unit/test_health_endpoints.py` 新增 5 个 case 全绿

## 关联文件
- `src/audiobook_studio/config/settings.py`
- `src/audiobook_studio/main.py` (lifespan)
- `src/audiobook_studio/api/monitoring.py` (health endpoints)
- `tests/unit/test_health_endpoints.py` (新建)
# PERF-001: 模型懒加载 + 预热端点

## 严重级别
**P1 - High** (冷启动延迟 / 水平扩容)

## 问题描述
`src/audiobook_studio/tts/kokoro_backend.py:45` `voxcpm2_backend.py:60` `__init__` 同步加载 ONNX/PyTorch 模型 (2-5s)，阻塞事件循环，导致：
- 容器启动 >8s
- 健康检查超时
- K8s HPA 扩容冷启动慢

## 修复方案
1. 移除 `__init__` 模型加载，改为 `async def lazy_load()` + `asyncio.to_thread(load_model)`
2. 实例级 `_loaded: bool` 守卫，首次推理前自动加载
3. 新增 `POST /admin/warmup` 端点：
   ```python
   @router.post("/admin/warmup")
   async def warmup(background_tasks: BackgroundTasks):
       for backend in tts_backends:  # 并发预热
           background_tasks.add_task(backend.lazy_load)
       return {"status": "warming_up"}
   ```
4. `/health/ready` 检查 `all(backend._loaded for backend in tts_backends)`

## 验收标准
- [ ] 容器冷启动 `< 3s` (含 uvicorn 就绪)
- [ ] `/health/live` 即时 200，`/health/ready` 模型加载后 200
- [ ] 并发 10 请求首次推理无 503/超时
- [ ] Locust 压测：冷启动 + 预热后 p95 < 500ms

## 关联文件
- `src/audiobook_studio/tts/kokoro_backend.py`
- `src/audiobook_studio/tts/voxcpm2_backend.py`
- `src/audiobook_studio/tts/edge_tts_engine.py` (无模型加载，仅预热连接)
- `src/audiobook_studio/api/monitoring.py` (health endpoints)
- `src/audiobook_studio/api/admin.py` (新建 warmup 端点)
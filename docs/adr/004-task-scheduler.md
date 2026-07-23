# ADR-004: 任务调度引擎

## 状态
Accepted (2026-06-18, implemented)

## 背景
Audiobook Studio 的 Pipeline 包含多个长耗时阶段：
- **TTS 合成**: 单段落 3-30s，整书可达数百段落 → 数十分钟
- **音频后处理**: FFmpeg 闪避/合并/M4B 封装 → 数十秒至数分钟
- **质量评审**: LLM Judge 多维度打分 → 数秒/段落
- **导出发布**: M4B 封装 + Audiobookshelf 上传 → 数分钟

这些操作不能阻塞 HTTP 请求响应周期，且需要：
- 异步执行 + 进度可查询
- 失败重试 + 幂等保护
- 并发控制 (GPU Worker 有限)
- 监控可观测 (任务状态、耗时、队列深度)

约束：
- MVP 阶段尽量复用成熟生态，不自研调度器
- 与 FastAPI 异步模型兼容
- Redis 已在技术栈中 (缓存/锁/状态)

## 决策
**选定 Celery + Redis (Broker/Backend) + Flower 监控**

```
┌──────────────┐     enqueue     ┌──────────────┐
│  FastAPI     │ ──────────────→ │  Redis       │
│  (web)       │                 │  (broker)    │
└──────────────┘                 └──────┬───────┘
                                        │ dequeue
                               ┌────────▼───────┐
                               │  Celery Worker │
                               │  (tts/export)  │
                               └────────┬───────┘
                                        │ result
                               ┌────────▼───────┐
                               │  Redis         │
                               │  (backend)     │
                               └────────┬───────┘
                                        │ poll
                               ┌────────▼───────┐
                               │  FastAPI       │ ← GET /tasks/{id}
                               │  Flower :5555  │ ← 监控面板
                               └────────────────┘
```

关键参数：
| 参数 | 值 | 理由 |
|------|-----|------|
| Broker | Redis (redis://redis:6379/0) | 已在栈中、性能足够、自带持久化 |
| Result Backend | Redis (同实例 db 1) | 任务结果 TTL 1h，不长期占用内存 |
| 并发 (worker) | 4 (TTS) / 2 (export) | GPU 并发限制 + ffmpeg CPU 控制 |
| 幂等 | Redis Lua script (SET NX + EX) | 相同 text+voice_id+prosody → 相同结果 |
| 重试 | tenacity exponential jitter | 最大 3 次，避让 API rate limit |
| 监控 | Flower (:5555) + Prometheus metrics | 队列深度、失败率、平均耗时 |

## 替代方案

| 方案 | 优势 | 劣势 | 判定 |
|------|------|------|------|
| **RQ (Redis Queue)** | 比 Celery 更轻、配置更简 | 无内置结果后端、无任务路由、社区较小 | ❌ 缺少生产所需的任务路由和监控 |
| **Dramatiq** | 性能优秀、中间件模式好 | 生态不如 Celery、Flower 不支持 | ⬜ 值得关注但当前生态不够成熟 |
| **Temporal** | 工作流引擎、SAGA、极强容错 | 重依赖 (Temporal Server)、学习曲线陡 | ❌ MVP 阶段过度设计; 适合复杂多步骤 Saga |
| **自研 (asyncio.create_task + Redis 状态)** | 零额外依赖 | 缺乏持久化、无 Worker 隔离、无监控 | ❌ 重复造轮子; 生产不可靠 |

## 后果

### 正面
- Celery 成熟生态: 重试、路由、任务链、速率限制、Beat 定时任务
- Flower 实时监控面板: 任务成功率、队列长度、Worker 状态
- Redis Lua 脚本提供无锁原子幂等 + 并发控制
- 任务检查点支持断点续跑 (checkpoint JSON in Redis)

### 负面
- Celery 是重依赖 (~15MB) + Redis 单点 (未来需 Sentinel/Cluster)
- Worker 进程管理增加运维复杂度
- 本地开发需 Docker Redis + Celery Worker 双进程

### 后续行动
- 评估 Redis Sentinel 高可用方案
- 评估 Dramatiq 替代 Celery (简化 Worker 管理)
- 大模型 (VoxCPM2) 远程调度不使用 Celery，走独立 HTTP RPC + Cloudflare Tunnel

## 关联
- Implementation: `src/audiobook_studio/celery_app.py`, `tasks/tts_tasks.py`, `tasks/export_tasks.py`
- Redis: [`PERF-003`](../../.github/issues/PERF-003-redis-pool-tuning.md), `utils/redis_pool.py`
- Monitoring: Flower (:5555), `api/monitoring.py` Prometheus metrics
- Related issue: [#31](../../.github/issues/PERF-003-redis-pool-tuning.md)
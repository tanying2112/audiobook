# ADR-002: TTS 后端编排策略

## 状态
Accepted (2026-06-15, implemented; revised 2026-07-20 with EngineRegistry)

## 背景
有声书制作需要文本转语音 (TTS) 能力，且需求多样：
- 本地离线场景 (完全本地 CPU/GPU 推理，无网络依赖)
- 云端高质量场景 (商业 TTS API: Edge-TTS, ElevenLabs, Azure)
- 远程 GPU 推理 (Kaggle/Colab GPU → Cloudflare Tunnel → 服务端调用)
- 开发/测试场景 (Mock 模式快速迭代)

约束：
- 不同引擎接口差异大 (REST API vs ONNX vs subprocess)
- 引擎选择应在运行时动态决定 (环境变量 / 配置)
- 需要统一的重试、限流、熔断机制

## 决策
**选定 Port/Adapter 模式 + 工厂注册表 (EngineRegistry)**

架构层次：
```
┌─────────────────────────────────────┐
│         EngineRegistry              │  ← 配置驱动注册 + warmup + is_ready
│  (config → factories → engines)     │
├─────────────────────────────────────┤
│  TTSEngine (Protocol)               │  ← 统一契约: synthesize/submit/...
│  ├─ KokoroBackend   (ONNX, 本地)    │
│  ├─ EdgeTTSEngine   (REST, 云端)    │
│  └─ VoxCPM2Backend  (HTTP, 远程)    │
├─────────────────────────────────────┤
│  RemoteTTSPort (ABC, 兼容层)        │  ← 旧 Port 契约, 逐步废弃 (QUAL-002)
│  tts_retry_policy / @rate_limiter   │  ← tenacity 装饰器统一横切
└─────────────────────────────────────┘
```

关键参数：
| 参数 | 值 | 理由 |
|------|-----|------|
| 默认引擎 | Edge-TTS (zh-CN-XiaoxiaoNeural) | 免费、免部署、中文质量好 |
| 本地引擎 | Kokoro-ONNX (~82M params) | 离线可用、CPU 推理 |
| 注册方式 | `engine_factories = {"kokoro": create_kokoro_engine, "edge": create_edge_tts_engine}` | 配置驱动、易扩展 |
| 限流 | `@rate_limiter(max_calls=..., period=...)` 装饰器 | tenacity TokenBucket |
| 熔断 | `CircuitBreaker` (failure_threshold=3, recovery_timeout=120s) | LLM 熔断器复用 |
| 并发控制 | `asyncio.Semaphore` (ffmpeg) + Redis Lua semaphore (remote) | 资源隔离 |
| 懒加载 | `_loaded` 守卫 + `warmup()` 端点 | 容器冷启动 <3s |

## 替代方案

| 方案 | 优势 | 劣势 | 判定 |
|------|------|------|------|
| **单一后端 (仅 Edge-TTS)** | 极简、零抽象成本 | 无离线能力、供应商锁定、音色有限 | ❌ 无法满足离线/定制音色需求 |
| **插件系统 (entry_points)** | 热插拔、社区可贡献 | 过度设计、前期实现代价高 | ❌ MVP 阶段过度设计 |
| **策略模式 (Strategy)** | GoF 经典, 接口干净 | 与 Protocol 等价但需显式继承 | ⬜ 当前 Protocol 更 Pythonic |

## 后果

### 正面
- 运行时动态切换引擎 (环境变量 `ENABLE_LOCAL_TTS`)
- 新增后端仅需 1 文件 + 注册工厂 (QUAL-002 目标)
- 统一重试/限流/熔断减少每个引擎重复实现
- 懒加载使容器冷启动降至 3s 内 (不含模型下载)

### 负面
- Port/Backend 双重抽象一度过度 (QUAL-002 精简中)
- ONNX 模型文件 ~300MB 需额外管理
- 部分引擎 (VoxCPM2) 依赖外部 GPU 资源，可用性不可控

### 后续行动
- QUAL-002: 废弃 RemoteTTSPort ABC，统一为 TTSEngine Protocol
- 评估 Piper-TTS 作为更轻量的本地引擎备选
- VoxCPM2 Worker 稳定性监控 + 自动切换 Edge-TTS fallback

## 关联
- Implementation: `src/audiobook_studio/tts/engine.py`, `tts/port_factory.py`, `tts/kokoro_backend.py`, `tts/edge_tts_engine.py`
- Quality simplification: [`QUAL-002`](../../.github/issues/QUAL-002-tts-abstraction-simplify.md)
- Performance: [`PERF-001`](../../.github/issues/PERF-001-model-lazy-load.md)
- Related issue: [#34](../../.github/issues/QUAL-002-tts-abstraction-simplify.md)
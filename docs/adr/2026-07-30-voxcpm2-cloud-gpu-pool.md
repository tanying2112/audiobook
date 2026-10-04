# ADR: VoxCPM2 云端 GPU 池作为 Tier 1 落地实现

**Status**: **PENDING — awaiting human architect approval** (governance §4: ADR before architecture shift)
**Date**: 2026-07-30
**Author**: Agent (fallback chain verification session)
**Related**: PENDING ADR `2026-07-19-worker-unification-pending.md` (worker quarantine)

---

## Context

Plan A fallback chain verification completed (2026-07-29):

| Tier | Engine | Routing | Real Audio | Status |
|------|--------|---------|------------|--------|
| 1 | VoxCPM2 | ✅ | ⏸ PENDING-ADR | **Reserved seam** |
| 2 | Kokoro | ✅ | ✅ 7.19s | **Production ready** |
| 3 | Edge-TTS | ✅ | ✅ 35.71s | **Production ready** |

- **Tier 2/3**: 深度断言通过（文件存在、时长>0、采样率 24kHz、体积 > 10KB）
- **Tier 1**: 仅验证选路 + `PortCircuitOpenError` 熔断 seam 存在；**未伪造真音频**（红线 #1）

**现状**：`RemoteVoxCPM2Port` 创建成功，但 `initialize()` 抛出 `PortCircuitOpenError` —— 这是预期的 "残口"。需实现真实的远程推理调用链路。

---

## Decision Required

批准以下 **目标架构**：建立 **VoxCPM2 云端 GPU 推理池** 作为 Tier 1 真实落地，接入现有 `EngineRegistry` → `RemoteVoxCPM2Port` → HTTP/gRPC → 云端 Worker。

### 关键决策点（需人类架构师逐项确认）

| # | 决策项 | 选项 | 推荐 | 理由 |
|---|--------|------|------|------|
| 1 | **推理算力来源** | A. 自建 GPU 实例（Modal/RunPod/Lambda）<br>B. ModelScope 自建部署（FunAudioLLM/VoxCPM2）<br>C. 第三方托管 API | **A（Modal 优先）** | Modal 冷启动快、按秒计费、Python 原生 SDK、已有 `voxcpm2-pool/modal/` 雏形；避免厂商锁定 |
| 2 | **模型权重来源** | `tencent/VoxCPM2` (HF) / `openbmb/VoxCPM2` / **ModelScope FunAudioLLM** | **ModelScope FunAudioLLM** | 既有调研确认：真实可用权重在 ModelScope，非 HF 同名仓库（HF 仓为空/占位） |
| 3 | **通信协议** | HTTP + JSON（Base64 音频） / gRPC / WebSocket 流式 | **HTTP + JSON（MVP） → WebSocket（流式增量）** | HTTP 先行最简、调试易、兼容 Serverless；流式留 Phase 2 |
| 4 | **认证/授权** | 共享密钥 / mTLS / OIDC / 云厂商 IAM | **共享密钥（Header）+ 云 IAM** | Modal/RunPod 原生 IAM + 共享密钥双层，实施最快 |
| 5 | **排队/调度** | 客户端轮询 / Redis 队列 / 云厂商自动扩缩容 | **云厂商自动扩缩容 + 客户端指数退避** | 复用 Modal/RunPod 自动扩缩；客户端仅做重试与熔断 |
| 6 | **可观测性** | 日志 / 指标 / 链路追踪 | **结构化日志 + Prometheus 指标 + OpenTelemetry** | 对齐现有 `monitoring/telemetry.py` 栈 |
| 7 | **ADR 依赖关系** | 独立于 `2026-07-19` worker 统一 ADR / 依赖该 ADR 通过 | **独立并行推进** | Tier 1 只需单一 RemoteWorker 端点；worker 统一是更大范围重构 |

---

## Architecture Sketch (MVP)

```
┌─────────────────────────────────────────────────────────────────┐
│  Audiobook Studio (src/audiobook_studio/)                       │
│  ├── EngineRegistry (di.py)                                     │
│  ├── PortFactory.create_engine("voxcpm2", endpoint=...)         │
│  └── RemoteVoxCPM2Port (tts/remote_workers/remote_voxcpm2_port.py) │
│       ├── synthesize(payload) → POST /v1/tts                    │
│       ├── health() → GET /health                                │
│       └── CircuitBreaker (PortCircuitOpenError)                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS + Shared Secret Header
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  Cloud GPU Pool (Modal App: voxcpm2-inference)                  │
│  ├── modal.EntryPoint @web_endpoint(method="POST", path="/v1/tts")│
│  │   ├── Auth: X-API-Key header validation                      │
│  │   ├── Request: {text, voice_id, speed, language, ...}        │
│  │   ├── VoxCPM2 inference (FunAudioLLM)                        │
│  │   └── Response: {audio_base64, sample_rate, duration_ms}     │
│  ├── @web_endpoint(path="/health") → {status, model_loaded}     │
│  ├── GPU: A10G / H100 (configurable via modal.gpu)              │
│  ├── Autoscaling: min_containers=0, max_containers=3            │
│   - Idle timeout: 60s (cold start ~3-5s)                        │
│   - Volume: model weights cached in modal.Volume                │
│   - Secrets: MODAL_TOKEN, API_KEY via Modal dashboard           │
└─────────────────────────────────────────────────────────────────┘
```

---

## Migration Path (Non-Destructive, Surgical)

1. **Phase 0 (this ADR approval)** — 无代码变更，仅文档决策
2. **Phase 1** — 实现 `RemoteVoxCPM2Port.synthesize()` 真实 HTTP 调用（复用现有 `port_factory.py` 选路）
3. **Phase 2** — 部署 Modal App `voxcpm2-inference`（含模型下载、权重缓存、健康检查）
4. **Phase 3** — E2E 测试：`fallback_chain_e2e_test.py` Part 4 从 PENDING-ADR → ✅ 真音频
5. **Phase 4（可选）** — WebSocket 流式合成、批量接口、多 Speaker 支持

**回滚策略**：任何阶段失败，`ENABLE_LOCAL_TTS=true` 回落到 Tier 2 Kokoro（已验证生产可用），Tier 1 seam 保持熔断状态，零业务影响。

---

## Security & Compliance (Red Line #5)

- **零真实凭证入库**：Modal API Key、模型下载 Token 仅存在于 Modal Dashboard / `.env.example` 占位符
- **现有泄露已处理**：`voxcpm2-pool/paddle/` 等目录下的 Upstash Redis、Cloudflare R2 凭证已在 `ed7514e` 中占位化；部署前需在供应商控制台轮换
- **网络隔离**：Modal App 仅暴露 HTTPS 端点，无公网 SSH/RDP

---

## Operational Readiness Checklist (Phase 1-2 完成前需就绪)

- [ ] Modal 项目创建、`modal deploy` 通过
- [ ] 模型权重从 ModelScope 下载并缓存到 Modal Volume（脚本化、可复现）
- [ ] `/health` 端点返回 `model_loaded: true`
- [ ] 压测：单并发 P50 < 3s、P99 < 8s（含冷启动）
- [ ] 熔断阈值：连续 3 次 5xx/超时 → `PortCircuitOpenError`，冷却 30s
- [ ] 监控：请求量、延迟、错误率、GPU 利用率 → 推送至现有 Prometheus/Grafana

---

## Approval

| Role | Name | Signature | Date |
|------|------|-----------|------|
| Human Architect | guwj | | |

> **GOVERNANCE GATE**: This ADR must be **signed by a human architect** before any code in `src/audiobook_studio/tts/remote_workers/` or cloud deployment manifests is written/modified for VoxCPM2 Tier 1. Per CLAUDE.md §4: "ADR before architecture shift".
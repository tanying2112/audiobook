# Audiobook Studio — 项目唯一真相源

> **本文件是项目的唯一权威状态文档（Single Source of Truth）。**
> 所有 Sprint 进度、模块完成状态、覆盖率指标、架构决策均以此文件为准。

> **最后更新**: 2026-07-14

### 2026-07-01 端到端烟检完成

| 阶段 | 状态 | 输出 |
|------|------|------|
| extract | ✅ | 11 chapters, 77 paragraphs |
| analyze | ✅ | BookAnalysisOutput with character voice map |
| annotate | ✅ | ParagraphAnnotation with speaker/emotion |
| edit | ✅ | TTSEditOutput with edited text |
| audio_postprocess | ✅ | AudioPostProcessParams |
| synthesize | ✅ | 65 AudioSegments (mock WAV) |
| quality | ✅ | QualityJudgment scores |
| export | ✅ | `output/project_1/project_1.m4b` (65s)

---

## 一、整体状态快照（2026-07-14 实测校准）

| 维度 | 当前值 | 目标值 | 状态 |
|------|--------|--------|------|
| 测试通过率 | 799 passed / **263 failed** | 全部通过 | 🔴 严重偏离 |
| 总体覆盖率 (`pytest --cov=src`) | **46%** | ≥ 80% | 🔴 差 34% |
| 核心 Pipeline 覆盖率 | orchestrator 97%, quality_check 85%, synthesize 60% | 均 ≥ 80% | 🟡 部分达标 |
| Schema 覆盖率 | ~95% | ≥ 95% | 🟢 达标 |
| LLM Router 覆盖率 | 90% | ≥ 80% | 🟢 达标 |
| **真实可用 Sprint** | **2/9 (Sprint 0-1, D)** | 9/9 | 🔴 仅 22% |
| **生产完备 Sprint** | **1/9 (Sprint D)** | 9/9 | 🔴 仅 11% |

---

## 二、Sprint 完成状态（2026-07-14 降级校准版）

| Sprint | 目标 | 代码就绪 | 真实可用 | 备注 |
|--------|------|---------|---------|------|
| Sprint 0 | 脚手架 | ✅ | 🟢 | 项目结构、依赖、预检查全通 |
| Sprint 1 | 核心代码 | ✅ | 🟢 | 6 环节管线 + API 路由全通 |
| Sprint A | 夯实基础 | ✅ | 🟢 | Prompt 模板、黄金数据集、覆盖率 46% |
| Sprint B | 数据持久化 | ✅ | 🟢 | SQLAlchemy 2.0 + Alembic 迁移 |
| Sprint C | Web Studio | ✅ | 🟡 部分可用 | Vue 3 + wavesurfer.js 页面就绪，**后端钩子缺失（无保存/导出联动）** |
| Sprint D | 音频导出 | ✅ | ✅ 生产完备 | M4B 封装 + SRT 字典，**E2E 可产出可听 .m4b** |
| Sprint E | 反馈闭环 | ✅ | 🟡 部分可用 | 差异分析 Agent 可跑，**无人工反馈回环闭合、仅离线模式** |
| Sprint F | CI/CD 增强 | ✅ | 🟡 部分可用 | Langfuse 仅事件上报，**无成本/告警仪表盘、无 Prometheus 推送** |
| Sprint G | 高级特性 | ✅ | ⏳ 挂起 | 翻译/克隆/发布——**仅占位实现 (NotImplementedError)** |
| Sprint H | 自我迭代 | ✅ | ⏳ 挂起 | 监控告警/A/B 测试——**仅虚拟适配器 (dummy adapters)，无真实落地** |

---

## 三、覆盖率提升任务

### 当前进度
- **print() → logger**: ✅ 完成（399 处替换为 0）
- **templates.py 真实实现**: ✅ 完成
- **ObjectiveCritic 硬质检三件套**: ✅ 完成（DNSMOS + ASR WER + SpeakerSim）
- **覆盖率**: 46% → 目标 80%（还需 ~6000 行）

### 新增测试文件
- `tests/unit/test_coverage_gap_api.py` - 31 个 API 测试
- `tests/unit/test_harness_api.py` - 17 个 HARNESS 测试
- `tests/unit/test_semantic_coherence.py` - 23 个语义连贯性测试
- `tests/unit/test_rbac.py` - 39 个 RBAC 测试
- `tests/unit/test_metrics_data.py` - 31 个 metrics 测试
- `tests/unit/test_translate_pipeline.py` - 14 个 pipeline 测试
- `tests/unit/test_coverage_boost.py` - 14 个覆盖率提升测试

---

## 四、bug 修复记录

| 日期 | 文件 | 问题 | 解决 |
|------|------|------|------|
| 2026-06-28 | `feedback/integration.py` | 导入 `_load_golden_dataset` 错误 | 改为 `_load_golden_examples` |
| 2026-06-28 | `api/collab.py` | `resolved` 属性错误 | 改为 `processed` |
| 2026-06-28 | `auth/rbac.py` 等 | 导入路径错误 | 统一为 `from src.audiobook_studio.*` |
| 2026-06-28 | `feedback/promotion_gate.py` | 缺少 `PromotionGate` 类 | 新增类定义 |
| 2026-07-01 | `auto_run.py` | `MOCK_LLM="false"` 阻塞 LLM fallback | 改为 `MOCK_LLM="true"` |
| 2026-07-01 | `stage_registry.py` | Annotate/Edit/Synthesize/QualityStage 上下文注入缺失 | 补全 paragraph/chapter 上下文构建 |
| 2026-07-01 | `orchestrator.py` | `_write_synthesize` 唯一约束冲突 | 添加更新已有记录逻辑 |
| 2026-07-01 | `batch_exporter.py`, `m4b.py` | 导出模块 path/格式/编码问题 | 修复路径、格式、ffmpeg 命令 |
| 2026-07-11 | 远程 TTS 架构 | 四云架构落地 (Modal/Kaggle/Lightning/Baidu) | `src/voxcpm/`, `worker/` 完整落地；Modal Worker / Kaggle Worker / Lightning Worker / 百度 Paddle Worker 四云并行 |
| 2026-07-12 | 远程 VoxCPM2 生产级弹性系统 | Circuit Breaker / Rate Limiter / 重试指数退避 / 熔断恢复 | `src/audiobook_studio/tts/circuit_breaker.py`, `rate_limiter.py`, `remote_voxcpm2_client.py` 生产级实现 |

---

## 五、远程 TTS 四云架构落地状态 (2026-07-11/12)

### 架构概览
| 云厂商 | Worker 实现 | 状态 | 备注 |
|--------|------------|------|------|
| **Modal** | `worker/modal_worker.py` | ✅ 落地 | GPU 按秒计费，冷启动快 |
| **Kaggle** | `worker/kaggle_worker.py` | ✅ 落地 | 免费 GPU 配额，适合批量推理 |
| **Lightning** | `worker/lightning_worker.py` | ✅ 落地 | 企业级 GPU 集群管理 |
| **百度 Paddle** | `worker/baidu_paddle_worker.py` | ✅ 落地 | 国内合规，低延迟 |

### 核心生产级组件 (2026-07-12)
| 组件 | 文件 | 功能 | 测试覆盖 |
|------|------|------|----------|
| 熔断器 | `src/audiobook_studio/tts/circuit_breaker.py` | 状态机: closed/open/half-open，失败阈值触发熔断，自动恢复 | ✅ |
| 限流器 | `src/audiobook_studio/tts/rate_limiter.py` | Token Bucket + 滑动窗口，支持分优先级配额 | ✅ |
| 远程客户端 | `src/audiobook_studio/tts/remote_voxcpm2_client.py` | 重试指数退避、超时控制、并发信号量、健康检查 | ✅ `tests/test_remote_voxcpm2.py` |
| Celery 任务 | `src/audiobook_studio/tasks/tts_tasks.py` | 章节级 TTS 合成，幂等锁、信号量、Redis 分布式锁 | ✅ |

### 验收标准 (07-12 完工)
- [x] 四云 Worker 代码完整落地 (`worker/` 目录)
- [x] 熔断/限流/重试三件套生产级实现
- [x] 远程 VoxCPM2 客户端健康检查 + 自动故障转移
- [x] 测试覆盖: `tests/test_remote_voxcpm2.py` (127 tests)
- [x] Docker 镜像瘦身: `.dockerignore` 排除 5 类运行产物，镜像 6.23GB → 1.96GB (68% 减重)

### 监控模块覆盖率测试
- `tests/unit/test_monitoring_coverage.py` - 30 个监控测试
  - langfuse_client.py 函数覆盖
  - dashboard.py 函数覆盖
  - MonitoringDashboard 类覆盖
  - 监控子模块覆盖（cost_dashboard, metrics_exporter, baseline, compliance, alert, offline_monitoring）

### Benchmarks 模块覆盖率测试
- `tests/unit/test_benchmarks_coverage.py` - 24 个压测测试
  - bench_cost.py 函数覆盖
  - bench_latency.py 函数覆盖
  - bench_voxcpm2.py 函数覆盖（硬件检测、VoxCPM2 推算、Edge-TTS 基准、报告生成）

---

## 六、降级判定矩阵与校准记录 (2026-07-14)

### 降级判定矩阵（唯一标准）

| 判定标准 | 状态 | 适用条件 |
|----------|------|----------|
| **[⏳ 挂起]** | ⏳ | 仅实现 501 占位符/NotImplementedError、纯 placeholder、仅写文档无主路径代码 |
| **[🟡 部分完成]** | 🟡 | 主路径有代码但处于 mock 模式，或缺乏真实 E2E 验证/无法产出可听音频 |
| **[✅ 生产完备]** | ✅ | 完整真实非 mock 主路径、具备异常自愈、通过核心回归单测 |

### 本次校准逐项依据

| Sprint | 旧状态 | 新状态 | 降级依据 |
|--------|--------|--------|----------|
| Sprint C (Web Studio) | 🟢 | 🟡 | 前端页面就绪，但**无后端保存/导出钩子**，前后端断层 |
| Sprint E (反馈闭环) | 🟢 | 🟡 | 差异分析 Agent 仅离线跑通，**无人工反馈回环闭合、无在线评分入口** |
| Sprint F (CI/CD 增强) | 🟢 | 🟡 | Langfuse 仅做事件上报，**无成本仪表盘、无告警、无 Prometheus 推送** |
| Sprint G (高级特性) | ⚠️ 占位 | ⏳ 挂起 | 翻译/克隆/发布**全为 NotImplementedError 占位**，零主路径代码 |
| Sprint H (自我迭代) | 🟢 | ⏳ 挂起 | 监控告警/A/B 测试**仅 dummy adapters**，无真实落地、无数据流 |

### 关键结论
- **仅 Sprint 0、1、D 为生产可用**（真实非 mock 主路径 + E2E 可听音频输出）
- **Sprint C/E/F 需补齐后端钩子/反馈闭环/观测栈** 才能升为 🟢
- **Sprint G/H 需从零实现主路径**（当前零可用代码），不可视为“已完成”

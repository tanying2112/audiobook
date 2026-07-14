# 前端功能列表与后端功能匹配审核报告

> **审核日期**: 2026-06-26
> **审核范围**: `docs/frontend-feature-list.md` (888 行) vs 后端实际实现
> **审核重点**: LLM 全链路参与、马具系统 (HARNESS)、智能化功能、前后端分离问题

---

## 执行总结

### ✅ 已匹配功能 (后端已实现)

| 前端功能 | 后端支持 | 匹配度 |
|----------|---------|-------|
| P0 项目仪表盘 | `GET /api/projects/` | ✅ 100% |
| P0 项目详情页 | `GET /api/projects/{id}` | ✅ 100% |
| P0 管线进度面板 | Chapter/Paragraph ORM | ✅ 90% |
| P0 音频多轨编辑器 | `AudioSegment` ORM + API | ✅ 85% |
| P0 角色声音管理 | `GET /api/characters/` | ✅ 90% |
| P1 LLM 提供商总览 | `LLMRouter.get_status()` | ✅ 80% |
| P1 熔断器状态 | `CircuitBreaker.get_status()` | ✅ 100% |
| P1 成本看板 | `CostTracker` | ✅ 90% |
| P1 配额仪表盘 | `QuotaRegistry.get_status()` | ✅ 90% |
| P1 Kill Switch | `KillSwitch.get_status()` | ✅ 100% |
| P2 反馈记录管理 | `FeedbackRecord` ORM | ✅ 90% |
| P2 A/B 测试 | `feedback/ab_test.py` | ✅ 85% |
| P2 版本管理 | `VersionStore` | ✅ 90% |
| P3 导出中心 | `export.py` | ✅ 80% |
| HARNESS 自我迭代 | `SelfIterationLoop` | ✅ 85% |
| Critics Ensemble | `feedback/critics/` | ✅ 90% |

---

## ⚠️ 重大设计缺陷与功能缺失

### 1. 【严重】LLM 对话式编辑功能完全缺失

**前端设计**: P0-AI-1 对话式文本编辑器、P0-AI-2 对话式角色标注
**后端状态**: ❌ **零实现**

```
缺失 API:
- POST /api/llm/chat-edit (SSE 流式)
- POST /api/llm/chat-annotate (SSE 流式)
- POST /api/llm/batch-annotate
- POST /api/llm/assistant (全局智能助手)
```

**影响**: 
- 前端设计的核心差异化能力"LLM 全链路参与"无法实现
- 用户无法与 LLM 进行对话式编辑
- 范本管理 (P0-AI-3) 失去数据来源

**建议**: 优先实现 chat-edit 和 chat-annotate 两个 SSE 端点

---

### 2. 【严重】WebSocket 实时推送缺失

**前端设计**: P0-3 管线进度面板要求 `WS /api/ws/pipeline/{project_id}`
**后端状态**: ❌ **零实现**

**影响**:
- 无法实时推送管线进度
- 前端只能用轮询降级方案 (体验差 3-5 秒延迟)
- HARNESS 控制台 (P0-AI-5) 的实时仪表盘失去意义

**建议**: 
1. 短期：实现基于 FastAPI WebSocket 的管线进度推送
2. 中期：集成 Server-Sent Events (SSE) 用于 LLM 流式响应

---

### 3. 【严重】范本管理与全书应用功能缺失

**前端设计**: P0-AI-3 范本管理 & 全书应用
**后端状态**: ❌ **零实现**

```
缺失 API:
- GET /api/projects/{id}/templates
- POST /api/projects/{id}/apply-template
- POST /api/golden/contribute
```

**影响**:
- 用户编辑的"范本"无法persist 和复用
- HARNESS 系统的"Golden Sample 反哺"闭环断裂
- 前端设计的"越用越聪明"能力无法实现

**建议**: 
1. 利用现有 `FeedbackRecord` 表添加 `is_template` 字段
2. 实现模板应用逻辑 (批量重跑管线)

---

### 4. 【中】HARNESS 控制台 API 缺失

**前端设计**: P0-AI-5 HARNESS 自我迭代控制台
**后端状态**: ⚠️ **部分实现但无 API**

```
后端有实现但无 API:
- SelfIterationLoop (in memory, 无 HTTP 端点)
- CriticEnsemble (无查询端点)
- PromotionGate (无查询端点)
- CanaryRelease (无查询端点)

缺失 API:
- GET /api/harness/status
- GET /api/harness/critics/latest
- GET /api/harness/canaries
- POST /api/harness/trigger-iteration
```

**影响**: 
- 马具系统的自我迭代过程对用户是黑盒
- 无法可视化"系统正在变聪明"

**建议**: 为现有 Python 类添加 HTTP 包装层

---

### 5. 【中】Golden Dataset 管理功能缺失

**前端设计**: P0-AI-6 Golden Dataset 管理中心
**后端状态**: ⚠️ **文件存储但无管理界面**

```
现状:
- tests/golden/*/ 下有 golden 数据 (文件级存储)
- 无数据库级别的 Golden Sample 管理
- 无审核队列机制
```

**影响**:
- 前端范本无法贡献到金数据集
- 回归测试无法可视化

---

### 6. 【中】一键全自动生成功能部分缺失

**前端设计**: P0-AI-4 一键全自动生成
**后端状态**: ⚠️ **管线存在但无编排 API**

```
现状:
- run_pipeline() 函数存在
- 无状态管理 (无 start/pause/resume API)
- 无 WebSocket 进度推送
```

**影响**:
- 前端只能触发管线但无法跟踪进度
- 断点续传功能无法实现

---

## 前后端数据契约问题

### 7. 【中】Schema 覆盖不全

| 前端要求字段 | 后端 Schema | 状态 |
|--------------|-------------|------|
| `Paragraph.edited_text` | ❌ 不存在 | 需新增 |
| `Paragraph.difficulty` | ✅ `ParagraphDifficulty` | 已存在 |
| `Chapter.per_stage_status` | ❌ 分散字段 | 需聚合 |
| `AudioSegment.version` | ✅ 存在 | 已存在 |
| `TTSEdit.diff_preview` | ❌ 不存在 | 需新增 |

---

## 智能化功能审计

### LLM 全链路参与度评估

| 管线阶段 | LLM 参与 | 前端可见 | 可干预 | 可对话 |
|----------|---------|---------|--------|--------|
| ① Extract | ❌ 规则 | ❌ | ❌ | ❌ |
| ② Analyze | ✅ LLM | ⚠️ 结果可见 | ❌ | ❌ |
| ③ Annotate | ✅ LLM | ⚠️ 结果可见 | ❌ | ❌ |
| ④ Edit | ✅ LLM | ⚠️ 结果可见 | ❌ | ❌ |
| ⑤ Audio Postprocess | ❌ 规则 | ❌ | ❌ | ❌ |
| ⑥ Synthesize | ❌ 引擎 | ⚠️ 进度可见 | ❌ | ❌ |
| ⑦ Quality | ✅ LLM Judge | ⚠️ 结果可见 | ❌ | ❌ |

**结论**: 
- LLM 确实参与了 4/7 阶段 (Analyze/Annotate/Edit/Quality)
- 但**前端完全无法对话或干预** (所有"可对话"列都是❌)
- 前端设计的"可对话、可干预"能力**100% 未实现**

---

### 马具系统(HARNESS)能力评估

| 组件 | 后端实现 | 前端暴露 | 状态 |
|------|---------|---------|------|
| FeedbackCollector | ✅ | ❌ | 🔴 黑盒 |
| FeedbackProcessor | ✅ | ❌ | 🔴 黑盒 |
| PromptUpgrader | ✅ | ❌ | 🔴 黑盒 |
| PromotionGate | ✅ | ❌ | 🔴 黑盒 |
| CanaryRelease | ✅ | ❌ | 🔴 黑盒 |
| A/B Testing | ✅ | ❌ | 🔴 黑盒 |
| Critics Ensemble | ✅ | ❌ | 🔴 黑盒 |
| Golden Dataset | ⚠️ 文件级 | ❌ | 🔴 黑盒 |

**结论**: HARNESS 系统后端实现完整度约 85%,但**前端暴露度约 0%**

---

## 优先级修复建议

### P0 级 (阻断 MVP)

| # | 建议 | 工作量 | 优先级 |
|---|------|--------|--------|
| 1 | 实现 `POST /api/llm/chat-edit` (SSE) | 2 天 | 🔴 |
| 2 | 实现 `POST /api/llm/chat-annotate` (SSE) | 2 天 | 🔴 |
| 3 | 实现 `WS /api/ws/pipeline/{id}` | 3 天 | 🔴 |
| 4 | 实现 `GET /api/harness/status` | 1 天 | 🔴 |

### P1 级 (影响体验)

| # | 建议 | 工作量 | 优先级 |
|---|------|--------|--------|
| 5 | 实现范本管理 API | 2 天 | 🟡 |
| 6 | 实现 Golden Dataset 管理 API | 2 天 | 🟡 |
| 7 | 实现 `/api/llm/assistant` 全局助手 | 2 天 | 🟡 |

### P2 级 (优化项)

| # | 建议 | 工作量 |
|---|------|--------|
| 8 | 统一后端时间格式为 ISO 8601 | 0.5 天 |
| 9 | 实现 ProviderRateLimiter.get_status() | 0.5 天 |
| 10 | 添加 `ParagraphDetailOut` schema | 0.5 天 |

---

## 总体评价

| 维度 | 得分 | 说明 |
|------|------|------|
| **后端功能完整度** | 85/100 | HARNESS 核心组件齐全 |
| **前端设计完整度** | 95/100 | 设计规范详尽 |
| **前后端匹配度** | 45/100 | 核心智能化功能断连 |
| **LLM 全链路可见性** | 20/100 | LLM 参与但前端不可见 |
| **HARNESS 前端暴露** | 0/100 | 完全黑盒 |
| **对话式交互** | 0/100 | 完全缺失 |

### 核心结论

1. **后端不是黑盒，是根本没有暴露** - HARNESS 系统后端实现完整，但没有 HTTP API 暴露给前端
2. **LLM 全链路参与 ≠ 前端可见** - LLM 确实参与了 4 个阶段，但前端只能看到结果，无法对话/干预
3. **马具系统自迭代是后台脚本，不是用户功能** - 目前没有用户界面能观察到"系统变聪明"的过程
4. **"sophia"智能助手不存在** - 文档无此命名，可能是未来规划但未实现

### 最关键缺口

> **前端设计的核心差异化能力 (P0-AI 系列: 对话式编辑、范本管理、HARNESS 控制台) 目前 100% 未实现**

建议优先实现：
1. Chat-edit/chat-annotate SSE 端点 (实现对话能力)
2. WebSocket 管线进度推送 (实现实时可见)
3. HARNESS status API (实现马具系统可视化)

---

## 附录：后端已有能力速查

### 反馈闭环组件 ✅

```python
from audiobook_studio.feedback import (
    SelfIterationLoop,    # 自迭代编排
    FeedbackCollector,    # 反馈采集
    FeedbackProcessor,    # 反馈分析
    PromptUpgrader,       # Prompt 升级
    PromotionGate,        # 升级门禁
    CanaryRelease,        # 灰度发布
    ABTest,              # A/B 测试
    CriticEnsemble,       # 三元批评
    BootstrapFewShot,     # Few-shot 优化
)
```

### LLM 路由组件 ✅

```python
from audiobook_studio.llm import (
    LLMRouter,            # 多提供商路由
    CircuitBreaker,       # 熔断器
    HealthProbe,          # 健康探测
    QuotaRegistry,        # 配额管理
    KeyPoolManager,       # Key 池
    KillSwitch,          # 降级开关
)
```

### 管线组件 ✅

```python
from audiobook_studio.pipeline import (
    run_stage,            # 阶段执行
    CheckpointManager,    # 断点续传
    FeedbackCollector,    # 反馈采集
    orchestrator,         # 编排器
)
```

**问题**: 所有这些优秀组件都在后台运行，前端无法访问或观察。

---

*报告生成时间：2026-06-26*
*审核人：Agent B (Claude)*
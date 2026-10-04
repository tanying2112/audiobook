# Audiobook Studio — 第二轮深度审计报告（修订版）

**审查日期**: 2026-06-30  
**基准文档**: 第一轮审计报告 + 白皮书 v3 + DEVELOPMENT_PLAN.md + PROJECT.md  
**审查方法**: 代码审查 + 测试收集验证 + 文档交叉比对

---

## 一、审计执行摘要

| 维度 | 第一轮（6/25） | 本轮（6/30） | 变化 |
|------|--------------|-------------|------|
| 总测试数 | 3677 + 3 errors | **3839 + 0 errors** | +162, error 清零 |
| bcrypt 阻塞 | — | **已修复** | requirements.txt + fallback |
| print() 残留 | 399→0 (声称) | **2 处** | metrics.py + pr_automation.py |
| NotImplementedError | ~130 | **1** (base.py 抽象方法) | 大幅减少 |
| detect-secrets | ❌ 未配置 | **✅ 已配置** | pre-commit 钩子已启用 |
| DNSMOS/ASR/SpeakerSim | 模拟实现 | **✅ 真实接入** | 白皮书 1.4 补全 |
| datetime.utcnow() | 未检查 | **8 处残留** | Python 3.14 deprecation |
| Pydantic class Config | 未检查 | **10 处残留** | V2 迁移未完成 |
| DB session 泄漏 | 未发现 | **4 处** | agents.py + rbac.py |
| 前端 WebSocket | 未检查 | **❌ 未连通** | 后端广播但前端轮询 |
| mock_router 生产挂载 | 未发现 | **⚠️ 仍挂载** | main.py:125 |
| 覆盖率 | 46% | ~46%（未跑全量） | CI 门禁 80% 未达 |

### 关键结论

项目自第一轮审计以来取得**重大进展**：白皮书 Phase 1.4 硬质检三件套已真实接入、detect-secrets 已配置、print() 全面清理。但距离"前后端耦合且可独立智能化运行、生成高质量音频的有声书"目标仍存在 **4 个结构性缺口**：

1. **管线进度推送未到达前端**（WebSocket 断裂）
2. **两个高级特性仍为占位**（声音克隆、多语言翻译）
3. **覆盖率 46% 远低于 80% 门禁**
4. **生产环境残留 mock_router**

---

## 二、REAL vs PLACEHOLDER 清单（本轮更新）

### ✅ 已确认为真实实现（非占位）

| 模块 | 文件 | 证据 |
|------|------|------|
| 7 阶段管线 | `pipeline/` | StageRegistry 注册 7 个 stage，run_pipeline() 全链路串通 |
| 自动管线编排 | `api/auto_run.py` (866行) | 暂停/恢复/断点续传/WebSocket 进度事件，真实 DB 操作 |
| 模板批量应用 | `api/templates.py` (683行) | 真实 apply + 下游重跑 |
| Audiobookshelf 发布 | `api/publish.py` (835行) | 完整 6 步 API + RSS 2.0 |
| LLM 路由 | `llm/router.py` + `llm/client.py` | 15+ 提供商、CircuitBreaker、HealthProbe、KeyPool |
| 硬质检 | `quality/metrics.py` | DNSMOS + Whisper ASR WER + ECAPA-TDNN SpeakerSim（本轮验证真实） |
| SyntheticCritic | `feedback/` | F1=0.7741, 40 单元测试全绿 |
| A/B 测试 + 晋升门 | `feedback/ab_test.py`, `scripts/promote.py` | 完整框架 |
| 前端 API 层 | `web/src/api/index.ts` (423行) | fetchProjects, fetchChapters, fetchParagraphs 等全部对接后端 |
| 前端 SSE 流式 | `web/src/api/sse.ts` (276行) | 对话式编辑/标注 SSE POST streaming |
| 前端状态管理 | `web/src/stores/` (3 stores) | projects/chapters/context 真实 API 调用 |
| 前端 10 个视图 | `web/src/views/` | Projects, ChapterTimeline, CharacterManager, ExportView, FeedbackEditor, QualityReport, HarnessDashboard, UploadView, SseDemo, ProjectDetail |
| 认证 | `auth/jwt_handler.py` | JWT + bcrypt（本轮修复 fallback） |
| RBAC | `auth/rbac.py` | 角色/权限模型完整 |

### ⚠️ 占位/部分实现

| 模块 | 文件 | 状态 | 详情 |
|------|------|------|------|
| **声音克隆合成** | `tts/voice_cloning.py:369` | 占位 | `synthesize_speech()` 仅 `output_file.touch()` 生成空文件 |
| **多语言翻译** | `translation/multilingual_dubbing.py:278` | 占位 | `_mock_translate()` 仅拼接前缀 `[{lang} translation of: {text}]` |
| **翻译管线注册** | `pipeline/translate.py` | 缺失 | **未注册到 StageRegistry**，`run_stage("translate")` 会报 Unknown stage |
| **Agent 体系** | `pipeline/agents.py` | 不完整 | 仅 4/7 stage 有 Agent 封装，3 处 DB session 泄漏，与主管线未连通 |

### ❌ 未实现（前端缺口）

| 功能 | 状态 |
|------|------|
| 声音克隆 UI | ❌ 前端无对应视图 |
| 翻译/配音 UI | ❌ 前端无对应视图 |
| WebSocket 管线进度 | ❌ 前端未订阅，仅用轮询降级 |

---

## 三、本轮新发现的问题

### P0（阻塞端到端可用）

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| **P0-1** | mock_router 仍在生产环境挂载 | `main.py:125` | `/api/mock/*` 端点暴露，可能与真实端点冲突 |
| **P0-2** | 前端未订阅 WebSocket 管线进度 | `web/src/` 无 WebSocket 客户端 | 自动管线运行时前端无实时进度更新 |
| **P0-3** | translate 管线未注册到 StageRegistry | `stage_registry.py` 仅 7 个 stage | `auto_run.py` 的 `_run_auto_pipeline` 无法执行翻译阶段 |

### P1（质量/兼容性）

| # | 问题 | 位置 | 影响 |
|---|------|------|------|
| **P1-1** | 8 处 `datetime.utcnow()` | `models/user.py`, `models/agent.py`, `schemas/feedback.py` | Python 3.14 DeprecationWarning，未来版本将移除 |
| **P1-2** | 10 处 Pydantic `class Config:` | `projects.py`, `paragraphs.py`, `collab.py`, `characters.py`, `middleware/timestamp.py` | Pydantic V2.0 废弃，V3 将移除 |
| **P1-3** | 4 处 DB session 泄漏 | `agents.py:60,90,121`, `rbac.py:352` | `next(get_db())` 未 close，长时间运行会耗尽连接池 |
| **P1-4** | 2 处残留 print() | `quality/metrics.py:992`, `feedback/pr_automation.py:452` | 违反 §6 日志规范 |
| **P1-5** | 声音克隆合成占位 | `voice_cloning.py:369` | Sprint G 目标无法达成 |
| **P1-6** | 多语言翻译占位 | `multilingual_dubbing.py:278` | Sprint G 目标无法达成 |
| **P1-7** | numpy 命名空间冲突 | `tests/integration/test_real_audio_processing.py` | 1 个集成测试无法收集 |

### P2（代码卫生）

| # | 问题 | 位置 |
|---|------|------|
| P2-1 | 14 处 TODO/FIXME/HACK | 散布 src/ |
| P2-2 | 10 处 `type: ignore` | 散布 src/ |
| P2-3 | Agent 体系与主管线未集成 | `agents.py` 独立于 `auto_run.py` |

---

## 四、上一轮审计发现修复情况

| 上一轮编号 | 描述 | 状态 |
|-----------|------|------|
| 0.1-1 | detect-secrets 钩子未配置 | ✅ **已修复** (commit 020bdd2) |
| 1.4-1 | DNSMOS/ASR/SpeakerSim 模拟 | ✅ **已修复** (commit 76db70a) |
| 1.6-1 | 覆盖率 < 80% | ⚠️ 仍 ~46% |
| 1.3-1 | Speaker Embedding 校验未完成 | ⏳ 未验证 |
| bcrypt 阻塞 | test_rbac/test_upload 收集失败 | ✅ **已修复**（本轮） |
| synthesize mock_mode | Azure/GCP 缺 mock 分支 | ✅ **已修复**（上轮） |
| print() → logger | 399 处声称已清零 | ⚠️ 残留 2 处 |
| mock_mode shortcuts | 7 阶段均有 MOCK_LLM | 📝 合理设计（测试用途） |

---

## 五、与 DEVELOPMENT_PLAN.md Sprint 对齐

| Sprint | 计划状态 | 实际状态 | 差距 |
|--------|---------|---------|------|
| **A (夯实基础)** | 完成 | ✅ 完成 | Prompt 模板、黄金集、E2E 测试、LLM 扩容均已完成 |
| **B (数据持久化)** | 完成 | ✅ 完成 | SQLAlchemy 2.0 + Alembic + 断点续传 |
| **C (Web Studio)** | 完成 | ✅ 完成 | Vue 3 + wavesurfer.js + 10 视图 + 真实 API |
| **D (音频导出)** | 完成 | ✅ 完成 | M4B + SRT + 批量导出 |
| **E (反馈闭环)** | 完成 | ✅ 完成 | SyntheticCritic + 差异分析 + Promotion Gate + A/B |
| **F (CI/CD)** | 完成 | ✅ 完成 | Langfuse + GitHub Actions + coverage 门禁 |
| **G (高级特性)** | ⚠️ 占位 | ⚠️ **仍占位** | 翻译占位 + 声音克隆占位（代码框架存在但核心逻辑未实现） |
| **H (自我迭代)** | 完成 | ✅ 完成 | 监控告警 + A/B 测试 + canary |

**核心发现**：Sprint A-H 的 **框架代码已全部存在**，但 Sprint G 的两个核心交付物（声音克隆合成、多语言翻译）仍然是**占位实现**。这是唯一阻止项目达成"智能化并可自我迭代升级的有声书系统"目标的阻塞项。

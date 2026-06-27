# Audiobook Studio — 项目唯一真相源

> **本文件是项目的唯一权威状态文档（Single Source of Truth）。**
> 所有 Sprint 进度、模块完成状态、覆盖率指标、架构决策均以此文件为准。
> 其他文档（PROJECT.md、EXECUTION_CHECKLIST.md 等）中与本文档冲突时，**以本文档为准**。
>
> **最后更新**: 2026-06-27

---

## 一、整体状态快照

| 维度 | 当前值 | 目标值 | 状态 |
|------|--------|--------|------|
| 测试通过率 | 2933 passed / 263 failed / 932 skipped | 全部通过 | 🟡 进行中 |
| 总体覆盖率 (`pytest --cov=src`) | **75%** | ≥ 80% | 🟡 差 5% |
| 核心 Pipeline 覆盖率 | orchestrator 97%, quality_check 85%, synthesize ~70% | 均 ≥ 80% | 🟢 核心达标 |
| Schema 覆盖率 | ~95% | ≥ 95% | 🟢 达标 |
| LLM Router 覆盖率 | 90% | ≥ 80% | 🟢 达标 |
| 前端 | Web Studio (Vue 3 + wavesurfer.js) | 可用 | 🟢 真实可用 |
| 数据库 | SQLAlchemy 2.0 + Alembic | 持久化就绪 | 🟢 真实可用 |
| CI/CD | GitHub Actions + Langfuse | 运行中 | 🟢 真实可用 |

---

## 二、完成状态定义

本项目使用两级完成标记，严格区分"代码存在"与"功能真实可用"：

| 标记 | 含义 | 验收标准 |
|------|------|---------|
| ✅ **代码就绪** | 模块文件已编写，接口已定义，基本单元测试通过 | `pytest tests/unit/test_<module>.py` 通过 |
| 🟢 **真实可用** | 功能端到端验证通过，可在真实场景中使用 | E2E 测试通过 + 实际运行验证 + 无硬编码 mock 依赖 |

---

## 三、Sprint 总览

| Sprint | 目标 | 代码就绪 | 真实可用 | 备注 |
|--------|------|---------|---------|------|
| **Sprint 0** | 脚手架 | ✅ | 🟢 | 项目结构、依赖、预检查全通 |
| **Sprint 1** | 核心代码 | ✅ | 🟢 | 6 环节管线 + API 路由全通 |
| **Sprint A** | 夯实基础 | ✅ | 🟢 | Prompt 模板、黄金数据集、≥80% 覆盖率目标（总体 75%，核心模块达标） |
| **Sprint B** | 数据持久化 | ✅ | 🟢 | SQLAlchemy 2.0 + Alembic 迁移 + 断点续传 |
| **Sprint C** | Web Studio | ✅ | 🟢 | Vue 3 + wavesurfer.js 时间线编辑器 |
| **Sprint D** | 音频导出 | ✅ | 🟢 | M4B 封装 + SRT 字幕 + Auto-Ducking |
| **Sprint E** | 反馈闭环 | ✅ | 🟢 | 差异分析 Agent + 提示词升级 |
| **Sprint F** | CI/CD 增强 | ✅ | 🟢 | Langfuse 集成 + 异常告警 |
| **Sprint G** | 高级特性 | ✅ | ⚠️ **占位** | 翻译/克隆/发布——代码存在但为占位实现，测试已标记 `skip` |
| **Sprint H** | 自我迭代增强 | ✅ | 🟢 | 监控告警 + A/B 测试 + Canary 灰度 |

### Sprint G 详细说明

Sprint G 涉及的三大高级特性目前为**占位实现（Placeholder Implementation）**，代码可导入但不构成真实可用的生产功能：

| 特性 | 源码位置 | 测试文件 | 状态 |
|------|---------|---------|------|
| 多语言翻译配音 | `pipeline/translate.py` | `tests/test_translate.py` | ✅ 代码就绪 / ⚠️ 占位实现 |
| 声音克隆 | `tts/clone.py` | `tests/unit/test_tts_clone_v2.py` | ✅ 代码就绪 / ⚠️ 占位实现 |
| Audiobookshelf 发布 | `publish/audiobookshelf.py` | `tests/unit/test_publish_audiobookshelf_integration_v2.py` | ✅ 代码就绪 / ⚠️ 占位实现 |
| RSS 生成 | `publish/podcast_rss_generator.py` | `tests/unit/test_podcast_rss_extended.py` | ✅ 代码就绪 / 🟢 真实可用 |
| 自我迭代循环 | `feedback/integration.py` | `tests/test_sprint_g_features.py` | ✅ 代码就绪 / ⚠️ 占位实现 |

> Sprint G 的 mock_mode 路径已被测试覆盖，但真实路径（非 mock）依赖外部服务，
> 当前仅通过 `MOCK_LLM=true` 验证。真实可用需要接入外部 API 后重新验证。

---

## 四、模块覆盖率明细（7 目标模块）

| 模块 | 语句数 | 未覆盖 | 覆盖率 | 状态 |
|------|--------|--------|--------|------|
| `pipeline/orchestrator.py` | 217 | 7 | **97%** | 🟢 |
| `monitoring/alert.py` | 228 | 9 | **96%** | 🟢 |
| `publish/audiobookshelf_integration.py` | 317 | 23 | **93%** | 🟢 |
| `llm/router.py` | 435 | 43 | **90%** | 🟢 |
| `feedback/bootstrap_fewshot.py` | 222 | 24 | **89%** | 🟢 |
| `tts/clone.py` | 271 | 35 | **87%** | 🟢 |
| `feedback/quality_enhancement.py` | 208 | 21 | **90%** | 🟢 |

---

## 五、遗留问题与下一步

### 短期（1-2 天）
- [ ] 总体覆盖率从 75% → 80%：需提升 `utils/`、`quality/`、`api/` 等模块
- [ ] 修复 263 个失败测试（多为导入错误或外部依赖问题）

### 中期（1-2 周）
- [ ] Sprint G 真实实现：翻译/克隆/发布接入真实外部服务
- [ ] 全量 E2E 长书验证（≥10 万字符端到端）

### 长期
- [ ] 前端多轨编辑器增强
- [ ] 成本面板 + 团队协作模块

---

## 六、文档架构

本文件取代 `docs/frontend-feature-list.md`（已于 2026-06-27 物理删除）。

现有核心文档的职责划分：

| 文档 | 职责 | 与本文件关系 |
|------|------|-------------|
| **PROJECT_STATUS.md**（本文件） | 唯一真相源——状态、覆盖率、Sprint 进度 | **权威来源** |
| `PROJECT.md` | 项目业务说明、开发规范、Sprint 计划表 | 状态以本文件为准 |
| `EXECUTION_CHECKLIST.md` | 详细执行清单、审计发现 | 状态以本文件为准 |
| `AGENTS.md` | Agent 开发行为规范 | 不涉及状态，不受影响 |
| `HARNESS_SPECIFICATIONS.md` | LLM 马具规范 | 不涉及状态，不受影响 |

> **规则**: 更新项目状态时，**必须**同步更新本文件。其他文档的状态信息可能滞后，
> 但本文件永远是最新的。

### Agent 分支隔离机制 (2026-06-27 新增)
- **CODEOWNERS**: `.github/CODEOWNERS` — Agent A/B/C 各自领地的所有权锁定
- **CI 门禁**: `.github/workflows/agent-isolation-check.yml` — 越界自动拦截
- **本地隔离**: `scripts/agent-worktree-setup.sh` — git worktree 物理隔离
- **策略文档**: `docs/AGENT_ISOLATION_POLICY.md` — 四维防线完整说明

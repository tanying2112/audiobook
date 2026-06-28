# Agent 分支绝对隔离策略 (v2 — 审计修正版)

> **版本**: v2.0  
> **生效日期**: 2026-06-27  
> **变更说明**: 修正 Agent A/C 领地倒置问题，对齐白皮书 V3.0 ROI 靶心  
> **适用范围**: 所有参与本项目的 AI Agent 及人类开发者  
> **维护者**: @guwj（人类架构师）

---

## 一、设计目标

在多 Agent 高并发协作的生产环境中，仅靠口头约定无法防止分支冲突。本策略从四个维度建立刚性物理防线，确保每个 Agent 只能修改其管辖领地内的代码：

| 维度 | 工具 | 防护等级 |
|------|------|---------|
| **策略层** | Git 分支命名规范 `agent/A|B|C/*` + 受保护分支 | 规范约束 |
| **权限层** | `.github/CODEOWNERS` 领地所有权锁定 | PR 审批拦截 |
| **门禁层** | `.github/workflows/agent-isolation-check.yml` | CI 自动拦截 |
| **本地层** | `scripts/agent-worktree-setup.sh` + `git worktree` | 文件系统隔离 |

---

## 二、Agent 领地拓扑（白皮书 V3.0 ROI 对齐）

### Agent A：后端高吞吐爆破手

- **分支前缀**: `agent/A/*`
- **角色定位**: API CRUD 端点覆盖率冲刺 + 单元测试基建
- **领地范围**:
  - `src/audiobook_studio/api/` — 全部 API 端点（books, characters, paragraphs, projects, qualities, routings, tts_edits, harness, golden, upload, feedback, collab, templates, auto_run, export, websocket, mock_router）
  - `tests/unit/` — 全部单元测试文件
- **红线**: ❌ 禁止修改 pipeline/、tts/、llm/ 等核心管线代码
- **验收指标**: api/ 下各端点测试覆盖率 ≥ 80%

### Agent B：前端状态清洗 + 算法防御专家

- **分支前缀**: `agent/B/*`
- **角色定位**: 前端数据清洗基建 + 后端算法黑盒 Mock
- **领地范围**:
  - `web/src/utils/` — 前端工具函数与数据清洗
  - `web/src/stores/` — Pinia 状态管理
  - `web/src/main.ts` — 前端入口
  - `src/audiobook_studio/quality/` — 质量检测算法模块
  - `src/audiobook_studio/monitoring/` — 监控告警系统
  - `src/audiobook_studio/feedback/` — 反馈闭环系统
- **红线**: ❌ **严禁触碰 UI 组件**（`web/src/views/`、`web/src/components/`），仅限数据基建与算法模块
- **验收指标**: quality/monitoring/feedback 覆盖率 ≥ 80%

### Agent C：跨端通信 + 核心管线爆破手

- **分支前缀**: `agent/C/*`
- **角色定位**: 核心管线 synthesize.py 巨头 + LLM 路由 + TTS + 发布 + SSE 跨端
- **领地范围**:
  - `src/audiobook_studio/pipeline/` — 核心 6 环节管线（synthesize.py 为 ROI 巨头，未覆盖行高达 392 行）
  - `src/audiobook_studio/tts/` — TTS 合成引擎
  - `src/audiobook_studio/llm/` — LLM 路由与多提供商调度
  - `src/audiobook_studio/schemas/` — 数据契约模型
  - `src/audiobook_studio/models/` — 数据库模型
  - `src/audiobook_studio/utils/` — 工具函数（ffmpeg_probe 等）
  - `src/audiobook_studio/publish/` — 发布集成（audiobookshelf、RSS）
  - `web/src/api/` — 前端 API / SSE 层
- **红线**: ❌ 禁止修改 api/ 端点路由（这是 Agent A 的领地）
- **验收指标**: pipeline/ 覆盖率 ≥ 80%，整体 src 覆盖率 ≥ 80%

### 人类架构师（@guwj）

- **分支命名**: 无限制（推荐 `feature/*`、`bugfix/*`、`refactor/*`）
- **领地范围**: 全部文件
- **职责**: 架构决策、PR 审批、跨 Agent 协调、紧急热修复

---

## 三、受保护分支规则

对 `main` 和 `develop` 分支启用以下保护：

| 规则 | 设置 |
|------|------|
| 禁止直接推送 | ✅ 启用 |
| 强制 Pull Request | ✅ 启用 |
| 要求 CODEOWNERS 审批 | ✅ 至少 1 人 |
| 要求状态检查通过 | ✅ Agent Isolation Check |
| 禁止 force push | ✅ 启用 |
| 禁止分支删除 | ✅ 启用 |

---

## 四、CI/CD 越界拦截流水线

配置文件: `.github/workflows/agent-isolation-check.yml` (v2)

**工作原理**:
1. 检测 PR 分支名是否匹配 `agent/[A-C]/*` 模式
2. 获取 PR 相对于目标分支的所有变更文件
3. 根据 Agent 标识匹配领地白名单
4. 发现越界文件 → 直接 Fail Build，拒绝合并

**触发条件**: 所有 PR 到 `main` 或 `develop`

**绕过方式**: 人类架构师分支（非 `agent/*` 前缀）自动放行。

---

## 五、本地物理隔离（git worktree）

### 创建隔离工作树

```bash
./scripts/agent-worktree-setup.sh setup
```

执行后在项目父目录创建：

| 物理路径 | Agent | 分支 | 核心领地 |
|---------|-------|------|---------|
| `../audiobook-agent-A/` | Agent A | `agent/A/workspace` | api/ + tests/ |
| `../audiobook-agent-B/` | Agent B | `agent/B/workspace` | quality/ + monitoring/ + feedback/ |
| `../audiobook-agent-C/` | Agent C | `agent/C/workspace` | pipeline/ + tts/ + llm/ + utils/ |

### 隔离效果

- ✅ 每个 Agent 拥有独立的文件系统
- ✅ `pytest --cov` 扫描互不干扰
- ✅ `.coverage` 文件物理隔离，无读写冲突
- ✅ 各自独立的 `.venv` 虚拟环境

---

## 六、Agent 派发示例

```bash
# ── Agent A：后端高吞吐爆破手 ──
cd /Users/guwj/Desktop/AI_Lab/audiobook-agent-A
git checkout -b agent/A/fix-api-crud
# 💡 编码红线：只能修改第一、二梯队后端 API
# 目标领地：src/audiobook_studio/api/{books,characters,paragraphs,projects,...}.py + tests/unit/api/
git add src/audiobook_studio/api/ tests/unit/
git commit -m "test: 提升 api/paragraphs 端点覆盖率至 85%"
git push -u origin agent/A/fix-api-crud
# → 自动触发 CI 隔离检查 → 越界则 Fail Build

# ── Agent B：前端状态清洗 + 算法防御专家 ──
cd /Users/guwj/Desktop/AI_Lab/audiobook-agent-B
git checkout -b agent/B/feat-state-normalize
# 💡 编码红线：严禁触碰 UI 组件(views/components)
# 目标领地：quality/ + monitoring/ + feedback/ + web/src/{utils,stores}/
git add src/audiobook_studio/quality/ src/audiobook_studio/monitoring/
git commit -m "test: quality/metrics 覆盖率提升至 90%"
git push -u origin agent/B/feat-state-normalize

# ── Agent C：跨端管线爆破手 ──
cd /Users/guwj/Desktop/AI_Lab/audiobook-agent-C
git checkout -b agent/C/fix-sse-pipeline
# 💡 编码红线：死磕流式交互与 synthesize.py 音频管线巨头
# 目标领地：pipeline/synthesize.py + llm/router.py + tts/engine.py
git add src/audiobook_studio/pipeline/synthesize.py src/audiobook_studio/llm/
git commit -m "test: synthesize.py 覆盖率从 42% 提升至 80%"
git push -u origin agent/C/fix-sse-pipeline
```

---

## 七、违规处理流程

```
Agent A 修改了 pipeline/synthesize.py（Agent C 领地）
    ↓
创建 PR（分支 agent/A/feat-something）
    ↓
GitHub Actions 触发 Agent Isolation Check (v2)
    ↓
检测到 agent/A 分支修改了 pipeline/ 下的文件
    ↓
🚨 [越界警报]: Agent A 无权修改文件: pipeline/synthesize.py
    ↓
流水线 Fail → PR 无法合并
    ↓
Agent 收到通知 → 必须：
  方案 A：将修改移到 agent/C/* 分支
  方案 B：请求人类架构师在 feature/* 分支代为修改
```

---

## 八、领地对齐校验清单

每次修改领地规则时，必须确认以下文件保持同步：

| 文件 | 校验点 |
|------|--------|
| `.github/CODEOWNERS` | Agent A: api/ + tests/；Agent B: quality/ + monitoring/ + feedback/；Agent C: pipeline/ + tts/ + llm/ |
| `.github/workflows/agent-isolation-check.yml` | 白名单与 CODEOWNERS 完全一致 |
| `docs/AGENT_ISOLATION_POLICY.md` | 本文档描述与上述两文件一致 |
| `PROJECT_STATUS.md` | 领地拓扑表与本文档一致 |

---

## 九、变更日志

| 日期 | 版本 | 变更 | 作者 |
|------|------|------|------|
| 2026-06-27 | v1.0 | 初始版本：四维隔离策略建立 | @guwj |
| 2026-06-27 | v2.0 | **修正 Agent A/C 领地倒置**：Agent A → api/ + tests/；Agent C → pipeline/ + tts/ + llm/ | @guwj |

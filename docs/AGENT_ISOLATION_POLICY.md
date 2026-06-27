# Agent 分支绝对隔离策略

> **版本**: v1.0  
> **生效日期**: 2026-06-27  
> **适用范围**: 所有参与本项目的 AI Agent 及人类开发者  
> **维护者**: @guwj（人类架构师）

---

## 一、设计目标

在多 Agent 高并发协作的生产环境中，仅靠口头约定无法防止分支冲突。本策略从四个维度建立刚性物理防线，确保每个 Agent 只能修改其管辖领地内的代码：

| 维度 | 工具 | 防护等级 |
|------|------|---------|
| **策略层** | Git 分支命名规范 + 受保护分支 | 规范约束 |
| **权限层** | `.github/CODEOWNERS` | PR 审批拦截 |
| **门禁层** | GitHub Actions 隔离检查流水线 | CI 自动拦截 |
| **本地层** | `git worktree` 物理隔离 | 文件系统隔离 |

---

## 二、Agent 领地拓扑

### Agent A：后端核心

- **分支前缀**: `agent/A/*`
- **领地范围**:
  - `src/audiobook_studio/pipeline/` — 管线 6 环节
  - `src/audiobook_studio/quality/` — 质量检测
  - `src/audiobook_studio/utils/` — 工具函数
  - `src/audiobook_studio/llm/` — LLM 路由
  - `src/audiobook_studio/tts/` — TTS 合成
  - `src/audiobook_studio/schemas/` — 数据契约
  - `src/audiobook_studio/models/` — 数据库模型
  - `src/audiobook_studio/feedback/` — 反馈闭环
  - `tests/unit/` — 单元测试
- **职责**: 核心业务逻辑、管线编排、质量门禁

### Agent B：前端基建

- **分支前缀**: `agent/B/*`
- **领地范围**:
  - `web/src/views/` — 页面视图
  - `web/src/components/` — UI 组件
  - `web/src/stores/` — Pinia 状态管理
  - `web/src/composables/` — 组合式函数
  - `web/src/router/` — 路由配置
  - `web/src/types/` — TypeScript 类型
  - `web/src/assets/` — 静态资源
- **职责**: Web Studio 前端、时间线编辑器、多轨编辑

### Agent C：跨端胶水

- **分支前缀**: `agent/C/*`
- **领地范围**:
  - `src/audiobook_studio/api/` — FastAPI 路由
  - `src/audiobook_studio/monitoring/` — 监控告警
  - `src/audiobook_studio/publish/` — 发布集成
  - `src/audiobook_studio/auth/` — 认证授权
  - `src/audiobook_studio/middleware/` — 中间件
  - `src/audiobook_studio/config/` — 配置加载
  - `src/audiobook_studio/main.py` — 应用入口
  - `web/src/api/` — 前端 API 层
- **职责**: API 端点、监控面板、发布流程、跨端联调

### 人类架构师（@guwj）

- **分支命名**: 无限制（推荐 `feature/*` 或 `bugfix/*`）
- **领地范围**: 全部文件
- **职责**: 架构决策、PR 审批、跨 Agent 协调

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

配置文件: `.github/workflows/agent-isolation-check.yml`

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

| 物理路径 | Agent | 分支 |
|---------|-------|------|
| `../audiobook-agent-A/` | Agent A | `agent/A/workspace` |
| `../audiobook-agent-B/` | Agent B | `agent/B/workspace` |
| `../audiobook-agent-C/` | Agent C | `agent/C/workspace` |

### 隔离效果

- ✅ 每个 Agent 拥有独立的文件系统
- ✅ `pytest --cov` 扫描互不干扰
- ✅ `.coverage` 文件物理隔离，无读写冲突
- ✅ 各自独立的 `.venv` 虚拟环境

### 管理命令

```bash
./scripts/agent-worktree-setup.sh status     # 查看工作树状态
./scripts/agent-worktree-setup.sh teardown   # 移除所有工作树
```

---

## 六、违规处理流程

```
Agent A 修改了 web/src/views/App.vue
    ↓
创建 PR（分支 agent/A/feat-something）
    ↓
GitHub Actions 触发 Agent Isolation Check
    ↓
检测到 agent/A 分支修改了 web/src/views/ 下的文件
    ↓
🚨 [越界警报]: Agent A 无权修改文件: web/src/views/App.vue
    ↓
流水线 Fail → PR 无法合并
    ↓
Agent 收到通知 → 必须：
  方案 A：将修改移到 agent/B/* 分支
  方案 B：请求人类架构师在 feature/* 分支代为修改
```

---

## 七、与现有规范的对齐

| 本文档 | 关联文档 |
|--------|---------|
| Agent 领地拓扑 | `AGENTS.md` §一 操作边界 |
| 分支命名规范 | `AGENTS.md` §八 分支策略 |
| CI 门禁 | `.github/workflows/agent-isolation-check.yml` |
| 代码所有权 | `.github/CODEOWNERS` |
| 本地隔离 | `scripts/agent-worktree-setup.sh` |
| 项目状态 | `PROJECT_STATUS.md` |

---

## 八、变更日志

| 日期 | 变更 | 作者 |
|------|------|------|
| 2026-06-27 | 初始版本：四维隔离策略建立 | @guwj |

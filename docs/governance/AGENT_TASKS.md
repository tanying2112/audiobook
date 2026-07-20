# 多 Agent 任务分发框架

> **使用方式**：人类调度者将任务分配给各 Agent，每个 Agent 在自己的分支上工作，通过 Git PR 传递成果。
> **协作媒介**：Git 仓库（唯一真相来源）。Agent 间不直接通信，通过 commit + PR + 代码审查协作。

---

## Agent 角色定义

| 角色 | 执行环境 | 擅长 | 分配原则 |
|------|---------|------|---------|
| **Architect** (VS Code Copilot) | 当前会话 | 架构设计、代码审查、集成测试、文档 | 所有设计决策和接口定义 |
| **Coder-A** (本地 Claude Code) | tmux 会话 | 代码实现、单元测试 | 后端逻辑、数据处理 |
| **Coder-B** (本地 Claude Code) | tmux 会话 | 代码实现、单元测试 | TTS 引擎、音频处理 |
| **Runner** (云端 VPS) | SSH 终端 | 长时间运行任务 | DSPy 优化、模型下载、E2E 测试 |

---

## 任务分发协议

### 每个 Agent 收到的任务格式

```markdown
## Task: [任务编号] - [任务名称]

**分支**: feature/[分支名]
**依赖**: [前置任务编号，或"无"]
**预计耗时**: [时间]

### 目标
[一句话描述]

### 输入
- [需要读取的文件/数据]

### 输出
- [需要创建/修改的文件]
- [验收标准]

### 接口契约
[如果涉及跨模块协作，定义接口]

### 完成标志
- [ ] 代码通过 lint (flake8 + black + isort)
- [ ] 单元测试通过
- [ ] 提交到 feature 分支
- [ ] 创建 PR 到 develop
```

### Agent 间通信规则

1. **不直接通信**：Agent 之间不发消息
2. **通过 Git 协作**：
   - Architect 定义接口 → commit 到 `develop`
   - Coder 基于 `develop` 创建 `feature/*` 分支
   - Coder 完成后创建 PR
   - Architect 审查 PR，合并到 `develop`
3. **通过文件契约**：跨模块协作通过 Pydantic schema 文件定义接口
4. **通过 AGENTS.md 规范**：所有 Agent 遵循同一套项目规范

---

## 当前阶段任务清单

### Phase 0: 安全修复（Architect 直接执行）

| 编号 | 任务 | 执行者 | 分支 | 状态 |
|------|------|--------|------|------|
| 0.1 | 清除 llm_providers.yaml 硬编码密钥 | Architect | `hotfix/api-keys` | 🔄 进行中 |
| 0.2 | 创建 llm_providers.yaml.example 模板 | Architect | `hotfix/api-keys` | 🔄 进行中 |
| 0.3 | 将 config/llm_providers.yaml 加入 .gitignore | Architect | `hotfix/api-keys` | 🔄 进行中 |
| 0.4 | 修正 PROJECT.md Sprint G 状态 | Architect | `hotfix/api-keys` | 待定 |

### Phase 1: LLM 语义分析（可并行分发）

| 编号 | 任务 | 执行者 | 分支 | 依赖 | 状态 |
|------|------|--------|------|------|------|
| 1.1 | 新增 FeedbackAnalysis Pydantic schema | Coder-A | `feature/feedback-schema` | 无 | 待分发 |
| 1.2 | 新增 LLMFeedbackAnalyzer 类 | Coder-A | `feature/llm-analyzer` | 1.1 | 待分发 |
| 1.3 | 编写分析提示词模板 | Architect | `feature/llm-analyzer` | 1.1 | 待定 |
| 1.4 | 修改 processor.py 集成 LLM 分析 | Coder-A | `feature/llm-analyzer` | 1.2, 1.3 | 待分发 |
| 1.5 | 单元测试 | Coder-A | `feature/llm-analyzer` | 1.4 | 待分发 |
| 1.6 | 集成测试 | Runner | `feature/llm-analyzer` | 1.5 | 待分发 |

### Phase 2: LLM-as-a-Judge 盲评（可与 Phase 1 并行）

| 编号 | 任务 | 执行者 | 分支 | 依赖 | 状态 |
|------|------|--------|------|------|------|
| 2.1 | LLMJudge 新增 judge_pairwise() 方法 | Coder-A | `feature/judge-pairwise` | 无 | 待分发 |
| 2.2 | 编写盲评 rubric 提示词 | Architect | `feature/judge-pairwise` | 无 | 待定 |
| 2.3 | 修改 ab_test.py 集成盲评 | Coder-A | `feature/judge-pairwise` | 2.1, 2.2 | 待分发 |
| 2.4 | 完善配对 t 检验逻辑 | Coder-A | `feature/judge-pairwise` | 2.3 | 待分发 |
| 2.5 | 测试 | Runner | `feature/judge-pairwise` | 2.4 | 待分发 |

### Phase V: VoxCPM2 集成（可与 Phase 1-2 并行）

| 编号 | 任务 | 执行者 | 分支 | 依赖 | 状态 |
|------|------|--------|------|------|------|
| V.1 | 新增 TTSEngine 抽象接口 | Architect | `feature/tts-engine` | 无 | 待定 |
| V.2 | 实现 VoxCPM2Backend | Coder-B | `feature/voxcpm2-backend` | V.1 | 待分发 |
| V.3 | 简化 annotate_paragraph prompt | Architect | `feature/simplify-annotate` | V.1 | 待定 |
| V.4 | voice_mapping 升级为声音描述格式 | Coder-B | `feature/voice-design` | V.1 | 待分发 |
| V.5 | 音频质量评估模块 | Coder-B | `feature/audio-quality` | V.2 | 待分发 |
| V.6 | DSPy metric 集成音频指标 | Runner | `feature/dspy-audio-metric` | V.5 | 待分发 |

### Phase 3: DSPy 集成（依赖 Phase 1+2 完成）

| 编号 | 任务 | 执行者 | 分支 | 依赖 | 状态 |
|------|------|--------|------|------|------|
| 3.1 | 安装 DSPy，配置 litellm 后端 | Runner | `feature/dspy-setup` | Phase 1+2 | 待分发 |
| 3.2 | 定义 DSPy Signature | Architect | `feature/dspy-signatures` | 3.1 | 待定 |
| 3.3 | 定义质量评估 metric | Architect | `feature/dspy-metrics` | 3.2 | 待定 |
| 3.4 | 黄金数据集转换 | Coder-A | `feature/dspy-dataset` | 3.1 | 待分发 |
| 3.5 | 实现 DSPyOptimizer | Coder-A | `feature/dspy-optimizer` | 3.2, 3.3, 3.4 | 待分发 |
| 3.6 | CLI 工具 | Coder-A | `feature/dspy-cli` | 3.5 | 待分发 |
| 3.7 | 集成 prompt_upgrader | Coder-A | `feature/dspy-integration` | 3.6 | 待分发 |
| 3.8 | Promotion Gate 集成 | Coder-A | `feature/dspy-gate` | 3.7 | 待分发 |
| 3.9 | CI 集成 | Runner | `feature/dspy-ci` | 3.8 | 待分发 |
| 3.10 | E2E 测试 | Runner | `feature/dspy-e2e` | 3.9 | 待分发 |

---

## 分发给各 Agent 的指令模板

### 给本地 Claude Code Worker 的指令

```
你正在参与 Audiobook Studio 项目开发。请先阅读：
1. AGENTS.md — 项目规范（必须遵守）
2. AGENT_TASKS.md — 你的任务定义
3. [接口契约文件] — 依赖的接口定义

你的任务：[任务编号] - [任务名称]
分支：feature/[分支名]
基于：develop 分支

要求：
- 遵循 Conventional Commits 规范
- 代码通过 flake8 + black + isort
- 编写单元测试
- 完成后创建 PR 到 develop
```

### 给云端 VPS Agent 的指令

```
你正在参与 Audiobook Studio 项目开发。请先阅读：
1. AGENTS.md — 项目规范
2. AGENT_TASKS.md — 你的任务定义

你的任务：[任务编号] - [任务名称]
环境要求：[GPU/CPU/内存/磁盘]

注意：
- VPS 上 Python 环境可能不同，先检查 Python 版本
- 模型文件较大，下载到 models/ 目录
- 长时间任务注意断点续传
- 完成后将结果文件提交到 Git
```

---

## 并行执行计划

```
时间轴 →

Architect (我):  [Phase 0 安全修复] → [定义接口] → [审查PR] → [定义接口] → [审查PR]
                              ↓
Coder-A:                    [Phase 1.1-1.6] ──────────→ [Phase 3.4-3.8]
                              ↓                           ↓
Coder-B:                    [Phase V.2-V.5] ──────────→ ─┘
                              ↓
Runner (VPS):               [Phase 1.6 测试] → [Phase V.6] → [Phase 3.1, 3.9-3.10]
```

**关键路径**：Phase 0 → Phase 1 → Phase 3（DSPy 依赖 LLM 分析和 Judge）
**可并行**：Phase V（VoxCPM2）与 Phase 1-2 完全独立

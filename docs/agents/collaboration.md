# 多 Agent 合作规范

> **适用对象**：所有参与 Audiobook Studio 开发的人类开发者与 AI Agent。
>
> **目标**：让多个 Agent 能在同一台机器、不同计算机、离线环境和云上环境中安全、连续、可追溯地协作开发。
>
> **核心原则**：任务可交接、状态可恢复、文件不冲突、验证可重复、权限最小化。

---

## 一、总则

### 1.1 协作模型

Audiobook Studio 支持以下协作形态：

| 协作形态 | 适用场景 | 推荐机制 |
|---|---|---|
| 同一台电脑多 Agent | 快速原型、并行开发、本地调试 | Git Worktree + 独立 VS Code 窗口 |
| 不同计算机多 Agent | 远程团队、多人多机协作 | 分支 + Pull Request + CI |
| 离线多 Agent | 内网、保密项目、本地模型 | 本地 Git + 本地任务队列 + Docker/venv |
| 云上多 Agent | 自动化流水线、远程 Agent Runner | CI/CD + Secrets + 云存储 + 最小权限 Token |
| 云上 VPS + 本地 Agent 混合协作 | 本地开发 + 云上长任务/长耗时 TTS/CI Runner | Git 分支同步 + SSH/rsync + VPS checkpoint + 本地验收 |

### 1.2 不可突破的底线

无论协作形态如何，以下规则必须遵守：

1. **禁止多个 Agent 同时修改同一文件**，除非使用明确的任务拆分或冲突合并流程。
2. **禁止直接修改 `develop` / `main`**，所有功能变更必须走分支与 PR/MR。
3. **禁止硬编码密钥、Token、密码或私有配置**。
4. **长任务必须支持断点续传**，并保存 checkpoint。
5. **Agent 接手未完成任务时，必须先读取交接状态，不得凭猜测继续执行**。
6. **每次功能修改后必须运行验证命令**，至少包括相关测试。
7. **所有交接状态必须写入文档或任务文件**，不得只存在于聊天上下文。

---

## 二、Agent 角色模型

### 2.1 推荐角色

| 角色 | 英文代号 | 职责 | 默认权限 |
|---|---|---|---|
| 总控 Agent | `coordinator` | 拆解任务、分配 Agent、合并状态、最终验收 | 可写任务文档；代码变更需经执行 Agent |
| 后端 Agent | `backend-agent` | API、数据库、业务管线、TTS/LLM 集成 | 可写 `src/`、`config/`、`scripts/` 相关部分 |
| 前端 Agent | `frontend-agent` | Web Studio、组件、交互、样式 | 可写 `web/` |
| 测试 Agent | `test-agent` | 单元测试、E2E、覆盖率、回归测试 | 可写 `tests/` |
| 文档 Agent | `docs-agent` | README、docs、PROJECT 日志、贡献指南 | 可写 `docs/`、`README.md`、`PROJECT.md` |
| 审查 Agent | `review-agent` | 代码审查、安全检查、性能检查、文档一致性 | 默认只读；可写审查报告 |
| 运维 Agent | `ops-agent` | Docker、CI/CD、部署、监控、告警 | 可写 CI/CD、部署配置 |

### 2.2 角色职责边界

每个 Agent 必须遵守：

- 只处理自己角色范围内的任务。
- 需要跨角色修改时，必须在任务状态中说明原因。
- 不得替代其他 Agent 做长期决策，只能提出建议或发起交接。
- 发现上游任务状态不完整时，必须先补齐状态再执行。

### 2.3 最小权限原则

| 环境 | 权限建议 |
|---|---|
| 本地开发 | 可读写当前项目目录 |
| 分支开发 | 只能推自己的 feature/bugfix 分支 |
| 云上 Agent | 只授予当前任务所需仓库、存储、日志权限 |
| 生产部署 | Agent 不得直接操作生产；只能触发受控部署任务 |
| 密钥访问 | 只读 Secrets，不写入代码、日志或文档 |

---

## 三、任务模型

### 3.1 任务状态文件

推荐使用以下任务状态文件：

```text
docs/agents/task-queue.md
docs/agents/handoff.md
docs/agents/agent-log.md
```

如果项目需要机器可读状态，可新增：

```text
docs/agents/task-queue.json
```

### 3.2 任务状态字段

每个任务至少包含：

```yaml
task_id: TASK-001
title: 修复 TTS 增量合成断点续传
status: in_progress
owner: backend-agent
parent_task: TASK-000
branch: feature/tts-checkpoint
files:
  - src/audiobook_studio/pipeline/synthesize.py
  - tests/unit/test_synthesize.py
dependencies:
  - TASK-000
acceptance:
  - python3 -m pytest tests/unit/test_synthesize.py -q
notes: |
  需要复用磁盘元数据与 text_hash，避免重启后重复合成。
started_at: 2026-06-15T00:00:00+08:00
updated_at: 2026-06-15T00:00:00+08:00
```

### 3.3 任务状态枚举

| 状态 | 含义 | 允许动作 |
|---|---|---|
| `backlog` | 尚未开始 | 分配 owner、拆分子任务 |
| `ready` | 信息完整，可开始 | Agent 领取 |
| `in_progress` | 正在执行 | 更新进度、写 checkpoint |
| `blocked` | 被依赖或环境问题阻塞 | 记录阻塞原因 |
| `needs_review` | 实现完成，待审查 | Review Agent 审查 |
| `needs_rework` | 审查不通过 | 返回 owner 修改 |
| `done` | 验证通过，可合并 | 合并到 develop |
| `abandoned` | 明确放弃 | 归档原因 |

### 3.4 任务领取规则

Agent 领取任务前必须确认：

1. `status == ready` 或 `in_progress` 且原 owner 已交接。
2. 分支已创建。
3. 相关文件没有未提交冲突。
4. 验收命令明确。
5. 依赖任务已完成或明确无需等待。

---

## 四、新 Agent 接手未完成任务流程

### 4.1 接手触发场景

以下情况必须执行交接流程：

- 原 Agent 超时、中断或停止响应。
- 原 Agent 会话上下文丢失。
- 任务被重新分配给其他 Agent。
- 原 Agent 完成部分实现但未合并。
- 本地与云上 Agent 切换。
- 同一台机器上多个 Agent 轮换执行。

### 4.2 接手前检查清单

新 Agent 接手前必须执行：

```markdown
## Handoff Intake Checklist

- [ ] 读取 `PROJECT.md` 更新日志
- [ ] 读取 `docs/agents/task-queue.md`
- [ ] 读取 `docs/agents/handoff.md`
- [ ] 读取 `docs/agents/agent-log.md`
- [ ] 运行 `git status`
- [ ] 确认当前分支与任务分支一致
- [ ] 确认是否存在未提交变更
- [ ] 确认是否有 `.env`、密钥、临时大文件
- [ ] 运行相关测试或至少编译检查
- [ ] 在 `handoff.md` 中记录接手时间与新 owner
```

### 4.3 接手步骤

1. **读取任务状态**
   - 找到对应 `task_id`。
   - 确认 `owner`、`branch`、`files`、`acceptance`、`notes`。

2. **读取原 Agent 上下文**
   - 优先看 `handoff.md`。
   - 其次看 `agent-log.md`。
   - 最后看任务分支中的最近提交。

3. **检查当前工作区**
   - 如果有未提交变更，先判断是否属于当前任务。
   - 不属于当前任务的变更不得继续修改，应记录并通知协调者。

4. **恢复执行环境**
   - 激活 venv 或确认 Docker 环境。
   - 安装缺失依赖。
   - 确认 `.env.example` 与本地 `.env` 不泄露。

5. **运行验证基线**
   - 至少运行相关测试。
   - 如果基线失败，先记录失败，再判断是否由当前任务引入。

6. **继续执行**
   - 从最近 checkpoint 或最后一条日志继续。
   - 不得重写原 Agent 已完成且已验证的逻辑，除非有明确缺陷。

7. **写接手记录**
   - 在 `handoff.md` 中记录接手原因、当前状态、下一步动作。

### 4.4 接手记录模板

```markdown
## TASK-001 接手记录

- 接手时间：2026-06-15 10:30
- 原 owner：backend-agent
- 新 owner：backend-agent-2
- 接手原因：原 Agent 会话中断
- 当前分支：`feature/tts-checkpoint`
- 当前状态：部分实现完成，测试未运行
- 已确认文件：
  - `src/audiobook_studio/pipeline/synthesize.py`
  - `tests/unit/test_synthesize.py`
- 当前风险：
  - 磁盘元数据格式尚未文档化
- 下一步：
  1. 补充元数据 schema 说明
  2. 运行相关测试
  3. 更新 PROJECT.md 日志
```

---

## 五、同一台电脑多 Agent 协作（精简）

仅保留“核心对比维度”要点：

- 同步方式：工作区隔离（`git worktree`）；以本地磁盘为单一事实源。
- 资源分配：共享本地资源，优先将短任务与调试留在本地。
- 交接方式：本地 `handoff.md` 与 `agent-log.md`，及独立 worktree。
- 风险点：工作区/输出目录冲突、同文件并发修改。

---

## 六、不同计算机多 Agent 协作（精简）

仅保留“核心对比维度”要点：

- 同步方式：Git 分支 + PR/MR + CI 自动验证。
- 资源分配：各机资源独立，按硬件/任务需求分派。
- 交接方式：PR 描述 + `handoff.md`/`agent-log.md` 记录接手与验收。
- 风险点：合并冲突、分支不同步、环境差异导致验证失败。

---

## 七、离线多 Agent 协作（精简）

仅保留“核心对比维度”要点：

- 同步方式：本地状态文件（`task-queue.md`/`handoff.md`）与本地 Git 提交同步。
- 资源分配：本地计算与模型（Docker/venv），依赖本地镜像与缓存。
- 交接方式：离线文档为主，`handoff.md` + 本地 `agent-log.md`。
- 风险点：同步延迟、依赖不一致、缺乏远程验证手段。

---

## 八、云上多 Agent 协作（精简）

仅保留“核心对比维度”要点：

- 同步方式：Git 平台 + CI Runner；严格的 Secrets 与权限管理。
- 资源分配：云端弹性算力，适合长耗与批量任务。
- 交接方式：任务状态 + CI 输出 + `agent-log.md`。
- 风险点：权限/密钥泄露、日志敏感信息、云端输出成本。
---

## 八之一、云上 VPS Agent 与本地 Agent 混合协作

### 8.1.1 适用场景

云上 VPS 与本地 Agent 混合协作适用于：

- 本地机器负责快速编辑、UI 调试、轻量测试。
- VPS 负责长耗时任务，如批量 TTS、长文本分析、E2E、CI Runner。
- 本地 Agent 需要把未完成任务交给云上 Agent 继续执行。
- 云上 Agent 完成任务后，需要本地 Agent 做人工验收、前端联调或最终合并。
- 本地资源不足，但希望保留本地开发体验和上下文。

### 8.1.2 推荐架构

```text
本地 Agent
  ├── 编辑代码

  ### 八之一、云上 VPS Agent 与本地 Agent 混合协作（精简）

  仅保留“核心对比维度”要点：

  - 同步方式：以 Git 分支为主线；大文件采用 `rsync`/对象存储。
  - 资源分配：本地负责短迭代与验收，VPS 负责长耗时与批量任务。
  - 交接方式：在 `task-queue.md` / `handoff.md` 中明确 checkpoint、输出位置与验收命令；`agent-log.md` 记录执行。
  - 风险点：环境差异、checkpoint 丢失、大文件传输和密钥处理不当。

VPS 上运行的长任务必须：

- 使用 `task_id` 隔离输出目录。
- 每个阶段写 checkpoint。
- 支持从 checkpoint 恢复。
- 日志写入 `logs/YYYY-MM-DD_<agent>.log`。
- 失败时保留最后成功状态。
- 不把敏感信息写入日志。
- 不把大文件输出直接提交到 Git。

### 8.1.10 本地最终验收

本地 Agent 从 VPS 拉取结果后必须运行：

```bash
git pull origin feature/TASK-001-vps-long-run
git status
python3 -m compileall src
python3 -m pytest tests/ -q
./check_rules.sh --fast
```

如任务涉及前端：

```bash
cd web
npm install
npm run build
```

如任务涉及文档：

```bash
mkdocs build --strict
```

---

## 九、文件与目录规范

### 9.1 推荐新增文件

```text
docs/agents/
├── collaboration.md          # 本规范
├── roles.md                  # Agent 角色说明
├── task-queue.md             # 当前任务队列
├── handoff.md                # 交接记录
├── agent-log.md              # Agent 执行日志
└── local-runbook.md          # 本地多 Agent 操作手册
```

### 9.2 文件写入规则

| 文件 | 写入者 | 内容 |
|---|---|---|
| `task-queue.md` | `coordinator` | 任务分配、状态、验收命令 |
| `handoff.md` | 任何交接 Agent | 接手、中断、继续记录 |
| `agent-log.md` | 执行 Agent | 每一步关键操作和验证结果 |
| `PROJECT.md` | `docs-agent` 或 `coordinator` | 项目级更新日志 |
| `docs/agents/collaboration.md` | `docs-agent` | 协作规范维护 |

### 9.3 禁止写入内容

禁止在任务状态、日志、PR 描述中写入：

- API Key
- Token
- 密码
- 数据库连接串
- 私有用户数据
- 未脱敏音频样本
- 未授权的商业文本

---

## 十、验证规范

### 10.1 最小验证

每次任务完成必须至少运行：

```bash
git status
python3 -m compileall src
```

### 10.2 Python 任务验证

```bash
python3 -m pytest tests/unit/test_synthesize.py -q
python3 -m pytest tests/ -q
```

### 10.3 文档任务验证

```bash
mkdocs build
```

### 10.4 前端任务验证

```bash
cd web
npm install
npm run build
```

### 10.5 提交前验证

```bash
pre-commit run --all-files
./check_rules.sh --fast
```

### 10.6 接手验证

接手未完成任务时，至少运行：

```bash
git status
python3 -m compileall src
python3 -m pytest tests/unit/test_<affected_module>.py -q
```

如果接手任务涉及多个模块，应运行：

```bash
python3 -m pytest tests/ -q
```

---

## 十一、Checkpoint 与断点续传

### 11.1 何时需要 checkpoint

以下任务必须写 checkpoint：

- 长文本处理。
- 批量音频合成。
- 批量质量检测。
- 多文件批量迁移。
- 云上 Agent 长任务。
- 网络依赖任务。
- 可能中断的数据处理任务。

### 11.2 checkpoint 内容

```yaml
task_id: TASK-001
step: synthesize_segment
progress:
  processed: 120
  total: 500
last_success_id: book_001_ch1_p120
output_dir: output/book_001/ch1
created_at: 2026-06-15T12:00:00+08:00
next_action: 从 p121 继续合成
```

### 11.3 恢复规则

恢复任务时必须：

1. 读取最新 checkpoint。
2. 校验 checkpoint 对应输出是否存在。
3. 从最后成功步骤继续。
4. 不重复处理已成功步骤。
5. 在 `agent-log.md` 记录恢复过程。

---

## 十二、日志规范

### 12.1 日志位置

```text
logs/YYYY-MM-DD_<agent>.log
docs/agents/agent-log.md
```

### 12.2 日志格式

```text
[2026-06-15T12:00:00+08:00] TASK-001 backend-agent START 读取任务状态
[2026-06-15T12:05:00+08:00] TASK-001 backend-agent CHECK git status 干净
[2026-06-15T12:10:00+08:00] TASK-001 backend-agent TEST pytest tests/unit/test_synthesize.py -q 通过
[2026-06-15T12:15:00+08:00] TASK-001 backend-agent DONE 功能完成，待审查
```

### 12.3 日志要求

- 必须包含时间戳。
- 必须包含任务 ID。
- 必须包含 Agent 名称。
- 必须记录验证命令和结果。
- 不得记录密钥或敏感数据。

---

## 十三、冲突解决规范

### 13.1 冲突类型

| 类型 | 示例 | 处理方式 |
|---|---|---|
| 文件冲突 | 两个 Agent 修改同一文件 | 回到任务拆分，必要时重新分配 |
| 分支冲突 | PR 无法自动合并 | 当前 owner 拉取 develop 后解决 |
| 任务冲突 | 两个任务目标相互影响 | `coordinator` 重新排序 |
| 环境冲突 | 不同 Agent 使用不同依赖 | 统一 requirements 或 Docker |
| 输出冲突 | 多个 Agent 写同一 output 目录 | 使用 task_id 隔离输出 |

### 13.2 冲突解决流程

```text
发现冲突
→ 停止继续修改
→ 记录冲突文件/任务
→ 判断冲突类型
→ 回滚或隔离未验证改动
→ 通知 coordinator
→ 重新分配或解决冲突
→ 重新运行验证
→ 记录到 agent-log.md
```

### 13.3 禁止行为

- 禁止覆盖其他 Agent 的未提交改动。
- 禁止静默解决冲突后不记录。
- 禁止把未验证代码合并到 `develop`。
- 禁止用 `git push --force` 覆盖他人分支。

---

## 十四、安全规范

### 14.1 密钥管理

- 所有密钥放入 `.env`。
- `.env` 必须加入 `.gitignore`。
- 使用 `.env.example` 提供模板。
- 日志中不得打印密钥。
- PR 中不得出现密钥。

### 14.2 最小权限

每个 Agent 只授予完成任务所需权限：

| Agent | 不应拥有 |
|---|---|
| docs-agent | 生产部署权限 |
| test-agent | 生产数据库写权限 |
| review-agent | 代码强制合并权限 |
| frontend-agent | LLM 密钥写权限 |
| ops-agent | 无审批生产发布权限 |

### 14.3 审计要求

所有 Agent 必须记录：

- 开始时间。
- 结束时间。
- 修改文件。
- 运行命令。
- 测试结果。
- 是否接手未完成任务。
- 是否发生冲突。

---

## 十五、验收标准

一个多 Agent 协作流程合格，应满足：

- [ ] 每个任务都有明确 owner。
- [ ] 每个任务都有明确验收命令。
- [ ] 每个任务都使用独立分支。
- [ ] 没有多个 Agent 同时修改同一文件。
- [ ] 接手未完成任务时有 handoff 记录。
- [ ] 长任务有 checkpoint。
- [ ] 所有验证命令通过。
- [ ] 所有日志不含密钥。
- [ ] PR 描述包含协作记录。
- [ ] 合并前通过 CI。

---

## 十六、模板汇总

### 16.1 任务领取模板

```markdown
## 领取任务

- 任务 ID：
- 任务标题：
- 领取 Agent：
- 领取时间：
- 分支：
- 相关文件：
- 验收命令：
- 是否接手未完成任务：是/否
- 已读取交接记录：是/否
```

### 16.2 完成记录模板

```markdown
## 完成任务

- 任务 ID：
- 完成 Agent：
- 完成时间：
- 修改文件：
- 验证命令：
- 验证结果：
- 是否仍有风险：
- 是否可合并：是/否
```

### 16.3 阻塞记录模板

```markdown
## 任务阻塞

- 任务 ID：
- 阻塞 Agent：
- 阻塞时间：
- 阻塞原因：
- 需要谁处理：
- 临时 workaround：
- 下一步：
```

### 16.4 PR 模板片段

```markdown
## 协作说明

- 任务 ID：
- 原 owner：
- 当前 owner：
- 是否接手未完成任务：
- handoff 记录：
- 冲突记录：

## 验证

- [ ] 相关测试通过
- [ ] 全量测试通过
- [ ] lint 通过
- [ ] 文档已更新
- [ ] 无密钥泄露
```

---

## 十七、维护规则

本规范由 `docs-agent` 维护，由 `coordinator` 审核。

当出现以下情况时必须更新本规范：

- 新增协作形态。
- 发生严重协作冲突。
- 接手未完成任务流程失效。
- 新增云上 Agent 权限模型。
- 新增 checkpoint 或任务队列工具。

更新本规范后，应运行：

```bash
mkdocs build
```

并在 `PROJECT.md` 中记录。

# Agent 交接记录

本文件用于记录原 Agent 未完成、暂停、中断或转交任务时的上下文。

## 交接原则

- 新 Agent 接手前必须先读取本文件。
- 交接记录必须包含当前分支、已修改文件、已验证命令、当前风险与下一步。
- 不得只把交接信息放在聊天上下文或终端历史中。
- 长任务必须同时指向 checkpoint 文件。

## 接手记录模板

```markdown
## TASK-001 接手记录

- 接手时间：2026-06-15 10:30
- 原 owner：backend-agent
- 新 owner：backend-agent-2
- 接手原因：原 Agent 会话中断
- 当前分支：`feature/task-001-short-name`
- 当前状态：部分实现完成，测试未运行
- 已确认文件：
  - `path/to/file.py`
- 当前风险：
  - 风险说明
- 下一步：
  1. 运行验证命令
  2. 修复失败项
  3. 更新任务状态
```

## 暂停/中断记录模板

```markdown
## TASK-001 暂停记录

- 暂停时间：
- owner：
- 暂停原因：
- 最后成功步骤：
- checkpoint 位置：
- 未完成任务：
- 可安全重试命令：
- 下次接手建议：
```

## 当前交接记录

### 🤝 协作发起记录：VS Code Agent → 终端 Agent

- **发起时间**：2026-06-16 02:15
- **发起方**：vscode-agent（VS Code 扩展内置 Claude Code）
- **目标方**：terminal-agent（终端运行 `claude --dangerously-skip-permissions`，PID 4758）
- **协作意图**：并行推进 Audiobook Studio 全部 Sprint 任务（A→B→E→F→G）
- **建议协作模式**：
  1. **角色分工**：
     - `terminal-agent` → `backend-agent`：负责 Sprint B（SQLAlchemy/Alembic/断点续传）、Sprint E 后端、Sprint F/G 后端长任务
     - `vscode-agent` → `frontend-agent` + `test-agent` + `docs-agent`：负责 Sprint A 补测试/覆盖率、Sprint C 前端增强、Sprint E 前端反馈闭环、文档维护
  2. **同步机制**：
     - 共享 Git 仓库 + `docs/agents/task-queue.md` 任务队列
     - 通过 `handoff.md` 记录交接、`agent-log.md` 记录执行日志
     - 各自独立分支，PR 合并前跑全量测试 + `./check_rules.sh --fast`
  3. **任务分配**：请终端 Agent 确认后，在 `task-queue.md` 领取 Sprint B 任务
- **当前分支**：`main`（建议各自创建 feature 分支）
- **下一步**：
  1. 终端 Agent 读取此记录，在 `agent-log.md` 确认收到
  2. 双方在 `task-queue.md` 登记各自任务
  3. 开始并行开发

---

暂无其他交接。

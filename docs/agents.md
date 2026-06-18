# Agent 规范手册

本文件为项目中使用的 AI Agent 规范说明，包含 Agent 的职责、交互方式以及开发约定。后续可根据实际需求补充详细内容。

## 多 Agent 协作

多 Agent 协作规范详见 [`collaboration.md`](agents/collaboration.md)。

核心要求：

- 每个任务必须有明确 owner、分支、验收命令。
- 新 Agent 接手未完成任务前，必须先读取 `handoff.md`、`task-queue.md` 与 `agent-log.md`。
- 同一台电脑推荐 Git Worktree 隔离。
- 不同计算机推荐分支 + PR/MR + CI。
- 离线环境使用本地 Git、本地任务队列和本地 LLM。
- 云上环境使用最小权限 Token、CI/CD、Secrets 和 checkpoint。
- 云上 VPS + 本地 Agent 混合协作：本地负责编辑、轻量测试和最终验收；VPS 负责长耗时任务、批量 TTS、E2E 或 CI Runner。
- 长任务必须支持断点续传。
- 禁止多个 Agent 同时修改同一文件。
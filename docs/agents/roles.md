# Agent 角色说明

本文件补充 [`collaboration.md`](./collaboration.md) 中的 Agent 角色模型。

## 角色清单

| 角色 | 代号 | 主要职责 | 典型可修改范围 |
|---|---|---|---|
| 总控 Agent | `coordinator` | 拆解任务、分配 owner、合并状态、最终验收 | `docs/agents/task-queue.md`、`docs/agents/handoff.md`、`PROJECT.md` |
| 后端 Agent | `backend-agent` | API、数据库、LLM/TTS 管线、业务逻辑 | `src/`、`config/`、`scripts/` |
| 前端 Agent | `frontend-agent` | Web Studio、组件、样式、交互 | `web/` |
| 测试 Agent | `test-agent` | 单元测试、集成测试、E2E、覆盖率 | `tests/` |
| 文档 Agent | `docs-agent` | 文档、README、更新日志、贡献指南 | `docs/`、`README.md`、`PROJECT.md` |
| 审查 Agent | `review-agent` | 代码审查、安全、性能、文档一致性 | 默认只读；可写审查报告 |
| 运维 Agent | `ops-agent` | Docker、CI/CD、部署、监控、告警 | `.github/`、`Dockerfile`、`docker-compose.yml`、监控脚本 |
| VPS Agent | `vps-agent` | 云上长任务、批量 TTS、E2E、CI Runner、资源密集型验证 | VPS 工作目录、`checkpoints/`、`output/`、`logs/` |

## 领取任务规则

Agent 领取任务前必须确认：

- 任务状态为 `ready` 或 `in_progress` 且已完成交接。
- 分支已创建。
- 验收命令明确。
- 相关文件没有未提交冲突。
- 已读取 `handoff.md` 与 `agent-log.md`。

## 完成任务规则

Agent 完成任务后必须：

- 运行相关测试。
- 更新 `task-queue.md` 状态。
- 在 `agent-log.md` 记录验证结果。
- 如需交接，在 `handoff.md` 写清楚当前状态、风险、下一步。
- 更新 `PROJECT.md` 的更新日志。

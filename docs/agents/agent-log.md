# Agent 执行日志

本文件用于记录多 Agent 协作中的关键操作、验证结果、冲突和接手信息。

## 日志格式

```text
[YYYY-MM-DDTHH:mm:ss+08:00] TASK-001 agent-name START 读取任务状态
[YYYY-MM-DDTHH:mm:ss+08:00] TASK-001 agent-name CHECK git status 干净
[YYYY-MM-DDTHH:mm:ss+08:00] TASK-001 agent-name TEST pytest tests/unit/test_example.py -q 通过
[YYYY-MM-DDTHH:mm:ss+08:00] TASK-001 agent-name DONE 功能完成，待审查
```

## 必须记录的信息

- 任务 ID。
- Agent 名称。
- 开始/结束时间。
- 修改文件。
- 运行命令。
- 测试结果。
- 是否接手未完成任务。
- 是否发生冲突。
- 是否存在风险或阻塞。

## 禁止记录的信息

- API Key、Token、密码。
- 数据库连接串。
- 未脱敏用户数据。
- 未授权商业文本。
- 未脱敏音频样本。

## 当前日志

[2026-06-16T02:15:00+08:00] COLLAB-INIT vscode-agent START 发起与终端 Agent 协作
[2026-06-16T02:15:00+08:00] COLLAB-INIT vscode-agent WRITE docs/agents/handoff.md 记录协作提议（角色分工、同步机制、任务分配）
[2026-06-16T02:15:00+08:00] COLLAB-INIT vscode-agent WRITE docs/agents/task-queue.md 登记 Sprint A/B/E/F/G 任务分工
[2026-06-16T02:15:00+08:00] COLLAB-INIT vscode-agent WAIT 等待终端 Agent 读取 handoff.md 并在 agent-log.md 确认收到

---

暂无。

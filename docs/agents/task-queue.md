# 当前任务队列

本文件用于记录多 Agent 协作中的任务状态。

> 说明：如果项目需要机器可读任务队列，可同步维护 `task-queue.json`。

## 任务模板

```yaml
task_id: TASK-001
title: 任务标题
status: ready
owner: agent-name
parent_task: TASK-000
branch: feature/task-001-short-name
files:
  - path/to/file.py
dependencies:
  - TASK-000
acceptance:
  - python3 -m pytest tests/unit/test_example.py -q
notes: |
  任务说明、边界、风险、已知问题。
started_at: 2026-06-15T00:00:00+08:00
updated_at: 2026-06-15T00:00:00+08:00
```

## 任务列表

| task_id | title | status | owner | branch | acceptance |
|---|---|---|---|---|---|
| TASK-001 | 多 Agent 协作规范 | done | docs-agent | docs/multi-agent-collaboration | `mkdocs build` |
| **TASK-A1** | **Sprint A：补全测试提升覆盖率至 ≥80%** | ready | **vscode-agent (test-agent)** | `feature/sprint-a-coverage` | `pytest --cov=src --cov-fail-under=80` |
| **TASK-A2** | **Sprint A：黄金数据集完善（6 环节 × 3 用例）** | ready | **vscode-agent (test-agent)** | `feature/sprint-a-golden` | `pytest tests/golden/ -q` |
| **TASK-A3** | **Sprint A：E2E 长书验证通过** | ready | **vscode-agent (test-agent)** | `feature/sprint-a-e2e` | `python -m pytest tests/e2e/ -q` |
| **TASK-B1** | **Sprint B：SQLAlchemy 2.0 层级模型** | ready | **terminal-agent (backend-agent)** | `feature/sprint-b-models` | `pytest tests/unit/test_models.py -q` |
| **TASK-B2** | **Sprint B：Alembic 迁移 + 检查点/断点续传** | ready | **terminal-agent (backend-agent)** | `feature/sprint-b-checkpoint` | `pytest tests/unit/test_checkpoint.py -q` |
| **TASK-E1** | **Sprint E：反馈闭环 - 差异分析 Agent** | backlog | TBD | `feature/sprint-e-feedback` | TBD |
| **TASK-E2** | **Sprint E：提示词自动升级 + Promotion Gate** | backlog | TBD | `feature/sprint-e-promotion` | TBD |
| **TASK-F1** | **Sprint F：Langfuse 集成 + 成本看板** | backlog | TBD | `feature/sprint-f-observability` | TBD |
| **TASK-G1** | **Sprint G：多语言翻译配音 + 声音克隆** | backlog | TBD | `feature/sprint-g-advanced` | TBD |

## 状态说明

- `backlog`：尚未整理
- `ready`：信息完整，可领取
- `in_progress`：正在执行
- `blocked`：被依赖或环境问题阻塞
- `needs_review`：实现完成，待审查
- `needs_rework`：审查不通过
- `done`：验证通过，可合并
- `abandoned`：明确放弃

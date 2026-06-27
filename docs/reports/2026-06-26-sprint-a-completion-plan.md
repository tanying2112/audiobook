# Sprint A 收尾计划 - 2026-06-26

> 基于全面审计发现，Sprint A 尚需完成以下任务才能正式收尾

## 当前状态

| 指标 | 状态 |
|------|------|
| Pipeline 平均覆盖率 | 81.5% ✅ |
| 总体覆盖率 | 67.79% ⚠️ |
| Mock Router | ✅ 已实现 |
| ISO 8601 时间戳 | ✅ 已实现 |
| 阶段命名映射 | ✅ 已实现 |
| TTS 音色枚举 | ✅ 已实现 |
| 导出/发布 API | ✅ 已实现 |

## 任务清单

### P0 级任务（阻塞 Sprint A 收尾）

| 任务 | 文件 | 目标覆盖率 | 状态 |
|------|------|------------|------|
| T-P0-1 | `api/auto_run.py` | 80% | 34.5% → 80% |
| T-P0-2 | `api/templates.py` | 80% | 25.7% → 80% |
| T-P0-3 | `api/publish.py` | 70% | 12.6% → 70% |

### P1 级任务（建议提升）

| 任务 | 工作量 | 状态 |
|------|--------|------|
| T-P1-1 | 删除 `orchestrator.py` 旧文件 | 0.5 天 |
| T-P1-2 | Python 3.14 ffprobe 音频分析 | 1 天 |
| T-P1-3 | 硬编码 test values 清理 | 0.5 天 |

## 执行命令

```bash
# 1. 创建 feature 分支
git checkout -b feature/sprint-a-completion

# 2. 运行当前覆盖率
.pytest --cov=src --cov-report=term-missing -q

# 3. 实现业务逻辑
# - auto_run.py: 实现 _run_auto_pipeline()
# - templates.py: 实现 _apply_template_background()
# - publish.py: 实现真实 API 对接

# 4. 添加测试
# - tests/unit/test_auto_run_business.py
# - tests/unit/test_templates_business.py
# - tests/integration/test_publish_real.py

# 5. 验证 & 提交
pytest --cov=src --cov-fail-under=75
git commit -m "feat: Sprint A 收尾 - API 业务逻辑填充 + 覆盖率提升"
```

## 验收标准

- [ ] 总体覆盖率 ≥ 75% (CI 当前阈值)
- [ ] `api/auto_run.py` 覆盖率 ≥ 80%
- [ ] `api/templates.py` 覆盖率 ≥ 80%
- [ ] `api/publish.py` 覆盖率 ≥ 70%
- [ ] mypy --strict 通过
- [ ] pre-commit 检查通过

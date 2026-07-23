# QUAL-004: mypy --strict 分阶段达标

## 严重级别
**P1 - Medium** (类型安全 / 重构信心)

## 问题描述
当前 `mypy --strict src/audiobook_studio --ignore-missing-imports` 报 200+ 错误：大量 `Any`、缺失返回类型、Pydantic v1/v2 混用 `.dict()`/`.model_dump()`、泛型未参数化。

## 分阶段计划
| 阶段 | 目标 | 预估工时 |
|------|------|----------|
| 1 | 关闭 `ignore_missing_imports`，补全 `types-*` stubs | 4h |
| 2 | 核心模块 `database.py` `config/` `auth/` `models/` 清零 | 8h |
| 3 | Pipeline/Task/API 层清零 | 12h |
| 4 | 全仓 `--strict` 0 error，CI gate | 4h |

## 关键修复点
- `database.py:63` `AsyncSessionLocal` 类型显式标注 `async_sessionmaker[AsyncSession]`
- `config/settings.py` Pydantic v2 `model_config` 替代 `Config`
- `auth/jwt_handler.py` 移除 `Optional[List]` 显式默认 `[]`
- `pipeline/orchestrator.py` 泛型 `Agent[Input, Output]` 显式参数化
- 所有 `.dict()` → `.model_dump(mode='json')`

## 验收标准
- [ ] `mypy --strict src/audiobook_studio` 0 error
- [ ] CI `mypy` job 必须通过（阻断 merge）
- [ ] `pre-commit` 增加 `mypy` hook

## 关联文件
- `mypy.ini` / `pyproject.toml[tool.mypy]`
- 全仓 `src/audiobook_studio/**/*.py`
- `.pre-commit-config.yaml`
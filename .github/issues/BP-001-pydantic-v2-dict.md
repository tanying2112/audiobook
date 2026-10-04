# BP-001: 统一 Pydantic v2 `.model_dump()` 替代 `.dict()`

## 严重级别
**P1 - Medium** (兼容性 / 技术债)

## 问题描述
记忆 `pydantic-v2-migration.md` 已记录，但新代码仍混用：
- `src/audiobook_studio/api/publish.py:200+` `audiobookshelf_config.model_dump()`
- `src/audiobook_studio/api/auto_run.py` `.dict()`
- `src/audiobook_studio/agent/agents.py` `.dict()`

## 修复方案
1. 全仓 `grep -rn "\.dict()" src/` → 统一 `.model_dump(mode='json')`
2. 启用 `pydantic.aliases` 检查或 `ruff` rule `pydantic-dict-method`
3. CI 增加 `grep` 门禁

## 验收标准
- [ ] `grep -rn "\.dict()" src/audiobook_studio` 仅剩测试/兼容层
- [ ] `pytest tests/` 全绿
- [ ] CI 新增 `check-pydantic-v2` job

## 关联文件
- `src/audiobook_studio/api/publish.py`
- `src/audiobook_studio/api/auto_run.py`
- `src/audiobook_studio/agent/agents.py`
- `pyproject.toml` (ruff rules)
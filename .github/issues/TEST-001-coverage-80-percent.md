# TEST-001: 测试覆盖率达标 80% (当前 ~46%)

## 严重级别
**P2 - High** (CI 门禁)

## 现状
`pyproject.toml:87` `fail_under = 80` 但实际 ~46%：
- `src/audiobook_studio/auth/router.py` 0% (测试文件被删)
- `src/audiobook_studio/tts/voice_cloning.py` 排除覆盖
- `pipeline/*.py` 核心链路仅集成测试覆盖，单测缺失

## 修复方案
1. **恢复 `test_auth_router.py`**：
   - Mock `get_current_user` 依赖
   - 覆盖 `/register` `/login` `/refresh` `/me` 4 个端点
   - 正向 + 逆向 (401/422/400) 全覆盖

2. **`voice_cloning.py` 拆分纯函数**：
   - 仅排除 `torch` 模型加载分支
   - 音频预处理、文本清洗、输出验证函数单测覆盖

3. **Pipeline 每阶段单测**：
   - `extract.py` `analyze.py` `annotate.py` `edit.py` `synthesize.py` `quality.py` `review.py`
   - Mock LLM/TTS/DB，测试输入→输出转换逻辑

## 验收标准
- [ ] `pytest --cov=src/audiobook_studio --cov-fail-under=80` 通过
- [ ] `pytest tests/unit/auth/` 10+ 测试全绿
- [ ] `pytest tests/unit/pipeline/` 每阶段 ≥ 5 单测

## 关联文件
- `tests/unit/test_auth_router.py` (新建/恢复)
- `tests/unit/pipeline/test_extract.py` 等 (新建)
- `src/audiobook_studio/tts/voice_cloning.py` (重构拆分)
- `pyproject.toml` (覆盖率配置)
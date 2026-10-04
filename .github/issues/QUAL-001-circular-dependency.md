# QUAL-001: 拆解循环依赖 (audiobook_studio.__init__ ↔ config ↔ database)

## 严重级别
**P0 - High** (架构隐患 / 启动风险)

## 问题描述
`src/audiobook_studio/__init__.py:9` 导入 `config` → `config/settings.py` 实例化 `_settings` 调用 `validate_jwt_secret()` → 读取环境变量 → 触发 `database.py` 导入模型 → 模型导入 `__init__.py` 形成循环。

## 风险
- 解释器启动时随机 `ImportError` / `AttributeError`
- 热重载 / 测试收集阶段不稳定
- 难以排查的生产故障

## 修复方案
1. **配置加载器分离**：`config/loader.py` 仅含 `get_settings()` + `@lru_cache`，无副作用导入
2. **数据库层不导入模型**：`database.py` 仅导出 `Base, engine, SessionLocal, get_async_session`，**不** `from .models import ...`
3. **模型按需显式导入**：`models/__init__.py` 显式 `from .book import Book` 等，上层按需 `from audiobook_studio.models import Book`

## 验收标准
- [ ] `python -c "import src.audiobook_studio; print('ok')"` 无循环导入警告
- [ ] `pydeps src/audiobook_studio --max-bacon=0` 无环
- [ ] 现有测试 `pytest tests/unit/` 全绿
- [ ] 启动时间无回归

## 关联文件
- `src/audiobook_studio/__init__.py:9`
- `src/audiobook_studio/config/settings.py:139-155`
- `src/audiobook_studio/config/loader.py` (新建)
- `src/audiobook_studio/database.py`
- `src/audiobook_studio/models/__init__.py`
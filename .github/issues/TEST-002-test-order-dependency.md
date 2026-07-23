# TEST-002: 消除测试顺序依赖 / 全局状态污染

## 严重级别
**P2 - High** (测试可靠性)

## 问题描述
记忆 `test-order-dep-stub-gotcha.md`：`test_run_pipeline.py` 单独跑 45 error、全量跑 1 fail。根因：模块级 `sys.path.insert` 污染全局导入缓存，新测试成"填充者"复现全量常态。

## 现象
- `pytest tests/unit/test_run_pipeline.py` 单独 45 error
- `pytest tests/unit/` 全量 1 fail
- `pytest tests/unit/test_xxx.py tests/unit/test_run_pipeline.py` 顺序相关

## 修复方案
1. **禁止模块级副作用 import**：
   - 所有 `conftest.py` 使用 `pytest.fixture(scope="session", autouse=True)` 隔离 `sys.path`
   - 禁用 `sys.path.insert`，改为 `PYTHONPATH` 或 `pytest.ini pythonpath`

2. **Fixture 注入替代全局状态**：
   ```python
   # conftest.py
   @pytest.fixture(scope="session", autouse=True)
   def _isolate_sys_path():
       orig = sys.path.copy()
       yield
       sys.path[:] = orig
   ```

3. **CI 增加随机顺序卡冒烟**：
   - `pytest --random-order --random-order-seed=42`
   - 连跑 3 次 0 flaky

## 验收标准
- [ ] `pytest --random-order tests/unit/` 连跑 3 次 0 failed / 0 error
- [ ] `test_run_pipeline.py` 单独 / 全量 / 随机顺序结果一致
- [ ] `grep -r "sys.path.insert" tests/` 仅剩 fixture 内部

## 关联文件
- `tests/conftest.py`
- `tests/conftest_minimal.py`
- `tests/unit/test_run_pipeline.py`
- `pyproject.toml` (pytest-random-order)
- `.github/workflows/ci.yml` (新增 random-order job)
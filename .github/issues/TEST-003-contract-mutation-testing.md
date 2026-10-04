# TEST-003: 引入契约测试 + 变异测试

## 严重级别
**P2 - Medium** (测试质量纵深)

## 现状
仅 `pytest` 单元/集成，无：
- `schemathesis` OpenAPI 契约测试 (CI 有 job 但未强制)
- `mutmut` 变异测试验证断言质量
- `hypothesis` 基于属性测试 (仅 `test_ab_test.py` 少量使用)

## 修复方案
### 1. Schemathesis 契约测试 (强制 CI)
```python
# tests/contract/test_openapi.py
import schemathesis
from src.audiobook_studio.main import app

schema = schemathesis.openapi.from_asgi("/openapi.json", app)

@schema.parametrize()
def test_api_conformance(case):
    case.call_and_validate()
```
- CI `golden-contract` job `schemathesis run --checks=all` 必过
- 覆盖所有 `/api/*` 端点，含 4xx/5xx 响应 schema 验证

### 2. Mutmut 变异测试
```bash
# CI 新增 job
mutmut run --paths-to-mutate=src/audiobook_studio --tests-dir=tests/unit --runner="pytest -x"
mutmut results --threshold=80  # 变异杀灭率 ≥ 80%
```
- 重点模块：`security.py` `jwt_handler.py` `safe_subprocess.py` `upload.py`

### 3. Hypothesis 扩展
- `security.py::sanitize_filename` / `safe_join` / `validate_file_path` 属性测试
- `pipeline/extract.py::split_into_chapters` 文本分割不变量
- `quality/metrics.py` 指标计算边界

## 验收标准
- [ ] CI 新增 `contract-test` `mutation-test` job 必过
- [ ] `schemathesis` 零 schema 违规
- [ ] `mutmut` 杀灭率 ≥ 80% (核心安全模块 ≥ 90%)
- [ ] `hypothesis` 新增 10+ 属性测试

## 关联文件
- `.github/workflows/ci.yml` (新增 jobs)
- `tests/contract/test_openapi.py` (新建)
- `tests/unit/security/test_sanitize_hypothesis.py` (新建)
- `tests/unit/pipeline/test_extract_hypothesis.py` (新建)
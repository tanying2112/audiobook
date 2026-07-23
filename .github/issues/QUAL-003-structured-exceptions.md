# QUAL-003: 统一结构化异常 + 错误码枚举

## 严重级别
**P1 - Medium** (可观测性 / 故障诊断)

## 问题描述
`src/audiobook_studio/api/upload.py:380-420` `run_extraction()` 仅 `except Exception as e: error=str(e)`，丢失 traceback、输入上下文、Redis 状态。前端无法展示友好错误码。

## 修复方案
1. 定义错误码枚举 `src/audiobook_studio/exceptions.py`：
   ```python
   class ExtractionErrorCode(IntEnum):
       FILE_NOT_FOUND = 1001
       UNSUPPORTED_FORMAT = 1002
       OCR_FAILED = 1003
       CHAPTER_SPLIT_FAILED = 1004
       DB_COMMIT_FAILED = 1005
       REDIS_JOB_LOST = 1006
   ```

2. 自定义异常基类 `AppException(Exception)` 携带 `error_code: ExtractionErrorCode, context: dict`

3. 统一结构化日志：`structlog.get_logger().bind(job_id=..., project_id=...).exception("extraction failed", error_code=...)`

4. FastAPI 全局异常处理器返回统一格式：
   ```json
   {"error": {"code": 1003, "message": "OCR failed", "details": {...}}}
   ```

## 验收标准
- [ ] 故障注入测试 `tests/unit/api/test_upload.py::test_extraction_failure_logging` 验证日志含 traceback/error_code/context
- [ ] 所有 `except Exception` 重构为具体异常或 `AppException`
- [ ] 前端可按 `error.code` 做差异化展示
- [ ] Sentry/DataDog 等 APM 自动识别错误码

## 关联文件
- `src/audiobook_studio/exceptions.py` (新建/扩展)
- `src/audiobook_studio/api/upload.py`
- `src/audiobook_studio/main.py` (exception handlers)
- `tests/unit/api/test_upload.py` (新增故障注入测试)
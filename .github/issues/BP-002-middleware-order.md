# BP-002: FastAPI 中间件顺序修正

## 严重级别
**P1 - Medium** (规范 / 可观测性)

## 问题描述
`src/audiobook_studio/main.py` 中间件注册顺序错误：
```python
app.add_middleware(ISOTimestampMiddleware)  # 在 CORS 之后
app.add_middleware(CORSMiddleware, ...)
```
导致 CORS 响应头不被时间戳归一化中间件处理，且违反最佳实践顺序。

## 标准顺序
1. `TrustedHostMiddleware` (安全)
2. `CORSMiddleware` (跨域)
3. `GZipMiddleware` (压缩)
4. `ISOTimestampMiddleware` (响应归一化)
5. 认证/授权中间件
6. 限流/审计中间件

## 修复方案
重排 `main.py` 中间件注册顺序，补充缺失的 `TrustedHostMiddleware`、`GZipMiddleware`。

## 验收标准
- [ ] `curl -H "Origin: https://evil.com" -I http://localhost:8000/health` 返回标准 CORS 头
- [ ] 响应体中 `datetime` 字段均为 ISO 8601 (`2026-07-21T12:00:00Z`)
- [ ] `pytest tests/unit/test_timestamp_middleware.py` 全绿

## 关联文件
- `src/audiobook_studio/main.py`
- `src/audiobook_studio/middleware/timestamp.py`
- `tests/unit/test_timestamp_middleware.py`
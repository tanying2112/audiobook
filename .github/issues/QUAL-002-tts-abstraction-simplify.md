# QUAL-002: TTS 抽象层精简 30% (Port/Adapter 过度设计)

## 严重级别
**P1 - Medium** (技术债 / 维护成本)

## 问题描述
仅 3 个后端却有 6 层抽象：`EnginePort` 协议 + 8 backend 实现 + `PortFactory` + `CircuitBreaker` 类 + `RateLimiter` 类 + `port_factory.py`。每新增后端需改 4 文件，违反 YAGNI。

## 现状文件
- `src/audiobook_studio/tts/port.py` (Protocol)
- `src/audiobook_studio/tts/kokoro_backend.py` / `edge_tts_engine.py` / `voxcpm2_backend.py` / `clone.py` / `remote_*_port.py` (8 实现)
- `src/audiobook_studio/tts/port_factory.py`
- `src/audiobook_studio/tts/circuit_breaker.py`
- `src/audiobook_studio/tts/rate_limiter.py`

## 修复方案
1. 保留 `EnginePort` 协议类（结构化类型提示）
2. 移除 `PortFactory`，改用配置驱动动态加载：`settings.TTS_BACKENDS = ["edge", "kokoro", "voxcpm2"]`
3. `tenacity.retry` + `httpx.AsyncClient` 统一重试/熔断，移除单独类
4. `RateLimiter` 合并为 `@rate_limit` 装饰器
5. 新后端仅需：1 文件实现 `EnginePort` + 1 配置行注册

## 验收标准
- [ ] 新增 `dummy` 后端仅需 1 文件 + 1 配置行
- [ ] 代码行数 -30%（`wc -l src/audiobook_studio/tts/*.py` 对比）
- [ ] 现有测试 `pytest tests/unit/tts/` 全绿
- [ ] 熔断/限流功能 behavior-preserving 验证通过

## 关联文件
- `src/audiobook_studio/tts/` 全目录重构
- `src/audiobook_studio/config/settings.py` 新增 `TTS_BACKENDS` 配置
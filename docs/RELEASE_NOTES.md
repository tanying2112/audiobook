# Release Notes

## 2026-06-24 — v0.2.0 Engineering Hardening Release

### Highlights
- **mypy --strict 类型检查通过**: 183 个源文件，0 错误
- **ORM-Schema 单向同步自动化**: `schemas/project.py`、`schema_validator.py` 实现并验证
- **文档站点完善**: MkDocs 24 个核心页面，涵盖架构、API、规范、快速开始等
- **ffprobe 替代 pydub**: Python 3.14 兼容性问题解决
- **FastAPI lifespan 迁移**: `on_event("startup")` → `@asynccontextmanager` 现代模式

### 类型清理详情 (Task #9)
- 修复 `feedback/critics/objective_critic.py`: `prompt_dir` 类型注解
- 修复 `feedback/critics/semantic_critic.py`: `TtsRoutingDecision` 字段访问
- 修复 `schemas/project.py`: `confloat` → `Annotated[float, Field(...)]`
- 移除所有生产代码 `mock_mode` 分支，改用 `MOCK_LLM` 环境变量控制
- 测试文件全面更新以匹配新架构

### 测试状态
- 单元测试：1083 passed, 22 failed (剩余失败集中在 translate.py，非本次范围)
- mypy --strict: ✅ 183 source files, 0 errors
- 核心模块覆盖率：pipeline 83.8% / schemas 99.1% / router 72.5%

### 新增文件
- `src/audiobook_studio/schemas/project.py` — Project ORM 的 Pydantic 对应
- `src/audiobook_studio/schemas/schema_validator.py` — ORM-Schema 同步验证器
- `scripts/docs_guard.py` — 文档守卫脚本（检查代码变更是否需要同步文档）
- `docs/README.md` — 文档维护指南

### 修改文件
- `.pre-commit-config.yaml` — 新增 docs-guard 和 mkdocs-build-check hooks
- `mkdocs.yml` — 添加 24 个文档页面
- `src/audiobook_studio/main.py` — FastAPI lifespan 迁移完成
- `src/audiobook_studio/utils/ffmpeg_probe.py` — pydub 替代方案

### Contributors
- Agent A: Phase 0 基础设施与安全
- Agent B: Phase 1-3 业务与测试

---

## 2026-06-10 – Audiobook Studio MVP Release

### Highlights
- 完成项目所有核心功能，实现文本提取、音频合成、质量检测等完整工作流。
- CI/CD 与 Docker 镜像构建通过，镜像已推送至 Docker Hub（`guwj/audiobook-studio:latest`）。
- 项目文档已使用 MkDocs 完成构建并部署至 GitHub Pages。

### 包含内容
- `src/`：FastAPI 服务实现及业务逻辑。
- `docs/`：MkDocs 文档站点，包含快速入门、API 参考、Agent 使用指南等。
- `Dockerfile`：基于 `python:3.11-slim` 的生产镜像。
- `requirements.txt`：项目依赖列表。

### 已知问题 & 待改进
- 暂未实现多语言配音支持，计划在后续 Sprint 中加入声纹模型。
- 部分大型音频文件的合成速度仍有提升空间，后续将优化并行处理。

---

*此文件为占位发布说明，后续可根据实际发布情况补充细节。*

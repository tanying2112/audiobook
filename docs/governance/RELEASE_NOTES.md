# Release Notes

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

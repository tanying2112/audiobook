# 贡献指南

本项目欢迎任何形式的贡献，包括代码、文档、测试、示例以及改进建议。请遵循以下流程确保贡献顺利合并。

## 前置条件

- 已完成项目的本地开发环境搭建（参考 `docs/quick_start.md`）。
- 熟悉 Git 工作流，了解 **Conventional Commits** 规范。
- 安装了项目的开发依赖（`requirements-dev.txt` 包含 `pytest`, `black`, `isort`, `flake8`, `pre-commit` 等）。

## 开发流程

1. **Fork** 本仓库并 **Clone** 到本地。
2. 创建基于 `develop` 分支的功能分支，例如 `feature/add-new-endpoint`。
3. 在分支上完成代码或文档修改。
4. 运行以下命令确保代码质量：
   ```bash
   pre-commit run --all-files
   pytest --cov=src
   ```
5. 提交更改，使用 **Conventional Commits** 编写提交信息，例如：
   - `feat: add new /books endpoint`
   - `fix: correct typo in docs/quick_start.md`
6. 推送分支并在 GitHub 上创建 **Pull Request**，目标分支为 `develop`。
7. 在 PR 中简要描述更改内容、动机以及可能的影响，必要时附上截图或示例。

## 代码规范

- **格式化**：使用 `black` 自动格式化代码。
- **导入排序**：使用 `isort`。
- **静态检查**：使用 `flake8` 检查 PEP8 违规。
- **类型检查**：项目使用 Pydantic v2，建议在提交前运行 `mypy`（已在 `pre-commit` 中配置）。

## 文档贡献

- 所有文档均使用 **MkDocs**，位于 `docs/` 目录。
- 新增或修改文档后，请运行 `mkdocs build` 确认站点能够成功生成且无警告。
- 文档中涉及的代码示例请确保在当前代码基线上可运行。

## 测试

- 为新功能编写单元测试，放置于 `tests/` 目录，遵循 `pytest` 约定。
- 测试覆盖率应保持在 **80% 以上**（`pytest --cov=src`）。

## 发布流程

- 当 `develop` 分支通过所有 CI 检查后，维护者会合并到 `main` 并打标签发布。
- 发布后会自动构建 Docker 镜像并推送到 Docker Hub（CI 中已配置）。

感谢你的贡献！如果有任何疑问，请在 Issue 区提出或直接联系项目维护者。
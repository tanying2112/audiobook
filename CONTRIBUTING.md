# 贡献指南 (CONTRIBUTING)

## 目标
欢迎任何人参与 **Audiobook Studio** 项目！本指南帮助您快速上手、遵循项目规范并顺利提交代码。

## 前置条件
1. **安装 Git** 并拥有 GitHub 账户。
2. **Python 3.11+**（推荐使用 `venv` 虚拟环境）。
3. **Docker**（用于本地服务编排）。
4. **MkDocs**（文档站点生成），已在 `requirements.txt` 中声明。

## 开发流程概览
1. **Fork 本仓库** → 在自己的 GitHub 账户下创建 fork。
2. **克隆仓库**：`git clone https://github.com/<your-username>/audiobook.git && cd audiobook`
3. **创建分支**：`git checkout -b feature/<简短描述>`（或 `bugfix/`、`hotfix/`）。
4. **安装依赖**：`python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
5. **安装 pre‑commit**：`pre-commit install`
6. **本地自检**：在每次提交前运行 `./check_rules.sh`，确保文档、质量、环境符合规范。
7. **编写代码 & 测试**：在 `src/` 中实现功能，在 `tests/` 中补充对应单元/集成测试。
8. **提交代码**：`git add . && git commit -m "feat: 添加新功能描述"`
9. **推送分支**：`git push origin feature/<name>`
10. **创建 Pull Request**：在 GitHub 上打开 PR，填写 PR 模板，指派审查者。
11. **CI 自动检查**：GitHub Actions 将运行 lint、test、coverage、docker build、health‑report 等。
12. **审查 & 合并**：至少 1 位审查者通过后，CI 通过即可合并到 `develop` 分支。
13. **发布**：合并后 CI 自动构建 Docker 镜像并推送，更新 `PROJECT_HEALTH.md`。

## 提交信息规范
使用 **Conventional Commits** 前缀：
- `feat:` 新功能
- `fix:` 错误修复
- `docs:` 文档更新
- `refactor:` 代码重构（不影响功能）
- `test:` 添加/修改测试
- `chore:` 其他杂务（依赖升级、构建脚本等）

## 代码风格
- **Black**（自动格式化）
- **isort**（导入排序）
- **flake8**（PEP8 检查）
- **bandit**（安全审计）
- **detect‑secrets**（密钥泄露检测）

> 所有上述检查均由 `pre‑commit` 自动执行，提交前请确保 `git commit` 不被阻止。

## 测试要求
- 单元测试覆盖率 **≥ 80%**（`pytest --cov=src`）
- 所有测试必须在 CI 中通过。

## 多 Agent 协作
本项目支持多 Agent 协作开发。多人、多机、离线或云上协作时，请遵循 [`docs/agents/collaboration.md`](docs/agents/collaboration.md)。

重点要求：

- 每个任务使用独立分支。
- 新 Agent 接手未完成任务前必须读取交接记录。
- 云上 VPS 与本地 Agent 可混合协作：本地负责编辑、轻量测试和最终验收，VPS 负责长耗时任务、批量 TTS、E2E 或 CI Runner。
- 长任务必须写 checkpoint。
- 禁止多个 Agent 同时修改同一文件。
- 合并前必须通过测试、lint 与文档检查。

## 文档更新
- 每次功能变更后，请在 `docs/` 中相应更新文档（`index.md`、`architecture.md`、`quick_start.md` 等），并在提交信息中使用 `docs:` 前缀。

## 常见问题
- **密钥泄露**：请勿在代码中硬编码 API 密钥，使用 `.env` 并确保 `.env` 已加入 `.gitignore`。若误提交，请立即使用 `git filter-repo` 清除历史并更换密钥。
- **CI 失败**：检查 GitHub Actions 日志，确保所有 lint、test、docker build 均通过。
- **本地运行错误**：先运行 `./check_rules.sh`，根据提示修复文档或环境问题。

## 联系我们
如有任何疑问，请在 GitHub Issues 中提出，或加入项目的 Slack/Discord 社区（链接见 `README.md`）。

# 文档维护指南

## 文档结构

```
docs/
├── index.md                    # 首页
├── quick_start.md              # 快速开始
├── installation.md             # 安装指南
├── architecture.md             # 架构概述
├── architecture_deep_dive.md   # 架构深入
├── pipeline_tts.md             # Pipeline 与 TTS 规范
├── harness_specifications.md   # HARNESS 规范
├── agents.md                   # Agent 协作系统
├── api.md                      # API 参考 (中文)
├── api_reference.md            # API 参考
├── contributing.md             # 贡献指南
├── troubleshooting.md          # 故障排除
└── ...                         # 其他文档
```

## 文档更新规则

### 何时需要更新文档

| 代码变更类型 | 需要更新的文档 |
|-------------|---------------|
| 新增/修改 API 端点 | `api.md`, `api_reference.md` |
| 修改 Pipeline 逻辑 | `pipeline_tts.md`, `harness_specifications.md` |
| 架构变更 | `architecture.md`, `architecture_deep_dive.md` |
| 新增配置项 | `installation.md`, `quick_start.md` |
| 修改 Schema | `api_reference.md`, `harness_specifications.md` |
| 新增/修改 Agent | `agents.md` |
| 修改核心流程 | `DEVELOPMENT_PLAN.md` (更新状态) |

### 文档更新检查

项目配置了 `Docs Guard` 脚本，在 `pre-push` 阶段自动检查代码变更是否需要同步更新文档。

```bash
# 手动运行检查
python scripts/docs_guard.py
```

### 文档构建

```bash
# 安装依赖
pip install mkdocs mkdocs-material mkdocstrings-python

# 本地预览
mkdocs serve

# 构建静态站点
mkdocs build --strict

# 部署到 GitHub Pages
mkdocs gh-deploy
```

## 文档规范

### 文件格式

- 使用 Markdown 语法
- 代码块指定语言：\`\`\`python
- 使用 admonition 标注注意事项
- 使用 pymdownx.tabbed 组织多选项内容
- 使用 pymdownx.tasklist 表示任务列表

### 命名规范

- 文件名使用 snake_case
- 标题使用 Sentence case
- 代码引用使用 \`inline code\`
- 文件链接使用相对路径

### 版本控制

在文档顶部添加元数据：

```markdown
# 文档标题

> **最后更新**: 2026-06-24
> **关联代码**: `src/audiobook_studio/module.py`
> **版本**: v1.0
```

### 代码示例

示例代码应该：
1. 可独立运行（或明确标注依赖）
2. 包含必要的注释
3. 遵循项目代码风格

## Pre-commit 检查

项目配置了以下文档相关的 pre-commit 检查：

| Hook | 检查内容 | 阶段 |
|------|---------|------|
| `docs-guard` | 检查代码变更是否需要同步更新文档 | pre-push |
| `mkdocs-build-check` | 验证 MkDocs 构建成功 | pre-push |
| `schema-sync-check` | 验证 ORM-Schema 同步 | pre-push |

## 文档审查清单

在提交文档更新前，请确认：

- [ ] 文档内容与实际代码行为一致
- [ ] 代码示例可运行（或已标注为伪代码）
- [ ] 链接有效（无 404）
- [ ] MkDocs 构建成功 (`mkdocs build --strict`)
- [ ] 更新了文档顶部的"最后更新"日期
- [ ] 如有需要，更新了 RELATED_FILES 映射（`scripts/docs_guard.py`）

## 自动化文档生成

部分文档可以通过脚本自动生成：

```bash
# 生成 API 参考
python scripts/gen_api_docs.py

# 合并多个文档
python docs/merge_docs.py
```
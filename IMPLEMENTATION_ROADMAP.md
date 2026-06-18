# Audiobook Studio — 实施路线图（从 0 到 1）

> **生成时间**：2026-06-09
> **前置规范**：[`PROJECT.md`](./PROJECT.md) · [`AGENTS.md`](./AGENTS.md) · [`HARNESS_SPECIFICATIONS.md`](./HARNESS_SPECIFICATIONS.md)
> **本文件作用**：对项目当前状态做精确审计，列出"从零搭建"还缺什么，按优先级给出 6 阶段路线图与可量化目标，并提供"今天就能动手"的 5 件事。

---

## 〇、一句话结论

> **当前项目状态：规范层 100% 完备（1500+ 行），代码层 0%（零文件、零目录、零提交）。**
> **从今天开始，最小可跑通版本（MVP）需要 5 个 Sprint（≈ 5 周）。**

---

## 一、精确审计：实施前还缺什么

### 🔴 P0 · 致命缺口（无这些无法启动）

| # | 缺口 | 现状 | 阻塞什么 |
|---|------|------|---------|
| 1 | **源码目录** | `src/`、`audiobook_studio/`、`__init__.py` 均不存在 | `python -m audiobook_studio.main` 失败 |
| 2 | **契约/Schema 模块** | 6 个 Pydantic 模型（HARNESS §2.1.7 / §2.2.7 / §2.3.7 / §2.4.3 / §2.5.7 / §3.4.4）零实现 | 所有 LLM 环节无类型约束 |
| 3 | **LLM 路由层** | `src/audiobook_studio/llm/router.py`、`client.py`、`judge.py` 不存在 | 多厂商轮换、降级、Kill Switch 无法运行 |
| 4 | **Pipeline 编排** | `pipeline/extract.py`～`quality_check.py` 6 个脚本不存在 | 8 步流水线无法串联 |
| 5 | **提示词资产** | `prompts/` 目录不存在，6 套 Jinja2 模板（`analyze_structure/v1.j2` 等）零文件 | LLM 不知道听谁的指挥 |
| 6 | **黄金数据集** | `tests/golden/` 不存在，至少需要 10 条种子用例 | 评估、回归、Promotion Gate 全部空转 |
| 7 | **环境变量模板** | `.env.example` 不存在，密钥管理全靠默契 | 上线即泄密 |
| 8 | **Dockerfile 缺 ffmpeg** | 当前只装 `build-essential/git/curl` | 音频处理 100% 失败 |
| 9 | **CI 配置断裂** | `.github/workflows/ci.yml` 引用 `scripts/generate_health_report.sh` 与 `pytest --cov=src`，二者均不存在 | CI 红灯、PR 无法合并 |
| 10 | **`.mcp.json` 硬编码** | 引用绝对路径 `/Users/guwj/Desktop/AI_Lab/audiobook_agent2/...` | 任何换机器的开发人员立即崩溃 |

### 🟡 P1 · 严重缺口（影响 MVP 质量）

| # | 缺口 | 影响 |
|---|------|------|
| 11 | **HARNESS §1.5 架构变更未落地** | 多模态 LLM 流式 + 章节 partial_output 合并机制只写在规范里，无任何实现 |
| 12 | **依赖未拆分** | `requirements.txt` 把开发工具（black/flake8/isort）和运行时（pydantic/litellm/instructor）混在一起，Docker 镜像臃肿 |
| 13 | **依赖版本错位** | `black==24.2.0` vs `pre-commit rev: 23.9.1`；`flake8 7.0.0` vs `6.1.0` | pre-commit 与 CI 行为不一致 |
| 14 | **核心 TTS 依赖缺失** | 缺少 `edge-tts`、`kokoro-onnx`、`piper-tts` 等 | 音频合成环节空谈 |
| 15 | **核心提取依赖缺失** | 缺少 `pdfplumber`、`PyPDF2`、`ebooklib`、`python-docx` | 文本提取跑不起来 |
| 16 | **前端零起步** | Web Studio 完全未设计 | 用户无法可视化编辑 |
| 17 | **数据模型未定** | 没用 SQLAlchemy / Tortoise 定义 Project→Chapter→Paragraph→AudioSegment | 持久化、版本回滚、增量合成无法实现 |
| 18 | **音频后处理工具** | 缺 `pydub`、`numpy`、`soundfile`、`ffmpeg-python` | M4B 封装、Auto-Ducking 无从下手 |
| 19 | **`.gitignore` 漏网** | 未排除 `.idea/`、未细化密钥通配 | 协作时易误提交 |
| 20 | **MCP 服务未自检** | `audiobook_agent2/uacf_mcp_bridge.py` 存在性未验证 | 即使能启动，可能调不通 |

### 🟢 P2 · 体验性缺口（不阻塞 MVP）

| # | 缺口 |
|---|------|
| 21 | `docs/` 目录无文件（mkdocs 站点是空壳） |
| 22 | 没有 `LICENSE`（README 宣称 MIT） |
| 23 | 没有 PR / Issue 模板（已有 issue_template.md，需补充 PR） |
| 24 | `random_arrays_demo.ipynb` 与项目无关，应删除 |
| 25 | 无成本看板（每千字 $/每章 $） |

---

## 二、6 阶段实施路线图（30 周 / ≈ 7 个月）

> **核心原则**：每阶段结束都有"可演示成果"（Demo），绝不空对空。
> **执行人**：Agent 全程自主（按 PROJECT.md 授权），用户仅在 P0 决策点（密钥、成本上限）介入。

### 🟢 Phase 0：地基（1 周 · 立即开工）

**目标**：仓库可 `pip install -e .`、可 `pytest`、可 `docker build`。

| 任务 | 产出 | 验收 |
|------|------|------|
| 0.1 修复 `.gitignore` | 删除 Dockerfile/docker-compose 条目；补充 `.idea/`、密钥通配 | `git status` 干净 |
| 0.2 拆分依赖 | `requirements.txt`（运行时）+ `requirements-dev.txt`（工具） | `pip install -e ".[dev]"` 成功 |
| 0.3 补 `.env.example` | 含所有 LLM API key 占位（OPENAI/ANTHROPIC/GEMINI/GROQ/OPENROUTER/DEEPSEEK） | `cp .env.example .env` 即可 |
| 0.4 修复 Dockerfile | 加 `ffmpeg`、`libsndfile1`、`git-lfs`；分阶段 `RUN` 减小镜像 | `docker build` < 2 GB |
| 0.5 修复 `.mcp.json` | 路径相对化（`./scripts/uacf_bridge.py`）+ 启动自检 | VSCode 加载 MCP 成功 |
| 0.6 修复 `.pre-commit-config.yaml` | 版本号与 requirements 对齐 | `pre-commit run --all-files` 通过 |
| 0.7 创建目录骨架 | `src/audiobook_studio/{llm,schemas,pipeline,utils}/`、`tests/{unit,golden,integration}/`、`prompts/{analyze_structure,annotate_paragraph,edit_for_tts,tts_routing,quality_judge}/`、`scripts/`、`docs/` | `tree -L 3` 显示完整 |
| 0.8 写 `scripts/generate_health_report.sh` | 输出 `health.json` 报告（章节/角色/片段统计） | CI 引用即通过 |
| 0.9 删除 `random_arrays_demo.ipynb` | — | — |
| 0.10 首次提交 | `chore: 初始化项目骨架(Phase 0)` | `git log` 有 1 条 |

**Demo**：`docker compose up --build` 启动空壳服务，返回 200 OK；`pytest` 跑通（含 0 个测试也 OK）。

---

### 🔵 Phase 1：契约 + 黄金数据集骨架（2 周 · 第 2-3 周）

**目标**：所有数据模型定义清楚，黄金数据集有 10 条种子用例，DeepEval 能跑通。

| 任务 | 产出 | 验收 |
|------|------|------|
| 1.1 实现 6 个 Pydantic Schema | `schemas/{extraction,book,paragraph,tts_edit,tts_routing,quality,feedback}.py` | `Model.model_validate({...})` 通过 |
| 1.2 写 10 条黄金用例 | `tests/golden/{analyze_structure,annotate_paragraph,edit_for_tts}/` 共 10 条 JSONL | `pytest tests/golden/` 通过 |
| 1.3 实现 LLM 路由层 | `llm/router.py`（LiteLLM + Instructor）、`judge.py` | `router.call(...)` 单元测试通过 |
| 1.4 接 DeepEval | `eval/deepeval_config.py` | `deepeval test run` 跑通种子用例 |
| 1.5 配置 CI Quality Gate | `.github/workflows/llm_quality_gate.yml`（即使 LLM 缺失也跑 schema 校验） | PR 触发 CI，绿勾 |

**Demo**：上传一份样例 PDF → 自动调用 LLM（任一免费厂商）→ 输出符合 Schema 的 `BookAnalysisOutput` JSON → DeepEval 评分 100%。

---

### 🟣 Phase 2：流水线 6 环节全部跑通（3 周 · 第 4-6 周）

**目标**：8 步流水线在 CLI 模式下端到端跑通，处理 1 本 5,000 字短篇童话。

| 任务 | 产出 | 验收 |
|------|------|------|
| 2.1 实现环节①+②（多模态 LLM 流式） | `pipeline/extract.py` + `analyze_structure.py`，支持 partial_output 合并 | 输入 5K 字 PDF → 产出 `BookAnalysisOutput` |
| 2.2 实现环节③ 段落标注 | `pipeline/annotate_paragraph.py` | 30 段全标注，注入"上帝视角" |
| 2.3 实现环节④ 文本编辑 | `pipeline/edit_for_tts.py` | 难度锁、断句、数字归一化全生效 |
| 2.4 实现环节⑤ TTS 路由 + Edge-TTS 实际合成 | `pipeline/synthesize.py` + `tts/edge.py` | 5K 字 → 30 分钟音频，MP3 输出 |
| 2.5 实现环节⑥ 质量检测 | `pipeline/quality_check.py`（规则层）+ LLM Judge | 自动标出 3 类问题 |
| 2.6 实现 Kill Switch | 当所有厂商失败时启用启发式回退 | 单元测试覆盖 |
| 2.7 端到端 smoke test | `tests/integration/test_e2e_short_story.py` | 一键跑通 1 本短篇 |

**Demo**：5,000 字 PDF → 30 分钟 M4B 有声书 + 字幕 SRT + JSON 项目包 + 质量报告。

---

### 🟡 Phase 3：数据持久化 + 增量合成 + Web UI（4 周 · 第 7-10 周）

**目标**：引入数据库与 Web Studio，支持段落级重生成、角色声音管理。

| 任务 | 产出 | 验收 |
|------|------|------|
| 3.1 数据模型 | SQLAlchemy 2.0 定义 Project/Chapter/Paragraph/AudioSegment/Character/Feedback | 迁移脚本可重放 |
| 3.2 项目存储 | `storage/` 布局（`books/<id>/{raw,extracted,annotated,audio,reports}/`） | 路径可配置 |
| 3.3 增量合成 | 仅重跑变更段落，Crossfade 重拼 | 修改 1 段 → 整章 < 30s 重生成 |
| 3.4 FastAPI 后端 | `api/{projects,chapters,paragraphs,audio,quality}.py` | Swagger 文档自动生成 |
| 3.5 Web Studio 基础 | Vue3 + wavesurfer.js，时间轴 / 波形 / 试听 / 重生成 | 浏览器能打开、可操作 |
| 3.6 M4B 封装 | `export/m4b.py`（ffmpeg 章节标记） | 单文件可播、章节可跳 |

**Demo**：浏览器打开 Web Studio，看到 5,000 字项目的完整时间轴，点击任意一句可试听/重生成/编辑，导出 M4B。

---

### 🟠 Phase 4：反馈回路 + 自动迭代（3 周 · 第 11-13 周）

**目标**：马具规范自我升级机制跑通，黄金数据集自动增长。

| 任务 | 产出 | 验收 |
|------|------|------|
| 4.1 反馈采集 | `FeedbackRecord` 在编辑/质检环节自动捕获 | UI 修改 → 数据库有记录 |
| 4.2 差异分析 Agent | `scripts/feedback_processor.py`：LLM 对比原始 vs 修改理由，提取 pattern_tags | 10 条反馈产出 5 条规律 |
| 4.3 提示词版本管理 | `prompts/<stage>/v{N+1}.j2` 自动生成（基于 pattern_tags） | 评审通过后 v2 可用 |
| 4.4 Promotion Gate | `eval/promote.py` 4 项硬指标 | 任何一项不达标即拒绝升级 |
| 4.5 A/B 测试 | 同段文本新旧提示词并行，LLM Judge 评判 | 可视化对比报告 |

**Demo**：故意改 5 条提示词 → CI 拒绝合并（4 项指标未达）→ 修复后再合并 → 自动 v2 升级。

---

### 🔴 Phase 5：CI/CD + 监控 + 灰度发布（2 周 · 第 14-15 周）

**目标**：Production-ready 流水线，监控告警全开。

| 任务 | 产出 | 验收 |
|------|------|------|
| 5.1 GitHub Actions 全套 | `ci.yml` + `llm_quality_gate.yml` + `release.yml` | PR / merge / release 全自动化 |
| 5.2 Langfuse 集成 | Trace 上报，提示词版本管理 UI 化 | Langfuse 控制台可见所有调用 |
| 5.3 监控告警 | 格式合规率 < 99% / Fallback > 5% / 成本超阈值 → Slack/邮件 | 钉钉/邮件告警 demo |
| 5.4 灰度发布 | 5%→25%→50%→100% 自动滚动 | 模拟回滚可 5s 内完成 |
| 5.5 成本看板 | Grafana 仪表盘：每千字 $ / 每章 $ | Web 端可视化 |

**Demo**：杀一个 LLM 厂商 API → 告警 30s 内触发 → 自动降级到备用厂商 → 用户无感。

---

### ⚪ Phase 6：高级特性（2 周 · 第 16-17 周 · 持续迭代）

- 6.1 多语言翻译配音
- 6.2 声音克隆集成（kokoro-onnx / GPT-SoVITS）
- 6.3 Audiobookshelf / Podcast RSS 同步
- 6.4 团队协作（评论、审批、版本）
- 6.5 内容分发（自媒体一键发布包）

---

## 三、目标与成功标准

### 🎯 业务目标（6 个月后）

| 维度 | 目标 |
|------|------|
| **端到端成功率** | 一本 5 万字现代小说 → 30 分钟出 M4B，< 5% 失败率 |
| **角色一致性** | 同一角色在 50 段中音色偏差 < 15% |
| **情感命中率** | LLM Judge 评估 ≥ 0.75 |
| **单本成本** | ≤ $20（环节②③ 走免费厂商 + Edge-TTS） |
| **人工返工率** | < 30% 段落需要人工调整 |
| **马具规范迭代** | 每月 ≥ 1 次有效升级（基于真实反馈） |
| **CI/CD** | PR 平均反馈时间 < 5 分钟 |
| **可观测性** | 100% 调用有 Trace，异常 30s 内告警 |

### 🛡️ Promotion Gate 4 项硬指标

任意一项不达标 → 升级失败：

1. **格式合规率** ≥ 99%
2. **黄金数据集通过率** ≥ 95%
3. **整体质量分** ≥ 旧版本 × 102%
4. **成本/延迟退化** ≤ 旧版本 × 110%

---

## 四、立即可执行的 5 件事（今天/明天动手）

> **按价值/成本比排序，每件事 < 30 分钟**：

1. **【5 分钟】删除 `random_arrays_demo.ipynb`**
   与项目无关，清爽仓库。

2. **【10 分钟】修复 `.gitignore`**
   删除 Dockerfile 排除；补充 `.idea/`、`*.pem`、`*.key`、`secrets.*`。

3. **【15 分钟】补 `.env.example`**
   列出全部 LLM 厂商 key 占位 + 注释说明获取方式。

4. **【20 分钟】创建目录骨架**
   ```bash
   mkdir -p src/audiobook_studio/{llm,schemas,pipeline,utils,tts,export,api} \
            tests/{unit,golden,integration} \
            prompts/{analyze_structure,annotate_paragraph,edit_for_tts,tts_routing,quality_judge} \
            eval scripts docs/architecture
   touch src/audiobook_studio/__init__.py \
         src/audiobook_studio/{llm,schemas,pipeline,utils,tts,export,api}/__init__.py
   ```

5. **【30 分钟】写 `scripts/generate_health_report.sh`**
   ```bash
   #!/usr/bin/env bash
   # 输出仓库健康状态 JSON,供 CI 引用
   set -e
   python -c "import json,sys; json.dump({
     'phase': '0-skeleton',
     'src_exists': __import__('os').path.exists('src'),
     'tests_exist': __import__('os').path.exists('tests'),
     'prompts_exist': __import__('os').path.exists('prompts'),
     'git_commits': len(__import__('subprocess').check_output(['git','log','--oneline']).decode().splitlines())
   }, sys.stdout, indent=2)" > health.json
   ```
   然后 `chmod +x scripts/generate_health_report.sh`。

完成这 5 件事，Phase 0 的 80% 已搞定。

---

## 五、风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| LLM 厂商全挂 | 中 | 高 | Kill Switch + 离线回退（已规划 §七） |
| 多模态 LLM 视觉能力差异 | 高 | 中 | 路由策略按视觉能力分级；先支持纯文本回退 |
| 30 万字长上下文超限 | 高 | 中 | 强制分章节 partial_output（已纳入 §1.5） |
| 用户预算失控 | 中 | 高 | 成本看板 + 硬上限（Phase 5） |
| 角色名混淆 | 高 | 中 | canonical_name 唯一性硬约束（§6.3 不变量） |
| 古籍/复杂版式 | 中 | 低 | MVP 不支持，质量预检直接转人工（§1.5） |

---

## 六、决策待用户确认（影响 Phase 0-1）

> 以下 4 个问题先问清楚，Phase 0/1 才能无缝推进：

1. **MVP 范围**（建议先用 5,000 字童话打通，30 万字长篇暂缓）
2. **数据库选型**（SQLite / PostgreSQL？建议 MVP 用 SQLite，单文件易部署）
3. **首选 LLM 厂商**（有免费额度的：Groq / Gemini / DeepSeek / OpenRouter）
4. **成本上限**（每本 $X 即暂停并告警？建议 $5/章节）

---

> **本文件维护者**：每完成一个 Phase，更新"已完成"勾选、记录实际耗时与偏差，沉淀成项目历史。
>
> **最后原则**：规范服务于落地，落地验证规范。如果某个 Phase 实际证明规范不合理，先改规范再写代码，不要为"合规"而堆垃圾。

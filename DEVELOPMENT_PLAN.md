# Audiobook Studio — 后续开发计划

> **生成时间**：2026-06-12
> **前置规范**：[`PROJECT.md`](./PROJECT.md) · [`AGENTS.md`](./AGENTS.md) · [`IMPLEMENTATION_ROADMAP.md`](./IMPLEMENTATION_ROADMAP.md) · [`HARNESS_SPECIFICATIONS.md`](./HARNESS_SPECIFICATIONS.md)
> **计划性质**：基于当前项目状态（72 测试通过、70% 覆盖率、6 管线就绪）制定的后续推进路线图，直至达成"智能化并可自我迭代升级的有声书系统"的终极目标。

---

## 当前状态快照

| 维度 | 状态 |
|------|------|
| **Pipeline 6 环节** | ✅ 全部实现（extract → analyze → annotate → edit → synthesize → quality） |
| **LLM 路由** | ✅ LiteLLM + Instructor + 7 厂商轮换 + fallback |
| **Pydantic Schema** | ✅ 10 个模块全覆盖 |
| **Prompt 模板** | ⚠️ 部分完成（analyze_structure ✅、edit_for_tts ✅、annotate_paragraph ✅；quality_judge ❌、tts_routing ❌） |
| **测试** | ✅ 72 通过，覆盖率 70% |
| **监控** | ⚠️ 基本（terminal dashboard + JSONL） |
| **CI** | ⚠️ 基本（ci.yml + llm_quality_gate.yml） |
| **Docker** | ⚠️ 存在但未充分测试 |
| **Web UI** | ❌ 未开始 |
| **数据库持久化** | ❌ 未开始 |
| **增量合成** | ❌ 未开始 |
| **M4B/SRT 导出** | ❌ 未开始 |
| **反馈回路/自我迭代** | ❌ 未开始 |
| **声音克隆** | ❌ 未开始 |
| **内容分发** | ❌ 未开始 |

---

## 总体路线图（7 个 Sprint，约 12-14 周）

### Sprint A：夯实基础 + 补全缺口（2 周）

**目标**：消除所有 P0/P1 缺口，覆盖率达到 80%，管线全部可独立验证。

| # | 任务 | 涉及文件 | 验收标准 |
|---|------|---------|---------|
| A1 | **补全 Prompt 模板**：为 `quality_judge` 和 `tts_routing` 编写 `v1.j2` + `few_shot.jsonl` | `prompts/quality_judge/v1.j2`, `prompts/tts_routing/v1.j2` | Jinja2 编译通过，pytest 渲染正常 |
| A2 | **完善黄金数据集**：为所有 6 个管线环节提供至少 3 条种子用例 | `tests/golden/*/` | `pytest tests/golden/` 全覆盖通过 |
| A3 | **补齐 E2E 集成测试**：编写 `test_e2e_short_story.py`，模拟完整 6 步管线端到端流程 | `tests/integration/test_e2e_short_story.py` | 输入短文本 → 6 步管线 → 输出音频元数据与质量报告 |
| A4 | **测试覆盖 pipeline/*.py**：为 analyze_structure、annotate_paragraph、edit_for_tts 添加独立测试 | `tests/test_analyze.py`, `tests/test_annotate.py`, `tests/test_edit.py` | 每文件 ≥ 60% 覆盖率 |
| A5 | **覆盖 API 路由**：为 FastAPI 端点添加测试（依赖注入 mock） | `tests/test_api_routes.py` | 全部 API 端点至少 1 个 happy-path 测试 |
| A6 | **Python 3.14 pyaudioop 兼容**：quality_check.py 音频分析改用 ffprobe 子进程替代 pydub | `src/audiobook_studio/pipeline/quality_check.py` | 音频分析在 Python 3.14 上正常输出 |
| A7 | **FastAPI lifespan 迁移**：`main.py` `on_event("startup")` → lifespan 上下文管理器 | `src/audiobook_studio/main.py` | 启动无 deprecation warning |
| A8 | **监控面板补强**：修复 E501 flake8 警告，添加异常检测逻辑 | `scripts/monitoring_dashboard.py` | flake8 通过，`--json` 输出完整 |
| A9 | **契约版本与监控基础**：<br>• 在 LLMCallResult 中添加 contract_version 字段并记录到日志<br>• 在 monitoring_dashboard.py 中添加 Pydantic schema 合规率监控指标（≥99%）<br>• 创建 config/quality_thresholds.yaml 外部化质量检测阈值<br>• 在 QualityJudgment 中添加结构化修复建议模型 FixSuggestion | `src/audiobook_studio/llm/client.py`, `scripts/monitoring_dashboard.py`, `config/quality_thresholds.yaml`, `src/audiobook_studio/schemas/quality.py` | contract_version 可见于 trace 日志；合规率指标能显示；quality_thresholds.yaml 可被加载；FixSuggestion 能被序列化/反序列化 |
| A10 | **宪法规则热加载接口**：新增 config/constitutional_rules.yaml 与 load_rules() 函数 | `config/constitutional_rules.yaml`, `src/audiobook_studio/config/loader.py` | 规则文件可热加载，无需重启进程 |
| A11 | **LLM 提供商池扩容（P0）**：扩展 ProviderType 枚举新增 13 类型；config/llm_providers.yaml 追加 10 个高优先级免费提供商；启用 Ollama 本地模型作为终极兜底 | `src/audiobook_studio/llm/config_loader.py`, `config/llm_providers.yaml` | 15+ 提供商可被路由选中；Ollama enabled=true |
| A12 | **多 Key 池支持**：ProviderConfig 新增 api_key_pool_env、key_rotation_strategy 字段；config_loader.py 解析 Key 池配置 | `src/audiobook_studio/llm/config_loader.py`, `config/llm_providers.yaml` | YAML 解析通过，Key 池字段可访问 |
| A13 | **环境变量模板同步**：.env.example 补全所有新提供商 API Key 模板 | `.env.example` | 所有新增提供商有对应 KEY 模板 |
| A14 | **免费模型定价归零**：client.py MODEL_PRICING 新增免费模型条目，input/output 定价设为 0.00 | `src/audiobook_studio/llm/client.py` | 免费模型成本追踪正确显示 $0.00 |

**Sprint A Demo**：`pytest --cov=src --cov-report=term-missing` 输出 ≥ 80% 绿色，E2E 测试跑通短篇管线。

---

### Sprint B：数据持久化 + 章节级模型（2 周）

**目标**：引入 SQLAlchemy 2.0 数据库，支持 Project → Chapter → Paragraph → AudioSegment 层级存储，实现断点续传。

| # | 任务 | 涉及文件 | 验收标准 |
|---|------|---------|---------|
| B1 | **数据库模型重构**：升级 `models/` 定义完整的 Project、Chapter、Paragraph、AudioSegment 层级，使用 SQLAlchemy 2.0 ORM | `src/audiobook_studio/models/` | 迁移脚本可创建表，关系完整 |
| B2 | **Alembic 迁移**：编写初始迁移脚本，支持增量模式变更 | `alembic/versions/` | `alembic upgrade head` 成功 |
| B3 | **存储层布局**：`storage/books/<id>/{raw,extracted,annotated,audio,reports}/` | `src/audiobook_studio/storage.py` | 路径可配置，自动创建 |
| B4 | **管线集成 DB**：修改 6 个 pipeline 步骤将结果写入数据库（而非仅返回内存对象） | `src/audiobook_studio/pipeline/*.py` | 管线运行后 DB 可查询完整记录 |
| B5 | **检查点 + 断点续传**：实现 `CheckpointManager`，记录每步完成状态；中断后自动从最后检查点恢复 | `src/audiobook_studio/pipeline/checkpoint.py` | 模拟中断 → 恢复后跳过已完成的步骤 |
| B6 | **API 端点增强**：更新 `api/books.py`、`api/paragraphs.py` 等以使用数据库 | `src/audiobook_studio/api/*.py` | Swagger 交互可 CRUD 项目和章节 |
| B7 | **版本管理与回滚**：<br>• 实现 VersionStore：每次成功 pipeline run 保存 ProcessingConfig + prompt_template + golden_score 为 JSONL 行<br>• 在 ProcessingRun 表中加入 parent_version_id 字段实现版本追溯<br>• 提供 CLI 命令 `python -m scripts.version_manager rollback <version_id>` 实现手动回滚 | `src/audiobook_studio/storage.py`, `src/audiobook_studio/version_store.py`, `scripts/version_manager.py`, `src/audiobook_studio/models/` | VersionStore 能保存和读取快照；ProcessingRun 有 parent_version_id；rollback CLI 能将系统恢复到指定版本 |

**Sprint B Demo**：启动 `uvicorn` → 创建一本书 → 运行管线 → 数据库中有完整数据层级 → 重启后管线从断点恢复 → 执行 `rollback` 命令验证版本回滚功能。

---

### Sprint C：Web Studio 前端（3 周）

**目标**：基于 Vue 3 + wavesurfer.js 构建可视化有声书编辑器，支持时间线浏览、段落试听、重生成。

| # | 任务 | 涉及文件 | 验收标准 |
|---|------|---------|---------|
| C1 | **前端脚手架**：Vite + Vue 3 + TypeScript + Pinia + Vue Router | `web/` 目录 | `npm run dev` 启动，页面加载 |
| C2 | **项目列表页**：展示所有项目，支持新建、删除、搜索 | `web/src/views/Projects.vue` | CRUD 操作通过 API 同步 |
| C3 | **章节时间线**：wavesurfer.js 波形渲染，段落标记，播放/暂停/跳转 | `web/src/views/ChapterTimeline.vue` | 波形显示，点击跳转 |
| C4 | **段落编辑器**：展示段落文本、情感标注、角色绑定、音频块列表，支持在线编辑<br>• 前端提交修改时发送 original_text + modified_text<br>• 后端 FeedbackRecord 自动计算 diff（使用 difflib 生成 ops）<br>• 添加"标记为误报"按钮，存到 FeedbackRecord.false_positive | `web/src/components/ParagraphEditor.vue` | 编辑后提交到 API；FeedbackRecord 包含结构化 diff 和 false_positive 标记 |
| C5 | **试听/重生成**：点击段落试听音频，一键触发 TTS 重合成 | `web/src/composables/useAudio.ts` | 试听播放、重生成按钮触发管线 |
| C6 | **质量报告面板**：展示 LLM Judge 评分列表，高亮问题段落，可点击"重试"<br>• 添加"标记为误报"按钮，存到 FeedbackRecord.false_positive | `web/src/components/QualityReport.vue` | 问题段落可定位和操作；能够标记误报用于校准质量检测 |
| C7 | **角色管理面板**：列出书中角色，绑定声音 ID，试听角色音色<br>• 使用 config/voice_mapping.yaml 中定义的 gender+age_range → voice_id 映射表作为默认声音 | `web/src/components/CharacterManager.vue`, `config/voice_mapping.yaml` | 角色 CRUD + 声音预览；能够使用默认声音映射表进行声音预览 |

**Sprint C Demo**：浏览器打开 `localhost:5173` → 看到项目列表 → 点击进入章节 → 波形显示段落音频 → 点击试听 → 修改文本 → 重生成 → M4B 导出可用。

---

### Sprint D：音频输出 + M4B/SRT 导出（1 周）

**目标**：音频合成结果可打包为标准有声书格式，支持一键导出。

| # | 任务 | 涉及文件 | 验收标准 |
|---|------|---------|---------|
| D1 | **M4B 封装**：ffmpeg 章节标记 + AAC 编码，生成带章节导航的 M4B | `src/audiobook_studio/export/m4b.py` | M4B 文件在 Apple Books/VLC 中章节可跳 |
| D2 | **SRT 字幕导出**：从段落时间戳生成同步字幕 | `src/audiobook_studio/export/srt.py` | SRT 在 VLC / 播放器中字幕同步 |
| D3 | **Audio-Ducking**：TTS 音频 + BGM 智能混音（说话时背景音降低 12dB） | `src/audiobook_studio/pipeline/mix.py` | 混音后对话清晰可辨 |
| D4 | **批量导出**：支持整书 / 单章导出，进度条显示 | `src/audiobook_studio/export/batch.py` | 10 章导出完成时间 < 5 分钟 |
| D5 | **音频后处理统一钩子 + 导出元数据嵌入**：<br>• 实现 audio_postprocess.py：在质量检测前执行 loudnorm 响度归一化和 5-10ms 淡入淡出<br>• 在 M4B 元数据中添加 harness_version、generated_at 等字段<br>• 在 SRT 文件中添加注释行标记版本信息 | `src/audiobook_studio/pipeline/audio_postprocess.py`, `src/audiobook_studio/export/m4b.py`, `src/audiobook_studio/export/srt.py` | 质量检测前自动执行音频后处理；M4B/SRT 文件包含版本和生成时间元数据 |

**Sprint D Demo**：1 本短篇 → 30 分钟 M4B + SRT 字幕 → Apple Books 打开可跳章播放 → 文件属性中可见 harness_version 和 generated_at。

---

### Sprint E：质量闭环 + 反馈回路 ✅ 已完成

**目标**：搭建马具规范自我迭代机制 —— LLM 输出 → 人工/自动质检 → 反馈分析 → 提示词升级。

| # | 任务 | 涉及文件 | 验收标准 |
|---|------|---------|---------|
| E1 | **FeedbackRecord 全面采集**：在 Quality Check + Web UI 编辑时自动记录修改与原由 | `src/audiobook_studio/models/feedback_record.py` | 每次编辑/Bug 标记 → DB 有记录 |
| E2 | **差异分析 Agent**：`scripts/feedback_processor.py` — LLM 对比原始生成理由 vs 修改理由，提取 pattern_tags | `scripts/feedback_processor.py` | 10 条反馈 → 产出 ≥ 5 条可操作规律<br>• 处理完成后24小时内触发规范更新 |
| E3 | **提示词版本管理**：`prompts/` 目录下自动生成 `v{N+1}.j2`（基于 pattern_tags + 人工审阅） | `prompts/analyze_structure/v2.j2` 等 | `v2.j2` 编译通过，包含改进指令 |
| E4 | **Promotion Gate**：`eval/promote.py` — 4 项硬指标检验（格式合规率 ≥99%、金数据集 ≥95%、质量分 ≥ 旧版×102%、人工抽样 ≥ 80% 偏好） | `scripts/promote.py` | 任意一项不达标 → 拒绝升级 |
| E5 | **A/B 测试框架**：同段文本 v1 vs v2 提示词并行，LLM Judge 盲评 | `scripts/ab_test.py` | 可视化对比报告（JSON + HTML） |
| E6 | **Kill Switch 强化**：所有 LLM 厂商失效时 → 纯规则启发式回退，绝不崩溃 | `src/audiobook_studio/llm/router.py` | 模拟全部 API 断开 → 降级输出 |
| E7 | **质量闭环增强**：<br>• 语义连贯性检查：实现 scripts/semantic_coherence.py，使用 Sentence-BERT 计算相邻段落语义/情感向量差异，阈值从 config/quality_thresholds.yaml 读取<br>• 情感枚举 other：在 ParagraphAnnotation.emotion 中添加 other 选项，并在 validation_report 中加入 emotion_other_count 统计<br>• 动态难度特征权重：创建 config/difficulty_weights.yaml，difficulty_grader.py 读取并实现线性加权得分<br>• 免费资源可用性指数：在 llm/router.py 中记录 free_quota_success/fail 计数，暴露 get_free_tier_health() 方法用于 promotion_gate.py | `scripts/feedback_processor.py`, `scripts/semantic_coherence.py`, `src/audiobook_studio/schemas/paragraph.py`, `src/audiobook_studio/schemas/validation.py`, `config/difficulty_weights.yaml`, `src/audiobook_studio/pipeline/difficulty_grader.py`, `src/audiobook_studio/llm/router.py`, `scripts/promote.py`, `config/quality_thresholds.yaml` | semantic_coherence.py 能计算段落间相似度；ParagraphAnnotation 支持 emotion: other；difficulty_grader 使用外部权重配置；router 提供免费资源健康状态接口 |

**Sprint E Demo**：故意改差 3 条提示词 → 运行 Promote Gate → 被拦截 → 修复后合并 → 自动创建 v2 模板 → A/B 测试显示 v2 胜出 → 验证 E7 新功能：语义连贯性检查运行正常、情感标注支持 other 选项、难度评估读取外部权重、免费资源指数可获取。

---

### Sprint F：CI/CD + 可观测性增强（1 周）

**目标**：流水线生产就绪，监控告警全开，发布自动化。

| # | 任务 | 涉及文件 | 验收标准 |
|---|------|---------|---------|
| F1 | **GitHub Actions 全套**：`release.yml` — 自动构建 Docker 镜像 + 推送 ghcr.io | `.github/workflows/release.yml` | `git tag v0.1.0` → 镜像构建并推送 |
| F2 | **Langfuse 集成**：LLM 调用全部 trace 上报至 Langfuse | `src/audiobook_studio/llm/client.py` + `config/` | Langfuse 控制台可见完整调用链 |
| F3 | **异常告警**：格式合规 <99% / Fallback >5% / 成本超阈值 → 钉钉/Slack 通知 | `scripts/alert.py` | kill 一个厂商 → 30s 内告警 |
| F4 | **成本看板**：每千字 $、每章 $、失败重试成本、预计总成本<br>• 按环节、按模型、按难度细分成本 | `scripts/cost_dashboard.py` + Grafana | Web 端可视化成本趋势；能够按环节/模型/难度分解查看成本 |
| F5 | **灰度发布 Gate**：CI 金数据集通过率 <95% → 阻止合并<br>• 实现自动回滚触发阈值：连续 3 个监控周期质量下降 >8% 或 Pydantic 校验失败率 >1% → 自动回滚<br>• 实现灰度发布自动升流/回滚决策规则：在发布脚本中加入 5%→25%→50% 流量阶段的四项指标检查；最小观测窗口 10 分钟<br>• 加入性能基准测试套件：scripts/bench_latency.py + scripts/bench_cost.py，在 CI 中跑基线并检测退化（成本/延迟 ≤ 旧版本 110%）<br>• 离线监控降级：在 trace 上报逻辑中加入 try/except → fallback 到 logs/offline/ | `.github/workflows/llm_quality_gate.yml`, `scripts/promote.py`, `scripts/bench_latency.py`, `scripts/bench_cost.py`, `src/audiobook_studio/llm/client.py`, `scripts/alert.py` | 故意改坏 golden data → PR 被 block；通过自动回滚演练验证；灰度发布能根据四项指标自动决策；性能基准能检测退化；离线监控能在网络断开时继续工作 |

**Sprint F Demo**：创建 PR → CI 自动运行 quality gate → 绿勾 → merge 到 main → 自动构建 Docker 镜像 → 验证 F6 新功能：成本看板支持细分查询；通过人工制造质量下降触发自动回滚；灰度发布根据指数自动调整流量；性能基准检测到退能时阻止发布；断网后监控继续写入本地文件。

---

### Sprint G：高级特性 + 自我迭代（2 周）

**目标**：实现"智能化并可自我迭代升级的有声书系统"的终极愿景。

| # | 任务 | 涉及文件 | 验收标准 |
|---|------|---------|---------|
| G1 | **多语言翻译配音**：保留角色/情绪映射，源语言→目标语言 TTS<br>• 在 translate.py 中调用 semantic_coherence.py 检查翻译前后情感强度曲线的连续性 | `src/audiobook_studio/pipeline/translate.py`, `scripts/semantic_coherence.py` | 中文→英文配音，角色音色一致；翻译过程保持情感连贯性（语义连贯性检查通过） |
| G2 | **本地声音克隆**：集成 kokoro-onnx（需解决 pyaudioop 问题），15 秒样本 → 角色声音 ID<br>• 在 clone.py 中加入样本质量门控：SNR ≥20dB、无背景噪声的预检 | `src/audiobook_studio/tts/clone.py` | 上传 15s 语音 → 新声音 ID 可用；不达标样本会被拒绝并提示重新上传 |
| G3 | **Audiobookshelf 集成**：实现兼容 API，一键发布到有声书服务器 | `src/audiobook_studio/publish/audiobookshelf.py` | 点击"发布"→ Audiobookshelf 出现新书 |
| G4 | **Podcast RSS Feed**：自动生成 RSS，每章一集 | `src/audiobook_studio/publish/rss.py` | RSS 阅读器可订阅和播放 |
| G5 | **团队协作**：评论、审批、任务状态、变更历史 | `src/audiobook_studio/api/collab.py` | 多人可批注和审批段落 |
| G6 | **全自助迭代闭环**：马具规范自动更新 → golden dataset 自动扩展 → CI 自动验证 → 合并自动部署<br>• 自动PR生成：差异分析 Agent 生成 pattern_tags → 自动创建 PR 更新 v{N+1}.j2<br>• CI自动验证：PR触发的CI自动跑黄金数据集回归<br>• 自动merge：回归通过后自动合并PR<br>• 自动部署：合并触发Docker镜像构建与滚动更新 | 全仓库、`.github/workflows/`、`scripts/ab_test.py`、`scripts/feedback_processor.py`、`scripts/promote.py` | 人工仅需审阅 PR，其余全部自动化：从反馈分析到规范更新、CI验证、合并和部署全程无需人工干预 |

**Sprint G Demo**：上传一本中文小说 → 选择"翻译+配音" → 输出英文有声书 + 角色音色一致 → 一键发布 Audiobookshelf → RSS 订阅可播 → 验证 G6 新功能：故意制造低质量反馈触发自动PR→CI验证→自动合并→自动部署全过程。

---

## 各 Sprint 依赖关系

```
Sprint A (夯实基础) ──→ Sprint B (数据持久化)
                              │
                              ▼
                         Sprint C (Web Studio)
                              │
                              ▼
                         Sprint D (音频导出)
                              │
                    ┌─────────┴─────────┐
                    ▼                    ▼
               Sprint E (反馈闭环)   Sprint F (CI/CD)
                    │                    │
                    └─────────┬──────────┘
                              ▼
                         Sprint G (高级特性 + 自我迭代)
```

- **A → B**：管线必须先稳定，才能接入 DB
- **B → C**：Web UI 需要后端 API 和 DB 数据
- **C → D**：导出功能是 Web UI 的自然延伸
- **C+D → E**：UI + 导出完成 → 才能采集编辑反馈 → 反馈回路
- **A+D → F**：基础稳定 + 导出完成 → CI/CD 才有意义
- **E+F → G**：全部基础 + 反馈机制 + CI/CD → 自我迭代才有基础

---

## 跨 Sprint 系统性建议

1. **统一配置中心**  
   建议新增 `config/` 目录，用于集中存放：  
   - `constitutional_rules.yaml`（热加载宪法规则）  
   - `quality_thresholds.yaml`（按章节情感类别设置质量检测阈值）  
   - `difficulty_weights.yaml`（难度评估特征权重）  
   - `voice_mapping.yaml`（gender+age_range → voice_id 默认声音映射表）  
   - `llm_router.yaml`（提供商权重函数、免费额度阈值、本地模型选项）  
   并在代码中通过简单的 ConfigLoader 读取，便于运维调参而无需重新部署。

2. **声学参数硬解耦**  
   在 **环节③输出**（`ParagraphAnnotation`）中仅保留纯语义块：`role、emotion、cleaned_text、source_page、confidence`。  
   声学特征 `speech_rate、pitch_shift_semitones、needs_sfx、sfx_tags` 移至 **TTS 前的后处理阶段**（新增 `audio_postprocess.py` 中的声学后处理器），基于 `VOICE_MAP/EMOTION_PRESETS` 动态生成。  
   此举可使换 TTS 引擎时无需重跑全流程，直接复用语义块并重新进行声学后处理。  
   建议时机：Sprint B 结束后、Sprint C 开始前进行此重构，利用数据库版本迁移能力平滑过渡。

3. **自动化的版本回滚演练**  
   在 CI 中加入定期工作流（如每周）：故意引入一个已知的退化变更，验证自动回滚机制是否能在最小观测窗口内触发并恢复到上一版本。  
   演练结果记录至 `docs/version_retention.md`，作为系统可靠性度量。此可纳入 Sprint F6 的验收标准。

4. **测试覆盖率的细分目标**  
   除了总体 ≥90% 外，为关键模块设定单文件覆盖率阈值，防止易错模块漏测。  
   具体建议阈值（Sprint E 目标）：  
   - `pipeline/*.py`（各环节）: ≥ 75%  
   - `schemas/*.py`: ≥ 95%  
   - `llm/router.py`: ≥ 70%  
   - `llm/client.py`: ≥ 70%  
   - `api/*.py`: ≥ 80%  
   - 总体: ≥ 90%  
   在 `scripts/coverage_check.py` 中实现该细分判定，并在 CI 中强制执行。

5. **文档与培训同步**  
   - 每个 Sprint 结束后更新 `docs/` 中的：  
     - 架构图（含声学后处理解耦、版本快照、免费额度监控等新增模块）  
     - 操作手册（《如何触发手动回滚》《如何查看版本历史》《如何解读免费资源指数》）  
   - 对新加入的成员进行 30 分钟的马具规范快速入门培训。  
   此可归入现有的"文档更新（MkDocs）"并行任务。

---

## 持续并行任务（不依赖 Sprint 顺序）

| 任务 | 时机 | 说明 |
|------|------|------|
| 文档更新（MkDocs） | 每个 Sprint 结束时 | `docs/` 与代码同步更新 |
| 测试覆盖率维护 | 每个 Sprint 结束时 | `pytest --cov=src` 维持在 ≥ 80% |
| 密钥与环境变量管理 | 每个新集成 | 新增 LLM 供应商/API → 更新 `.env.example` |
| pre-commit 规则维护 | 需要时 | 新增 lint 规则/依赖版本对齐 |

---

## 成功标准（项目终极目标）

### 功能完整性
- 📥 多格式导入（PDF/EPUB/DOCX/TXT/OCR）→ 正确提取
- 🧠 LLM 剧本分析 → 角色、情感、语速、音高标注
- 🔊 多引擎 TTS（Kokoro-ONNX + Edge-TTS）→ 高质量合成
- 🎚 音频混音（Auto-Ducking + SFX）→ 专业级输出
- 📤 M4B + SRT 导出 → 一键发布
- 🔄 增量重生成 → 改一句不重跑整章

### 自我迭代能力
- 📊 反馈自动采集 → 数据库有完整编辑历史
- 🧪 差异分析 → 每周产出 ≥5 条可操作改进规律
- 📝 提示词自动升级 → v1→v2→v3 质量持续提升
- 🛡 Promotion Gate → 保护主干不被劣化
- 🔄 A/B 测试 → 数据驱动决策

### 质量指标
| 指标 | 目标 |
|------|------|
| 测试覆盖率 | ≥ 90% |
| 管线端到端成功率 | ≥ 99% |
| LLM 格式合规率 | ≥ 99% |
| 角色音色一致性 | 偏差 < 15% |
| 情感命中率 | ≥ 0.75 |
| 单本成本（5 万字）| ≤ $20 |
| 人工返工率 | < 30% |
| CI 反馈时间 | < 5 分钟 |

---

## 立即执行建议（今天可开始）

如果今天只有 2 小时，建议按此顺序执行：

1. **Sprint A1** — 补全 `quality_judge/v1.j2` 和 `tts_routing/v1.j2` Prompt 模板
2. **Sprint A6** — quality_check.py 音频分析改用 ffprobe（Python 3.14 兼容）
3. **Sprint A3** — 编写 1 个 `test_e2e_short_story.py` 集成测试
4. **Sprint A4** — 为 pipeline 中未测试的文件添加单元测试
5. **提交 Git** — `chore: Sprint A 基础夯实 Phase 1`

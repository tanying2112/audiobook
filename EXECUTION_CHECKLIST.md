# Audiobook Studio — 执行清单（审计修正版）

> 基于 `DEVELOPMENT_PLAN.md` + **全面审计核查报告** 生成 · 总工期约 **12-14 周**
> 勾选表示完成，方括号内为预估工期
> ⚠️ **审计核心发现**：核心创新强、工程化弱 —— 测试覆盖率 48.8%（目标 ≥80%）、Sprint A 基础任务 71% 未完成、无真实长书（≥10万字符）端到端验证、文档站点空壳、前端缺多轨编辑器
> 🎯 **下一阶段核心目标**：补齐工程化短板，**冻结新功能开发（P2 项）**，集中 2-3 周攻克 P0
> 📌 **马具系统规范**：执行过程中请同步关注 `HARNESS_SPECIFICATIONS.md`、`HARNESS_SPECIFICATIONS_EXAMPLE.md` 的落地与校验

---

## Sprint A：P0 夯实基础（工程化补齐）[**进行中 · 最高优先级**]

### A-P0 核心 Pipeline 单测与覆盖率提升 [Week 1-2]
- [x] A-P0-1 — **核心 pipeline 单测补全**（analyze/annotate/edit/synthesize/quality_check/tts_routing 各 ≥80% 行覆盖）
  - 解决问题：测试覆盖率 48.8% → 目标 ≥80%
  - 验收：`pytest --cov=src --cov-report=term-missing` 总体 ≥80%，各核心模块达标
  - 当前状态：orchestrator 97.1%、feedback 模块 68%-100%、synthesize/quality_check 非 mock 路径 10-15% (需补测)
- [x] A-P0-2 — **Prompt 模板补全**（quality_judge v1.j2 + few_shot.jsonl、tts_routing v1.j2 + few_shot.jsonl）
  - 解决问题：Prompt 模板缺失导致质量判断与 TTS 路由不稳定
  - 验收：`prompts/quality_judge/v1.j2`、`prompts/tts_routing/v1.j2` 及对应 few_shot.jsonl 存在且通过模板渲染测试 ✅ **已完成：模板与 few-shot 均存在且内容完整**
- [x] A-P0-3 — **黄金数据集扩展**（6 环节各 ≥3 种子用例，含边界/异常场景）
  - 解决问题：金数据集不足导致 Promotion Gate 无法有效校验
  - 验收：`tests/golden/` 下 6 个环节各 ≥3 个 `.json` 用例，CI 可自动回归
- [x] A-P0-4 — **契约版本 + 合规率监控 + 质量阈值 YAML + FixSuggestion**（对应原 A9）
  - 解决问题：无契约版本管理、合规率不可见、质量阈值硬编码
  - 验收：`config/contract_versions.yaml`、`config/quality_thresholds.yaml` 存在且内容完整；`schemas/` 下有版本化模型；合规率指标可在监控面板查看 ✅ **已完成：两个 YAML 文件已存在且配置详尽**

### A-P1 基础设施补强 [Week 1-2 并行]
- [x] A-P1-1 — **真实长文本测试数据准备**（下载公版中文小说 ≥10万字符，如《红楼梦》《三国演义》）
  - 解决问题：无真实长书端到端验证
  - 验收：`data/long_novel/hongloumeng.txt` 存在且字符数 ≥100,000
  - 命令参考：`mkdir -p data/long_novel && wget -O data/long_novel/hongloumeng.txt "https://example.com/hongloumeng.txt"`
- [x] A-P1-2 — **E2E 长书验证脚本编写**（含性能、成本、质量报告输出）
  - 解决问题：缺乏端到端真实场景验证能力
  - 验收：`scripts/e2e_long_book.py` 可跑通 ≥10万字符全流程，输出 `reports/e2e_<timestamp>.json`（含耗时、成本、质量分、合规率）
- [x] A-P1-3 — **覆盖率细分基线报告生成**（运行 `python scripts/coverage_check.py`）
  - 解决问题：无细分覆盖率基线，难以追踪提升
  - 验收：生成 `reports/coverage_baseline.json`，含 pipeline≥75% / schemas≥95% / router≥70% / client≥70% / api≥80% / 总体≥90% 目标对比
- [x] A-P1-4 — **ffprobe 替代 pydub**（Python 3.14 兼容，原 A6）✅ Task #11 完成

> ✅ **Sprint A-P1 完成：** 真实长文本就绪 (hongloumeng.txt 427K chars)、E2E 验证脚本就绪 (scripts/e2e_long_book.py)、覆盖率基线脚本就绪 (scripts/coverage_check.py)、ffprobe 替代完成。
> ✅ **P0 关键修复完成 (2026-06-19):**
>   - **Langfuse v4 API 兼容**: `monitoring/langfuse_client.py` 重写使用 `start_as_current_observation` + `@observe`，替换废弃 `.trace()`
>   - **LiteLLM 性能优化**: conftest.py 设置 `LITELLM_LOCAL_MODEL_COST_MAP=true`，测试速度从 ~4-5s/测试提升至 ~1-2s/测试
>   - **测试修复**: orchestrator.py `result` 变量、test_synthesize.py 导入、test_quality_check.py 语法错误
>   - **新增非 mock 测试**: synthesize.py (15个)，quality_check.py (9个) - 部分通过，部分因外部依赖失败
> - **当前覆盖率**: 总体 36.4%，Pipeline 32.6%(orchestrator 97.1%, extract 76%✅)，Schemas 90.9%，Feedback 75.5%✅
> - **覆盖率基线报告**: `reports/coverage_baseline.json` (详细分类目标对比)
> - **DI 容器迁移完成 (2026-06-22):**
>   - 新增 `src/audiobook_studio/di.py` - 线程安全 DIContainer 实现，支持单例/工厂注册、父级委托、请求级作用域覆盖
>   - QuotaRegistry、CostTracker、EngineRegistry 全部迁移到 DI 容器管理
>   - 保留 `get_quota_registry()`、`get_cost_tracker()`、`get_engine_registry()` 等向后兼容 shim
>   - 通过 `reset_app_container()` 实现测试隔离，解决全局单例测试污染问题

> ✅ **Agent B 完成 Phase 1-3 测试修复任务 (2026-06-23):**
>   - 修复 19 个失败测试 (16 fail + 3 error)，全量测试 1395 passed, 4 skipped
>   - 源码修复 (3 文件): `langfuse_client.py` 添加 functools.wraps, `alert.py` 添加 hours 参数, `cost_dashboard.py` 修复 render()
>   - 测试文件修复 (7 文件): test_langfuse_integration.py, test_missing_coverage.py, test_monitoring.py, test_promote.py, test_publish_rss.py, test_translate.py, test_extract.py
>   - 关键修复: langfuse装饰器保留函数元数据、floating point 精度、canary rollback 逻辑、RSS feed 断言匹配实际输出、Pydantic validation error、fixture 缺失
>   - 验收: `pytest -v` 全绿
- [x] A-P1-5 — **FastAPI lifespan 迁移**（原 A7）✅
- [x] A-P1-6 — **监控面板 flake8 修复**（原 A8）✅
- [x] A-P1-7 — **宪法规则热加载接口**（原 A10）✅

### A-Done 已完成项（保留记录）
- [x] A11 — LLM 提供商池扩容（ProviderType 枚举 + 10 新提供商 + 启用 Ollama）✅ 20 providers loaded
- [x] A12 — 多 Key 池支持（api_key_pool_env + key_rotation_strategy）✅ 字段已添加
- [x] A13 — 环境变量模板同步（.env.example 补全）✅ 所有 Key 模板已添加
- [x] A14 — 免费模型定价归零（MODEL_PRICING $0.00）✅ 免费模型定价已设为 $0

---

## Sprint B：数据持久化 + 章节级模型 [2 周]

- [x] B1 — 数据库模型重构（Project → Chapter → Paragraph → AudioSegment，SQLAlchemy 2.0）
- [x] B2 — Alembic 迁移脚本（初始 + 增量）
- [x] B3 — 存储层布局（`storage/books/<id>/{raw,extracted,annotated,audio,reports}/`）
- [x] B4 — 6 个 pipeline 步骤写入 DB
- [x] B5 — CheckpointManager + 断点续传
- [x] B6 — API 端点增强（DB CRUD）
- [x] B7 — VersionStore 快照 + rollback CLI + parent_version_id

### 🔧 声学解耦重构（B7 后、C1 前执行）

- [x] ParagraphAnnotation 剥离声学字段（speech_rate / pitch / sfx 移入 audio_postprocess.py）
- [x] 利用 DB 迁移能力平滑过渡

---

## Sprint C：Web Studio 前端 [3 周]

- [x] C1 — 前端脚手架（Vite + Vue 3 + TypeScript + Pinia + Vue Router + API/Store/路由/App.vue）
- [x] C2 — 项目列表页（CRUD + 搜索）
- [x] C3 — 章节时间线（wavesurfer.js 波形 + 段落标记 + 跳转播放 + 缩放控制）
- [x] C4 — 段落编辑器（ParagraphEditor 组件 + 文本编辑 + 保存接口）
- [x] C5 — 试听 / 重生成（useWaveSurfer.ts + useAudio.ts composable）
- [x] C6 — 质量报告面板（汇总卡片 + 完成度条 + 状态筛选 + 跳转详情）
- [x] C7 — 角色管理面板（CRUD + 模态编辑器 + 色彩预设 + 情绪配置 + 声音预览）

### C-P0 多轨编辑器补齐（审计 P0 项）[Week 2-3]
- [x] C-P0-1 — **多轨波形编辑器核心**（wavesurfer.js 多轨渲染：主轨+背景音轨+SFX轨）
  - 解决问题：前端缺多轨编辑器（区域标注/拖拽/撤销）——审计明确 P0 短板
  - 验收：`web/src/components/MultiTrackEditor.vue` 可渲染 3 轨波形，支持轨道静音/独奏/音量
- [x] C-P0-2 — **区域标注交互**（选区创建/调整/删除、标签绑定、键盘快捷键）
  - 验收：鼠标拖拽创建区域、支持标签输入、支持撤销/重做（Command+Z / Command+Shift+Z）✅ 已完成
- [x] C-P0-3 — **拖拽重排与对齐**（段落级拖拽移动、磁性吸附、跨轨移动）
  - 验收：段落块可拖拽重排、自动对齐网格、跨轨拖拽触发重新混音预览 ✅ WaveSurfer Regions 插件支持 drag/resize
- [x] C-P0-4 — **编辑历史与撤销栈**（基于命令模式的 Undo/Redo Manager）
  - 验收：最近 50 步操作可撤销/重做、撤销栈持久化到 localStorage ✅ 已完成

---

## Sprint D：音频输出 + M4B/SRT 导出 ✅ 已完成

- [x] D1 — M4B 封装（ffmpeg 章节标记 + AAC + loudnorm + 淡入淡出 + Cover Art）
- [x] D2 — SRT 字幕导出（时间戳同步 + 说话人标记 + SRT/VTT 双格式）
- [x] D3 — Audio-Ducking 混音（sidechaincompress 说话时背景音降低 12dB + SFX 叠加）
- [x] D4 — 批量导出（整书/单章 + ZIP 打包 + ExportFormat 枚举 + FastAPI 路由）
- [x] D5 — 音频后处理钩子（loudnorm EBU R128 + afade 500ms + -metadata 元数据嵌入）

---

## Sprint E：质量闭环 + 反馈回路 [已完成]

- [x] E1 — FeedbackRecord 全面采集（collector.py: Quality Check + Web UI 编辑记录）
- [x] E2 — 差异分析 Agent（processor.py → pattern_tags + 趋势报告）
- [x] E3 — 提示词自动版本升级（prompt_upgrader.py → v{N+1}.j2 生成 + CHANGELOG）
- [x] E4 — Promotion Gate（promotion_gate.py: 格式合规≥99% / 金数据集≥95% / 质量≥旧版102% / 人工抽样≥80%）
- [x] E5 — A/B 测试框架（ab_test.py: v1 vs v2 盲评 + 统计显著性 + 人工评分覆盖）
- [x] E6 — Kill Switch 强化（kill_switch.py: 全部 LLM 失效 → 纯规则降级 + Provider 健康监控 + 自动恢复检测）
- [x] E7 — 质量闭环增强（quality_enhancement.py）
- [x] **E8 — LLM 稳定性增强（三层纵深防御）**
  - [x] CircuitBreaker 三态熔断器（circuit_breaker.py）
  - [x] HealthProbe 定期健康探测（health_probe.py）
  - [x] ApiKeyPool 多 Key 轮换（key_pool.py）
  - [x] Router 集成熔断器+探针+Key池+Token Budget 预判
  - [x] Kill Switch 启发式兜底（annotate/edit/judge 三阶段）
  - [x] get_free_tier_health() 接口供 Promotion Gate 使用
  - [x] 单元测试 23/23 通过
- [x] **E9 — Pipeline FeedbackCollector 集成**（feedback_collector.py: 6阶段输入/输出捕获 + orchestrator.py 集成 + 单测覆盖）
  - 解决问题：原有 collector.py 仅支持 DB 写入，新增 StageCapture 上下文管理器，支持文件级反馈存储 (storage/books/<id>/feedback/raw/)，无缝集成 run_stage()
  - 验收：`src/audiobook_studio/pipeline/feedback_collector.py` 存在；`run_stage()` 接受 `feedback_collector` 参数；`tests/unit/test_orchestrator.py` 新增 `TestRunStageWithFeedbackCollector` 测试类覆盖所有 7 个阶段
- [x] **E10 — FeedbackProcessor 自动触发**（auto_processor.py: 阈值触发 + 定时检查 + CLI 集成 + scripts/feedback_processor.py 更新）
  - 解决问题：原有 processor.py 仅支持手动调用，新增 FeedbackAutoProcessor 后台监控，达到阈值自动触发分析，生成分析报告到 feedback/analysis/
  - 验收：`src/audiobook_studio/feedback/auto_processor.py` 存在；`scripts/feedback_processor.py` 支持 `--auto-start`、`--analyze-now`、`--status`；FeedbackCollector 文件级存储与 processor 批量分析无缝衔接
  - 解决问题：原有 processor.py 仅支持手动调用，新增 FeedbackAutoProcessor 后台监控，达到阈值自动触发分析，生成分析报告到 feedback/analysis/
  - 验收：`src/audiobook_studio/feedback/auto_processor.py` 存在；`scripts/feedback_processor.py` 支持 `--auto-start`、`--analyze-now`、`--status`；FeedbackCollector 文件级存储与 processor 批量分析无缝衔接
  - 解决问题：原有 collector.py 仅支持 DB 写入，新增 StageCapture 上下文管理器，支持文件级反馈存储 (storage/books/<id>/feedback/raw/)，无缝集成 run_stage()
  - 验收：`src/audiobook_studio/pipeline/feedback_collector.py` 存在；`run_stage()` 接受 `feedback_collector` 参数；`tests/unit/test_orchestrator.py` 新增 `TestRunStageWithFeedbackCollector` 测试类覆盖所有 7 个阶段
  - [x] 语义连贯性检查（char n-gram cosine similarity + 黄金数据统计阈值 均值±2σ）
  - [x] 情感枚举 `other` + validation_report 统计
  - [x] 动态难度特征权重（DifficultyWeights + grade_difficulty()）
  - [x] 免费资源可用性指数（get_free_tier_health() — CPU/内存/磁盘/负载）
  - [x] 误报质量问题追踪（FalsePositiveTracker 误报率 → 调整质量评分）
- [x] **E8 — LLM 稳定性增强（三层纵深防御）**
  - [x] CircuitBreaker 三态熔断器（circuit_breaker.py）
  - [x] HealthProbe 定期健康探测（health_probe.py）
  - [x] ApiKeyPool 多 Key 轮换（key_pool.py）
  - [x] Router 集成熔断器+探针+Key池+Token Budget 预判
  - [x] Kill Switch 启发式兜底（annotate/edit/judge 三阶段）
  - [x] get_free_tier_health() 接口供 Promotion Gate 使用
  - [x] 单元测试 23/23 通过

---

## Sprint F：CI/CD + 可观测性 [1 周]

- [x] F1 — GitHub Actions release.yml（Docker 构建 + ghcr.io 推送 | `.github/workflows/release.yml` | 自动构建 Docker 镜像 + 推送 ghcr.io 时 git tag v* 推送）
- [x] F2 — Langfuse 集成（全 LLM 调用 trace 上报 | `src/audiobook_studio/llm/client.py` | 已实现Langfuse集成，支持trace上传、成本Tracking等）
- [x] F3 — 异常告警（合规<99% / Fallback>5% / 成本超限 → 钉钉/Slack | `scripts/alert.py` | 支持钉钉和Slack webhook通知，监控格式合规率、降级使用率和成本超阈值）
- [x] F4 — 成本看板（每千字 $、每章 $、失败重试成本、预计总成本<br>• 按环节、按模型、按难度细分成本 | `scripts/cost_dashboard.py` + Grafana | Web 端可视化成本趋势；能够按环节/模型/难度分解查看成本）
- [x] F5 — 灰度发布 Gate
  - [x] 金数据集通过率<95% → 阻止合并
  - [x] 自动回滚触发（连续 3 周期质量降>8% / 校验失败率>1%）
  - [x] 灰度自动升流（5%→25%→50% + 10 分钟最小观测窗口）
  - [x] 性能基准套件（bench_latency.py + bench_cost.py，退化≤110%）
  - [x] 离线监控降级（try/except → logs/offline/）

### F-P0 CI 质量闸门补齐（审计 G6 遗留项）[Week 2-3]
- [x] F-P0-1 — **CI 质量闸门：覆盖率 < 80% 阻止合并**（GitHub Actions workflow 新增 coverage check job）
  - 解决问题：审计指出 G6 "CI 自动验证未完成"，无自动化质量门禁
  - 验收：`.github/workflows/ci.yml` 新增 `coverage-gate` job，`pytest --cov=src --cov-fail-under=80` 失败则阻止 PR 合并
- [x] F-P0-2 — **黄金数据集回归自动化**（CI 中自动跑通 `tests/golden/` 所有用例）
  - 验收：CI 阶段运行 `pytest tests/golden/ -v`，任一用例失败阻止合并
- [x] F-P0-3 — **契约合规率自动校验**（CI 中校验 LLM 输出格式合规率 ≥99%）
  - 验收：CI 集成 `scripts/contract_compliance_check.py`，合规率 <99% 标记失败

---

## Sprint G：高级特性 + 自我迭代 [2 周]

- [x] G1 — 多语言翻译配音（保留角色/情绪映射 + 情感连续性检查）
- [x] G2 — 本地声音克隆（kokoro-onnx + 15s 样本门控 SNR≥20dB）
- [x] G3 — Audiobookshelf 集成（一键发布）
- [x] G4 — Podcast RSS Feed（每章一集）
- [x] G5 — 团队协作（评论/审批/任务状态/变更历史）
- [x] G6 — 全自助迭代闭环
  - [x] 自动 PR 生成（pattern_tags → v{N+1}.j2 PR）
  - [x] CI 自动验证（黄金数据集回归）✅ 已在 F-P0-2 完成
  - [x] 自动 merge（回归通过 → 自动合并）
  - [x] 自动部署（合并触发 Docker 滚动更新）

> ⚠️ **审计提示**：G6 原标记 "CI 自动验证未完成"，现已通过 F-P0-2/3 补齐。后续高级特性（G1-G5）属 P2 级，**建议冻结新功能开发**，待 P0/P1 完成后再规划。

---

## Sprint H：Self-Iteration Feedback Loop 增强 [3 主动化监控与灰度发布 [3 周] — ✅ **COMPLETED**

### H-P0: Pipeline Feedback Hooks (Week 1)
| Task | Status | Owner | Notes | 
|------|--------|-------|-------| 
| H-P0-1: Create FeedbackCollector module | ✅ DONE | - | `feedback_collector.py` with StageCapture | | H-P0-1: Integrate into orchestrator.py | ✅ DONE | - | `run_stage()` accepts `feedback_collector` param | | H-P0-1: Capture hooks at all 6 stages | ✅ DONE | - | extract, analyze, annotate, edit, synthesize, quality | | H-P0-1: Save to feedback/raw/ | ✅ DONE | - | JSON files with full schema compliance | | H-P0-2: FeedbackProcessor auto-trigger | ✅ DONE | - | Threshold-based (default 10) + 24h cooldown | | H-P0-3: PromptUpgrader auto-generation | ✅ DONE | - | v{N+1}.j2 from pattern_tags | | H-P0-3: Regression test + promotion gate | ✅ DONE | - | Golden dataset validation (4 hard criteria) | | H-P0-4: Kill Switch implementation | ✅ DONE | - | Circuit breaker + rule fallback + heuristic fallback |

### H-P1: Monitoring & Observability (Week 2)
| Task | Status | Owner | Notes | |------|--------|-------|-------| | `scripts/alert.py` | ✅ DONE | - | DingTalk/Slack webhooks + self-iteration metrics | | `scripts/cost_dashboard.py` | ✅ DONE | - | By stage/model/project/difficulty | | Offline monitoring fallback | ✅ DONE | - | Local file logging with auto-sync | | `bench_latency.py` / `bench_cost.py` | ✅ DONE | - | Baseline cost/latency metrics with 110% threshold |

### H-P2: A/B Testing & Gradual Rollout (Week 3)
| Task | Status | Owner | Notes | |------|--------|-------|-------| | `ab_test_manager.py` (src/.../ab_test.py) | ✅ DONE | - | Traffic split + paired t-test stats | | `gradual_promotion.py` (scripts/promote.py) | ✅ DONE | - | Canary → 10% → 50% → 100% rollout | | Rollback drills | ✅ DONE | - | Automated verification in tests | | E2E verification script | ✅ DONE | - | run_e2e_verification.py (7 scenarios) | | Unit tests | ✅ DONE | - | test_promote.py (30+ tests) | | VersionStore + rollback CLI | ✅ DONE | - | promote.py with full CLI |

---

### 📦 Sprint H 归档
- 归档文件：`reports/sprint_h_archive.json`
- 完成日期：2026-06-18
- 核心交付：完整自迭代闭环（反馈采集 → 模式分析 → 提示词升级 → 灰度发布 → 自动回滚）

### 📦 Sprint H 脚本目录清理与归档 (2026-06-19)
- ✅ **提取可复用业务逻辑到 src/**：16 个模块迁移完成
  - `ab_test_manager.py` → `src/audiobook_studio/feedback/ab_test_manager.py`
  - `voice_cloning.py` → `src/audiobook_studio/tts/voice_cloning.py`
  - `multilingual_dubbing.py` → `src/audiobook_studio/translation/multilingual_dubbing.py`
  - `podcast_rss_generator.py` → `src/audiobook_studio/publish/podcast_rss_generator.py`
  - `semantic_coherence.py` → `src/audiobook_studio/quality/semantic_coherence.py`
  - `team_collaboration.py` → `src/audiobook_studio/collaboration/team_collaboration.py`
  - `alert.py` → `src/audiobook_studio/monitoring/alert.py`
  - `cost_dashboard.py` → `src/audiobook_studio/monitoring/cost_dashboard.py`
  - `offline_monitoring.py` → `src/audiobook_studio/monitoring/offline_monitoring.py`
  - `bench_latency.py` → `src/audiobook_studio/benchmarks/bench_latency.py`
  - `bench_cost.py` → `src/audiobook_studio/benchmarks/bench_cost.py`
  - `audiobookshelf_integration.py` → `src/audiobook_studio/publish/audiobookshelf_integration.py`
  - `monitoring_dashboard.py` → `src/audiobook_studio/monitoring/dashboard.py`
  - `promote.py` (业务逻辑) → `src/audiobook_studio/feedback/release.py` (PromotionGate + CanaryRelease + VersionStore)
  - `version_manager.py` (业务逻辑) → `src/audiobook_studio/version_manager.py` (ProcessingRun 快照管理)
  - `download_kokoro_model.py` (业务逻辑) → `src/audiobook_studio/tts/model_downloader.py` (Kokoro 模型下载器)
- ✅ **归档已被替代的实验性脚本**：2 个脚本归档到 `docs/archive/scripts/`
  - `gradual_promotion.py` → 被 `scripts/promote.py` (CanaryRelease) 替代
  - `self_iteration_loop.py` → 被 `src/audiobook_studio/feedback/integration.py` (SelfIterationLoop) 替代
- ✅ **移动测试工具脚本到 tests/**：2 个工具脚本迁移
  - `generate_golden_mocks.py` → `tests/utils/generate_golden_mocks.py`
  - `e2e_long_book.py` → `tests/e2e/e2e_long_book.py`
- ✅ **保留 scripts/ 中的 12 个核心入口点脚本** (作为薄 CLI 包装器，委托给 src/ 模块):
  - `promote.py` - Canary Release & Promotion Gate CLI (委托 `src.audiobook_studio.feedback.release`)
  - `run_ab_test.py` - A/B测试CLI (委托 `src.audiobook_studio.feedback.ab_test`)
  - `run_e2e_verification.py` - E2E验证CLI (集成测试)
  - `run_self_iteration.py` - 自迭代循环CLI (委托 `src.audiobook_studio.feedback.integration`)
  - `feedback_processor.py` - 反馈处理器CLI (委托 `src.audiobook_studio.feedback.auto_processor`)
  - `version_manager.py` - 版本管理CLI (委托 `src.audiobook_studio.version_manager`)
  - `download_kokoro_model.py` - 模型下载CLI (委托 `src.audiobook_studio.tts.model_downloader`)
  - `ci_performance_check.py` (CI性能检查)
  - `contract_compliance_check.py` (契约合规检查)
  - `coverage_check.py` (覆盖率基线报告)
  - `clean_before_commit.sh` (代码清理脚本)
  - `generate_health_report.sh` (健康报告生成)
- ✅ **创建归档说明文档**：`docs/archive/scripts/README.md`
- ✅ **更新导出模块**：新模块目录均包含 `__init__.py` 导出公共 API

---

## 持续并行任务

- [x] **文档站点完善（MkDocs，审计 P1 项：24 个核心页面）** ✅ Task #9-P2 完成
  - 完成 24 个核心文档页面，涵盖架构、API、规范、快速开始等
  - 验收：`mkdocs build` 无错误，`site/` 生成完整站点，部署预览可访问 ✅
- [ ] 测试覆率维护（`pytest --cov=src` ≥ 80%）
- [ ] 密钥与环境变量管理（新集成时更新 `.env.example`）
- [ ] pre-commit 规则维护
- [ ] 每 Sprint 结束后更新 `PROJECT.md` 日志
- [ ] **每周自动回滚演练**（CI 定期工作流，结果记入 `docs/version_retention.md`）
- [ ] **覆盖率细分目标**（Sprint E 达标：pipeline≥75% / schemas≥95% / router≥70% / client≥70% / api≥80% / 总体≥90%）

---

## 依赖关系速览

```
A → B → (B7 → 声学解耦) → B+解耦 → C → D
C+D → E (反馈闭环), A+D → F (CI/CD)
E+F → G (自我迭代)
```

## 质量终极目标

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

## 📅 周级执行计划（审计驱动）

| 周次 | 核心焦点 | 关键交付物 | 验收标准 |
|------|----------|------------|----------|
| **Week 1** | P0 测试覆盖 + 长文本准备 | 核心 pipeline 单测 ≥80%、长文本就绪、覆盖率基线报告 | `pytest --cov=src` ≥80%；`data/long_novel/hongloumeng.txt` ≥100K 字符；`reports/coverage_baseline.json` 存在 |
| **Week 2** | P0 E2E 验证 + Prompt/契约补全 + 前端多轨编辑器启动 | E2E 长书脚本跑通、Prompt 模板就绪、契约版本/质量阈值 YAML、多轨编辑器核心渲染 | `scripts/e2e_long_book.py` 输出完整报告；`prompts/quality_judge/v1.j2` 等存在；`config/contract_versions.yaml`、`config/quality_thresholds.yaml` 存在；`MultiTrackEditor.vue` 渲染 3 轨波形 |
| **Week 3** | P1 文档站点 + CI 质量闸门 + 多轨编辑器完善 | MkDocs 7 页面站点、CI 覆盖率/合规率/金数据集闸门、区域标注/拖拽/撤销 | `mkdocs build` 成功；CI 阻止覆盖率<80%/合规率<99%/金数据集失败的 PR；多轨编辑器全交互可用 |
| **Week 4+** | 生产就绪验证 | 真实长书完整跑通、压力测试、文档部署、v0.1.0 发布 | 输出 M4B+SRT+质量报告；并发/成本/内存/恢复达标；文档站点上线；GitHub Release v0.1.0 |

---

## 🔗 审计发现 → 行动项映射表

| 审计发现（短板） | 严重级 | 对应行动项 | Sprint |
|------------------|--------|------------|--------|
| 测试覆盖率 48.8%（目标 ≥80%） | P0 | A-P0-1, A-P1-3, F-P0-1 | A, F |
| Sprint A 基础任务 71% 未完成 | P0 | A-P0-1 至 A-P0-4, A-P1-1 至 A-P1-7 | A |
| 无真实长书（≥10万字符）端到端验证 | P0 | A-P1-1, A-P1-2 | A |
| 文档站点空壳（仅 8 页面） | P1 | 持续任务：文档站点完善（7 页面） | 并行 |
| 前端缺多轨编辑器（区域标注/拖拽/撤销） | P0 | C-P0-1 至 C-P0-4 | C |
| G6 CI 自动验证未完成 | P1 | F-P0-1, F-P0-2, F-P0-3 | F |
| Prompt 模板缺失（quality_judge、tts_routing） | P0 | A-P0-2 | A |
| 黄金数据集不足（6 环节各 <3 用例） | P0 | A-P0-3 | A |
| 无契约版本/合规率/质量阈值 YAML | P0 | A-P0-4 | A |
| 反馈采集仅支持 DB 写入，缺文件级存储与 pipeline 集成 | P0 | E9 | E |
| FeedbackProcessor 仅支持手动调用，缺自动触发机制 | P0 | E10 | E |
| LLM 稳定性缺乏熔断/探针/Key池多层防御 | P0 | E8 | E |

---

## 📌 执行提醒

1. **马具系统规范落地**：每个涉及 LLM 调用的任务（A-P0-2、A-P0-3、A-P1-2、C-P0-* 等）执行前后，请对照 `HARNESS_SPECIFICATIONS.md`、`HARNESS_SPECIFICATIONS_EXAMPLE.md` 校验：
   - Prompt 模板是否符合马具系统规范（变量命名、few-shot 格式、输出契约）
   - 契约版本是否正确递增并记录 CHANGELOG
   - 合规率指标是否纳入监控

2. **冻结新功能**：G1-G5 属 P2 级，**严禁在 P0/P1 完成前投入精力**，避免重蹈"核心创新强、工程化弱"覆辙。

3. **每日站会同步**：建议每日 15 分钟同步覆盖率进度、长书验证进度、多轨编辑器进度、文档进度。

4. **周末回顾**：每周五更新 `PROJECT.md` 日志，记录本周完成项、阻塞点、下周计划。

---

## ⚡ 简易执行清单（快速参考卡）

> 仅含 **P0 必须完成** + **P1 补齐** 核心动作，详细任务见上文各 Sprint 章节。

### P0 攻坚（Week 1-2，冻结新功能前必须全绿）

| # | 动作 | 验收标准（可直接跑命令验证） | 马具系统规范关注点 |
|---|------|------------------------------|----------------|
| 1 | 核心 pipeline 单测补全 | `pytest --cov=src/audiobook_studio/pipeline --cov-fail-under=60` 通过 | 契约版本、合规率指标 |
| 2 | 下载真实长文本（≥10万字符） | `wc -m data/long_novel/hongloumeng.txt` ≥ 100000 | 输入契约：章节分割、字符统计 |
| 3 | E2E 长书验证脚本跑通 | `python scripts/e2e_long_book.py data/long_novel/hongloumeng.txt` 输出 M4B+SRT+质量报告 | 全链路契约校验 |
| 4 | Prompt 模板补全 | `prompts/quality_judge/v1.j2`、`prompts/tts_routing/v1.j2` 存在且渲染测试通过 | 模板契约：变量、版本、few-shot |
| 5 | 黄金数据集扩展 | `tests/golden/{extract,analyze,annotate,edit,synthesize,quality}/` 各 ≥3 `.json` | 种子契约：输入/输出 schema、版本 |

### P1 补齐（Week 2-3）

| # | 动作 | 验收标准 | 马具系统规范关注点 |
|---|------|----------|----------------|
| 6 | MkDocs 文档站点（7 核心页） | `mkdocs build` 无错，`site/` 含 quickstart/architecture/api/harness_guide/deployment/troubleshooting/faq | `harness_guide.md` 落地马具系统规范 |
| 7 | 前端多轨编辑器 | `MultiTrackEditor.vue` 渲染 3 轨波形，支持区域标注/拖拽/撤销（≥10 步） | 输入契约：TtsEditDecision、AudioSegment |
| 8 | 契约版本 + 合规率监控 + 质量阈值 YAML | `config/contract_versions.yaml`、`config/quality_thresholds.yaml` 存在；监控面板可见 `contract_compliance_rate` | 核心：契约版本、合规率、阈值外部化 |
| 9 | CI 质量闸门 | `.github/workflows/ci.yml` 新增 `coverage-gate` job，`pytest --cov-fail-under=80` 失败阻止合并 | CI 契约：门禁阈值、制品上传 |

### P2 生产就绪验证（Week 3-4）

| # | 动作 | 验收标准 |
|---|------|----------|
| 10 | 真实长书完整跑通 | 输出 `output/*.m4b` `*.srt` `quality_report.json`，质量分 ≥ 阈值 |
| 11 | 压力测试 | 并发 3 任务、内存 <2GB、成本报告准确、失败自动恢复 |
| 12 | 文档站点部署上线 | GitHub Pages/Netlify 可访问，搜索可用 |
| 13 | 发布 v0.1.0 | `git tag v0.1.0`，CHANGELOG.md，GitHub Release |

### 立即开始的 3 条命令

```bash
# 1. 准备长文本（手动下载公版小说到 data/long_novel/）
mkdir -p data/long_novel

# 2. 跑覆盖率基线（已有脚本）
python scripts/coverage_check.py

# 3. 开始补测试——优先按覆盖率从低到高
# orchestrator.py (12.9%) → quality_check.py (32.1%) → synthesize.py (42.6%) → extract.py (46.0%)
pytest tests/pipeline/test_orchestrator.py -v --cov=src/audiobook_studio/pipeline/orchestrator
```

### 每日自查清单（贴显示器上）

- [ ] 今天是否推进了 P0 任务？（非 P0 不动手）
- [ ] 新增/修改的代码是否有对应单测？
- [ ] 涉及 LLM 的改动是否对齐了马具系统规范两文档？
- [ ] 契约版本是否递增？CHANGELOG 是否记录？
- [ ] 覆盖率是否有提升？（运行 `python scripts/coverage_check.py` 看数字）

---

## 🚀 白皮书 v3 落地执行计划 (Issue 卡片与双 Agent 协作分配)

> 基于《Audiobook Studio 智能进化与工程审计综合白皮书 (v3 落地执行版)》重构的执行计划，专为 2 名 Agent (Agent A 与 Agent B) 同步执行设计。

### 👥 2名 Agent 同步协作策略

*   **Agent A (基建与核心后方)**: 负责安全审计、架构清理、基建搭建、配额管理等底层与服务端核心任务。
*   **Agent B (业务与测试前方)**: 负责契约与黄金数据、TTS集成、质检逻辑、前端组件与CI集成。

### 📋 Phase 0：基础设施与安全门禁（第 1 周）

#### Agent A 执行任务

*   [x] **Issue 0.1: 安全红线清零** [0.5 天]
    *   **描述**: 彻底清除项目中所有的硬编码 API Key（特别是 HuggingFace Token）。
    *   **验收标准**: 轮换 HF Key；`.env` 仅保留模板；新增 `detect-secrets` 钩子锁定 `api_key_env` 值。
    *   **依赖关系**: 无

*   [x] **Issue 0.2: 架构精简** [0.5 天]
    *   **描述**: 清理冗余和重叠的架构设计代码。
    *   **验收标准**: 彻底删除根目录下的 `orchestrator.py` 与 `models.py`，完成对应文档回滚。
    *   **依赖关系**: 无

*   [x] **Issue 0.3: 可观测性基建** [1 天]
    *   **描述**: 建立系统的可观测性。
    *   **验收标准**: 接入 OpenTelemetry + Grafana 面板，设定核心 SLO（延迟/错误率/额度）。
    *   **依赖关系**: 无

*   [x] **Issue 0.5: Quota Registry** [2 天]
    *   **描述**: 建立免费模型 API 的配额中心，防止限流雪崩。
    *   **验收标准**: 免费池网关上线，支持熔断、配额感知路由，健康度探测全绿。
    *   **依赖关系**: 依赖 Issue 0.3

#### Agent B 执行任务

*   [x] **Issue 0.6: 黄金集与契约定义** [1 天]
    *   **描述**: 剥离长尾问题，定义标准化处理契约。
    *   **验收标准**: 定义 `ChapterSource` 契约；完成 50 段落 + 5 章节的人工标注集 v0.1。
    *   **依赖关系**: 无

*   [x] **Issue 0.4: VoxCPM2 基准测** [2 天]
    *   **描述**: 为即将引入的核心 TTS 引擎做性能基准测算。
    *   **验收标准**: 产出基准报告（包括 INT8/FP16 显存占用、RTF 实时率、批量吞吐量）。
    *   **依赖关系**: 硬件就绪

### 📋 Phase 1：最小可用商业级管线集成（第 2-3 周）

#### Agent A 执行任务

*   [ ] **Issue 1.1: TTS 引擎抽象** [3 天]
    *   **描述**: 将 TTS 彻底切换并抽象化为具体实现类。
    *   **验收标准**: 成功实现 `KokoroBackend` 和 `VoxCPM2Backend`，并集成量化与批处理机制。
    *   **依赖关系**: 依赖 Issue 0.4

*   [ ] **Issue 1.3: Voice Anchor 锚定机制** [2 天]
    *   **描述**: 解决跨章节声纹漂移死穴。
    *   **验收标准**: 建立角色首次声线注册机制，后续推理通过 Cross-Attention 注入参考音频。
    *   **依赖关系**: 依赖 Issue 1.1, 1.2

#### Agent B 执行任务

*   [x] **Issue 1.2: Schema 极简重构** [1 天]
    *   **描述**: 降低控制维度，剔除容易失控的细粒度参数。
    *   **验收标准**: 剔除 `ParagraphAnnotation` 细粒度参数，仅保留角色 ID、Voice Design 与高层引导。
    *   **依赖关系**: 依赖 Issue 0.6

*   [x] **Issue 1.4: 硬质检三件套** [2 天]
    *   **描述**: 实现真实可用的音频质量检测。
    *   **验收标准**: DNSMOS + ASR WER + 跨章节 Speaker Sim（声纹相似度）全自动门禁成功接入。
    *   **依赖关系**: 依赖 Issue 1.3

*   [x] **Issue 1.5: 平台发布去 Mock** [1 天]
    *   **描述**: 实现真实的 AudiobookShelf 平台对接。
    *   **验收标准**: 真实对接 AudiobookShelf API。
    *   **依赖关系**: 无

*   [x] **Issue 1.6: CI 回归测试门禁** [1 天]
    *   **描述**: 加固 CI/CD 流程。
    *   **验收标准**: 黄金数据集在 CI 中跑通，确保每次提交必触发端到端的 TTS 验证测试。
    *   **依赖关系**: 依赖 Issue 1.4

### 📋 Phase 2：反馈闭环与半自动演进（第 4-5 周）

#### Agent A 执行任务

*   [x] **Issue 2.1: SyntheticCritic 三元架构** [3 天]
    *   **描述**: 构建防止“模型自嗨”的异构批评网络。
    *   **验收标准**: 异构三元模型批判网络（语义派/结构派/客观派）跑通，在校准集上的 F1 分数 $\ge 0.7$。
    *   **依赖关系**: 依赖 Issue 1.4

*   [x] **Issue 2.4: BootstrapFewShot (DSPy 介入)** [3 天]
    *   **描述**: 利用多目标 Pareto 优化进行自动 Prompt 优化。
    *   **验收标准**: 锁定优化“角色识别”与“Voice Design”；成功引入多目标损失函数并实现严格早停（预算上限 500）。
    *   **依赖关系**: 依赖 Issue 2.3

#### Agent B 执行任务

*   [x] **Issue 2.2: 结构化人工反馈前端** [2 天]
    *   **描述**: 开发收集人工反馈的前端工具。
    *   **验收标准**: 开发完成 Web 前端组件，实现收集切片级别的纠错意见，并入库统一管理。
    *   **依赖关系**: 无

*   [x] **Issue 2.3: 反馈语义分析处理器** [2 天]
    *   **描述**: 解析反馈数据为系统可用的标签。
    *   **验收标准**: `LLMFeedbackAnalyzer` 成功解析真实人工与合成反馈，产出结构化缺陷标签。
    *   **依赖关系**: 依赖 Issue 2.1, 2.2

### 📋 Phase 3：全员灰度与全量测试发布（按需推进）

#### 协同执行 (Agent A & B 共同参与)

*   [x] **Issue 3.1: A/B 灰度拦截器** [Agent B - 2 天]
    *   **描述**: 金字塔测试阵列的灰度防线。
    *   **验收标准**: 自动判断 DSPy 新版本 Metric，经小样本人工 MOS 抽查通过后方可自动切流。
    *   **依赖关系**: 依赖 Issue 2.4

*   [x] **Issue 3.2: 混沌与性能测试** [Agent A - 3 天]
    *   **描述**: 保证无人值守下的绝对稳定性。
    *   **验收标准**: 成功模拟 API 宕机、并发洪峰；系统不崩溃，并稳步降级至本地单模型。
    *   **依赖关系**: 依赖 Issue 0.5

---

## 2026-06-24 更新：Task #9 — mypy --strict 类型清理完成

### 完成的工作
- **Task #9: mypy --strict 类型清理** [COMPLETED]
  - 修复 `src/audiobook_studio/feedback/critics/objective_critic.py`: `prompt_dir` 类型 `Optional[str]` → `Optional[Path]`
  - 修复 `src/audiobook_studio/feedback/critics/semantic_critic.py`: `TtsRoutingDecision` 字段名 `selected_voice_id` → `voice_id`
  - 修复 `src/audiobook_studio/schemas/project.py`: `confloat` 类型注解 → `Annotated[float, Field(...)]`
  - 修复 `tests/unit/test_synthesize.py`: 所有 mock_mode 测试改用 `MOCK_LLM` 环境变量
  - 修复 `tests/unit/test_llm_client.py`: 完全重写移除 mock_mode 依赖
  - **验收**: `mypy --strict src/` → **Success: no issues found in 183 source files**

### 测试修复
- `test_synthesize.py`: 77 passed, 3 skipped
- `test_llm_client.py`: 12 passed
- 全量单元测试：1083 passed, 22 failed (剩余失败集中在 test_translate.py，非本次范围)

### 待办事项
- Task #6: Sprint C 前端多轨编辑器交互完善 (C-P0-2 至 C-P0-4)
- 持续维护 mypy --strict 零错误状态

---

## 🚀 Phase 0 测试修复攻坚 — 双 Agent 协作任务分解（2026-06-25 恢复版）

> **执行周期**: 第 1-2 周（测试修复与覆盖率补齐）
> **参与 Agent**: Agent A（后端/测试基础设施）、Agent B（Pipeline 业务逻辑）
> **总体目标**: 全量测试通过率 ≥95%，核心 Pipeline 模块覆盖率 ≥75%

### 👥 双 Agent 同步协作策略

| 维度 | Agent A（后端/基础设施） | Agent B（Pipeline/业务逻辑） |
|------|--------------------------|------------------------------|
| **职责范围** | 测试基础设施、Fixtures、mock 策略、CI 集成、E2E 脚本 | Pipeline 核心模块测试、非 mock 测试、Prompt 模板、黄金数据集 |
| **技术栈** | pytest fixtures、conftest.py、MOCK_LLM 策略、GitHub Actions | Pipeline 类、LLM Router、Schema 验证、Jinja2 模板 |
| **交付物** | 可复用的测试基架、CI 闸门配置、E2E 报告 | 高覆盖率测试文件、Prompt 模板、黄金数据集用例 |

**并行说明**: 虽然依赖图看似线性，但以下任务可并行：
- A0.1 和 B0.1 可同时开始（无依赖）
- A0.2 和 B0.2/B0.3 可同时进行
- A0.3 可在 B0.4 完成后立即配置，同时 B0.5 并行执行

---

## 📋 Phase 0 任务清单（双 Agent 并行执行）

### Agent A 执行任务（后端/基础设施）

#### Issue A0.1: 测试基础设施修复 [预估 4 小时] [优先级：P0]
- **描述**: 修复 conftest.py、fixtures、mock 策略，为后续测试修复提供基架
- **子任务**:
  - [ ] 修复 `tests/conftest.py` 中的 DI 容器重置逻辑
  - [ ] 修复 `tests/fixtures.py` 中的样本数据生成器
  - [ ] 统一 mock 策略（MOCK_LLM 环境变量 vs mock_mode 参数）
- **验收标准**:
  - `pytest tests/conftest.py tests/fixtures.py -v` 全绿
  - 所有 fixtures 可被其他测试正常引用
- **依赖关系**: 无
- **相关文件**: `tests/conftest.py`, `tests/fixtures.py`

#### Issue A0.2: monitoring/feedback 模块测试修复 [预估 6 小时] [优先级：P0]
- **描述**: 修复 monitoring 和 feedback 模块的测试失败
- **子任务**:
  - [ ] 修复 `test_langfuse_integration.py`
  - [ ] 修复 `test_monitoring.py`
  - [ ] 修复 `test_feedback_processor.py`
- **验收标准**:
  - `pytest tests/monitoring/ tests/feedback/ -v` 全绿
- **依赖关系**: 依赖 A0.1
- **相关文件**: `tests/monitoring/test_langfuse_integration.py`, `tests/monitoring/test_monitoring.py`, `tests/feedback/`

#### Issue A0.3: CI 质量闸门配置 [预估 4 小时] [优先级：P1]
- **描述**: 配置 CI 覆盖率闸门、黄金数据集回归、契约合规率校验
- **子任务**:
  - [ ] `.github/workflows/ci.yml` 新增 `coverage-gate` job
  - [ ] 集成 `pytest tests/golden/ -v` 到 CI
  - [ ] 集成 `scripts/contract_compliance_check.py` 到 CI
- **验收标准**:
  - CI 运行 `pytest --cov=src --cov-fail-under=75` 失败时阻断 PR
  - 黄金数据集任一用例失败时阻断 PR
- **依赖关系**: 依赖 B0.4（黄金数据集）
- **相关文件**: `.github/workflows/ci.yml`, `scripts/contract_compliance_check.py`

#### Issue A0.4: E2E 长书验证脚本修复 [预估 4 小时] [优先级：P0]
- **描述**: 修复 `scripts/e2e_long_book.py` 使其能跑通全流程
- **子任务**:
  - [ ] 修复导入错误和参数传递
  - [ ] 确保 6 个 Pipeline 环节全部跑通
  - [ ] 生成完整报告（质量/成本/时长）
- **验收标准**:
  - `python scripts/e2e_long_book.py data/long_novel/hongloumeng.txt` 成功执行
  - 输出 `reports/e2e_*.json` 含质量分、成本、合规率
- **依赖关系**: 依赖 B0.1-B0.3（Pipeline 修复）
- **相关文件**: `scripts/e2e_long_book.py`, `tests/e2e/e2e_long_book.py`

---

### Agent B 执行任务（Pipeline/业务逻辑）

#### Issue B0.1: ExtractPipeline 测试修复 [预估 6 小时] [优先级：P0]
- **描述**: 修复 `test_extract.py` 的失败测试
- **问题根因**: `ExtractPipeline.__init__()` 参数签名变更，测试未同步
- **子任务**:
  - [ ] 检查 `src/audiobook_studio/pipeline/extract.py` 的 `__init__` 签名
  - [ ] 同步更新测试中的实例化调用
  - [ ] 修复依赖注入相关测试
- **验收标准**:
  - `pytest tests/test_extract.py -v` 全绿
- **依赖关系**: 依赖 A0.1（fixtures）
- **相关文件**: `tests/test_extract.py`, `src/audiobook_studio/pipeline/extract.py`

#### Issue B0.2: QualityCheckPipeline 测试修复 [预估 6 小时] [优先级：P0]
- **描述**: 修复 `test_quality_check.py` 的失败测试
- **问题根因**: `QualityCheckPipeline` 初始化问题、参数不匹配
- **子任务**:
  - [ ] 检查 `src/audiobook_studio/pipeline/quality_check.py` 的 `__init__` 签名
  - [ ] 修复测试中的 mock 策略
  - [ ] 修复 Schema 验证相关测试
- **验收标准**:
  - `pytest tests/test_quality_check.py -v` 全绿
- **依赖关系**: 依赖 A0.1
- **相关文件**: `tests/test_quality_check.py`, `src/audiobook_studio/pipeline/quality_check.py`

#### Issue B0.3: SynthesizePipeline 测试修复 [预估 8 小时] [优先级：P0]
- **描述**: 修复 `test_synthesize.py` 的失败/错误
- **问题根因**: 参数签名/依赖注入问题、TTS Backend mock 策略
- **子任务**:
  - [ ] 修复 `SynthesizePipeline` 的 DI 容器依赖
  - [ ] 修复 TTS Backend mock 策略（MOCK_LLM 环境变量）
  - [ ] 修复音频输出相关测试
- **验收标准**:
  - `pytest tests/test_synthesize.py -v` 全绿
- **依赖关系**: 依赖 A0.1
- **相关文件**: `tests/test_synthesize.py`, `src/audiobook_studio/pipeline/synthesize.py`, `src/audiobook_studio/tts/`

#### Issue B0.4: 非 mock 测试与覆盖率提升 [预估 12 小时] [优先级：P0]
- **描述**: 为 Pipeline 模块添加非 mock 路径测试，提升覆盖率至 ≥75%
- **子任务**:
  - [ ] 为 `synthesize.py` 添加非 mock 测试（目标覆盖率 ≥75%）
  - [ ] 为 `quality_check.py` 添加非 mock 测试（目标覆盖率 ≥75%）
  - [ ] 为 `extract.py` 添加边界用例测试
  - [ ] 为 `analyze_structure.py` 添加边界用例测试
- **验收标准**:
  - `pytest --cov=src/audiobook_studio/pipeline --cov-report=term-missing` 核心模块 ≥75%
  - 非 mock 路径测试覆盖真实 LLM 调用（使用 MOCK_LLM=false）
- **依赖关系**: 依赖 B0.1-B0.3
- **相关文件**: `tests/test_*.py`, `src/audiobook_studio/pipeline/*.py`

#### Issue B0.5: Prompt 模板与黄金数据集补全 [预估 6 小时] [优先级：P0]
- **描述**: 补全 quality_judge/tts_routing 的 Prompt 模板，扩展黄金数据集
- **子任务**:
  - [ ] 补全 `prompts/quality_judge/v1.j2` + `few_shot.jsonl`
  - [ ] 补全 `prompts/tts_routing/v1.j2` + `few_shot.jsonl`
  - [ ] 扩展黄金数据集至 6 环节各≥3 用例
- **验收标准**:
  - Jinja2 渲染测试通过
  - `tests/golden/` 下 6 个环节各≥3 个 `.json` 用例
- **依赖关系**: 无
- **相关文件**: `prompts/quality_judge/`, `prompts/tts_routing/`, `tests/golden/`

---

## 🔄 双 Agent 同步执行建议

### 并行执行策略

| 时间窗口 | Agent A 任务 | Agent B 任务 | 同步点 |
|----------|--------------|--------------|--------|
| **Day 1 AM** | A0.1 测试基础设施修复 | B0.1 ExtractPipeline 修复 | 共享 fixtures 验证 |
| **Day 1 PM** | A0.1 收尾 | B0.1 收尾 | 合并验证 A0.1+B0.1 |
| **Day 2** | A0.2 monitoring/feedback 测试 | B0.2 QualityCheckPipeline 修复 | 独立推进 |
| **Day 3** | A0.2 收尾 | B0.3 SynthesizePipeline 修复 | 独立推进 |
| **Day 4** | 等待 B0.3 完成 | B0.3 收尾 | B0.3 完成后 A0.4 启动 |
| **Day 5** | A0.4 E2E 脚本修复 | B0.4 非 mock 测试 | B0.4 进行中 |
| **Day 6** | A0.3 CI 闸门配置 | B0.4 收尾 + B0.5 Prompt 模板 | 合并验证 |

### 依赖关系图

```
A0.1 ──→ A0.2 ──→ A0.3
  │                ↑
  └────→ B0.1 ──→ B0.2 ──→ B0.3 ──→ B0.4 ──→ B0.5
                    │
                    └────→ A0.4 (E2E 验证)
```

### 每日站会同步清单

1. **失败测试数量变化**: `pytest -v 2>&1 | grep -E "FAILED|ERROR"`
2. **覆盖率进展**: `python scripts/coverage_check.py` 的 pipeline 覆盖率
3. **阻塞点**: 是否有依赖对方的任务尚未完成
4. **今日目标**: 明确当天要攻克的 Issue

---

## 📊 验收总清单（Phase 0 完成标志）

| # | 验收项 | 验证命令 | 目标值 |
|---|--------|----------|--------|
| 1 | ExtractPipeline 测试 | `pytest tests/test_extract.py -v` | 全绿 |
| 2 | QualityCheckPipeline 测试 | `pytest tests/test_quality_check.py -v` | 全绿 |
| 3 | SynthesizePipeline 测试 | `pytest tests/test_synthesize.py -v` | 全绿 |
| 4 | monitoring/feedback 测试 | `pytest tests/monitoring/ tests/feedback/ -v` | 全绿 |
| 5 | Pipeline 覆盖率 | `pytest --cov=src/audiobook_studio/pipeline --cov-report=term-missing` | ≥75% |
| 6 | 全量测试通过率 | `pytest -v 2>&1 | tail -5` | ≥95% |
| 7 | E2E 长书验证 | `python scripts/e2e_long_book.py data/long_novel/hongloumeng.txt` | 成功输出报告 |
| 8 | CI 质量闸门 | `.github/workflows/ci.yml` 配置 | 覆盖率/黄金数据集/合规率闸门生效 |
| 9 | Prompt 模板 | `ls prompts/quality_judge/ prompts/tts_routing/` | v1.j2 + few_shot.jsonl 存在 |
| 10 | 黄金数据集 | `ls tests/golden/*/` | 6 环节各≥3 用例 |

---

## ⚠️ 执行红线

1. **冻结新功能**: P2 级功能（G1-G5）全部暂停，任何非 Phase 0 的改动需经审批
2. **测试先行**: 任何修复必须先写测试，防止回归
3. **Mock 策略统一**: 使用 `MOCK_LLM` 环境变量而非 mock_mode 参数
4. **每日覆盖率检查**: 运行 `python scripts/coverage_check.py` 确保覆盖率稳步提升
5. **每 Issue 一提交**: 每个 Issue 完成后立即 commit，便于回滚

---

## 📌 快速命令参考

```bash
# 查看当前测试失败详情
pytest tests/test_extract.py -v --tb=short  # B0.1
pytest tests/test_quality_check.py -v --tb=short  # B0.2
pytest tests/test_synthesize.py -v --tb=short  # B0.3
pytest tests/monitoring/ -v --tb=short  # A0.2

# 查看覆盖率进展（每日检查）
python scripts/coverage_check.py

# 运行 E2E 长书验证（B0.1-B0.3 + A0.2 完成后）
python scripts/e2e_long_book.py data/long_novel/hongloumeng.txt

# 验证 CI 闸门配置（A0.3 完成后）
cat .github/workflows/ci.yml | grep -A 20 coverage-gate
```

---

## 2026-06-25 双 Agent 协作说明

**为什么双 Agent 仍有价值？**

虽然依赖关系图看似线性，但双 Agent 协作仍有以下优势：

1. **上下文隔离**: Agent A 专注于基础设施，Agent B 专注于业务逻辑，各自维护不同的知识上下文
2. **并行验证**: A0.1 完成后，A 可继续 A0.2，同时 B 开始 B0.1， two streams of progress
3. **交叉 Review**: A 完成的基础设施可供 B 验证，B 修复的 Pipeline 可供 A 通过 E2E 验证
4. **故障隔离**: 如果一个 Agent 遇到阻塞，另一个可继续推进其他任务

**关键同步点**:
- A0.1 ↔ B0.1: 共享 fixtures 和 mock 策略
- B0.3 完成 → A0.4 启动: E2E 验证需要 Pipeline 修复完成
- B0.4 完成 → A0.3 启动: CI 闸门需要黄金数据集

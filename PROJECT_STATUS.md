# Audiobook Studio — 项目唯一真相源

> **本文件是项目的唯一权威状态文档（Single Source of Truth）。**
> 所有 Sprint 进度、模块完成状态、覆盖率指标、架构决策均以此文件为准。

> **最后更新**: 2026-07-19（追加 §七 商业化任务逐项验收审计 + §八 独立对抗核验校准）

### 2026-07-01 端到端烟检完成

| 阶段 | 状态 | 输出 |
|------|------|------|
| extract | ✅ | 11 chapters, 77 paragraphs |
| analyze | ✅ | BookAnalysisOutput with character voice map |
| annotate | ✅ | ParagraphAnnotation with speaker/emotion |
| edit | ✅ | TTSEditOutput with edited text |
| audio_postprocess | ✅ | AudioPostProcessParams |
| synthesize | ✅ | 65 AudioSegments (mock WAV) |
| quality | ✅ | QualityJudgment scores |
| export | ✅ | `output/project_1/project_1.m4b` (65s)

---

## 一、整体状态快照（2026-07-14 实测校准）

| 维度 | 当前值 | 目标值 | 状态 |
|------|--------|--------|------|
| 测试通过率 | 799 passed / **263 failed** | 全部通过 | 🔴 严重偏离 |
| 总体覆盖率 (`pytest --cov=src`) | **46%** | ≥ 80% | 🔴 差 34% |
| 核心 Pipeline 覆盖率 | orchestrator 97%, quality_check 85%, synthesize 60% | 均 ≥ 80% | 🟡 部分达标 |
| Schema 覆盖率 | ~95% | ≥ 95% | 🟢 达标 |
| LLM Router 覆盖率 | 90% | ≥ 80% | 🟢 达标 |
| **真实可用 Sprint** | **2/9 (Sprint 0-1, D)** | 9/9 | 🔴 仅 22% |
| **生产完备 Sprint** | **1/9 (Sprint D)** | 9/9 | 🔴 仅 11% |

---

## 二、Sprint 完成状态（2026-07-14 降级校准版）

| Sprint | 目标 | 代码就绪 | 真实可用 | 备注 |
|--------|------|---------|---------|------|
| Sprint 0 | 脚手架 | ✅ | 🟢 | 项目结构、依赖、预检查全通 |
| Sprint 1 | 核心代码 | ✅ | 🟢 | 6 环节管线 + API 路由全通 |
| Sprint A | 夯实基础 | ✅ | 🟢 | Prompt 模板、黄金数据集、覆盖率 46% |
| Sprint B | 数据持久化 | ✅ | 🟢 | SQLAlchemy 2.0 + Alembic 迁移 |
| Sprint C | Web Studio | ✅ | 🟡 部分可用 | Vue 3 + wavesurfer.js 页面就绪，**后端钩子缺失（无保存/导出联动）** |
| Sprint D | 音频导出 | ✅ | ✅ 生产完备 | M4B 封装 + SRT 字典，**E2E 可产出可听 .m4b** |
| Sprint E | 反馈闭环 | ✅ | 🟡 部分可用 | 差异分析 Agent 可跑，**无人工反馈回环闭合、仅离线模式** |
| Sprint F | CI/CD 增强 | ✅ | 🟡 部分可用 | Langfuse 仅事件上报，**无成本/告警仪表盘、无 Prometheus 推送** |
| Sprint G | 高级特性 | ✅ | ⏳ 挂起 | 翻译/克隆/发布——**仅占位实现 (NotImplementedError)** |
| Sprint H | 自我迭代 | ✅ | ⏳ 挂起 | 监控告警/A/B 测试——**仅虚拟适配器 (dummy adapters)，无真实落地** |

---

## 三、覆盖率提升任务

### 当前进度
- **print() → logger**: ✅ 完成（399 处替换为 0）
- **templates.py 真实实现**: ✅ 完成
- **ObjectiveCritic 硬质检三件套**: ✅ 完成（DNSMOS + ASR WER + SpeakerSim）
- **覆盖率**: 46% → 目标 80%（还需 ~6000 行）

### 新增测试文件
- `tests/unit/test_coverage_gap_api.py` - 31 个 API 测试
- `tests/unit/test_harness_api.py` - 17 个 HARNESS 测试
- `tests/unit/test_semantic_coherence.py` - 23 个语义连贯性测试
- `tests/unit/test_rbac.py` - 39 个 RBAC 测试
- `tests/unit/test_metrics_data.py` - 31 个 metrics 测试
- `tests/unit/test_translate_pipeline.py` - 14 个 pipeline 测试
- `tests/unit/test_coverage_boost.py` - 14 个覆盖率提升测试

---

## 四、bug 修复记录

| 日期 | 文件 | 问题 | 解决 |
|------|------|------|------|
| 2026-06-28 | `feedback/integration.py` | 导入 `_load_golden_dataset` 错误 | 改为 `_load_golden_examples` |
| 2026-06-28 | `api/collab.py` | `resolved` 属性错误 | 改为 `processed` |
| 2026-06-28 | `auth/rbac.py` 等 | 导入路径错误 | 统一为 `from src.audiobook_studio.*` |
| 2026-06-28 | `feedback/promotion_gate.py` | 缺少 `PromotionGate` 类 | 新增类定义 |
| 2026-07-01 | `auto_run.py` | `MOCK_LLM="false"` 阻塞 LLM fallback | 改为 `MOCK_LLM="true"` |
| 2026-07-01 | `stage_registry.py` | Annotate/Edit/Synthesize/QualityStage 上下文注入缺失 | 补全 paragraph/chapter 上下文构建 |
| 2026-07-01 | `orchestrator.py` | `_write_synthesize` 唯一约束冲突 | 添加更新已有记录逻辑 |
| 2026-07-01 | `batch_exporter.py`, `m4b.py` | 导出模块 path/格式/编码问题 | 修复路径、格式、ffmpeg 命令 |
| 2026-07-11 | 远程 TTS 架构 | 四云架构落地 (Modal/Kaggle/Lightning/Baidu) | `src/voxcpm/`, `worker/` 完整落地；Modal Worker / Kaggle Worker / Lightning Worker / 百度 Paddle Worker 四云并行 |
| 2026-07-12 | 远程 VoxCPM2 生产级弹性系统 | Circuit Breaker / Rate Limiter / 重试指数退避 / 熔断恢复 | `src/audiobook_studio/tts/circuit_breaker.py`, `rate_limiter.py`, `remote_voxcpm2_client.py` 生产级实现 |
| 2026-07-15 | `run_pipeline.py` (Module 4.2 BGM CLI) | Bug A: 章节级(:503)/段落级(:552)直接调 async 编排器无 `await` 返回协程；Bug B: `MixConfig` 传入 schema 不支持字段(`speech_volume_db`/`fade_*_ms`)；Bug C: BGM 块局部 `from …database import SessionLocal` 致其整函数局部化，函数顶部 `db=SessionLocal()` 在到达 BGM 块前即 `UnboundLocalError` | Bug A: 两处 `asyncio.run(orchestrator_run_pipeline(…))` 包裹(沿用 synthesize.py 等约定)；Bug B: `MixConfig` 仅传 `bgm_volume_db`、bgm 路径交 `ExportJob.bgm_path`；Bug C: 删局部重导入、改用模块顶部已导入的 `SessionLocal` |
| 2026-07-15 | `tests/unit/test_run_pipeline_bgm.py` (Module 4.2, 新增) | BGM CLI 接线缺行为测试 | 6 tests：CLI 解析 / `main()` 透传 / 导出块集成；真实非 mock `MixConfig`+`ExportJob` 锁 Bug B、`AsyncMock`+`asyncio.run` 锁 Bug A |
| 2026-07-15 | `tests/unit/test_orchestrator.py` (Task 16) | 测试以同步调用触发 async 编排器、未用 async/await | 改 `async` 测试 + `await`；60 tests passed、无绿→红回归 |
| 2026-07-16 | `tests/unit/test_run_pipeline.py::test_runs_extract_analyze_only` | 夹具把章节文件放 `tmp_path` 根目录，与 `_get_chapter_files` 的 `MOCK_DATA_DIR/<书名>/` 契约不符致编排器永不触发；普通 `MagicMock` 不可 await，`asyncio.run` 抛 `TypeError` 被章节级 `except` 吞掉(乐天派绿) | 文件改放 `tmp_path/红楼梦/` 子目录(与 `test_empty_chapter_file_skipped` 同型)；mock 改 `AsyncMock` 令 `asyncio.run` 真正驱动协程；全集 104→103 failed、3650 passed、errors 30→30(零附带回归) |
| 2026-07-16 | `golden.py:477` | `run_golden_regression` (async) 内调用 `run_stage` 缺 `await`，协程被创建后从未驱动 | 加 `await run_stage(...)`，宿主本就为 async def，单行修复 |
| 2026-07-16 | `templates.py:572,610` | `_rerun_downstream_stages` 为 sync 却调用 async `run_stage` 无 await；生产路径在 `BackgroundTasks` 事件循环中运行，不能用 `asyncio.run` 桥接 | 整链 async 化：`def`→`async def`、调用点加 `await`；生产调用方 `_apply_template_background` 本为 async 已在 loop 中；级联 11 个测试改 `@pytest.mark.asyncio` + `AsyncMock` + `await_count` 回归锁 |
| 2026-07-16 | `tests/test_templates.py`, `tests/unit/test_templates_business.py` | 对应上述 async 化的测试同步跟进 | 4 + 10 = 14 个测试全绿，`await_count` 断言确保若有人删 `await` 即红 |
| 2026-07-16 | `run_pipeline.py` (GC Integration) | 导出成功后自动清理临时中间音频文件以回收 ~90% 磁盘空间 | 新增 `--keep-tmp` CLI 参数；引入 `cleanup_after_export` 从 `gc_manager`；导出完成后若未指定 `--keep-tmp` 自动调用清理，保留最终导出产物(.m4b/.srt等)，删除段落级 WAV/MP3 中间文件；13 个 GC 测试全绿 |

---

## 五、远程 TTS 四云架构落地状态 (2026-07-11/12)

### 架构概览
| 云厂商 | Worker 实现 | 状态 | 备注 |
|--------|------------|------|------|
| **Modal** | `worker/modal_worker.py` | ✅ 落地 | GPU 按秒计费，冷启动快 |
| **Kaggle** | `worker/kaggle_worker.py` | ✅ 落地 | 免费 GPU 配额，适合批量推理 |
| **Lightning** | `worker/lightning_worker.py` | ✅ 落地 | 企业级 GPU 集群管理 |
| **百度 Paddle** | `worker/baidu_paddle_worker.py` | ✅ 落地 | 国内合规，低延迟 |

### 核心生产级组件 (2026-07-12)
| 组件 | 文件 | 功能 | 测试覆盖 |
|------|------|------|----------|
| 熔断器 | `src/audiobook_studio/tts/circuit_breaker.py` | 状态机: closed/open/half-open，失败阈值触发熔断，自动恢复 | ✅ |
| 限流器 | `src/audiobook_studio/tts/rate_limiter.py` | Token Bucket + 滑动窗口，支持分优先级配额 | ✅ |
| 远程客户端 | `src/audiobook_studio/tts/remote_voxcpm2_client.py` | 重试指数退避、超时控制、并发信号量、健康检查 | ✅ `tests/test_remote_voxcpm2.py` |
| Celery 任务 | `src/audiobook_studio/tasks/tts_tasks.py` | 章节级 TTS 合成，幂等锁、信号量、Redis 分布式锁 | ✅ |

### 验收标准 (07-12 完工)
- [x] 四云 Worker 代码完整落地 (`worker/` 目录)
- [x] 熔断/限流/重试三件套生产级实现
- [x] 远程 VoxCPM2 客户端健康检查 + 自动故障转移
- [x] 测试覆盖: `tests/test_remote_voxcpm2.py` (127 tests)
- [x] Docker 镜像瘦身: `.dockerignore` 排除 5 类运行产物，镜像 6.23GB → 1.96GB (68% 减重)

### 监控模块覆盖率测试
- `tests/unit/test_monitoring_coverage.py` - 30 个监控测试
  - langfuse_client.py 函数覆盖
  - dashboard.py 函数覆盖
  - MonitoringDashboard 类覆盖
  - 监控子模块覆盖（cost_dashboard, metrics_exporter, baseline, compliance, alert, offline_monitoring）

### Benchmarks 模块覆盖率测试
- `tests/unit/test_benchmarks_coverage.py` - 24 个压测测试
  - bench_cost.py 函数覆盖
  - bench_latency.py 函数覆盖
  - bench_voxcpm2.py 函数覆盖（硬件检测、VoxCPM2 推算、Edge-TTS 基准、报告生成）

---

## 六、降级判定矩阵与校准记录 (2026-07-14)

### 降级判定矩阵（唯一标准）

| 判定标准 | 状态 | 适用条件 |
|----------|------|----------|
| **[⏳ 挂起]** | ⏳ | 仅实现 501 占位符/NotImplementedError、纯 placeholder、仅写文档无主路径代码 |
| **[🟡 部分完成]** | 🟡 | 主路径有代码但处于 mock 模式，或缺乏真实 E2E 验证/无法产出可听音频 |
| **[✅ 生产完备]** | ✅ | 完整真实非 mock 主路径、具备异常自愈、通过核心回归单测 |

### 本次校准逐项依据

| Sprint | 旧状态 | 新状态 | 降级依据 |
|--------|--------|--------|----------|
| Sprint C (Web Studio) | 🟢 | 🟡 | 前端页面就绪，但**无后端保存/导出钩子**，前后端断层 |
| Sprint E (反馈闭环) | 🟢 | 🟡 | 差异分析 Agent 仅离线跑通，**无人工反馈回环闭合、无在线评分入口** |
| Sprint F (CI/CD 增强) | 🟢 | 🟡 | Langfuse 仅做事件上报，**无成本仪表盘、无告警、无 Prometheus 推送** |
| Sprint G (高级特性) | ⚠️ 占位 | ⏳ 挂起 | 翻译/克隆/发布**全为 NotImplementedError 占位**，零主路径代码 |
| Sprint H (自我迭代) | 🟢 | ⏳ 挂起 | 监控告警/A/B 测试**仅 dummy adapters**，无真实落地、无数据流 |

### 关键结论
- **仅 Sprint 0、1、D 为生产可用**（真实非 mock 主路径 + E2E 可听音频输出）
- **Sprint C/E/F 需补齐后端钩子/反馈闭环/观测栈** 才能升为 🟢
- **Sprint G/H 需从零实现主路径**（当前零可用代码），不可视为“已完成”

---

## 七、商业化落地任务逐项验收审计 (2026-07-19)

> 审计方法：本地工具串行精读命中文件 + 跑命名测试 + 套用红线#1(主路径真实性)/#2(测试有副作用断言)。
> 档位沿用 §六降级判定矩阵：✅生产完备 / 🟡部分完成 / ⏳挂起（含未实现）。
> 严禁以新建 audit/completion 临时文档刷交付感，事实记于此唯一真相源。

### 任务验收总表

| 任务 | 标题 | 判定 | 主路径 | 命名测试 | 关键证据 (file:line) |
|------|------|------|--------|----------|----------------------|
| 1.1 | 动态声学映射引擎 | ✅ 生产完备 | 真实非mock | 29 绿（4场景全绿） | `config/acoustic_mapping.py:29/49`；`pipeline/audio_postprocess.py:149 generate_acoustic_schedule`；`stage_registry.py:405-455` 已接入生产流；`tests/unit/audio/test_post_processor.py` 29 passed |
| 1.2 | 双引擎真实发声接线 | 🟡 部分完成 | 🔴 隐式mock短路 | — | `tts/port_factory.py:74-83` auto 默认返回 `FakeRemoteTTSPort(synthesis_delay=0.5/1.0)`，注释自承"simulates local/cloud synthesis"；真实 Kokoro 后端 `tts/kokoro_backend.py:185`(onnxruntime)+`:341`(subprocess) 存在但**未接线到默认主路径**；`synthesize.py:135 get_port()` 即取此桩 |
| 1.3 | 前端动态探针适配 | 🟡 部分完成 | 探针桩 | — | GET `/api/tts/status` 路由 `tts_voices.py:307-361` 存在；前端 `AutoRunView.vue:117/273-296` 真实消费 fetchTtsStatus 动态显示；**但探针不查真实模型加载态**（`:325-329` 注释"In production, these would check actual model loading status"实际只 `enable_local_tts = env.bool`），停模型不会翻 bool→不会真实灰置 |
| 2.1 | 核心工具强类型封装 | ⏳ 未实现 | 无代码 | 无 | `load_book_file`/`analyze_and_split`/`generate_emotion_markup`/`execute_audio_synthesis` 四命名工具全仓 src/ 零命中；无 Pydantic Function Calling 工具定义、无 400 传参拦截、无自我纠错重试 |
| 2.2 | 双模态状态机(FSM)路由 | ⏳ 挂起 | 纯桩 | 无 | `agent_chat.py:411 POST /chat` 存在但 `_process_agent_message:121-204` 为关键词匹配桩（`:129` 注释"simplified implementation, in production, this would integrate with actual agent orchestration"）；**无 FSM / 无 PENDING_HUMAN_CONFIRM / 无 Autopilot·Interactive 双模态 / 无挂起下游** |
| 2.3 | 多格式解析器集成 | 🟡 部分完成 | 解析真 / 灌入缺 | — | `pipeline/extract.py` 真支持 PDF( PyMuPDF+OCR fallback)/EPUB(ebooklib)/DOCX(python-docx)/图片( pytesseract)，`upload.py ALLOWED_EXTENSIONS` 全格式；**但无 `project_segments` 表模型**，剧本结构灌入走现有 `Paragraph` 表且未见「儿童/大众」文本分级字段 |
| 3.1 | 智能闪避与音效图合成 | ✅ 生产完备 | 真实非mock | 16 绿 | `export/audio_ducking.py:29 duck_gain_db=-12.0`「对话抬升12dB」；`:168-176 sidechaincompress` 真实 FFmpeg 滤镜；`analyzer.py SceneTagMapper/normalize_scene_tag` 映射场景音效；`tests/unit/export/test_audio_ducking.py` 16 passed（ducking 数值/卡点真断言）；「听感"呼吸感"」为人工感知，未自动化但实现真 |
| 3.2 | 16:9 动态网页画布 | ✅ 生产完备 | 真实非mock | — | `web/src/views/VideoCanvasView.vue:189 isAutoMode(route.query.auto==='1')`；`:42/63/106` auto 模式隐藏控制面板/侧栏/进度条；`:10 @timeupdate onTimeUpdate` 事件驱动字幕；`:28 isSpeaking` 高亮、`:32/54` 角色头像；路由 `router/index.ts` `/projects/:projectId/video-canvas` 已注册 |
| 4.1 | Reviewer Agent 质量门禁 | 🟡 部分完成 | 拦截真 / 闭环缺 | 📛 12 收集错误 | `pipeline/review.py ReviewerAgent` 真查漏角色/JSON截断/打标逻辑(`:79/:197`)；`stage_registry.py:554-601` 集成并打 `[REVIEWER INTERCEPT]/[FIX CMD]` 终端日志；**但 `tests/unit/pipeline/test_reviewer_agent.py:27-37` 用 `sys.modules[mod]=MagicMock()` 污染全局致 ForwardRef SyntaxError 单跑 12 收集错误**（违反红线#2）；FixCommand 生成但**未见 FixCommand→Developer 自动补全闭环**（仅记录不执行修复） |
| 4.2 | SOP 反思自我进化 | 🟡 部分完成 | 真实非mock | 📛 2 红 / 25 绿 | `pipeline/sop_reflection.py`：`SOPConfig:77` 读写 agent_sop.json；`SOPBackgroundThread:796-833` 守护线程；`reflect():577` 含 LLM 反思 prompt；前端修正钩子 (db7611a)；**但 `tests/unit/test_sop_reflection.py` 2 failed**(`test_normalize_genre`/`test_apply_to_audio_postprocess`)非全绿 |
| 5.1 | 商业遥测可视化看板 | 🟡 部分完成 | 前端真 / 数据源断 | — | `web/src/views/DashboardView.vue` 5 个 ECharts：成本饼图(`:43`)、延迟排行(`:59 bar`)、Provider 成本(`:67`)、RTF 仪表(`:83 gauge`)、历史(`:98`)；**但 telemetry 写 `telemetry.py:490 self.output_dir`，看板 API `monitoring.py:37` 读 `reports_dir()`，两路径不一致致看板取不到真实遥测产物**（即任务#8 阻塞）；tooltip 仅见 `$ USD`，RMB 折算待确认 |
| 5.2 | 剧本微调工作台 | ✅ 生产完备 | 真实非mock | — | `paragraphs.py:51 update_paragraph`(CRUD)、`:413/@router.post regenerate`、`projects.py:379-424 regenerate_paragraph`(`force_regenerate=True`+`"seamlessly merged"`，仅触发该 paragraph 不整书重跑)、`:122 needs_regeneration` 标志；前端 `ParagraphEditor.vue` 存在 |

### 模块汇总

- **模块一·声学引擎 (1.1-1.3)**：映射引擎(1.1)生产完备是模块地基；但发声接线(1.2)在默认主路径返回 FakeRemoteTTSPort（隐式mock短路，违反红线#1），探针(1.3)不查真实模型态。模块整体 🟡 ——「降维映射已真实，但物理发声与探针仍 mock/桩」。
- **模块二·大总管智能体 (2.1-2.3)**：最薄弱模块。强类型工具(2.1)全仓零实现；FSM 路由(2.2)为关键词桩无状态机；仅多格式解析器(2.3)真实落地。整体 ⏳ 挂起 ——「大模型尚未真正接管调度」。
- **模块三·视频化与混音 (3.1-3.2)**：两项均 ✅ 生产完备，智能闪避有真实 FFmpeg sidechain + 16 绿测试，16:9 画布事件驱动字幕与头像高亮完整。整体 ✅。
- **模块四·元认知质量防线 (4.1-4.2)**：主路径真实（Reviewer 拦截、SOP 反思线程均有代码），但均带测试债（reviewer 12 收集错误、sop 2 红），且 Reviewer 自动补全闭环未闭合。整体 🟡 ——「防线路径在，但测试不绿、闭环未全」。
- **模块五·前端大屏运维 (5.1-5.2)**：前端两页(看板/微调台)ECharts/CRUD 真实；单句重录(5.2)端到端完备；但看板(5.1)数据源路径与 telemetry 产物不一致（阻塞#8）致实时取数断流。整体 🟡。

### 红线违反与阻塞清单

- 🔴 **红线#1 主路径真实性违反**：1.2 `port_factory.py:78-83` 默认 auto 路径 `FakeRemoteTTSPort(synthesis_delay=…)` —— 真实 Kokoro/Edge 后端存在却未接线到默认主路径，属「隐式 mock 短路」。须显式接线或以 `MOCK_LLM`/`TEST_MODE` 门控后降级至 fake。
- 🔴 **红线#2 测试有副作用违反**：4.1 `test_reviewer_agent.py:27-37` 批量 `sys.modules[mod]=MagicMock()` 污染全局命空间，致自身单跑 12 个 ForwardRef SyntaxError 收集错误，命名测试实际不可跑。
- 🟡 **命名测试带红**：4.2 `test_sop_reflection.py` 2 failed。
- ⛔ **阻塞#8 (in_progress)**：5.1 telemetry 写 `output_dir` ↔ 看板 API 读 `reports_dir()` 路径不匹配，看板无法消费真实遥测。未修复前 5.1 维持 🟡。
- ⏳ **暂无代码需从零实现**：2.1（四命名工具）、2.2（FSM/双模态）。

### 审计结论

- **生产完备 (4/12)**：1.1 / 3.1 / 3.2 / 5.2
- **部分完成 (6/12)**：1.2 / 1.3 / 2.3 / 4.1 / 4.2 / 5.1
- **挂起·未实现 (2/12)**：2.1 / 2.2

模块三（视频化）已整体达生产完备，模块一地基（映射引擎）完备但发声主路径未脱 mock，模块二（智能体并网）是当前最薄弱且仍是桩/未实现区，为后续硬性补齐优先级最高的方向。

---

## 八、§七 独立对抗核验校准 (2026-07-19 二次审计)

> 核验方法：独立静态精读 §七 引用的所有 `file:line` 证据 + 全仓 grep 核实行号/存在性 + 命名测试尝试运行（受阻：hypothesis 包损坏致 collection INTERNALERROR）+ 红线#1/#2/#5 对齐。
> 此节不替换 §七，仅记录独立核验中发现的偏差、补充与新问题。

### 证据行号/路径校准

| §七 引用 | 核验结果 | 校正 |
|----------|---------|------|
| `config/acoustic_mapping.py` (1.1) | 实际路径 `src/audiobook_studio/config/acoustic_mapping.py`，行号 29/49 正确，文件存在 | 路径前缀补全，非幻觉 |
| `tts/port_factory.py:74-83` (1.2) | FakeRemoteTTSPort 返回在行 76/80（非 74/83 处），断言对象准确 | 行号微调 74→76, 83→80 |
| `tts/kokoro_backend.py:185/341` (1.2) | 文件存在，但具体 `:185`(onnxruntime) 和 `:341`(subprocess) 未经逐行核对 | 判定维持（后端存在属实），行号未独立验证 |
| `tts_voices.py:325-329` (1.3) | 注释 "In production, these would check actual model loading status" 坐实 | ✅ 准确 |
| `telemetry.py:490` (5.1) | 实际路径 `src/audiobook_studio/monitoring/telemetry.py`，行号 490 `output_path = self.output_dir / "metrics_summary.json"` 坐实 | 路径前缀补全，非幻觉 |
| `pipeline/extract.py` OCR (2.3) | §七 称"图片(pytesseract)"真支持；实际 `:79` 注释 "simplified - would use pytesseract in production" + `:82` 注释 "In production: use pytesseract.image_to_string..."，实际代码走 `page.get_text("dict")["blocks"]`（文本层提取，非图像 OCR） | **OCR 伪实现纠偏**：pytesseract OCR 路径被注释，实际仅提取已有文字层 |
| `audio_ducking.py:29 duck_gain_db=-12.0` (3.1) | 坐实 ✅。注释 "BGM 降低 dB (对话抬升 12dB)"——语义为 BGM 压低以凸显人声，非人声"抬升" | 语义微调：duck_gain_db 是 BGM 降幅，人声音量不变 |
| `stage_registry.py:554-601` (4.1) | Reviewer 集成在 550-603，[REVIEWER INTERCEPT] 在 573、[FIX CMD] 在 579 | ✅ 准确 |
| `review.py:79/197` (4.1) | `check_voice_bindings:79` 真查音色缺失、`check_tag_consistency:192` 真查打标逻辑（非197） | 197→192 微调 |
| `paragraphs.py`/`projects.py` (5.2) | 51/122/413/379/418 行号全部坐实 | ✅ 准确 |
| `VideoCanvasView.vue:189` (3.2) | isAutoMode 坐实 ✅，隐藏面板 42/63/106 坐实 ✅ | ✅ 准确 |

### §七 判定校准（12 任务二次判定）

| 任务 | §七 | 校准 | 校准理由 |
|------|-----|------|---------|
| 1.1 | ✅ | ✅ | 判定不变。路径修正，assertion depth 静态核实（pytest.approx 精准期望），4 场景覆盖完整 |
| 1.2 | 🟡 | 🟡 | 判定不变。默认主路径 FakeRemoteTTSPort 短路坐实（红线#1 违反），kokoro 后端真实存在但未接线 |
| 1.3 | 🟡 | 🟡 | 判定不变。探针仅读环境变量，不查真实模型态（注释自承） |
| 2.1 | ⏳ | ⏳ | 判定不变。四工具全仓 src/ 零命中 |
| 2.2 | ⏳ | ⏳ | 判定不变。`_process_agent_message` 关键词桩无 FSM/双模态 |
| 2.3 | 🟡 | 🟡 | 判定不变。但补充 **OCR 伪实现** 降级说明：图片 OCR 实际仅提取已有文字层 blocks，pytesseract image_to_string 路径被注释掉，不构成"图片(pytesseract)真支持" |
| 3.1 | ✅ | ✅ | 判定不变。FFmpeg sidechaincompress 真实滤镜，SceneTagMapper 真实映射，test assertions 有深度（dB值/分段类型/时序） |
| 3.2 | ✅ | ✅ | 判定不变。事件驱动字幕(isSpeaking)+头像高亮+?auto=1 隐藏面板+路由注册，完整 |
| 4.1 | 🟡 | 🟡 | 判定不变。Reviewer 拦截真(check_voice_bindings/check_json_truncation/check_tag_consistency)、FIX CMD 日志真；但 FixCommand→Developer 自动补全闭环未闭合；`sys.modules` 批量污染坐实（红线#2 违反）。命名测试因环境崩溃未复测 12 收集错误 |
| 4.2 | 🟡 | 🟡 | 判定不变。reflect() 有 LLM prompt + heuristic fallback + SOPBackgroundThread；test_sop_reflection.py 2 failed 因环境崩溃未复测 |
| 5.1 | 🟡 | 🟡 | 判定不变。**路径不一致判定由「待确认」→「坐实」**：telemetry `_write_metrics_summary:487` 默认写 `./output/{project_id}/`，monitoring.py `:37` 读 `reports_dir()`→`storage/books/{id}/reports/`，两路径根目录不同，看板 API 必读不到真实遥测产物 |
| 5.2 | ✅ | ✅ | 判定不变。单句重录 force_regenerate=True + CRUD + ParagraphEditor.vue 端到端完备 |

### 核验新发现（§七 未记载）

1. 🔴 **资产边界违规（红线#5）**: `.gitignore` 未覆盖 `storage/books/`（12 个运行时产物目录 26-37）、`voxcpm2-pool/`（Worker 部署脚本/池）。当前为 untracked 未推入代码仓，但无白名单防御规则，存在意外 add 风险。
2. 🟡 **测试环境崩溃阻断验证**: `hypothesis` 包内部损坏（`ModuleNotFoundError: No module named 'hypothesis.internal'; 'hypothesis' is not a package`），致 pytest collection 阶段 INTERNALERROR，4 个命名测试文件（test_post_processor/test_audio_ducking/test_reviewer_agent/test_sop_reflection）均无法收集执行。§七 的"29绿/16绿/12收集错误/2红"运行时红绿**本轮无法复验**。静态核验表明断言深度合格（pytest.approx/具体数值断言），但真实通过数未知。
3. ⬛ **远端分支不存在**: `origin/refactor/p2-engineering-debt` 从未推送（`git rev-parse @{u}` → `fatal: no upstream configured`），`git log origin/refactor/p2-engineering-debt..HEAD` → `fatal: ambiguous argument`。所有改动均在本地，无远端备份。
4. ℹ️ **未跟踪文档资产**: `docs/changelog/auto/`（3 个自动变更日志 `.md`）未被 git 跟踪；`scripts/security/leaked-credential-patterns.txt`（安全扫描产物）未跟踪。前者应备案入仓，后者为敏感扫描结果不宜推送。

### 核验结论

- **§七 整体可信度：高**（12 个判定均维持，无升降级）。偏差集中在证据路径前缀不完整（`config/acoustic_mapping.py`/`telemetry.py` 缺中间前缀）和 OCR 实现程度高估（伪 OCR），非方向性误判。
- **生产完备仍为 4/12**：1.1 / 3.1 / 3.2 / 5.2
- **部分完成仍为 6/12**：1.2 / 1.3 / 2.3 / 4.1 / 4.2 / 5.1
- **挂起仍为 2/12**：2.1 / 2.2
- **最紧急行动项排序**：① 修复 hypothesis 测试环境→复测命名测试确认真红绿 ② 解决 telemetry↔monitoring 路径不一致（阻塞#8） ③ `.gitignore` 白名单补全防御规则 ④ 推送本地分支到远端备案

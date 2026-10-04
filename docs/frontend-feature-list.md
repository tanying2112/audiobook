# Audiobook Studio — 前端界面设计功能列表

**版本**: v1.0-draft  
**日期**: 2026-06-25  
**对应后端**: Sprint 0-H（含 6+1 管线阶段、LLM 多提供商路由、反馈闭环、多轨编辑器）  
**关联文档**: `frontend-types-contract.ts`（TypeScript 数据模型契约）

---

## 设计原则

| 原则 | 说明 |
|------|------|
| **一站式管理** | 单页面板覆盖全部管线环节，无需切换工具 |
| **实时感知** | WebSocket 推送管线进度、LLM 状态变更、Kill Switch 告警 |
| **逐层下钻** | Project → Chapter → Paragraph → AudioSegment 四级钻取 |
| **状态可视化** | 所有状态机通过颜色编码 + 进度条 + 指示灯呈现 |
| **成本透明** | 每个粒度（Project/Chapter/Paragraph/Model）均可查看成本 |

---

# P0 — 核心面板（MVP 必须具备）

## P0-1 项目仪表盘

**路由**: `/` 或 `/projects`

| # | 功能点 | 说明 | 后端 API | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 项目卡片列表 | 展示所有项目的卡片（标题、作者、体裁、进度条、状态徽章、累计成本） | `GET /api/projects/?skip=0&limit=100` | `ProjectOut[]` |
| 2 | 搜索与筛选 | 按标题/作者搜索，按 status/difficulty/genre 筛选，按 created_at 排序 | 同上 + query params | — |
| 3 | 新建项目表单 | 弹窗 Modal：上传文件（PDF/EPUB/DOCX/TXT/图片，拖拽支持）+ 填写元信息（标题/作者/体裁/难度/语言/文风备注） | `POST /api/projects/` | `ProjectCreate` |
| 4 | 项目卡片快捷操作 | "启动管线"、"继续处理"、"删除" 三个按钮 | `POST /api/projects/{id}/pipeline/start` 等 | — |

**UI 参考**: Notion 数据库视图风格，卡片含进度条（0-100%）+ 状态徽章（draft 绿/processing 蓝/completed 金/failed 红）。

---

## P0-2 项目详情页

**路由**: `/projects/:id`

**分为 4 个 Tab**：

### Tab 1: 上帝视角档案（BookAnalysisOutput）

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 书籍元信息卡 | 展示 BookMeta：标题、作者、体裁、难度、语言、时代背景、预估章节数 | Project + analyzed_json | `BookMeta` |
| 2 | 故事主线摘要 | 可编辑文本区域（story_line_summary），支持人工修正后回写 | 同上 | — |
| 3 | 全局文风备注 | 可编辑文本区域（global_style_notes） | 同上 | — |
| 4 | 角色声音绑定表 | 表格：canonical_name + aliases + gender + age_range + voice_id(下拉) + sample_quote，支持 CRUD | Character ORM | `CharacterVoiceBinding[]` |
| 5 | 章节情感曲线 | 折线图：X=章节号，Y=intensity，点颜色=dominant_emotion（10 种情感 × 10 色） | EmotionSnapshot[] | `EmotionSnapshot[]` |
| 6 | 成本总览 | 累计成本 / 每书限额 / 每章限额 / 剩余额度 | Project.total_cost_usd 等 | `Project` |

### Tab 2: 管线进度面板（详见 P0-3）

### Tab 3: 音频编辑器（详见 P0-5）

### Tab 4: 导出 & 发布（详见 P3）

---

## P0-3 管线进度面板

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 阶段流水线图 | 横向 6+1 阶段节点（extract→analyze→annotate→edit→audio_postprocess→synthesize→quality），每个节点显示项目级状态 | Project.current_stage + progress | `PipelineStage` |
| 2 | 断点续传按钮 | 若管线中断，显示"从 [阶段名] 继续"按钮，读取 checkpoint 数据 | `CheckpointManager.resume_from()` | `PipelineCheckpoint` |
| 3 | 章节网格视图 | 每章一行（或卡片）：章节号 + 标题 + 7 个 stage status 小圆点（绿=completed/灰=pending/蓝=running/红=failed）+ 成本 + Token 数 | Chapter[] | `Chapter` |
| 4 | 章节点击 → 段落级视图 | 段落列表表格：index + text(截断) + speaker + emotion + is_dialogue + status(单字段流转) + 操作按钮 | Paragraph[] | `Paragraph` |
| 5 | 段落重新处理 | 单段落的"重新标注"/"重新编辑"/"重新合成"/"重新质检"按钮 | `POST /api/projects/{id}/pipeline/reprocess` | — |
| 6 | 实时进度推送 | WebSocket 推送 stage_enter/stage_exit 事件，节点闪烁动画 | `WS /api/ws/pipeline/{project_id}` | `PipelineWSMessage` |

**7 阶段定义**（注意：STAGE_ORDER 只有 6 阶段，此处统一为 7）:

```
extract → analyze → annotate → edit → audio_postprocess → synthesize → quality
  ①        ②        ③         ④          ⑤                   ⑥          ⑦
```

**Chapter per-stage status 字段映射**:

| 阶段 | Chapter ORM 字段 | 状态值 |
|------|-----------------|--------|
| ① extract | `extract_status` | pending/completed |
| ② analyze | `analyze_status` | pending/completed |
| ③ annotate | `annotate_status` | pending/completed |
|pleted |
| ④ edit | `edit_status` | pending/completed |
| ⑤ audio_postprocess | (无独立字段，含在 route_status 中) | pending/completed |
| ⑥ synthesize | `synthesize_status` | pending/completed |
| ⑦ quality | `quality_status` | pending/completed |

**Paragraph 单字段状态流转**:

```
pending → annotated → edited → audio_processed → synthesized → quality_checked
```

---

## P0-4 音频多轨编辑器

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 时间轴波形图 | Chapter 级：AudioSegment 按序排列在时间轴上，每段显示波形缩略图 + 引擎图标 | AudioSegment[] | `AudioSegment` |
| 2 | 片段选中高亮 | 点击某段高亮展开，下方显示详情面板 | — | — |
| 3 | 片段播放 | HTML5 `<audio>` 播放当前片段，支持上一段/下一段快速切换 | AudioSegment.file_path | — |
| 4 | 片段详情面板 | 右侧抽屉，展示：原始文本 → 编辑后文本 → 标注（speaker/emotion/intensity）→ TTS 路由（engine/voice/prosody）→ 质检 4 维评分 + issues + fix_suggestions | Paragraph._embedded | `TTSEdit` + `Routing` + `Quality` |
| 5 | 版本历史 | 当前片段的版本列表（version/parent_segment_id），可回退到旧版本 | AudioSegment.version | `AudioSegment` |
| 6 | 质量问题高亮 | `needs_regeneration=true` 的片段在时间轴上标红，hover 展示 issues 列表 | Quality.needs_regeneration | `Quality` |

**UI 参考**: Audacity 风格简化版 — 水平时间轴 + 波形色块 + 选中抽屉。

---

## P0-5 角色声音管理

**路由**: `/projects/:id/characters`（可作为项目详情 Tab 1 的子区域）

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 角色列表 | 表格：canonical_name + aliases(标签) + gender(图标) + age_range + voice_id + sample_quote | Character ORM | `CharacterVoiceBinding[]` |
| 2 | 新增/编辑角色 | Modal 表单：canonical_name(唯一校验) + aliases(可多选添加) + gender(下拉) + age_range(下拉) + voice_id(TTS 音色下拉) + sample_quote | `POST/PUT /api/characters/` | `CharacterVoiceBinding` |
| 3 | 音色试听 | voice_id 下拉旁的"试听"按钮，播放该音色的示例音频 | TTS Engine API | — |
| 4 | 角色关联统计 | 每角色关联的段落数、平均 confidence、常用 emotion | 聚合查询 | — |

**可用的 TTS 音色列表**（需后端提供枚举端点）:

| 引擎 | 音色数 | 示例 |
|------|--------|------|
| Kokoro | 系统预设 | — |
| Edge-TTS | 15 | XiaoxiaoNeural, YunxiNeural, GuyNeural 等 |
| Azure | 15 | 同 Edge 列表 |
| GCP | 24 | zh-CN Standard/Wavenet/Neural2 A-D, en-US Standard/Wavenet/Neural2 A-D |
| VoxCPM2 | 6 | zh_female_1, zh_female_2, zh_male_1, zh_male_2, en_female_1, en_male_1 |

---

# P1 — 运维监控面板

## P1-1 LLM 提供商总览

**路由**: `/monitoring` 或 `/llm`

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 提供商卡片网格 | 6 卡片：Gemini/Groq/NVIDIA/OpenRouter/Local/Others，每卡显示：状态灯（绿/黄/红）、当前并发、p95 延迟、今日成本、剩余额度、熔断器状态 | `LLMRouter.get_status()` | `LLMProviderStatus` |
| 2 | 模型下钻 | 点击卡片展开：该提供商下所有模型的并发/延迟/成本/错误率 | 同上 | — |
| 3 | 轮询策略配置 | 可视化拖拽调整优先级、启用/禁用、设置回退顺序 | `LLMRouter.config` | `StageConfigs` |
| 4 | 实时日志流 | 最近 50 条 LLM 调用记录：timestamp + provider + model + tokens + latency + status + error | `GET /api/llm/logs` | — |

---

## P1-2 熔断器状态面板

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 熔断器网格 | 每个 provider + model 组合一行：state(closed/open/half_open) + failure_count + last_failure + next_retry_at + 手动复位按钮 | `CircuitBreaker.get_all_status()` | `CircuitBreakerStatus[]` |
| 2 | 触发历史 | 列表：timestamp + provider + model + failure_reason + action_taken(fallback/abort) | 同步写入 DB | `CircuitBreakerEvent[]` |

---

## P1-3 成本看板

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 总览卡片 | 今日成本 / 本月成本 / 累计成本 / 预算使用率(进度条) | `CostTracker.get_summary()` | `CostSummary` |
| 2 | 趋势折线图 | 最近 30 天日成本堆叠图，按 provider/stackable 分层 | `CostTracker.get_daily_series(30)` | `DailyCostPoint[]` |
| 3 | 按项目分摊 | 表格：project_id + title + total_cost + cost_per_chapter + last_updated | 聚合查询 | — |
| 4 | 按阶段分摊 | 6+1 阶段各自成本占比饼图 + 单位成本（$/千 token / $/千字符） | `CostTracker.get_stage_breakdown()` | `StageCostBreakdown` |

---

## P1-4 配额仪表盘

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 配额进度条 | 每 provider 一个进度条：used / limit / reset_at，超限标红 | `QuotaRegistry.get_all()` | `QuotaStatus[]` |
| 2 | 预警规则 | 可配置：used_pct ≥ 80% 触发告警、used_pct ≥ 95% 自动切换 provider | `QuotaRegistry.alert_rules` | — |

---

## P1-5 Kill Switch 面板

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 全局开关 | 大按钮：ENABLED / DISABLED（红底白字），切换即时生效 | `KillSwitch.is_enabled()` | `KillSwitchStatus` |
| 2 | 触发历史 | 列表：timestamp + trigger_type(manual/threshold/panic) + affected_projects + operator | DB 记录 | `KillSwitchLog[]` |

---

## P1-6 硬件档位切换

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 当前档位展示 | CPU / int8_gpu / fp16_gpu / fp32_gpu，附带检测到的 GPU/VRAM 信息 | `HardwareProfile.detect()` | `HardwareProfile` |
| 2 | 一键切换 | 下拉选择目标档位 → 确认 → 重载 TTS 模型 | `PUT /api/hardware-profile` | `HardwareProfile` |

---

# P2 — 反馈闭环 & 版本管理

## P2-1 反馈记录管理

**路由**: `/feedback`

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 反馈列表表格 | project_id + chapter_idx + paragraph_idx + source(human_edit/quality_judge/user_rating) + pattern_tags + severity + original_text → suggested_text + status(pending/applied/rejected) + created_at | `FeedbackRecord[]` | `FeedbackRecord` |
| 2 | 筛选器 | source 多选 + severity 多选 + pattern_tags 搜索 + 日期范围 + status 单选 | query params | — |
| 3 | 详情侧滑 | 点击行展开：完整 diff 高亮（原文 vs 建议）+ 上下文段落 + 关联的 QualityJudgment + 操作按钮(采纳/拒绝/标记重试) | — | — |
| 4 | 统计仪表盘 | 总条数 / 已采纳率 / 按 source 分布饼图 / 按 pattern_tags 分布条形图 / 严重度热力图 | `FeedbackAnalysis.aggregate()` | `FeedbackAnalysis` |
| 5 | Pattern 词云 | 21 种 pattern 标签的出现频率词云/气泡图，点击 tag 过滤反馈列表 | 聚合统计 | — |

**反馈来源色标**:
- `human_edit` → 蓝色
- `quality_judge` → 紫色
- `user_rating` → 绿色

---

## P2-2 A/B 测试面板

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 测试列表 | test_id + name + variant_a_prompt vs variant_b_prompt + 状态 + 样本数 |
| 2 | 结果卡片 | score_a / score_b / improvement_pct / p_value / confidence_interval / winner_variant / statistically_significant |
| 3 | 创建测试 | 选择 prompt 对的 variant_a / variant_b + 测试段落范围 + judge_criteria |

---

## P2-3 版本管理

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | Prompt 版本树 | per stage：v1→v2→v3 时间线，当前版本标记 ✓，每个节点显示版本号+创建时间 | `VersionStore.get_status()` | `VersionStoreStatus` |
| 2 | 回滚操作 | 版本节点旁的"回滚到此版本"按钮 | `POST /api/versions/{stage}/rollback` | — |
| 3 | 回滚日志 | 列表：timestamp + stage + from_version → to_version + action(promotion/rollback) + success | `VersionStore.get_rollback_history()` | `RollbackLogEntry[]` |
| 4 | Promotion Gate | 4 个仪表盘：格式合规率(≥99%) / 金数据集通过率(≥95%) / 质量分数比(≥102%) / 人工偏好(≥80%)，大字 PASS/FAIL | `PromotionGate.evaluate()` | `PromotionGateResult` |
| 5 | Canary 灰度 | 运行中的 canary：traffic_pct + samples_collected + quality_ratio + 自动回滚事件 | `CanaryRelease.get_all_canaries()` | `CanaryStatus` |

---

## P2-4 Processing Run 版本树

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 运行历史列表 | ID + status + version_tag + stages_completed(进度条) + golden_score + started_at |
| 2 | 树形展示 | parent_run_id 形成版本追溯链，树形组件展示 |
| 3 | 运行详情 | config_json 解析展示 + prompt_versions 表 + stages_completed 列表 + error_message |

---

# P3 — 导出 & 发布

## P3-1 导出中心

**路由**: `/projects/:id/export`

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|----------|----------|
| 1 | 创建导出任务 | 表单：格式选择(M4B/SRT/VTT/ALL 多选) + 章节范围(全选/指定) + BGM(文件上传) + 混音参数(MixConfig) | `POST /api/export/` | `ExportJob` |
| 2 | 进度条 | 8 状态线性进度：pending→concatenating→chaptering→subtitles→ducking→compressing→complete/failed | ExportJob.progress | `ExportProgress` |
| 3 | 错误展示 | failed 状态时展示 error 信息 + "重试"按钮 | ExportJob.error | — |
| 4 | 导出历史 | 列表：format + output_paths(下载链接) + completed_at | 导出历史 | `ExportJob[]` |

---

## P3-2 发布管理

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | Audiobookshelf 推送 | 配置服务器地址 + API Key + 测试连接 + 一键推送 |
| 2 | Podcast RSS 生成 | Feed 元数据填写(title/description/link/language/categories) + episode 列表预览 + 生成 RSS XML + 下载 |

---

# P4 — 基准测试 & 系统健康

## P4-1 基准测试

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | VoxCPM2 基准 | RTF/throughput/VRAM 雷达图，按量化模式(fp32/fp16/int8)对比 |
| 2 | 硬件适配建议 | 根据 HardwareProfile 检测结果展示推荐模式(CPU/int8_gpu/fp16_gpu) |

---

## P4-2 系统健康

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 性能趋势图 | 折线图：p50/p95 延迟趋势 + 质量分数趋势 + 日成本趋势 |
| 2 | 契约合规率 | per-stage schema compliance rate 圆环图 |
| 3 | 告警列表 | AlertRecord 列表：level(颜色) + metric_name + threshold vs current_value + triggered_at |

---

# 后端 API 缺失清单

以下端点在后端尚未实现，前端开发前需优先补充：

| 优先级 | 端点 | 用途 |
|--------|------|------|
| **P0** | `GET /api/projects/{id}/checkpoint` | 获取断点续传状态 |
| **P0** | `POST /api/projects/{id}/pipeline/start` | 启动/继续管线 |
| **P0** | `POST /api/projects/{id}/pipeline/reprocess` | 重新处理单段/单阶段 |
| **P0** | `WS /api/ws/pipeline/{project_id}` | 实时进度推送 |
| **P0** | `GET /api/projects/{id}/paragraphs/{idx}/detail` | 段落全字段详情（当前 ParagraphOut 只有 12 字段） |
| **P1** | `GET /api/llm/status` | LLM 子系统聚合状态（熔断器+成本+配额+健康+密钥池） |
| **P1** | `POST /api/llm/circuit-breaker/{name}/reset` | 手动复位熔断器 |
| **P1** | `GET /api/hardware-profile` | 当前硬件档位 |
| **P1** | `PUT /api/hardware-profile` | 切换硬件档位 |
| **P2** | `GET /api/tts/voices` | 可用 TTS 音色列表 |
| **P3** | `POST /api/export/` | 创建导出任务 |
| **P3** | `GET /api/export/{job_id}` | 查询导出进度 |

---

# 页面路由表

| 路由 | 页面 | 优先级 |
|------|------|--------|
| `/` | 项目仪表盘（列表） | P0 |
| `/projects/new` | 新建项目 | P0 |
| `/projects/:id` | 项目详情（4 Tab） | P0 |
| `/projects/:id/chapters` | 章节管线进度 | P0 |
| `/projects/:id/chapters/:chIdx` | 段落级视图 | P0 |
| `/projects/:id/audio` | 音频多轨编辑器 | P0 |
| `/projects/:id/characters` | 角色声音管理 | P0 |
| `/projects/:id/export` | 导出中心 | P3 |
| `/monitoring` | LLM 运维监控 | P1 |
| `/feedback` | 反馈记录管理 | P2 |
| `/feedback/ab-tests` | A/B 测试面板 | P2 |
| `/versions` | 版本管理 | P2 |
| `/versions/runs` | Processing Run 历史 | P2 |
| `/benchmarks` | 基准测试 | P4 |

---

# 数据契约覆盖验证

## 管线状态覆盖

| 管线阶段 | Chapter status 字段 | Paragraph status 值 | 前端展示 | ✅ 覆盖 |
|----------|---------------------|---------------------|----------|--------|
| ① extract | `extract_status` | — | 阶段节点 + 章节圆点 | ✅ |
| ② analyze | `analyze_status` | — | 同上 | ✅ |
| ③ annotate | `annotate_status` | `annotated` | 同上 + 段落状态列 | ✅ |
| ④ edit | `edit_status` | `edited` | 同上 | ✅ |
| ⑤ audio_postprocess | `route_status`(共用) | `audio_processed` | 同上 | ⚠️ 需后端分离 |
| ⑥ synthesize | `synthesize_status` | `synthesized` | 同上 | ✅ |
| ⑦ quality | `quality_status` | `quality_checked` | 同上 + 质量高亮 | ✅ |

## 实体覆盖

| 实体 | ORM 模型 | Pydantic Schema | TS 接口 | ✅ 覆盖 |
|------|----------|-----------------|---------|--------|
| Project | `models/book.py:Project` | `schemas/project.py:Project` | `§1 Project` | ✅ |
| Chapter | `models/chapter.py:Chapter` | — | `§6 Chapter` | ✅ |
| Paragraph | `models/paragraph.py:Paragraph` | `schemas/paragraph.py:Paragraph`(简单版) | `§7 Paragraph`(全字段) | ✅ |
| AudioSegment | `models/audio_segment.py:AudioSegment` | — | `§8 AudioSegment` | ✅ |
| TTSEdit | `models/tts_edit.py:TTSEdit` | `schemas/tts_edit.py:TTSEdit`(简单版) | `§9 TTSEdit`(全字段) | ✅ |
| Routing | `models/routing.py:Routing` | — | `§10 Routing` | ✅ |
| Quality | `models/quality.py:Quality` | `schemas/quality.py:QualityJudgment` | `§11 Quality` | ✅ |
| Character | `models/character.py:Character` | `schemas/book.py:CharacterVoiceBinding` | `§3 CharacterVoiceBinding` | ✅ |
| EmotionSnapshot | `models/emotion_snapshot.py` | `schemas/book.py:EmotionSnapshot` | `§4 EmotionSnapshot` | ✅ |
| FeedbackRecord | `models/feedback_record.py:FeedbackRecord` | `schemas/feedback.py:FeedbackRecord` | `§21 FeedbackRecord` | ✅ |
| ProcessingRun | `models/processing_run.py:ProcessingRun` | — | `§26 ProcessingRun` | ✅ |
| ExportJob | (无 ORM) | — | `§27 ExportJob` | ✅ |
| Checkpoint | (文件系统 JSON) | — | `§30 PipelineCheckpoint` | ✅ |

## LLM 子系统覆盖

| 子系统 | 后端类 | `get_status()` | TS 接口 | ✅ 覆盖 |
|--------|--------|---------------|---------|--------|
| CircuitBreaker | `circuit_breaker.py` | ✅ | `§13` | ✅ |
| CostTracker | `router.py` | ✅ | `§14` | ✅ |
| QuotaRegistry | `quota_registry.py` | ✅ | `§15` | ✅ |
| HealthProbe | `health_probe.py` | ✅ | `§16` | ✅ |
| KeyPoolManager | `key_pool.py` | ✅ | `§17` | ✅ |
| ProviderRateLimiter | `router.py` | ❌ 缺失 | — | ⚠️ 需后端补充 |
| KillSwitch | `kill_switch.py` | ✅ | `§19` | ✅ |
| FreeTierHealth | `router.py` 方法 | ✅ | `§18` | ✅ |
| StageConfigs | `router.py` 属性 | ✅ | `§12` | ✅ |

## 反馈闭环覆盖

| 组件 | 后端类 | TS 接口 | ✅ 覆盖 |
|------|--------|---------|--------|
| ABTest | `feedback/ab_test.py` | (简化) | ✅ |
| PatternTaxonomy | `feedback/processor.py` | 通过 FeedbackRecord.pattern_tags | ✅ |
| PromotionGate | `feedback/release.py` | `§23` | ✅ |
| CanaryRelease | `feedback/release.py` | `§24` | ✅ |
| VersionStore | `feedback/release.py` | `§25` | ✅ |
| FeedbackAnalysis | `schemas/feedback_analysis.py` | `§22` | ✅ |
| LLMJudge | `llm/judge.py` | 通过 Quality | ✅ |

---

# 已知问题 & 待决事项

| # | 问题 | 严重程度 | 建议方案 |
|---|------|----------|----------|
| 1 | Stage 命名不一致（ORM/LLM/Checkpoint 三套） | 🟡 中 | 前端统一 7 阶段枚举，API 层做映射 |
| 2 | ParagraphOut 只暴露 12 字段 | 🟡 中 | 后端新增 `ParagraphDetailOut` schema |
| 3 | 后端时间类型不统一（epoch/ISO/relative） | 🟡 中 | 后端 API 统一输出 ISO 8601 |
| 4 | LLM Router 无聚合状态端点 | 🟡 中 | 后端新增 `GET /api/llm/status` |
| 5 | 缺少 WebSocket 端点 | 🟡 中 | 后端新增 `WS /api/ws/pipeline/{id}` |
| 6 | ExportJob 无持久化 ID | 🟢 低 | 增加 ORM 或 UUID |
| 7 | `audio_postprocess` 阶段在 Chapter 无独立 status 字段 | 🟡 中 | 后端新增 `audio_postprocess_status` 或复用 `route_status` |
| 8 | `ProviderRateLimiter` 无 `get_status()` 方法 | 🟢 低 | 后端补充方法 |


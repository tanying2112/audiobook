# Audiobook Studio — 前端界面设计功能列表

> **版本**: v1.1
> **日期**: 2026-06-25
> **对应后端**: Sprint 0-H（含 6+1 管线阶段、LLM 多提供商路由、反馈闭环、多轨编辑器）
> **关联文档**: `frontend-types-contract.ts`（TypeScript 数据模型契约）
> **技术选型**: 纯 HTML + 原生 JS + Tailwind CSS (CDN) + Alpine.js | WebSocket 实时推送 | 中英双语

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

## P0 — 核心面板（MVP 必须具备）

### P0-1 项目仪表盘

**路由**: `/` 或 `/projects`

| # | 功能点 | 说明 | 后端 API | 数据契约 |
|---|--------|------|---------|---------|
| 1 | 项目卡片列表 | 展示所有项目的卡片（标题、作者、体裁、进度条、状态徽章、累计成本） | `GET /api/projects/?skip=0&limit=100` | `ProjectOut[]` |
| 2 | 搜索与筛选 | 按标题/作者搜索，按 status/difficulty/genre 筛选，按 created_at 排序 | 同上 + query params | — |
| 3 | 新建项目表单 | 弹窗 Modal：上传文件（PDF/EPUB/DOCX/TXT/图片，拖拽支持）+ 填写元信息（标题/作者/体裁/难度/语言/文风备注） | `POST /api/projects/` | `ProjectCreate` |
| 4 | 项目卡片快捷操作 | "启动管线"、"继续处理"、"删除" 三个按钮 | `POST /api/projects/{id}/pipeline/start` 等 | — |

**UI 参考**: Notion 数据库视图风格，卡片含进度条（0-100%）+ 状态徽章（draft 绿/processing 蓝/completed 金/failed 红）。

---

### P0-2 项目详情页

**路由**: `/projects/:id`

**分为 4 个 Tab**：

#### Tab 1: 上帝视角档案（BookAnalysisOutput）

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
| 1 | 书籍元信息卡 | 展示 BookMeta：标题、作者、体裁、难度、语言、时代背景、预估章节数 | Project + analyzed_json | `BookMeta` |
| 2 | 故事主线摘要 | 可编辑文本区域（story_line_summary），支持人工修正后回写 | 同上 | — |
| 3 | 全局文风备注 | 可编辑文本区域（global_style_notes） | 同上 | — |
| 4 | 角色声音绑定表 | 表格：canonical_name + aliases + gender + age_range + voice_id(下拉) + sample_quote，支持 CRUD | Character ORM | `CharacterVoiceBinding[]` |
| 5 | 章节情感曲线 | 折线图：X=章节号，Y=intensity，点颜色=dominant_emotion（10 种情感 × 10 色） | EmotionSnapshot[] | `EmotionSnapshot[]` |
| 6 | 成本总览 | 累计成本 / 每书限额 / 每章限额 / 剩余额度 | Project.total_cost_usd 等 | `Project` |

#### Tab 2: 管线进度面板（详见 P0-3）

#### Tab 3: 音频编辑器（详见 P0-5）

#### Tab 4: 导出 & 发布（详见 P3）

---

### P0-3 管线进度面板

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
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
|------|------------------|--------|
| ① extract | `extract_status` | pending/completed |
| ② analyze | `analyze_status` | pending/completed |
| ③ annotate | `annotate_status` | pending/completed |
| ④ edit | `edit_status` | pending/completed |
| ⑤ audio_postprocess | (无独立字段，含在 route_status 中) | pending/completed |
| ⑥ synthesize | `synthesize_status` | pending/completed |
| ⑦ quality | `quality_status` | pending/completed |

**Paragraph 单字段状态流转**:

```
pending → annotated → edited → audio_processed → synthesized → quality_checked
```

---

### P0-4 音频多轨编辑器

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
| 1 | 时间轴波形图 | Chapter 级：AudioSegment 按序排列在时间轴上，每段显示波形缩略图 + 引擎图标 | AudioSegment[] | `AudioSegment` |
| 2 | 片段选中高亮 | 点击某段高亮展开，下方显示详情面板 | — | — |
| 3 | 片段播放 | HTML5 `<audio>` 播放当前片段，支持上一段/下一段快速切换 | AudioSegment.file_path | — |
| 4 | 片段详情面板 | 右侧抽屉，展示：原始文本 → 编辑后文本 → 标注（speaker/emotion/intensity）→ TTS 路由（engine/voice/prosody）→ 质检 4 维评分 + issues + fix_suggestions | Paragraph._embedded | `TTSEdit` + `Routing` + `Quality` |
| 5 | 版本历史 | 当前片段的版本列表（version/parent_segment_id），可回退到旧版本 | AudioSegment.version | `AudioSegment` |
| 6 | 质量问题高亮 | `needs_regeneration=true` 的片段在时间轴上标红，hover 展示 issues 列表 | Quality.needs_regeneration | `Quality` |

**UI 参考**: Audacity 风格简化版 — 水平时间轴 + 波形色块 + 选中抽屉。

---

### P0-5 角色声音管理

**路由**: `/projects/:id/characters`（可作为项目详情 Tab 1 的子区域）

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
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

## P0-AI — AI 智能工作台（核心差异化能力）

> **设计理念**: 将 HARNESS 马具规范系统（LLM 参与全链路管理 + 自我迭代增强）从后端黑盒变为前端可见、可干预、可对话的智能工作台。用户不再是被动等待管线跑完，而是与 LLM 协作完成编辑，并将确认结果作为范本（Golden Sample）反哺马具系统，形成"越用越聪明"的闭环。

### P0-AI-1 对话式文本编辑器

**路由**: `/projects/:id/chapters/:chIdx/edit-assistant`

**核心理念**: 用户选中任一章节片段（段落/对白块），与 LLM 进行多轮对话式编辑。确认后的编辑结果作为范本，可一键应用到全书同类片段。

| # | 功能点 | 说明 | 后端数据/能力 | 数据契约 |
|---|--------|------|--------------|---------|
| 1 | **左侧原文区** | 展示章节原文，支持选中段落/对白块（行内高亮），选中即触发右侧助手面板 | Paragraph[] | `Paragraph` |
| 2 | **右侧 LLM 对话面板** | 类 ChatGPT 对话界面：用户用自然语言描述编辑意图（如"把这段对白改得更口语化"、"这个角色语气再悲伤一些"），LLM 返回修改建议 + diff 预览 | 新增 `POST /api/llm/chat-edit` 流式响应 | `ChatEditRequest` / `ChatEditResponse` |
| 3 | **多轮上下文记忆** | 对话保留同一片段的多轮上下文（同一段落可连续 refine），并注入该段落的标注上下文（speaker/emotion/difficulty）让 LLM 理解语义 | `ChatSession` + Paragraph annotation | `ChatMessage` |
| 4 | **diff 预览与三向对比** | LLM 每次修改建议展示三栏 diff：原文 vs LLM 编辑后 vs 人工微调（用户可在 LLM 结果上再次修改） | TTSEdit 历史 + 新对话 | `TtsEditOutput` |
| 5 | **编辑能力快捷指令** | 顶部快捷按钮（LLM 常见编辑动作）：数字归一化 / 长句拆分 / 口语化 / 书面化 / 删除敏感词 / 调整语速提示，一键下发对应指令 | `TtsEditOutput.changes_made` 枚举 | — |
| 6 | **难度锁可视化** | `forbid_edit=true` 的段落显示锁图标 🔒，LLM 拒绝编辑对话主体（仅允许数字/标点清理），UI 明确提示 | `Paragraph.forbid_edit`, `TtsEditInput.difficulty` | `ParagraphDifficulty` |
| 7 | **采纳/拒绝/继续** | 三按钮：✅ 采纳（写入 Paragraph.edited_text 并记入 TTSEdit 版本）/ ❌ 拒绝（记录负反馈）/ 🔄 继续对话（不落盘） | `POST /api/projects/{id}/paragraphs/{idx}/edit` | `ReprocessRequest` |
| 8 | **采纳即生成范本** | 用户采纳的编辑自动带上"范本标记"，进入待确认范本队列（见 P0-AI-3） | FeedbackRecord (source=human_edit) | `FeedbackRecord` |

**对话交互数据流**:
```
用户选段 → 右侧面板注入 Paragraph 上下文（speaker/emotion/原文）
   ↓
用户输入意图："把奶奶的台词改得更慈祥"
   ↓
POST /api/llm/chat-edit (streaming SSE)
   { paragraph_id, intent, conversation_history, annotation_context }
   ↓
LLM 返回：edited_text + changes_made + rationale + confidence
   ↓
三栏 diff 渲染 → 用户微调 → 采纳
   ↓
写入 Paragraph.edited_text + TTSEdit(version+1) + FeedbackRecord(human_edit)
   ↓
范本队列 +1（P0-AI-3 确认后反哺 Golden Dataset）
```

---

### P0-AI-2 对话式角色声音标注

**路由**: `/projects/:id/chapters/:chIdx/annotate-assistant`

**核心理念**: 用户选中段落，与 LLM 对话调整语义标注（说话人/情感/语速/停顿），确认后同样作为范本应用到全书。

| # | 功能点 | 说明 | 后端数据/能力 | 数据契约 |
|---|--------|------|--------------|---------|
| 1 | **段落标注卡片** | 选中段落后展示当前标注：speaker_canonical_name（角色下拉）+ emotion（14 选 1 色块）+ intensity（滑块）+ is_dialogue（开关）+ difficulty | ParagraphAnnotation | `ParagraphAnnotation` |
| 2 | **LLM 对话微调标注** | 用户："这段其实是张三说的，语气应该更愤怒，强度提到 0.8" → LLM 返回调整后的标注 + 置信度 + 理由 | 新增 `POST /api/llm/chat-annotate` | `ChatAnnotateResponse` |
| 3 | **角色声音绑定联动** | 标注 speaker 时自动联想 CharacterVoiceBinding 表，若为未登录角色提示"是否新增角色并绑定音色" | Character ORM | `CharacterVoiceBinding` |
| 4 | **音色试听** | 选中 voice_id 后可试听该音色朗读当前段落（Edge-TTS 优先，见策略 D） | `POST /api/tts/preview` | — |
| 5 | **声学参数可视化** | speech_rate（7 档滑块 0.7-1.3）/ pitch_shift（-5~+5 半音）/ pause_before/after（0-2000ms）/ sfx_tags（标签）实时预览 | `AudioPostProcessParams` | `AudioPostProcessParams` |
| 6 | **批量标注建议** | LLM 扫描整章未标注段落，给出批量标注建议（带 confidence），用户可逐条确认或批量接受 | `POST /api/llm/batch-annotate` | `BatchAnnotateResponse` |
| 7 | **采纳即范本** | 用户修正的标注自动入范本队列 | FeedbackRecord | `FeedbackRecord` |

---

### P0-AI-3 范本管理 & 全书应用（Golden Sample Hub）

**路由**: `/projects/:id/templates`

**核心理念**: 用户在对话编辑中确认的优质结果（编辑范本 + 标注范本）汇聚成项目级"范本库"，经确认后既可一键应用到全书同类片段，又可作为 Golden Sample 反哺 HARNESS 自我迭代系统。

| # | 功能点 | 说明 | 后端数据/能力 | 数据契约 |
|---|--------|------|--------------|---------|
| 1 | **范本队列** | 列表展示所有待确认范本：来源段落 + 类型（edit/annotate）+ 修改前→修改后 diff + LLM 分析的 pattern_tags + 置信度 | FeedbackRecord (processed=false) | `FeedbackRecord[]` |
| 2 | **范本确认/拒绝** | 确认 → 标记 `processed=true` + `promoted=true`，进入 Golden Sample 候选；拒绝 → 标记 `processed=true` 不入库 | `POST /api/feedback/{id}/confirm` | — |
| 3 | **范本模式归类** | LLM 自动归类范本的 pattern_tag（21 种），相同 pattern 的范本聚合展示，方便用户批量管理 | FeedbackRecord.pattern_tags | `PatternTag` |
| 4 | **全书应用向导** | 多步向导：①选范本 → ②选应用范围（全书/指定章节/按 pattern 匹配）→ ③预览影响范围（命中多少段落）→ ④执行（调用对应阶段管线重跑匹配段落） | 新增 `POST /api/projects/{id}/apply-template` | `TemplateApplyRequest` |
| 5 | **应用进度跟踪** | 应用过程实时显示：已处理段落 / 总匹配段落 / 当前段落 LLM 输出 diff | WebSocket 推送 | `TemplateApplyProgress` |
| 6 | **应用回滚** | 应用后若不满意，可回滚到应用前快照（基于 ProcessingRun.parent_run_id） | ProcessingRun | `ProcessingRun` |
| 7 | **Golden Sample 反哺** | 确认的范本可一键"贡献到金数据集"，经全局管理员审核后写入 `tests/golden/`，成为所有项目共享的 Few-shot 样本 | 新增 `POST /api/golden/contribute` | `GoldenContribution` |

**全书应用数据流**:
```
确认范本（pattern: emotion_too_strong）
   ↓
全书应用向导：扫描所有 paragraph，匹配同 pattern 候选段落（如 emotion_intensity > 0.9 的对白）
   ↓
预览：展示 10 条样例 diff，用户确认范围
   ↓
执行：对匹配段落批量调用 annotate/edit 阶段管线（注入范本作为 few-shot）
   ↓
WebSocket 推送逐段进度
   ↓
生成 ProcessingRun 记录（parent_run_id 指向应用前），支持回滚
```

---

### P0-AI-4 一键全自动生成（Auto Mode）

**路由**: 项目卡片"一键生成"按钮 → `/projects/:id/auto-run`

**核心理念**: 全部由 LLM 按照 HARNESS 马具规范要求全自动完成从文本到有声书的全过程，用户只需提供原始文件和少量偏好。

| # | 功能点 | 说明 | 后端数据/能力 | 数据契约 |
|---|--------|------|--------------|---------|
| 1 | **偏好配置面板** | 启动前收集用户偏好：目标难度（A/B/C/D）/ 主音色偏好（男/女/中性）/ 语速偏好（偏慢/标准/偏快）/ 成本上限 / 质量阈值（自动重合成的 needs_regeneration 触发线） | `ProjectCreate` + 新增 `AutoRunConfig` | `AutoRunConfig` |
| 2 | **全流程可视化** | 7 阶段管线以动画流水线展示：extract→analyze→annotate→edit→audio_postprocess→synthesize→quality，每阶段实时显示 LLM 调用次数/Token/成本/进度 | `run_pipeline()` + WebSocket | `PipelineWSMessage` |
| 3 | **自动质量门禁** | quality 阶段 needs_regeneration=true 的段落自动重合成（最多 N 次），UI 展示"自动修复中：第 X/Y 段，第 N 次尝试" | Quality.needs_regeneration | `Quality` |
| 4 | **中间产物可干预** | 虽是全自动，但任意阶段完成后用户可暂停查看中间产物（如 analyze 完成后查看角色表是否合理），不满意可中断跳转到 P0-AI-1 对话编辑 | pipeline stage hooks | `StageEvent` |
| 5 | **完成通知 & 产物** | 完成后通知用户，展示最终产物：M4B 下载 + SRT 字幕 + 质量报告 + 成本报告 + ProcessingRun 版本号 | ExportJob + ProcessingRun | `ExportJob` |
| 6 | **失败兜底** | 任一阶段失败（如 LLM 全部不可用）时保存断点，提示"已暂停于 [阶段]，恢复后继续"，不丢失已完成进度 | CheckpointManager | `PipelineCheckpoint` |

---

### P0-AI-5 HARNESS 自我迭代控制台（马具系统仪表盘）

**路由**: `/harness`

**核心理念**: 把后端的自我迭代闭环（feedback capture → analysis → prompt upgrade → A/B test → promotion → golden）可视化为可观察、可干预的控制台。用户能看到"系统正在变聪明"。

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
| 1 | **自我迭代状态总览** | 展示 SelfIterationLoop 状态：running / iteration_count / 上次迭代时间 / 下次预估触发（未处理反馈数/阈值） | `SelfIterationLoop.get_status()` | `SelfIterationStatus` |
| 2 | **反馈漏斗** | 漏斗图：累计反馈数 → 已分析 → 已触发升级 → 已通过 PromotionGate → 已发布。每层显示转化率 | `processor.get_trend_report()` | `FeedbackFunnel` |
| 3 | **Pattern 热力图** | 21 种 pattern_tag 的出现频率热力图（按 stage 分维度），点击查看对应反馈列表 | FeedbackRecord.pattern_tags | `PatternTag` |
| 4 | **Prompt 版本演进时间线** | 每个 stage 的版本时间线（v1→v2→v3），节点显示：版本号 + 创建时间 + 触发该升级的 top patterns + 金数据集得分 + 状态（draft/canary/promoted） | `VersionStore` + `PromptRegistry` | `VersionStoreStatus` |
| 5 | **Promotion Gate 仪表盘** | 4 硬指标实时仪表盘（格式合规率/金数据集通过率/质量分比/人工偏好），每个指标显示当前值 vs 阈值，PASS/FAIL 大字 | `PromotionGate.evaluate()` | `PromotionGateResult` |
| 6 | **Canary 灰度监控** | 活跃 canary：版本 + 流量% + 已采样数 + quality_ratio（相对基线）+ 倒计时（max_duration_hours）+ 自动回滚阈值线 | `CanaryRelease.get_all_canaries()` | `CanaryStatus` |
| 7 | **A/B 测试结果** | 每次迭代的 A/B 测试：版本 A vs B + 样本数 + 胜出方 + p_value + 显著性 + 置信区间 | `ABTestReport` | `ABTestResult` |
| 8 | **手动触发迭代** | "立即触发迭代"按钮（绕过等待阈值），触发后展示迭代进度 | `SelfIterationLoop.trigger_iteration_now()` | — |
| 9 | **回滚操作** | 任一 stage 的历史版本旁"回滚到此版本"按钮，二次确认后执行 | `VersionStore.rollback_version()` | `VersionRollbackRequest` |
| 10 | **Critics Ensemble 评审** | 三元批评网络（语义派/结构派/客观派）最新评审结果：各派 verdict/score/reasoning + 加权融合结果 + 校准 F1 | `CriticEnsemble.to_dict()` | `CriticEnsembleResult` |

---

### P0-AI-6 Golden Dataset 管理中心

**路由**: `/harness/golden`

**核心理念**: 金数据集是 HARNESS 自我迭代的基石（Few-shot 注入 + 回归测试基线），需提供可视化的贡献、审核、回归测试管理。

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
| 1 | **金样本浏览** | 按 stage 浏览现有金样本（few_shot.jsonl），展示 input + expected_output + human_verified + quality_score | `tests/golden/` | `ChapterSource` |
| 2 | **贡献审核队列** | 来自 P0-AI-3 的范本贡献在此审核：展示贡献内容 + 来源项目 + pattern_tags，管理员可批准入库/拒绝/打回修改 | GoldenContribution（待实现持久化） | `GoldenContribution` |
| 3 | **回归测试触发** | "运行回归测试"按钮，触发金数据集对当前 prompt 版本的全量回归（显示每个 case 通过/失败 + 整体通过率） | `promotion_gate.py:check_golden_dataset()` | `GoldenTestReport` |
| 4 | **通过率趋势** | 历史 regression pass_rate 趋势折线图（每次 prompt 升级后的回归得分） | 历史快照 | `GoldenTestReport[]` |
| 5 | **Bootstrap Few-shot 优化** | 触发 DSPy GEPA 优化（从现有金样本中挑选最优 few-shot 子集），展示优化前后对比 | `bootstrap_fewshot.py` | — |

---

### P0-AI-7 智能助手全局浮层

**核心理念**: 在任意页面右下角提供常驻 AI 助手浮层，可随时呼出进行上下文相关的智能问答。

| # | 功能点 | 说明 | 后端能力 |
|---|--------|------|---------|
| 1 | **上下文感知** | 助手自动感知当前页面上下文（当前项目/章节/段落/选中文本），用户提问时自动注入上下文 | 新增 `POST /api/llm/assistant` |
| 2 | **快捷问答** | "这本书的角色一致性怎么样？" / "为什么这段质检失败？" / "建议如何优化？" | LLM 读取当前 Project 上下文回答 |
| 3 | **快速跳转** | 助手可建议操作："检测到 3 段质检失败，是否跳转处理？" 点击即跳转 | — |
| 4 | **HARNESS 知识库** | 助手内置 HARNESS 规范知识，可回答"马具系统是什么"、"自我迭代如何工作"等概念问题 | 静态知识 + RAG |

---

## P0-AI 功能新增的后端 API 清单

| 优先级 | 端点 | 用途 |
|--------|------|------|
| **P0-AI** | `POST /api/llm/chat-edit` (SSE) | 对话式文本编辑，流式返回 LLM 编辑建议 |
| **P0-AI** | `POST /api/llm/chat-annotate` (SSE) | 对话式标注微调，流式返回标注调整 |
| **P0-AI** | `POST /api/llm/batch-annotate` | 整章批量标注建议 |
| **P0-AI** | `POST /api/projects/{id}/paragraphs/{idx}/edit` | 采纳编辑结果落盘（写入 Paragraph + TTSEdit） |
| **P0-AI** | `POST /api/projects/{id}/paragraphs/{idx}/annotate` | 采纳标注结果落盘 |
| **P0-AI** | `GET /api/projects/{id}/templates` | 获取项目范本队列 |
| **P0-AI** | `POST /api/projects/{id}/apply-template` | 全书应用范本（流式进度） |
| **P0-AI** | `POST /api/projects/{id}/auto-run` | 一键全自动生成 |
| **P0-AI** | `GET /api/harness/status` | HARNESS 自我迭代状态总览 |
| **P0-AI** | `POST /api/harness/trigger-iteration` | 手动触发自我迭代 |
| **P0-AI** | `GET /api/harness/critics/latest` | 最新 Critics Ensemble 评审结果 |
| **P0-AI** | `GET /api/golden/samples` | 金样本浏览 |
| **P0-AI** | `POST /api/golden/contribute` | 贡献范本到金数据集 |
| **P0-AI** | `POST /api/golden/run-regression` | 触发回归测试 |
| **P0-AI** | `POST /api/llm/assistant` | 全局智能助手问答 |

---



### P1-1 LLM 提供商总览

**路由**: `/monitoring` 或 `/llm`

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
| 1 | 免费层健康灯 | 页面顶部三色指示灯（🟢 green / 🟡 yellow / 🔴 red），下方文字说明 | `LLMRouter.get_free_tier_health()` | `FreeTierHealthReport` |
| 2 | 提供商矩阵表 | 行=provider（按 priority 排序），列=6 维状态，每格颜色编码 | 6 个子系统 `get_status()` | 见下方 |
| 3 | Kill Switch 面板 | 全局降级等级 + 各提供商明细 | `KillSwitch.get_status_report()` | `KillSwitchReport` |
| 4 | 阶段-提供商映射 | 6×20 矩阵色块图：哪些 provider 支持哪些 stage | `LLMRouter.stage_configs` | `LLMProviderConfig.stages` |

**提供商矩阵 6 维定义**:

| 维度 | 后端数据源 | 状态判断 | 颜色 |
|------|-----------|---------|------|
| ① 熔断器 | `CircuitBreaker.get_status()` | closed=绿, half_open=黄, open=红 | — |
| ② 速率限制 | `ProviderRateLimiter`（需新增 `get_status()`） | TPM/RPM 余量 > 20%=绿, 5-20%=黄, <5%=红 | — |
| ③ 成本用量 | `CostTracker.get_status()` | usage_pct < 60%=绿, 60-80%=黄, > 80%=红 | — |
| ④ 健康探针 | `HealthProbe.get_all_statuses()` | is_healthy=true=绿, latency > 5s=黄, false=红 | — |
| ⑤ 配额 | `QuotaRegistry.get_all_statuses()` | healthy=true=绿, daily_pct > 80%=黄, > 95%=红 | — |
| ⑥ 密钥池 | `KeyPoolManager.get_all_stats()` | available_keys > 0=绿, =0=红 | — |

---

### P1-2 熔断器状态面板

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 状态卡片 | 每个 provider 一张卡片：state（图标）+ failure_count / failure_threshold（进度条）+ seconds_since_last_failure |
| 2 | Recovery 倒计时 | open 状态时，显示距 recovery_timeout_s 的倒计时进度条 |
| 3 | 手动复位 | "Reset" 按钮（需后端 `POST /api/llm/circuit-breaker/{name}/reset`） |

**状态转换图**:
```
CLOSED ──(failure≥3)──► OPEN
  ▲                        │
  └──(elapsed≥120s)── HALF_OPEN
  └──(success)───────────┘
```

---

### P1-3 成本看板

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 日成本柱状图 | X=model 名，Y=daily_cost_usd，叠加 daily_limit_usd 阈值线 |
| 2 | 告警闪烁 | usage_pct > 80% 时卡片边框闪烁黄色，> 100% 闪烁红色 |
| 3 | 累计成本表 | 汇总所有 model 的总日成本、总限额、平均利用率 |

---

### P1-4 配额仪表盘

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 圆环图 | per provider：daily requests_pct + daily tokens_pct 双环，绿色<80%/黄色80-95%/红色>95% |
| 2 | Minute 维度 | 同样圆环展示 minute 级配额（更快耗尽维度） |
| 3 | 整体健康分 | 全局 0-1 健康分数字显示 + 对应颜色 |

---

### P1-5 Kill Switch 面板

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 四级指示灯 | NORMAL(绿) / PARTIAL(黄) / DEGRADED(橙) / EMERGENCY(红) 大号显示 |
| 2 | 提供商明细 | per provider：is_alive(绿/灰) + error_rate(%) + consecutive_failures + last_error |
| 3 | EMERGENCY 全屏告警 | 当 level=EMERGENCY 时，全屏红色遮罩 + 告警信息 |

---

### P1-6 硬件档位切换

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 三档选择器 | potato / cloud_hybrid / pro_studio 三个按钮，当前档位高亮 |
| 2 | 档位说明 | 选择某档时展示该档位的能力范围：可用 TTS 引擎链、LLM 路由策略、特性列表 |

---

## P2 — 反馈闭环 & 版本管理

### P2-1 反馈记录管理

**路由**: `/feedback`

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
| 1 | 反馈列表 | 表格：id(截断) + source(色标徽章) + stage + book_id + pattern_tags(标签) + timestamp，支持按 source/stage/pattern_tags 筛选 | FeedbackRecord ORM | `FeedbackRecord` |
| 2 | 三栏对比详情 | 点击展开：左栏 input_snapshot、中栏 llm_output、右栏 corrected_output，差异文本高亮（绿色新增/红色删除） | FeedbackRecord | — |
| 3 | 提交修改理由 | 人工输入 rationale 文本（≥10 字），提交到后端 | `POST /api/feedback/` | `FeedbackRecord` |
| 4 | LLM 语义分析展示 | 显示关联的 FeedbackAnalysis：pattern_tags + semantic_summary + severity + root_cause + actionable_instruction | FeedbackAnalysis | `FeedbackAnalysis` |
| 5 | Pattern 词云 | 21 种 pattern 标签的出现频率词云/气泡图，点击 tag 过滤反馈列表 | 聚合统计 | — |

**反馈来源色标**:
- `human_edit` → 蓝色
- `quality_judge` → 紫色
- `user_rating` → 绿色

---

### P2-2 A/B 测试面板

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 测试列表 | test_id + name + variant_a_prompt vs variant_b_prompt + 状态 + 样本数 |
| 2 | 结果卡片 | score_a / score_b / improvement_pct / p_value / confidence_interval / winner_variant / statistically_significant |
| 3 | 创建测试 | 选择 prompt 对的 variant_a / variant_b + 测试段落范围 + judge_criteria |

---

### P2-3 版本管理

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
| 1 | Prompt 版本树 | per stage：v1→v2→v3 时间线，当前版本标记 ✓，每个节点显示版本号+创建时间 | `VersionStore.get_status()` | `VersionStoreStatus` |
| 2 | 回滚操作 | 版本节点旁的"回滚到此版本"按钮 | `POST /api/versions/{stage}/rollback` | — |
| 3 | 回滚日志 | 列表：timestamp + stage + from_version → to_version + action(promotion/rollback) + success | `VersionStore.get_rollback_history()` | `RollbackLogEntry[]` |
| 4 | Promotion Gate | 4 个仪表盘：格式合规率(≥99%) / 金数据集通过率(≥95%) / 质量分数比(≥102%) / 人工偏好(≥80%)，大字 PASS/FAIL | `PromotionGate.evaluate()` | `PromotionGateResult` |
| 5 | Canary 灰度 | 运行中的 canary：traffic_pct + samples_collected + quality_ratio + 自动回滚事件 | `CanaryRelease.get_all_canaries()` | `CanaryStatus` |

---

### P2-4 Processing Run 版本树

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 运行历史列表 | ID + status + version_tag + stages_completed(进度条) + golden_score + started_at |
| 2 | 树形展示 | parent_run_id 形成版本追溯链，树形组件展示 |
| 3 | 运行详情 | config_json 解析展示 + prompt_versions 表 + stages_completed 列表 + error_message |

---

## P3 — 导出 & 发布

### P3-1 导出中心

**路由**: `/projects/:id/export`

| # | 功能点 | 说明 | 后端数据 | 数据契约 |
|---|--------|------|---------|---------|
| 1 | 创建导出任务 | 表单：格式选择(M4B/SRT/VTT/ALL 多选) + 章节范围(全选/指定) + BGM(文件上传) + 混音参数(MixConfig) | `POST /api/export/` | `ExportJob` |
| 2 | 进度条 | 8 状态线性进度：pending→concatenating→chaptering→subtitles→ducking→compressing→complete/failed | ExportJob.progress | `ExportProgress` |
| 3 | 错误展示 | failed 状态时展示 error 信息 + "重试"按钮 | ExportJob.error | — |
| 4 | 导出历史 | 列表：format + output_paths(下载链接) + completed_at | 导出历史 | `ExportJob[]` |

---

### P3-2 发布管理

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | Audiobookshelf 推送 | 配置服务器地址 + API Key + 测试连接 + 一键推送 |
| 2 | Podcast RSS 生成 | Feed 元数据填写(title/description/link/language/categories) + episode 列表预览 + 生成 RSS XML + 下载 |

---

## P4 — 基准测试 & 系统健康

### P4-1 基准测试

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | VoxCPM2 基准 | RTF/throughput/VRAM 雷达图，按量化模式(fp32/fp16/int8)对比 |
| 2 | 硬件适配建议 | 根据 HardwareProfile 检测结果展示推荐模式(CPU/int8_gpu/fp16_gpu) |

---

### P4-2 系统健康

| # | 功能点 | 说明 |
|---|--------|------|
| 1 | 性能趋势图 | 折线图：p50/p95 延迟趋势 + 质量分数趋势 + 日成本趋势 |
| 2 | 契约合规率 | per-stage schema compliance rate 圆环图 |
| 3 | 告警列表 | AlertRecord 列表：level(颜色) + metric_name + threshold vs current_value + triggered_at |

---

## 后端 API 缺失清单

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

## 页面路由表

| 路由 | 页面 | 优先级 |
|------|------|--------|
| `/` | 项目仪表盘（列表） | P0 |
| `/projects/new` | 新建项目 | P0 |
| `/projects/:id` | 项目详情（4 Tab） | P0 |
| `/projects/:id/chapters` | 章节管线进度 | P0 |
| `/projects/:id/chapters/:chIdx` | 段落级视图 | P0 |
| `/projects/:id/chapters/:chIdx/edit-assistant` | **AI 对话式文本编辑** | P0-AI |
| `/projects/:id/chapters/:chIdx/annotate-assistant` | **AI 对话式标注** | P0-AI |
| `/projects/:id/audio` | 音频多轨编辑器 | P0 |
| `/projects/:id/characters` | 角色声音管理 | P0 |
| `/projects/:id/templates` | **范本管理 & 全书应用** | P0-AI |
| `/projects/:id/auto-run` | **一键全自动生成** | P0-AI |
| `/projects/:id/export` | 导出中心 | P3 |
| `/harness` | **HARNESS 自我迭代控制台** | P0-AI |
| `/harness/golden` | **Golden Dataset 管理中心** | P0-AI |
| `/monitoring` | LLM 运维监控 | P1 |
| `/feedback` | 反馈记录管理 | P2 |
| `/feedback/ab-tests` | A/B 测试面板 | P2 |
| `/versions` | 版本管理 | P2 |
| `/versions/runs` | Processing Run 历史 | P2 |
| `/benchmarks` | 基准测试 | P4 |

---

## 数据契约覆盖验证

### 管线状态覆盖

| 管线阶段 | Chapter status 字段 | Paragraph status 值 | 前端展示 | ✅ 覆盖 |
|----------|-------------------|---------------------|---------|--------|
| ① extract | `extract_status` | — | 阶段节点 + 章节圆点 | ✅ |
| ② analyze | `analyze_status` | — | 同上 | ✅ |
| ③ annotate | `annotate_status` | `annotated` | 同上 + 段落状态列 | ✅ |
| ④ edit | `edit_status` | `edited` | 同上 | ✅ |
| ⑤ audio_postprocess | `route_status`(共用) | `audio_processed` | 同上 | ⚠️ 需后端分离 |
| ⑥ synthesize | `synthesize_status` | `synthesized` | 同上 | ✅ |
| ⑦ quality | `quality_status` | `quality_checked` | 同上 + 质量高亮 | ✅ |

### 实体覆盖

| 实体 | ORM 模型 | Pydantic Schema | TS 接口 | ✅ 覆盖 |
|------|---------|----------------|----------|--------|
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

### LLM 子系统覆盖

| 子系统 | 后端类 | `get_status()` | TS 接口 | ✅ 覆盖 |
|--------|-------|---------------|----------|--------|
| CircuitBreaker | `circuit_breaker.py` | ✅ | `§13` | ✅ |
| CostTracker | `router.py` | ✅ | `§14` | ✅ |
| QuotaRegistry | `quota_registry.py` | ✅ | `§15` | ✅ |
| HealthProbe | `health_probe.py` | ✅ | `§16` | ✅ |
| KeyPoolManager | `key_pool.py` | ✅ | `§17` | ✅ |
| ProviderRateLimiter | `router.py` | ❌ 缺失 | — | ⚠️ 需后端补充 |
| KillSwitch | `kill_switch.py` | ✅ | `§19` | ✅ |
| FreeTierHealth | `router.py` 方法 | ✅ | `§18` | ✅ |
| StageConfigs | `router.py` 属性 | ✅ | `§12` | ✅ |

### 反馈闭环覆盖

| 组件 | 后端类 | TS 接口 | ✅ 覆盖 |
|------|-------|----------|--------|
| ABTest | `feedback/ab_test.py` | (简化) | ✅ |
| PatternTaxonomy | `feedback/processor.py` | 通过 FeedbackRecord.pattern_tags | ✅ |
| PromotionGate | `feedback/release.py` | `§23` | ✅ |
| CanaryRelease | `feedback/release.py` | `§24` | ✅ |
| VersionStore | `feedback/release.py` | `§25` | ✅ |
| FeedbackAnalysis | `schemas/feedback_analysis.py` | `§22` | ✅ |
| LLMJudge | `llm/judge.py` | 通过 Quality | ✅ |

---

## 已知问题 & 待决事项

| # | 问题 | 严重程度 | 建议方案 | 落地策略 |
|---|------|---------|---------|---------|
| 1 | Stage 命名不一致（ORM/LLM/Checkpoint 三套） | 🟡 中 | 前端统一 7 阶段枚举，API 层做映射 | **数据清洗层 `normalizeChapterPipeline()` 纯函数**（见下方策略 A） |
| 2 | ParagraphOut 只暴露 12 字段 | 🟡 中 | 后端新增 `ParagraphDetailOut` schema | **Mock JSON 契约先行**（见下方策略 B） |
| 3 | 后端时间类型不统一（epoch/ISO/relative） | 🟡 中 | 后端 API 统一输出 ISO 8601 | **`normalizeTimestamp()` 纯函数**统一清洗 |
| 4 | LLM Router 无聚合状态端点 | 🟡 中 | 后端新增 `GET /api/llm/status` | **Mock 聚合数据先行** |
| 5 | 缺少 WebSocket 端点 | 🟡 中 | 后端新增 `WS /api/ws/pipeline/{id}` | **EventSource 降级轮询兜底** |
| 6 | ExportJob 无持久化 ID | 🟢 低 | 增加 ORM 或 UUID | 前端生成 UUID 作为临时 job_id |
| 7 | `audio_postprocess` 阶段在 Chapter 无独立 status 字段 | 🟡 中 | 后端新增 `audio_postprocess_status` 或复用 `route_status` | **`normalizeChapterPipeline()` 内推断** |
| 8 | `ProviderRateLimiter` 无 `get_status()` 方法 | 🟢 低 | 后端补充方法 | Mock 数据填充 |

---

## 工程落地策略（v1.1 新增）

> 以下策略确保前端在 12 个后端 API 端点尚未就绪的情况下即可独立开发。

### 策略 A：数据清洗层 — `normalizeChapterPipeline()`

**核心思想**: 后端"脏状态"在进入 UI 之前全部洗净，UI 组件只接触标准化数据。

```javascript
// static/js/normalize.js — 数据清洗纯函数库

/**
 * 将后端 Chapter 的多套 stage status 字段清洗为前端统一 7 阶段枚举。
 * 决不污染 UI 组件 — 组件只处理 { stage, status: 'pending'|'running'|'completed'|'failed' }
 */
function normalizeChapterPipeline(chapter) {
  const mapping = {
    extract:    chapter.extract_status,
    analyze:    chapter.analyze_status,
    annotate:   chapter.annotate_status,
    edit:       chapter.edit_status,
    audio_postprocess: inferAudioPostprocessStatus(chapter),  // 策略：从 route_status 推断
    synthesize: chapter.synthesize_status,
    quality:    chapter.quality_status,
  };
  return PIPELINE_STAGE_ORDER.map(stage => ({
    stage,
    status: mapping[stage] || 'pending',
  }));
}

/**
 * audio_postprocess 无独立 status 字段（已知问题 #7）。
 * 推断规则：若 route_status=completed 且 edit_status=completed → audio_postprocess=completed
 */
function inferAudioPostprocessStatus(chapter) {
  if (chapter.route_status === 'completed' && chapter.edit_status === 'completed') {
    return 'completed';
  }
  if (chapter.route_status === 'running' || chapter.edit_status === 'running') {
    return 'running';
  }
  return chapter.route_status || 'pending';
}

/**
 * 统一清洗后端时间字段为 ISO 8601。
 * 处理三种情况：epoch seconds (number)、ISO string (string)、relative seconds (number)。
 */
function normalizeTimestamp(raw) {
  if (typeof raw === 'string') return raw;              // 已是 ISO 字符串
  if (typeof raw === 'number') {
    if (raw > 1e12) return new Date(raw).toISOString(); // epoch ms
    if (raw > 1e9) return new Date(raw * 1000).toISOString(); // epoch s
    return null;                                         // relative seconds，无绝对时间
  }
  return null;
}
```

**禁止 UI 组件中出现**:
```javascript
// ❌ 绝对禁止：让组件处理脏状态
if (status === 'route_status' || stage === 'audio_processed')

// ✅ 正确：组件只消费清洗后的标准数据
pipelineStages.forEach(({ stage, status }) => {
  renderStageDot(stage, status); // status 必为 'pending'|'running'|'completed'|'failed'
});
```

### 策略 B：Mock Service Worker 替代方案 — 契约优先的静态 Mock

由于我们选择了**纯 HTML + 原生 JS**（无构建工具链），无法使用 MSW（需要 Service Worker + ES Module 拦截）。替代方案：

**采用 FastAPI 自身提供 Mock 端点**（`/api/mock/...`），利用 TypeScript 契约中的接口定义生成静态 JSON：

```
static/mock/
├── projects.json              # Project[]
├── project-1.json             # Project (含 _embedded)
├── project-1-chapters.json    # Chapter[]
├── project-1-ch1-paragraphs.json  # Paragraph[] (全字段)
├── project-1-checkpoint.json  # PipelineCheckpoint
├── llm-status.json            # LLMStatusAggregate
├── feedback-records.json      # FeedbackRecord[]
├── export-jobs.json           # ExportJob[]
└── versions.json              # VersionStoreStatus
```

**实现方式**: 新增一个 FastAPI Mock Router（仅开发环境启用），路径为 `/api/mock/*`，返回 `static/mock/` 下的 JSON 文件。前端在开发阶段请求 `/api/mock/` 路径，后端就绪后一键切换为 `/api/` 路径。

```python
# src/audiobook_studio/api/mock_router.py
from fastapi import APIRouter
from pathlib import Path

router = APIRouter(prefix="/mock", tags=["mock"])

MOCK_DIR = Path("static/mock")

@router.get("/projects")
async def mock_projects():
    return json.loads((MOCK_DIR / "projects.json").read_text())

# ... 其他 mock 端点
```

### 策略 C：WebSocket 降级兜底

后端 WebSocket 端点就绪前，前端采用**双模式连接**：

```javascript
// static/js/ws.js

function connectPipelineWS(projectId) {
  // 优先尝试 WebSocket
  const ws = new WebSocket(`ws://${location.host}/api/ws/pipeline/${projectId}`);

  ws.addEventListener('open', () => {
    console.log('[WS] connected, using real-time push');
    startKeepAlive(ws);
  });

  ws.addEventListener('message', (event) => {
    const data = JSON.parse(event.data);
    handlePipelineEvent(data);
  });

  ws.addEventListener('close', () => {
    console.warn('[WS] closed, falling back to polling');
    startPollingFallback(projectId);
  });

  return ws;
}

function startPollingFallback(projectId) {
  // 每 3 秒轮询项目状态，模拟事件推送
  return setInterval(async () => {
    const project = await fetch(`/api/projects/${projectId}`).then(r => r.json());
    if (project.status === 'completed') {
      clearInterval(pollingId);
    }
  }, 3000);
}
```

### 策略 D：优先打通 Edge-TTS 轻量链路

在 P0-5 角色声音管理和 P0-3 管线联调阶段，**优先使用 Edge-TTS**：
- ✅ 免鉴权、零配置、低延迟
- ✅ 支持 15 个中文音色 + 3 个英文音色
- ✅ 验证多轨拼接逻辑无需任何 Token 成本
- ✅ 前端试听按钮可直接调用 Edge-TTS 的短文本合成

**建议后端新增**: `POST /api/tts/preview` — 接收 `text` + `voice_id` + `engine`，返回合成的音频片段 URL（仅限 < 100 字的试听场景）。

### 策略 E：多轨编辑器性能方案

纯 HTML 环境下，波形渲染方案：

| 方案 | 技术 | 适用场景 |
|------|------|---------|
| **WaveSurfer.js** (CDN) | Canvas 渲染，支持虚拟化 | 章节级 50-200 片段 |
| Peaks.js | 简化版波形 | 段落级预览 |
| 自绘 Canvas | 最小依赖，灵活控制 | 时间轴概览 |

推荐：**WaveSurfer.js v7** (ESM CDN)，天然支持 Alpine.js 集成，体积 < 50KB gzip。配合 `IntersectionObserver` 做可见区域加载，避免一次性渲染所有波形。

### 策略 F：国际化实现

中英双语在纯 HTML 环境下的实现：

```html
<!-- i18n 通过 data-i18n 属性 + Alpine.js x-data 驱动 -->
<body x-data="i18nApp()" :lang="$store.locale">

  <h1 data-i18n="dashboard.title">项目仪表盘</h1>
  <span data-i18n="stage.extract">文本提取</span>
  <span data-i18n="emotion.happy" :data-i18n-code="'happy'">开心</span>

</body>
```

```javascript
// static/js/i18n.js
const I18N = {
  zh: {
    'dashboard.title': '项目仪表盘',
    'stage.extract': '文本提取',
    'stage.analyze': '结构分析',
    'emotion.happy': '开心',
    'emotion.sad': '悲伤',
    'status.pending': '待处理',
    // ... 全量映射
  },
  en: {
    'dashboard.title': 'Project Dashboard',
    'stage.extract': 'Text Extraction',
    'stage.analyze': 'Structure Analysis',
    'emotion.happy': 'Happy',
    'emotion.sad': 'Sad',
    'status.pending': 'Pending',
  },
};

function i18nApp() {
  return {
    locale: localStorage.getItem('locale') || 'zh',
    t(key) {
      return I18N[this.locale]?.[key] || I18N.zh[key] || key;
    },
    toggleLocale() {
      this.locale = this.locale === 'zh' ? 'en' : 'zh';
      localStorage.setItem('locale', this.locale);
      document.documentElement.lang = this.locale;
    },
  };
}
```

### 前端文件结构规划

```
static/
├── index.html                    # SPA 入口（路由由 Alpine.js hash router 驱动）
├── css/
│   └── app.css                   # Tailwind 补充样式
├── js/
│   ├── app.js                    # Alpine.js 应用入口 + 路由
│   ├── normalize.js              # 数据清洗纯函数（策略 A 核心）
│   ├── api.js                    # API 请求层（自动切换 mock/real）
│   ├── ws.js                     # WebSocket + 轮询降级（策略 C）
│   ├── sse.js                    # SSE 流式响应处理（LLM 对话/P0-AI）
│   ├── i18n.js                   # 国际化字典 + Alpine 指令（策略 F）
│   ├── store.js                  # 全局状态（Alpine store）
│   └── components/
│       ├── project-card.js       # 项目卡片组件
│       ├── pipeline-stages.js    # 管线阶段可视化
│       ├── chapter-grid.js       # 章节网格
│       ├── paragraph-table.js    # 段落表格
│       ├── audio-editor.js       # 多轨编辑器（WaveSurfer.js）
│       ├── quality-radar.js      # 质量雷达图
│       ├── provider-matrix.js    # LLM 提供商矩阵
│       ├── emotion-chart.js      # 情感曲线图
│       ├── feedback-diff.js      # 三栏对比
│       ├── export-progress.js    # 导出进度条
│       ├── chat-edit-panel.js    # AI 对话编辑面板（P0-AI-1）
│       ├── chat-annotate-panel.js # AI 对话标注面板（P0-AI-2）
│       ├── template-hub.js       # 范本管理 & 全书应用（P0-AI-3）
│       ├── auto-run-wizard.js    # 一键全自动向导（P0-AI-4）
│       ├── harness-console.js    # HARNESS 自我迭代控制台（P0-AI-5）
│       ├── golden-manager.js     # Golden Dataset 管理（P0-AI-6）
│       ├── assistant-fab.js      # 全局智能助手浮层（P0-AI-7）
│       └── markdown-diff.js      # Markdown diff 渲染（被多处复用）
├── mock/
│   ├── projects.json             # Mock 数据（策略 B）
│   ├── ...
│   └── llm-status.json
└── img/
    └── icons/                    # SVG 图标
```

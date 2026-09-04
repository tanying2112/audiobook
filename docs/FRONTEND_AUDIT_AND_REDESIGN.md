# 前端全面评估与 UI 重规划设计（2026-09-04）

## 一、评估方法与范围

- 后端 API 面：openapi.json 160 端点 + 36 个路由模块（含本轮新增的 /api/tts/preview/{voice_id}.mp3、/api/publish/{job_id}/status）
- 前端实现面：24 个 views、21 条路由、api/index.ts 59 个导出函数、4 个 store、8 个 composable
- 方法：端点↔页面双向映射、视图源码级核查（import/调用链）、导航结构分析

## 二、总体结论

| 维度 | 评级 | 结论 |
|------|------|------|
| 核心生产链路覆盖 | ⭐⭐⭐⭐☆ | 项目/上传/角色/段落/合成/质量/导出/发布/翻译/克隆 主链路均有页面 |
| 自我进化功能暴露 | ⭐⭐☆☆☆ | Harness 仪表盘在，但 SOP 规则库、金标数据、A/B 晋升工作流无专门 UI |
| 管理/治理能力 | ⭐⭐☆☆☆ | RBAC 用户角色、审计、批量运营端点完全无界面 |
| 代码健康 | ⭐⭐⭐☆☆ | FeedbackEditor 绕过统一 api 客户端裸用 axios；views 体积过大（AgentChat 1355 行） |
| 信息架构 | ⭐⭐⭐☆☆ | 侧边栏 7 项扁平，项目内功能入口藏深，工作台/全局功能混排 |

## 三、后端功能 → 前端覆盖矩阵

### ✅ 已覆盖（主链路完整）

| 后端域 | 端点数 | 前端落点 |
|--------|--------|----------|
| 项目/章节/段落 CRUD | ~15 | Projects / ProjectManagement / ProjectDetail / ChapterTimeline |
| 上传（含分片） | 5 | UploadView |
| 角色与音色绑定 | 4 | CharacterManager |
| TTS 试听/克隆/推荐 | 6 | VoiceCloneView（preview 已含本轮新端点） |
| AutoRun 流水线控制 | 8 | AutoRunView + usePipelineProgress(WS) |
| 质量报告 | 2 | QualityReport |
| 导出（M4B/MP3/母带） | 4 | ExportView |
| 发布（含任务状态机） | 5 | PublishView（含 /api/publish/{job_id}/status 轮询） |
| 翻译配音 | 3 | TranslationView |
| 监控遥测 | 4 | MonitoringDashboard |
| Provider 管理 | 5 | ProviderManager |
| 模型市场 | 2 | ModelMarket |
| Agent 对话 | 5 | AgentChatView（WS 优先 + HTTP 降级） |
| Harness 只读看板 | 10 | HarnessDashboard |

### ⚠️ 部分覆盖（有端点但 UI 薄弱/绕行）

| 后端能力 | 现状 | 缺口 |
|----------|------|------|
| 用户反馈 /feedback | FeedbackEditor 裸 axios 调用 | 未走统一 api 客户端（无 token 刷新/错误码统一），且无反馈统计页（/feedback/stats/summary 未用） |
| SOP 自我迭代 | 仅 useSopCorrection 局部使用 | /sop/genres、/sop/config/snapshot、/sop/reflect、/sop/background/* 无管理界面 |
| 金标数据集 | 后端 7 端点 | 无金标样本浏览/审批/贡献 UI（approve/reject/contribute 均不可达） |
| Harness 干预 | trigger-iteration/rollback 有 api 函数 | 无晋升审批工作流界面（Promotion Gate 决定需人工确认但无确认入口页） |
| 音频片段精修 | /audio-segments trim/merge/reorder | 仅 VideoCanvasView 只读消费，无 trim/merge/reorder 编辑控件 |
| 书籍库 /books | 5 端点 | 无独立书籍管理页（被项目页吸收但搜索/筛选弱） |
| Agent 知识库 | /agent/knowledge | 无知识库管理界面 |
| 流水线手动控制 | /pipeline/run-stage | AutoRunView 只支持 autopilot，无单阶段手动触发+中间产物查看（/auto-run/intermediate/{stage} 未用） |

### ❌ 完全无 UI（纯后端能力）

| 后端能力 | 端点 | 影响 |
|----------|------|------|
| RBAC 用户/角色/权限管理 | /api/auth/users、roles、permissions 等 11 个 | 超管无法通过界面管理用户与权限 |
| 配置热更新 | /config/reload-all、rules/thresholds update 6 个 | 阈值/规则调整必须改文件重启 |
| TTS 编辑历史 | /tts_edits CRUD 5 个 | 编辑历史不可追溯 |
| 质量记录 CRUD | /qualities 5 个 | 仅报告页展示聚合 |
| 路由决策记录 | /routings 5 个 | 无决策审计视图 |
| 协作功能 | collab 模块 | 团队批注/协作无界面 |
| 管理操作 | /admin/*（warmup 等） | 无运维操作页 |

## 四、UI/UX 问题清单

1. **导航扁平混乱**：侧边栏把"项目工作区（/projects/:id/*）"与"全局功能（/harness、/monitoring、/providers）"平铺；项目上下文切换靠隐式 contextStore
2. **入口断层**：项目详情页 → 角色/翻译/克隆/自动跑/导出/发布 的跳转入口分散且不一致；ChapterTimeline 是核心生产页但导航权重低
3. **超大组件**：AgentChatView 1355 行、VideoCanvasView 1276 行、AutoRunView 829 行，逻辑与视图未拆分
4. **反馈闭环断点**：用户在 ChapterTimeline 纠正 → SOP 学习 → 晋升门禁，全程无"我的纠正产生了什么影响"的可视化
5. **空态/加载态**：多数页面缺少骨架屏与空态引导（首次使用无项目时无引导流程）
6. **SseDemo.vue 为开发残留**（553 行演示页混入生产路由候选）

## 五、重规划设计方案

### 5.1 信息架构（IA）重构

```
├── 工作台（/）                    — 全局概览：项目卡片、最近活动、系统健康摘要
├── 项目空间 /projects/:id         — 进入后切换为项目内导航（左侧二级菜单）
│   ├── 概览 Overview              — 进度环 + 各阶段状态 + 快捷操作
│   ├── 内容 Content               — 章节时间线（吸收 ChapterTimeline 为默认主页）
│   ├── 角色 Voices                — 角色管理 + 音色绑定 + 克隆 + 试听（合并 Character/VoiceClone）
│   ├── 生产 Studio                — 合成控制 + 段落编辑 + 音频精修（trim/merge/reorder）
│   ├── 质量 Quality               — 质量报告 + 逐段落质量 + 重新合成入口
│   ├── 翻译 Translate             — 多语言配音（现有 TranslationView 增强）
│   ├── 导出与发布 Publish         — 导出格式 + 发布任务 + RSS（合并 Export/Publish）
│   └── 运行 Runs                  — AutoRun 控制 + 单阶段手动运行 + 中间产物查看
├── 进化中心 /evolution            — 【新】自我迭代专属域
│   ├── 总览 Dashboard             — 现 HarnessDashboard 迁移
│   ├── SOP 规则库                 — 按体裁查看/编辑/回滚 SOP 规则（/sop/*）
│   ├── 金标数据 Golden            — 样本浏览/审批/贡献/回归测试（/golden/*）
│   ├── 晋升流水线 Promotions      — A/B 测试 + Canary + 晋升审批工作流
│   └── 反馈洞察 Feedback          — 纠正统计 + 反馈漏斗 + 模式热力图
├── 资源中心                       — Providers / 模型市场 / 声音库
├── 监控 /monitoring               — 现有增强
└── 系统管理 /admin                — 【新】用户/角色/权限 + 系统配置 + 运维操作
```

### 5.2 新页面清单（按优先级）

| 优先级 | 页面 | 对接端点 | 价值 |
|--------|------|----------|------|
| P0 | 项目概览 Overview | 聚合 status/quality/progress | 生产主入口，替代当前多层跳转 |
| P0 | 晋升审批 Promotions | /harness/promotion-gate + rollback + trigger-iteration | 自我迭代的"人在环路"落点 |
| P0 | 金标数据 Golden | /golden/* 7 端点 | C1 燃料库可视化 |
| P1 | SOP 规则库 | /sop/genres + rules + reflect + background | 学习成果可见可控 |
| P1 | 音频精修器 | /audio-segments trim/merge/reorder | WaveSurfer 已有基建 |
| P1 | 用户权限管理 | /api/auth/users/roles | 生产部署必需 |
| P2 | 反馈洞察 | /feedback/stats/summary + funnel | 用户贡献成就感 |
| P2 | 系统配置 | /config/* 热更新 | 运维免重启 |
| P2 | 运行记录 Runs 详情 | /auto-run/intermediate/{stage} | 调试与审计 |
| P3 | 知识库管理 | /agent/knowledge | Agent 增强 |

### 5.3 工程整改

1. **统一数据层**：FeedbackEditor 等所有裸 axios 调用迁入 api/index.ts；新增 7 个域模块文件（api/golden.ts、api/sop.ts、api/admin.ts、api/audioSegments.ts 等），api/index.ts 只做聚合 re-export（治理 M2 后遗症）
2. **组件拆分**：AgentChatView/VideoCanvasView/AutoRunView 拆分为 view + composable + 子组件（目标单文件 ≤400 行）
3. **布局系统**：新增 ProjectLayout（项目内二级导航 + 面包屑 + 项目切换器）与 AdminLayout；移除 SseDemo 或移至 dev-only
4. **状态引导**：全局空态组件 + 首次使用引导（无项目 → 创建向导 → 上传 → Autopilot 一键）
5. **i18n 补全**：新页面全部走 i18n（zh-CN/en-US 双语言包同步扩充）
6. **路由守卫**：admin 域按角色（superuser）守卫；项目域按 projectId 校验权限

### 5.4 视觉/交互规范

- 沿用 Element Plus + 现有主题切换；新增设计令牌文档（间距/字号/色阶）
- 生产页面统一"三段式"：顶部上下文条（项目/章节/阶段）→ 中部工作区 → 底部状态栏（WS 连接/任务进度）
- 所有长任务统一走 usePipelineProgress 的 WS 进度协议 + 断线轮询降级

### 5.5 验收标准

| 项 | 标准 |
|----|------|
| 覆盖度 | openapi 端点前端触达率 ≥ 85%（不含 /mock/* 与纯健康检查） |
| 数据层 | 全前端 0 处裸 axios/fetch（统一 api 客户端） |
| 组件体积 | 单 view 文件 ≤ 400 行 |
| 构建 | npm run build 无 >500KB chunk；vue-tsc 0 error |
| 测试 | 新页面各有 ≥1 个 vitest 组件测试；i18n key 双语言齐全 |
| e2e | 关键路径（创建→上传→autopilot→导出）playwright 冒烟通过 |
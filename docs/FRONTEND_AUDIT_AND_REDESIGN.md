# 前端全面评估与 UI 重规划设计（2026-09-04；状态更新 2026-09-06）

> 本文档是前端重构的规划/设计文档，同时作为实施跟踪看板。
> 最近一次状态核验：2026-09-06，以 `web/src` 当前代码为准。

## 一、评估方法与范围

- 后端 API 面：openapi.json 160 端点 + 36 个路由模块（含 /api/tts/preview/{voice_id}.mp3、/api/publish/{job_id}/status）
- 前端实现面：28 个 views、28 条路由、10 个 api 模块共 110 个导出函数、4 个 store、8 个 composable
- 方法：端点↔页面双向映射、视图源码级核查（import/调用链）、导航结构分析

## 二、总体结论与当前进度

| 维度 | 评级 | 结论 |
|------|------|------|
| 核心生产链路覆盖 | ⭐⭐⭐⭐☆ | 项目/上传/角色/段落/合成/质量/导出/发布/翻译/克隆 主链路均有页面 |
| 自我进化功能暴露 | ⭐⭐⭐☆☆ | Promotions / Golden / SOP 已上线；反馈洞察、晋升审批的人工确认入口已具备基础版 |
| 管理/治理能力 | ⭐⭐⭐☆☆ | AdminView 已提供用户/角色/配置重载；权限细粒度、审计、批量运营仍无界面 |
| 代码健康 | ⭐⭐⭐☆☆ | FeedbackEditor 与 MonitoringDashboard 均已走统一 api 客户端；超大组件仍在 |
| 信息架构 | ⭐⭐⭐☆☆ | ProjectTabs 已落地项目内二级导航；全局侧边栏仍扁平，进化/管理入口已并入 |

### 本轮已落地（相对 2026-09-04 版）

| 类别 | 落地内容 |
|------|----------|
| 新页面 | ProjectOverviewView、PromotionsView、GoldenDataView、SopRulesView、AdminView、AudioSegmentEditor、FeedbackInsightsView |
| 布局 | ProjectTabs 项目内二级导航（10 个子页）+ 项目切换器/面包屑；App.vue 按项目子路由渲染 |
| 路由 | /evolution/promotions、/evolution/golden、/evolution/sop、/evolution/feedback、/admin、/projects/:id/overview、/projects/:id/audio-segments |
| API 模块 | api/admin.ts、api/sop.ts、api/golden.ts、api/audioSegments.ts；FeedbackEditor 已迁入统一 api 客户端 |
| 清理 | 删除开发残留 SseDemo.vue |
| 数据层 | MonitoringDashboard 裸 axios 已迁入 api/index.ts（fetchProjectsWithMetrics / fetchProjectMetrics） |
| 路由守卫 | /admin 已按 requiresSuperuser 角色守卫（未登录/非超管跳转） |
| 状态引导 | 新增 EmptyState 全局空态组件，并用于 Projects 空列表（含新建项目引导） |

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
| 监控遥测 | 4 | MonitoringDashboard（已走统一 api 客户端） |
| Provider 管理 | 5 | ProviderManager |
| 模型市场 | 2 | ModelMarket |
| Agent 对话 | 5 | AgentChatView（WS 优先 + HTTP 降级） |
| Harness 只读看板 | 10 | HarnessDashboard |
| 金标数据集 | 7 | GoldenDataView（浏览/审批/贡献/回归） |
| SOP 自我迭代 | 8 | SopRulesView（体裁规则/反思/后台开关） |
| 晋升审批/回滚 | 3 | PromotionsView（gate/canary/A-B/trigger/rollback） |
| 音频片段精修 | 3 | AudioSegmentEditor（trim/merge/reorder/delete） |
| RBAC 用户/角色（基础） | 7 | AdminView（用户/角色分配/启用禁用/配置重载） |

### ⚠️ 部分覆盖（有端点但 UI 薄弱/绕行）

| 后端能力 | 现状 | 缺口 |
|----------|------|------|
| 用户反馈 /feedback | FeedbackEditor 已走统一 api 客户端 | 无反馈统计页（/feedback/stats/summary 未用）；反馈→SOP→晋升闭环可视化仍缺 |
| 反馈洞察 | FeedbackInsightsView（反馈漏斗/模式热力图，基于 /harness/* 聚合） | /feedback/stats/summary 独立统计接口未用；反馈→SOP→晋升闭环仍待端到端打通 |
| SOP 配置快照/规则导入 | SopRulesView 覆盖规则查看与反思 | /sop/config/snapshot、/sop/import/apply-rules 有 api 函数但无独立管理 UI |
| Harness 干预 | PromotionsView 覆盖 trigger/rollback | 晋升审批的人工确认入口仍需和门禁决策联动成工作流 |
| 书籍库 /books | 5 端点 | 无独立书籍管理页（被项目页吸收但搜索/筛选弱） |
| Agent 知识库 | /agent/knowledge | 无知识库管理界面 |
| 流水线手动控制 | /pipeline/run-stage | AutoRunView 只支持 autopilot，无单阶段手动触发+中间产物查看（/auto-run/intermediate/{stage} 未用） |
| 配置热更新 | AdminView 覆盖 reload-all/status | /config/* thresholds/rules update 端点无专项维护界面 |

### ❌ 完全无 UI（纯后端能力）

| 后端能力 | 端点 | 影响 |
|----------|------|------|
| RBAC 权限细粒度 | /api/auth/permissions 等 4 个 | 无法在界面管理权限集合与路由/菜单授权 |
| TTS 编辑历史 | /tts_edits CRUD 5 个 | 编辑历史不可追溯 |
| 质量记录 CRUD | /qualities 5 个 | 仅报告页展示聚合 |
| 路由决策记录 | /routings 5 个 | 无决策审计视图 |
| 协作功能 | collab 模块 | 团队批注/协作无界面 |
| 管理操作 | /admin/*（warmup 等） | 无运维操作页 |
| 运行记录 Runs 详情 | /auto-run/intermediate/{stage} | 无中间产物查看与单阶段调试 UI |

## 四、UI/UX 问题清单（含状态）

1. **导航扁平混乱**（🔶 部分解决）：侧边栏已并入进化中心（promotions/golden/sop）与 admin；项目内已新增 ProjectTabs 二级导航。但全局功能仍与项目功能在侧边栏平铺，未做完整 ProjectLayout/AdminLayout 分离。
2. **入口断层**（✅ 已改善）：ProjectTabs 覆盖 overview/characters/quality/translation/voice-clone/auto-run/dashboard/audio-segments/export/publish 10 个子页；ProjectOverviewView 提供快捷入口。
3. **超大组件**（❌ 未解决）：AgentChatView 1355 行、VideoCanvasView 1276 行、AutoRunView 829 行，逻辑与视图未拆分，目标单文件 ≤400 行仍未达标。
4. **反馈闭环断点**（🔶 部分解决）：Golden/SOP/Promotions 已形成学习/晋升可视化；但“我的纠正产生了什么影响”的反馈统计与漏斗未实现。
5. **空态/加载态**（🔶 部分解决）：新增 EmptyState 组件并在项目列表空态使用（含“新建项目”引导）；多数页面骨架屏与首次使用向导仍待铺开。
6. **SseDemo.vue 为开发残留**（✅ 已删除）：已移除。

## 五、重规划设计方案

### 5.1 信息架构（IA）重构与现状对照

```
├── 工作台（/）                    — 全局概览：项目卡片、最近活动、系统健康摘要（现有 Projects/ProjectManagement）
├── 项目空间 /projects/:id         — ProjectTabs 二级导航已落地
│   ├── 概览 Overview              — ProjectOverviewView ✅
│   ├── 内容 Content               — ChapterTimeline（已默认 overview 导航含章节）
│   ├── 角色 Voices                — CharacterManager / VoiceCloneView ✅
│   ├── 生产 Studio                — Dashboard / VideoCanvas / AudioSegmentEditor（音频精修 ✅）
│   ├── 质量 Quality               — QualityReport ✅
│   ├── 翻译 Translate             — TranslationView ✅
│   ├── 导出与发布 Publish         — ExportView / PublishView ✅
│   └── 运行 Runs                  — AutoRunView ✅；中间产物查看 ⏳
├── 进化中心 /evolution            — ✅ 路由已建
│   ├── 总览 Dashboard             — HarnessDashboard
│   ├── SOP 规则库                 — SopRulesView ✅
│   ├── 金标数据 Golden            — GoldenDataView ✅
│   ├── 晋升流水线 Promotions      — PromotionsView ✅
│   └── 反馈洞察 Feedback          — ✅ FeedbackInsightsView
├── 资源中心                       — Providers / 模型市场 / 声音库
├── 监控 /monitoring               — MonitoringDashboard（待统一 api）
└── 系统管理 /admin                — AdminView ✅（用户/角色/配置重载；权限细粒度 ⏳）
```

### 5.2 新页面清单（含实施状态）

| 优先级 | 页面 | 对接端点 | 状态 |
|--------|------|----------|------|
| P0 | 项目概览 Overview | 聚合 status/quality/progress | ✅ ProjectOverviewView |
| P0 | 晋升审批 Promotions | /harness/promotion-gate + rollback + trigger-iteration | ✅ PromotionsView |
| P0 | 金标数据 Golden | /golden/* 7 端点 | ✅ GoldenDataView |
| P1 | SOP 规则库 | /sop/genres + rules + reflect + background | ✅ SopRulesView |
| P1 | 音频精修器 | /audio-segments trim/merge/reorder | ✅ AudioSegmentEditor |
| P1 | 用户权限管理 | /api/auth/users/roles | 🔶 AdminView（基础版已落地；permissions 细粒度 ⏳） |
| P2 | 反馈洞察 | /harness/feedback-funnel + pattern-heatmap | ✅ FeedbackInsightsView（基于 Harness 聚合数据） |
| P2 | 系统配置 | /config/* 热更新 | 🔶 AdminView 覆盖 reload-all；thresholds/rules 维护 ⏳ |
| P2 | 运行记录 Runs 详情 | /auto-run/intermediate/{stage} | ⏳ |
| P3 | 知识库管理 | /agent/knowledge | ⏳ |

### 5.3 工程整改（含状态）

1. **统一数据层**（✅）：FeedbackEditor 已迁入统一 api；新增 api/golden.ts、api/sop.ts、api/admin.ts、api/audioSegments.ts；MonitoringDashboard 已改用 fetchProjectsWithMetrics / fetchProjectMetrics。全前端 0 处裸 axios/fetch。
2. **组件拆分**（❌）：AgentChatView/VideoCanvasView/AutoRunView 仍超 400 行，未拆分。
3. **布局系统**（🔶）：ProjectTabs 已实现项目内二级导航 + 项目切换器/面包屑；ProjectLayout/AdminLayout 正式组件仍未抽象。
4. **状态引导**（🔶）：EmptyState 全局空态组件已落地，并在项目列表使用；首次使用向导（创建→上传→Autopilot 一键）仍未做。
5. **i18n 补全**（✅/🔶）：新页面已具备 zh-CN/en-US 双语（admin/promotions/golden/sop/overview/segments）；仍有历史页面 key 未完全对齐（由 localeParity 测试兜底）。
6. **路由守卫**（✅）：已有登录守卫；admin 域角色守卫（superuser）已实现。

### 5.4 视觉/交互规范

- 沿用 Element Plus + 现有主题切换；新增设计令牌文档（间距/字号/色阶）仍未产出。
- 生产页面统一“三段式”：顶部上下文条（项目/章节/阶段）→ 中部工作区 → 底部状态栏（WS 连接/任务进度）。
- 所有长任务统一走 usePipelineProgress 的 WS 进度协议 + 断线轮询降级。

### 5.5 验收标准（当前状态）

| 项 | 标准 | 当前状态 |
|----|------|----------|
| 覆盖度 | openapi 端点前端触达率 ≥ 85%（不含 /mock/* 与纯健康检查） | 🔶 生产主链路 + 进化域/管理域大幅补全，仍缺知识库/审计/协作/中间产物 UI |
| 数据层 | 全前端 0 处裸 axios/fetch（统一 api 客户端） | ✅ `grep` 已无裸 axios/fetch（api 模块之外 0 处） |
| 组件体积 | 单 view 文件 ≤ 400 行 | ❌ AgentChatView(1355)、VideoCanvasView(1276)、AutoRunView(829) 未拆分 |
| 构建 | npm run build 无 >500KB chunk；vue-tsc 0 error | ✅ `npm run build` 通过，最大 chunk < 500KB |
| 测试 | 新页面各有 ≥1 个 vitest 组件测试；i18n key 双语言齐全 | 🔶 现有 15 个测试文件/121 用例通过；已补 MonitoringDashboard、FeedbackInsightsView 组件测试，其余新页面组件测试待补 |
| e2e | 关键路径（创建→上传→autopilot→导出）playwright 冒烟通过 | ⏳ 未在 web 侧跑通（后端已有 E2E 修复记录） |

# Audiobook Studio

<!-- STATUS BANNER -->
<div align="center">

| 状态 | 说明 | 对应模式 |
|------|------|----------|
| 🟢 **已落地** | 核心流水线、双引擎 TTS、质检、导出、前端编辑、遥测看板、单句重录 | 土豆模式 / 云端白嫖模式 |
| 🟡 **规划中** | 模型市场、接口限流、自我迭代演进（DSPy 路径）、管理预热端点 | 专业显卡模式 / 需额外依赖 |
| 🔴 **需 GPU** | 跨语言声纹克隆、零样本声纹锁定克隆、CosyVoice/VoxCPM2 神经模型、高保真声纹复用 | 专业显卡模式（独显 ≥16GB VRAM） |

</div>

## 项目概述
Audiobook Studio 是一个 **一站式有声书制作平台**，从原始手稿到成品音频全链路自动化。核心功能包括文件上传、文本提取、LLM 剧本结构化、情感标注、并发 TTS 合成、音频混音、质量检测以及多格式音频输出。

## 关键特性
- **多格式文本导入**：PDF、EPUB、DOCX、TXT、图片（OCR）
- **LLM 剧本生成**：基于马具规范的角色、情感、语速、音高标注
- **并发 TTS**：本地 Kokoro‑ONNX 与云端 Edge‑TTS 双引擎
- **自动化质量检测**：多模态模型检测音频缺陷并自动重合成
- **可视化编辑**：基于 wavesurfer.js 的时间线编辑器
- **成本与资源监控**：实时 token、字符、费用统计
- **安全与合规**：环境变量安全、密钥泄露检测、审计日志

## 💻 四档变速架构 (4-Tier Hardware Profiles)
为实现“让人人都能用得起开源智能有声书”的普惠目标，系统深度解耦并支持一键切换运行模式：
- 🥔 **土豆模式 (Potato Mode)**：无 GPU、断网可用。TTS 走本地 `Kokoro-82M ONNX` 真合成（断网仍出可播放音频）；LLM 在断网时**诚实降级为启发式规则**（`router._heuristic_fallback`，非真生成，标记 `schema_compliance=False`），联网时回真云免费 API。README 早期描述的 `Qwen2.5-3B-GGUF` (CPU 推理) 为规划项，当前仓库无落地代码/依赖。零成本、绝对隐私。
- 📴 **完全离线兜底模式 (Offline, 零档)**：无网/配额耗尽/隐私场景的完全离线兜底，`llama.cpp` + `Qwen2.5-3B-GGUF` 承担全部 LLM 与自迭代教练，本地零成本闭环（见 `hardware_profile.yaml` 的 `offline` 档）。
- ☁️ **云端白嫖模式 (Cloud-Hybrid, 默认)**：轻量级本地。依赖 `QuotaRegistry` 调度的免费大模型 API 轮换池 + 本地 `Kokoro-82M` 极速合成。
- 🚀 **专业显卡模式 (Pro Studio)**：针对拥有独显或云端算力的专业用户。对接 `CosyVoice/VoxCPM2`（**GPU 神经克隆模型**，需独显/云端算力）实现零样本声纹锁定克隆——**此能力仅限专业显卡模式**。默认土豆/云端白嫖模式的 `Kokoro-82M` / `Piper` 会丢弃 `reference_audio`、不做真实声纹锁定，仅提供谱质心占位特征（非真实声纹，见 `clone.py` 内诚实声明）；`real_clone_available()` 现已改为**诚实探针**——免费 + 无 GPU（未配置克隆后端）时返回 `False`、`clone_mode()` 返回 `'preset'`，但自托管 `docker-compose.gpu.yml`（VoxCPM2/CosyVoice2 且 `/health` 可达）时返回 `True`、声纹克隆从占位变真实（Track B 已接通，可用 `CLONE_BACKEND_DISABLED=true` 强制回退预设）。默认的自我迭代演进通过 **SOP 反思 + 晋升门禁** 路径实现（见 `feedback/sop_reflection.py` + `promotion_gate.py`）；**DSPy 深度演进循环**(GEPA / BootstrapFewShot)为可选实验性路径，需单独安装未声明的 `dspy` 依赖后才可启用，默认未启用。

## S3 长期愿景功能详解（入口与用法）

> 以下为 S3 阶段（长期愿景）交付的能力入口与基本用法。**注意**：跨语言声纹克隆、CosyVoice/VoxCPM2 神经模型等能力**仅限专业显卡模式（需 GPU）**，不包含在免费资源模式中。免费模式（土豆/云端白嫖）仅提供 `Kokoro-82M` 谱质心占位特征，非真实声纹克隆。

### 跨语言声纹克隆（Multilingual Voice Clone）— 🔴 **需 GPU / 专业显卡模式**
- **语言注册表**：`src/audiobook_studio/languages.py` — 集中管理管线可端到端处理的语言及其 TTS 音色、提示词引导。
- **声纹克隆**：`src/audiobook_studio/tts/clone.py` 的 `VoiceCloner.clone_voice()` / `extract_voice_features()` / `VoicePrint`。**零样本声纹锁定与跨语言复用仅限专业显卡模式（Pro Studio，对接 `CosyVoice/VoxCPM2` 等 GPU 神经模型）**；默认土豆/云端模式走 `Kokoro-82M`，其 `extract_voice_features` 仅生成谱质心占位特征（非真实声纹，见 `clone.py` 内诚实声明），不得用于声纹比对。
- 专业显卡模式可对接 `CosyVoice/VoxCPM2`（见上方「四档变速架构 → 专业显卡模式」）。

### BGM 混音（背景音乐 Ducking）
- **实现**：`src/audiobook_studio/export/audio_ducking.py`（`MixConfig`）+ 导出管线自动 ducking。
- **用法**：导出 CLI 支持 `--bg-music <path>` 与 `--bg-volume <dB>` 参数，导出时对人声做 ducking 混音。

### 模型市场（Model Market）
- **REST**：`GET /models`（列出可用/已装模型）、`POST /models/install`、`POST /models/uninstall`（见 `src/audiobook_studio/api/models_market.py`，路由前缀 `/models`）。
- **前端**：`web/src/views/ModelMarket.vue` 可视化安装/卸载与状态查看。

### 接口限流（Rate Limiting，S3.6）
- **实现**：`src/audiobook_studio/api/rate_limit_middleware.py` 的令牌桶中间件，对全部非豁免请求生效；复用 `tts/rate_limiter.py` 的 `TokenBucket`，可接 Redis 做分布式限流，保护 Cloud Studio 免费配额。

### 自我迭代演进（Self-Iteration，S3.1 / S3.7）
- **脚本入口**：`scripts/run_self_iteration.py`（运行演进）、`scripts/validate_self_iteration.py`（校验）。
- **核心**：`src/audiobook_studio/pipeline/self_iteration.py` + `src/audiobook_studio/feedback/`（SOP 反思 `sop_reflection.py`、晋升门禁 `promotion_gate.py`）。
- **演进 API**（GEPA / BootstrapFewShot 为可选实验路径）：
  - `POST /evolution/enable` — 启用 / 停用演进循环
  - `POST /evolution/run` — 运行 BootstrapFewShot 优化
  - `GET  /evolution/progress` — 查询演进进度
  - `POST /progress` — 启用 GEPA 演进循环（S3.1）

### 管理与预热端点（Admin / Warmup）
- `POST /admin/warmup` — 预热引擎与 LLM 客户端（`src/audiobook_studio/api/admin.py`）。
- `POST /evolution/warmup` — 预热引擎 / LLM 客户端（S3.1）。
- `GET  /apply/{task_id}/progress` — 查询模板应用进度（`src/audiobook_studio/api/templates.py`）。

### 真实集成验证（Phase B，免费资源）
> 详见 `docs/NEXT_STEPS.md`「Phase B 完成总结」。以下脚本均**仅用免费资源**，可本地复跑：
- **B1（S3.7 自迭代闭环）**：`scripts/run_self_iteration_b1.py` — 本机无本地 LLM(Kokoro/qwen)时走确定性 mock 并明确标注；闭环产出 `gain_pct=75%`（>10%）+ 人工复核提示。
- **B2（S3.1 GEPA）**：`scripts/run_gepa_b2.py` — DSPy 已装时真实跑 GEPA/BootstrapFewShot few-shot 优化（经 `/admin/evolution/run` 底层路径），`/admin/evolution/progress` 反映运行状态。
- **B3（S3.3 端到端）**：`scripts/run_e2e_bgm_mp4.py` — 真实 ffmpeg + 免费 Edge-TTS：TTS→BGM 混音→MP4 封装，产出**可播放 MP4**（audio+video+subtitle 三轨）。
- **B4（S3.4 跨语言）**：`scripts/run_cross_language_b4.py` — 免费 LLM 将 en/ja/ko 译为 zh + 免费 Edge-TTS 外语音色，产出外语音频。

## 🚀 5 分钟快速开始

### 方式一：一键演示脚本（推荐新手）
```bash
# 1. 克隆并进入
git clone <repo-url>
cd audiobook

# 2. 解密环境变量（如有加密）
./scripts/decrypt_env.sh

# 3. 一键跑通全流程（Mock 模式，约 1-2 分钟）
./scripts/demo_full_pipeline.sh --book hongloumeng --mock
```
> **原理**：启动免费栈 → 下载模型 → 导入《红楼梦》样书 → 跑 7 级流水线 → 导出 M4B  
> **Mock 模式** 无需任何 API Key，使用确定性模拟响应，**1-2 分钟**即可跑通全流程

### 方式二：标准本地开发（完整环境）
```bash
# 1. 克隆并进入
git clone <repo-url>
cd audiobook

# 2. 创建并激活虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装 pre-commit 钩子
pre-commit install

# 5. 启动后端服务
docker compose up -d

# 6. 启动前端开发服务器(新终端)
cd web && npm install && npm run dev
# 访问 http://localhost:5188
# 7. 运行演示（真实 LLM，需配置 .env 中的 API Key）
./scripts/demo_full_pipeline.sh --book hongloumeng
```

### 方式三：专业显卡模式
```bash
# 仅限 NVIDIA/AMD 独显 ≥16GB VRAM
bash scripts/setup_pro.sh
```
> 脚本会检测 GPU 显存，**不达标时诚实降级退出**；模型权重需手动拉取（免费资源上限）

---

## 🏗️ 架构图速览

| 图表 | 链接 | 说明 |
|------|------|------|
| **全流水线流程** | [Architecture.md#full-pipeline-flow](docs/architecture.md#full-pipeline-flow) | 7 级管线：Extract→Analyze→Annotate→Edit→AudioPost→Synthesize→Quality |
| **自迭代闭环** | [Architecture.md#self-iteration-loop-harness](docs/architecture.md#self-iteration-loop-harness) | Feedback→SOP Reflection→Prompt Version→Canary→Promotion Gate |
| **TTS 合成与音色** | [Architecture.md#tts-synthesis-and-voice-pipeline](docs/architecture.md#tts-synthesis-and-voice-pipeline) | Kokoro/Edge-TTS/CosyVoice 三档引擎选择 |
| **发布导出管线** | [Architecture.md#publish-and-export-pipeline](docs/architecture.md#publish-and-export-pipeline) | M4B/SRT/RSS/MP4 多格式导出 + Audiobookshelf 推送 |
| **HARNESS 三层架构** | [Architecture.md#harness-three-layer-architecture](docs/architecture.md#harness-three-layer-architecture) | Contract→Execution→Evaluation 三层纵深防御 |
| **数据流总览** | [Architecture.md#data-flow-overview](docs/architecture.md#data-flow-overview) | 输入→7级管线→输出，含重试回路 |

> 完整架构文档见 [`docs/architecture.md`](docs/architecture.md)

---

## 🖥️ 前端功能使用指南

> 前端技术栈:Vue 3 + Vite + Element Plus + Pinia + vue-i18n  
> 支持深色/浅色主题切换,中英双语界面,移动端自适应。

### 1. 登录与注册

**访问地址:** `http://localhost:5188`

1. 打开浏览器访问前端地址,自动跳转到登录页。
2. 输入用户名和密码,点击 **Log in** 按钮。
3. 首次部署请先运行后端脚本创建管理员账号:
   ```bash
   python scripts/bootstrap_admin.py
   ```
4. 没有账号?点击 **Don't have an account? Register a new user** 跳转注册页。
5. 注册成功后自动跳转登录页。

---

### 2. 项目列表 (Projects)

**侧边栏位置:** WORKSPACE → Projects

- 查看所有项目卡片,按最近更新时间排序。
- 顶部搜索栏可按项目名称筛选。
- 点击 **+ 新建项目** 按钮,填写项目标题、作者、语言后创建。
- 点击任意项目卡片进入项目概览。
- 点击卡片上的操作按钮可删除项目(会弹出确认对话框)。

---

### 3. 项目管理 (Project Management)

**侧边栏位置:** WORKSPACE → Project Management

- 查看全部项目的 7 阶段流水线状态。
- 顶部搜索栏按名称筛选。
- 点击卡片可直接跳转到对应项目。
- 支持批量操作:运行流水线、导出、发布。

---

### 4. 项目概览 (Project Overview)

**进入方式:** 点击项目列表中的项目卡片,或侧边栏 CURRENT PROJECT → Dashboard

顶部显示:
- **项目标题与元数据** — 项目 ID、创建时间、字数统计等。
- **Pipeline 进度条** — 横向展示 7 个阶段(Extract→Analyze→Annotate→Edit→Postprocess→Synthesize→Quality)的完成状态,右侧显示完成百分比。
- **快捷操作** — 6 个常用入口按钮:
  - 🎙️ 自动运行 — 一键跑通全流程
  - 📥 上传文件 — 上传新书源
  - 📤 导出 — 多格式音频导出
  - 🌐 发布 — 推送到外部平台
  - 📊 质检报告 — 查看质量检测结果
  - 🎭 角色管理 — 配置角色与声线
- **最近章节列表** — 展示最近处理的章节及其状态。

---

### 5. 文件上传 (Upload)

**进入方式:** 项目概览 → 上传文件,或侧边栏 → Upload

**步骤:**

1. **选择项目** — 从下拉列表选择已有项目,或新建一个。
2. **上传文件** — 拖拽文件到上传区域,或点击选择文件。
   - 支持格式:PDF、EPUB、DOCX、TXT
   - 最大文件大小:50MB
3. **提取文本** — 文件上传完成后,点击 **开始提取**。
   - 系统自动执行 OCR、文本清洗、段落分割。
   - 提取完成后显示:创建的章节数、总段落数、检测到的语言。
4. 点击 **查看项目** 进入项目详情。

---

### 6. 自动运行 (Auto Run) — 一键跑通全流程

**进入方式:** 项目概览 → 自动运行,或侧边栏 → Auto Run

**使用步骤:**

1. **配置引擎** — 选择 TTS 引擎(Kokoro/Edge-TTS)和声线(男声/女声/中性)。
2. **调整参数** — 语速、质量阈值、目标难度等。
3. **启动运行** — 点击 **Start Auto Run** 按钮。
4. **实时监控** — 通过 WebSocket 实时查看:
   - 当前阶段与进度条
   - 每阶段耗时与状态
   - 预计剩余时间
5. **控制操作** — 运行中可随时:
   - ⏸️ 暂停 — 暂停当前阶段
   - ▶️ 继续 — 恢复运行
   - ⏹️ 取消 — 终止本次运行

**7 阶段流程:**
| 阶段 | 说明 |
|------|------|
| Extract | 文本提取 — 从上传文件中提取纯文本 |
| Analyze | 结构分析 — LLM 识别章节、段落结构 |
| Annotate | 段落标注 — 标注角色、情感、语速、音高 |
| Edit | TTS 编辑 — 优化文本以适配 TTS 合成 |
| AudioPost | 音频后处理 — 降噪、标准化、BGM 混音 |
| Synthesize | 音频合成 — TTS 引擎将文本转为语音 |
| Quality | 质量检测 — 多模态模型检测音频缺陷 |

---

### 7. 章节时间线 (Chapter Timeline)

**进入方式:** 项目概览 → 章节列表中点击某章节

- 左侧段落列表,支持搜索与筛选。
- 右侧波形编辑器(wavesurfer.js),可视化音频。
- 点击段落可预览对应音频。
- 支持播放/暂停、倍速、音量调节。
- 底部显示段落元数据:说话人、情感、语速、音高。
- 已编辑段落显示 **已编辑** 标签。

---

### 8. TTS 编辑 (TTS Edit)

**进入方式:** 项目概览 → 顶部标签页 TTS Edit

- 选择章节查看段落列表。
- 点击段落进入编辑模式,修改文本以优化 TTS 合成效果。
- 支持搜索段落、仅显示未编辑项。
- 右侧 AI 对话面板可获取智能修改建议。
- 编辑后点击 **Save** 保存。

---

### 9. 角色管理 (Characters & Voices)

**进入方式:** 项目概览 → Characters & Voices,或侧边栏 → Character Manager

- **角色列表** — 展示所有已定义角色及其声线配置。
- **新增角色** — 点击 **+ 新增角色**,填写:
  - 角色名称(必填)
  - 声音 ID(可选,留空使用默认)
  - 默认情感(中性/高兴/悲伤/愤怒等)
  - 默认音高与语速
- **编辑角色** — 点击角色卡片上的编辑按钮。
- **删除角色** — 点击删除按钮,确认后移除。

---

### 10. 质量报告 (Quality Report)

**进入方式:** 项目概览 → 质检报告,或侧边栏 → Quality Report

- **统计概览** — 顶部 4 张统计卡片:
  - 📊 总章节数
  - ✅ 已完成数
  - ⏳ 待处理数
  - ❌ 异常数
- **完成进度** — 进度条显示整体完成百分比。
- **筛选** — 下拉选择按状态筛选(全部/已完成/待处理/异常)。
- **章节列表** — 每行显示章节名称、状态徽章、查看详情按钮。
  - 状态图标颜色:绿色=完成,黄色=待处理,红色=异常。
- 点击 → 按钮跳转到章节详情。

---

### 11. 导出 (Export)

**进入方式:** 项目概览 → 导出,或侧边栏 → Export

**步骤:**

1. **选择导出格式** — 勾选需要的格式(可多选):
   - ☑️ M4B Audiobook — 包含章节和元数据的单个 M4B 文件
   - ☐ SRT Subtitles — 每个章节的 SRT 字幕文件
   - ☐ VTT Subtitles — WebVTT 字幕文件
   - ☐ M4B + SRT Bundle — 带字幕的 M4B 有声书
   - ☐ All Formats — 以所有可用格式导出
2. **配置选项**:
   - ☑️ 标准化音频音量
   - ☑️ 包含封面图片
   - 每行字幕最大字符数(默认 40)
3. 点击 **Start Export** 开始导出。
4. 导出完成后可在项目目录的 `output/` 下找到生成的文件。

---

### 12. 发布 (Publish)

**进入方式:** 项目概览 → 发布,或侧边栏 → Publish

**支持两种发布目标:**

#### Audiobookshelf 推送
1. 勾选 **Audiobookshelf** 目标。
2. 填写配置:
   - 服务器地址 — 如 `http://localhost:13378`
   - API Key — 从 Audiobookshelf 设置中获取
   - 库 ID — 目标库的 ID
3. 点击 **Start Publish** 推送。

#### Podcast RSS 生成
1. 勾选 **Podcast RSS** 目标。
2. 填写 RSS 信息:
   - Feed 标题、描述、链接
   - 作者、所有者邮箱
   - Feed 语言
3. 点击 **Start Publish** 生成 RSS 订阅源。

- 底部 **发布历史** 表格记录每次发布的状态与时间。

---

### 13. 翻译配音 (Translation Dubbing)

**进入方式:** 项目概览 → Translation Dubbing

1. **选择目标语言** — 从下拉列表选择翻译目标语言。
2. **选择章节范围** — 翻译全部已合成章节,或指定起止章节。
3. **启动翻译** — 点击 **开始翻译配音**。
4. **实时进度** — 通过 WebSocket 查看翻译进度。
5. **双语对比** — 翻译完成后,选择段落对比原文与译文的音频效果。

---

### 14. 声音克隆 (Voice Cloning)

**进入方式:** 项目概览 → Voice Cloning

> ⚠️ 真实声纹克隆仅限专业显卡模式(需 GPU + CosyVoice/VoxCPM2)。免费模式下为占位特征。

**步骤:**
1. **上传样本** — 拖拽或选择 15 秒以上的 WAV/MP3 音频文件。
2. **波形预览** — 查看波形、采样率、信噪比(SNR ≥ 20dB 为佳)。
3. **开始克隆** — 点击 **开始克隆**,等待模型处理。
4. **试听结果** — 输入试听文本,生成并播放克隆声音。
5. **使用声线** — 克隆成功后,在角色管理中选择新声线 ID。

---

### 15. 运行记录 (Run Logs)

**进入方式:** 项目概览 → Run Logs

- 查看所有历史运行记录,包括自动运行和手动单阶段运行。
- **手动单阶段运行** — 选择阶段和章节,单独运行某个阶段。
- **中间产物** — 查看每个阶段的输出文件(标注结果、合成音频等)。
- 点击阶段名称可跳转到对应详情页。

---

### 16. 项目仪表盘 (Project Dashboard)

**进入方式:** 项目概览 → Dashboard

- **KPI 卡片** — 总成本、总 Token 数、总音频时长、RTF(实时因子)、每分钟成本、合成率。
- **成本分布饼图** — 各 LLM Provider 的成本占比。
- **延迟排行榜** — 各阶段延迟排名。
- **Provider 成本明细** — 每个 Provider 的 Token 用量、调用次数、平均延迟、成功率。
- **复原力指标** — LLM 重试/回退次数、TTS 成功率。

---

### 17. 知识库 (Knowledge Base)

**进入方式:** 项目概览 → Knowledge Base

- **搜索** — 按主题搜索已有知识条目。
- **新增知识** — 点击 **新增知识**,填写主题、来源、内容(JSON 格式)。
- 知识条目会为 Agent 提供上下文辅助。

---

### 18. 反馈录入 (Feedback Entry)

**侧边栏位置:** WORKSPACE → Feedback Entry

- 填写反馈表单:
  - 来源 — 人工编辑 / 质量评判 / 用户评分
  - 阶段 — 该反馈对应的管线阶段
  - 书籍 ID、章节索引、段落索引
  - 输入快照 / LLM 输出 / 修正后输出
  - 修改理由(至少 10 字符)
- 点击 **提交反馈** 保存。

---

### 19. 监控仪表盘 (Monitoring)

**侧边栏位置:** SYSTEM → Monitoring

- **成本分析饼图** — 按 Provider 统计总成本。
- **阶段延迟排行榜** — 各阶段平均耗时排名。
- **复原力指标** — LLM 调用总数、重试次数、TTS 成功率等。
- **Provider 成本明细** — 详细的 Token 消耗与费用。
- **流水线元数据** — 项目 ID、Pipeline ID、运行时间。
- 点击 **刷新数据** 获取最新指标。

---

### 20. HARNESS 控制台

**侧边栏位置:** SYSTEM → HARNESS Console

- **自我迭代状态** — 当前迭代版本、运行状态、迭代次数。
- **反馈漏斗** — 总反馈 → 已分析 → 已触发 → 已晋升 → 已发布。
- **模式热力图** — 按模式标签统计频次与严重度。
- **提示词时间线** — Prompt 版本演进历史。
- **晋升门禁** — 各阶段阈值与通过状态。
- **金丝雀发布** — 流量分配、采样数、质量比。
- **A/B 测试** — 变体对比、P 值、显著性判定。
- **批评器** — 语义派/结构派/客观派的 F1、精确率、召回率。

**操作:**
- 点击 **触发迭代** 启动新一轮自我优化。
- 点击 **回滚** 恢复到上一版本。

---

### 21. 管理后台 (Admin Console)

**侧边栏位置:** SYSTEM → Admin Console

- **用户管理** — 查看所有用户,分配/移除角色。
- **系统配置** — 查看和管理后端配置。
- **重载配置** — 点击按钮热重载全部配置(无需重启)。

---

### 22. 供应商管理 (Provider Management)

**侧边栏位置:** SYSTEM → Provider Management

- **供应商列表** — 左侧面板显示所有已配置的 LLM 提供商。
- **添加供应商** — 点击按钮填写:名称、类型、API 地址、密钥等。
- **模型列表** — 右侧面板显示选中供应商的所有模型。
- **热重载** — 修改后点击 **热重载到路由器**,变更即时生效。
- **启用/禁用** — 切换开关控制供应商状态。

---

### 23. 模型市场 (Model Market)

**侧边栏位置:** SYSTEM → Model Market

- **TTS 引擎** — 查看可用的本地 TTS 引擎(Kokoro、Piper 等)。
- **插件** — 查看可安装的插件扩展。
- **一键安装** — 点击安装按钮,自动下载并配置模型。
- **卸载** — 不再需要时可卸载已安装模型。

---

### 24. 波形编辑器 (Waveform Editor Demo)

**侧边栏位置:** SYSTEM → Waveform Editor Demo

- 多轨道波形编辑器,用于精细音频编辑。
- 支持:播放/暂停、前进/后退 10 秒、缩放、撤销/重做。
- 多轨道管理:添加/移除轨道、静音、独奏、锁定、拖拽排序。
- 区域编辑:设置情感标签、语速、音高、音效。
- 导出区域:将选定区域导出为独立文件。

---

### 25. 晋升审批 (Promotions)

**侧边栏位置:** EVOLUTION CENTER → Promotions

- **晋升门禁状态** — 各阶段的阈值与通过/失败状态。
- **金丝雀发布** — 活跃 Canary 的流量占比、采样数、质量比。
- **A/B 测试结果** — 变体对比、P 值、显著性。
- **回滚** — 一键回滚到上一版本。

---

### 26. 金标数据集 (Golden Dataset)

**侧边栏位置:** EVOLUTION CENTER → Golden Dataset

- **样本列表** — 查看所有金标样本,按阶段筛选。
- **贡献样本** — 提交新的高质量样本供团队复用。
- **批准/拒绝** — 审核样本质量。
- **回归测试** — 对金标数据集运行回归测试,统计通过率。
- **趋势** — 查看历史评分趋势。

---

### 27. SOP 规则库 (SOP Rules)

**侧边栏位置:** EVOLUTION CENTER → SOP Rules

- **体裁选择** — 按体裁查看已学习的 SOP 规则。
- **后台学习** — 启动/停止后台自动学习模式。
- **立即反思** — 触发一次即时反思,从反馈中提炼规则。

---

### 28. 反馈洞察 (Feedback Insights)

**侧边栏位置:** EVOLUTION CENTER → Feedback Insights

- **反馈漏斗** — 可视化反馈流转:总反馈 → 已分析 → 触发升级 → 晋升通过 → 已发布。
- **模式热力图** — 按模式标签统计频次与严重度。

---

### 29. AI 智能助手 (Agent Chat)

**进入方式:** 项目概览 → Agent Chat

- 与 AI 助手对话,获取项目管理建议。
- 支持文件附件、复制回复、重新生成。
- 聊天设置:助手性格(通用/专家/创意/简洁)、回复长度。
- 支持 WebSocket 实时通信或 HTTP 轮询降级。
- 快捷建议:查看进度、生成章节、优化 TTS、检查质量、导出成品。

---

### 30. 音频精修 (Audio Segments)

**进入方式:** 项目概览 → Audio Segments

- 按顺序展示所有音频段。
- **剪辑** — 调整段落的开始/结束时间(ms)。
- **合并** — 勾选多个段落,点击合并。
- **删除** — 移除不需要的音频段。
- **保存顺序** — 调整段落顺序后保存。

---

### 31. 主题切换

- 点击侧边栏底部的主题切换按钮。
- 支持三种模式:
  - ☀️ **浅色** — 亮色背景
  - 🌙 **深色** — 深色背景,护眼
  - 🔄 **跟随系统** — 自动匹配系统主题
- 切换即时生效,偏好保存在 localStorage。

---

### 32. 国际化 (i18n)

- 界面支持 **中文** 和 **English** 两种语言。
- 切换语言后所有界面文本即时更新。
- URL 路由、表单提示、错误消息均已完整翻译。
- 开发者可在 `web/src/locales/` 下维护翻译文件。

---

### 33. 移动端适配

- 响应式布局,支持手机/平板访问。
- 侧边栏在移动端自动收起,点击汉堡菜单展开。
- 表格在窄屏下转为卡片布局。
- 触摸目标尺寸 ≥ 44px,符合无障碍标准。
- 图标按钮均配有 `aria-label`,支持屏幕阅读器。

---

## ❓ 常见问题 (FAQ)

### Q1: 运行 `./scripts/demo_full_pipeline.sh` 报错 "Docker not found"
**A**: 请先安装 Docker Desktop / Docker Engine，确保 `docker compose` 可用。  
Linux: `sudo apt-get install docker.io docker-compose-plugin`  
macOS/Windows: 下载 Docker Desktop

### Q2: 运行时报错 "No module named 'kokoro_onnx'"
**A**: 需下载模型文件：
```bash
python scripts/download_kokoro_model.py
```
或运行演示脚本时加 `--skip-model-download` 跳过（需手动放置模型到 `models/` 目录）。

### Q3: 报错 "JWT_SECRET_KEY not set"
**A**: 复制 `.env.example` 为 `.env` 并填入密钥：
```bash
cp .env.example .env
# 生成密钥
python scripts/generate_secrets.py --jwt-secret
```
或运行 `./scripts/decrypt_env.sh` 解密已加密的 `.env.encrypted`（需 `.agekey` 私钥）。

### Q4: LLM 调用超时 / 失败
**A**: 系统内置多提供商自动轮换（Gemini→Groq→NVIDIA→OpenRouter...）。  
检查 `.env` 中至少配置了一个可用的 API Key：
```bash
# 至少配置一个
GEMINI_API_KEY=...
GROQ_API_KEY=...
OPENROUTER_API_KEY=...
```
或使用 Mock 模式绕过：`./scripts/demo_full_pipeline.sh --mock`

### Q5: TTS 合成极慢 / 卡住
**A**: 
- Mock 模式下秒级完成：`MOCK_TTS=true`
- 真实模式下 Kokoro ONNX 首次加载模型较慢，后续复用会加速
- 确保 `models/kokoro-v1.0.onnx` 和 `models/voices-v1.0.bin` 存在

### Q6: 如何查看流水线进度？
```bash
# 实时日志
docker compose logs -f celery-worker

# API 查询
curl http://localhost:8000/api/projects/<project_id>/auto-run/status | jq
```

### Q7: 导出 M4B 后如何导入 Audiobookshelf？
1. 确保 Audiobookshelf 已运行并获取 API Key
2. 设置环境变量：
```bash
export AUDIOBOOKSHELF_URL=http://localhost:13378
export AUDIOBOOKSHELF_API_KEY=your-api-key
```
3. 重新运行演示脚本（会自动推送），或手动上传：
```bash
curl -X POST "$AUDIOBOOKSHELF_URL/api/items" \
  -H "Authorization: Bearer $AUDIOBOOKSHELF_API_KEY" \
  -F "file=@output/<project_id>/output.m4b"
```

### Q8: 如何切换 LLM 提供商优先级？
编辑 `config/llm_providers.yaml`，调整 `priority` 数值（越小优先级越高）：
```yaml
providers:
  - name: gemini
    priority: 1
  - name: groq
    priority: 2
```
免费模型的 `pricing.per_1k_tokens` 设为 0 可优先使用。

### Q9: 如何启用/禁用自我迭代？
```bash
# 启用
curl -X POST http://localhost:8000/admin/evolution/enable \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "stage": "annotate_paragraph"}'

# 查看进度
curl http://localhost:8000/admin/evolution/progress
```

### Q10: 前端如何启动开发服务器?
**A**:

```bash
cd web
npm install
npm run dev
# 访问 http://localhost:5188
```

前端开发服务器支持热重载,修改代码后自动刷新。构建生产版本: `npm run build`。

### Q11: 前端如何运行测试?
**A**:

```bash
cd web
npx vitest run              # 运行全部 132 个测试
npx vitest run --reporter verbose  # 详细输出
```

TypeScript 类型检查: `npx vue-tsc --noEmit`

### Q12: 如何切换前端语言?
**A**: 界面右上角或设置页面可切换 中文/English。所有界面文本即时更新,翻译文件位于 `web/src/locales/`。

### Q13: 如何切换深色/浅色主题?
**A**: 侧边栏底部有主题切换按钮,支持 浅色/深色/跟随系统 三种模式。偏好自动保存在浏览器 localStorage 中。

### Q14: 遇到未知错误如何排查？
1. 查看错误日志：`tail -f logs/$(date +%F)_errors.log`
2. 查看主日志：`tail -f logs/$(date +%F)_main.log`
3. 运行自检：`./check_rules.sh`
4. 提交 Issue 时附带：错误日志、环境信息（`python -c "import sys; print(sys.version)"`）、复现步骤

## 项目结构
```
audiobook/
├─ .github/                # CI / Issue / PR 模板
├─ .pre-commit-config.yaml # 代码风格、密钥检测等
├─ Dockerfile              # 构建容器镜像
├─ docker-compose.yml      # 本地服务编排
├─ docs/                   # MkDocs 文档站点
│   ├─ index.md
│   ├─ architecture.md
│   ├─ quick_start.md
│   ├─ governance/         # 治理文档 (AGENTS.md, CLAUDE.md, CONTRIBUTING.md 等)
│   └─ legacy/             # 归档文档 (CHANGELOG.md, 测试报告等)
├─ src/                    # Python 后端源码
│   └─ audiobook_studio/   # 核心应用
├─ web/                    # Vue 3 前端源码
│   └─ src/
│       ├─ views/          # 页面组件 (33 个视图)
│       ├─ components/     # 可复用组件 (Sidebar, EmptyState, autorun/* 等)
│       ├─ composables/    # 组合式函数 (useTheme, useInlineChat 等)
│       ├─ stores/         # Pinia 状态管理
│       ├─ locales/        # i18n 翻译文件 (en-US.js, zh-CN.js)
│       ├─ api/            # API 请求封装
│       ├─ router/         # 路由配置
│       └─ style.css       # 设计令牌 (Design Tokens)
├─ tests/                  # 单元/集成测试
├─ requirements.txt        # Python 依赖
├─ mkdocs.yml              # MkDocs 配置
├─ LICENSE                 # MIT 许可证
├─ ONBOARDING_CHECKLIST.md # 新成员入职清单
├─ PROJECT_STATUS.md       # 项目全局进度与状态 (唯一真相源)
├─ README.md               # 本文件
└─ SECURITY.md             # 安全报告流程
```

## 文档导航 (Documentation)
- **治理文档** → [`docs/governance/`](docs/governance/) — AGENTS.md, CLAUDE.md, CONTRIBUTING.md, CODE_OF_CONDUCT.md, 开发计划与执行清单等
- **归档文档** → [`docs/legacy/`](docs/legacy/) — CHANGELOG.md, ANALYSIS_SUMMARY.md, 测试报告等历史文档
- **MkDocs 站点** → [`docs/`](docs/) — 在线文档站点源码 (`mkdocs serve` 预览)
- **项目状态** → [`PROJECT_STATUS.md`](PROJECT_STATUS.md) — 唯一进度真相源，Sprint 进度与技术债记录

## 开发流程概览
1. **分支**：`feature/<name>`、`bugfix/<name>`、`hotfix/<name>`，基于 `develop` 分支创建。
2. **提交信息**：使用约定前缀 `feat:`、`fix:`、`docs:`、`refactor:`、`test:`、`chore:`。
3. **代码检查**：`pre‑commit` 自动执行 `black`、`isort`、`flake8`、`detect‑secrets`、`bandit`。
4. **本地自检**：`./check_rules.sh` 检查文档、质量、环境等。
5. **Pull Request**：提交 PR，至少 1 位审查者 + CI 通过后合并。
6. **CI**：GitHub Actions 自动运行 lint、test、coverage、docker build、health‑report 生成。
7. **发布**：通过 `docker tag` 与 `docker push` 将镜像推送至仓库，更新 `PROJECT_HEALTH.md`。

## 常见问题 & 注意事项
- **密钥泄露**：所有 `.env`、`keys.json`、`config_real.py` 均列入 `.gitignore`，`detect‑secrets` 会阻止提交。
- **大模型费用**：`config.py` 中可配置每日 token 上限，超出后自动降级为本地模型。
- **断点续传**：长时间 TTS 合成会在 `audiobook_studio/checkpoints/` 保存进度，网络中断后自动恢复。
- **日志**：`logs/` 目录保存 `*_main.log` 与 `*_errors.log`，`logger.py` 已统一格式化。
- **Agent 自动化**：通过 `./check_rules.sh`、CI 脚本以及预置的 Git 钩子，Agent 可在每次代码变更后自动执行检查、文档提醒、质量报告生成，几乎实现 **零人工干预** 的闭环。

---
*本文件仅为模板，后续可根据实际需求增删内容。*

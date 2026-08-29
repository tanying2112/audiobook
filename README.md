# Audiobook Studio

<!-- STATUS BANNER -->
<div align="center">

| 状态 | 说明 | 对应模式 |
|------|------|----------|
| 🟢 **已落地** | 核心流水线、双引擎 TTS、质检、导出、前端编辑、遥测看板、单句重录 | 土豆模式 / 云端白嫖模式 |
| 🟡 **规划中** | 跨语言声纹克隆、模型市场、接口限流、自我迭代演进（DSPy 路径）、管理预热端点 | 专业显卡模式 / 需额外依赖 |
| 🔴 **需 GPU** | 零样本声纹锁定克隆、CosyVoice/VoxCPM2 神经模型、高保真声纹复用 | 专业显卡模式（独显 ≥16GB VRAM） |

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

## 💻 三档变速架构 (3-Tier Hardware Profiles)
为实现“让人人都能用得起开源智能有声书”的普惠目标，系统深度解耦并支持一键切换运行模式：
- 🥔 **土豆模式 (Potato Mode)**：无 GPU、断网可用。TTS 走本地 `Kokoro-82M ONNX` 真合成（断网仍出可播放音频）；LLM 在断网时**诚实降级为启发式规则**（`router._heuristic_fallback`，非真生成，标记 `schema_compliance=False`），联网时回真云免费 API。README 早期描述的 `Qwen2.5-3B-GGUF` (CPU 推理) 为规划项，当前仓库无落地代码/依赖。零成本、绝对隐私。
- ☁️ **云端白嫖模式 (Cloud-Hybrid, 默认)**：轻量级本地。依赖 `QuotaRegistry` 调度的免费大模型 API 轮换池 + 本地 `Kokoro-82M` 极速合成。
- 🚀 **专业显卡模式 (Pro Studio)**：针对拥有独显或云端算力的专业用户。对接 `CosyVoice/VoxCPM2`（**GPU 神经克隆模型**，需独显/云端算力）实现零样本声纹锁定克隆——**此能力仅限专业显卡模式**。默认土豆/云端白嫖模式的 `Kokoro-82M` / `Piper` 会丢弃 `reference_audio`、不做真实声纹锁定，仅提供谱质心占位特征（非真实声纹，见 `clone.py` 内诚实声明）；`real_clone_available()` 现已改为**诚实探针**——免费 + 无 GPU（未配置克隆后端）时返回 `False`、`clone_mode()` 返回 `'preset'`，但自托管 `docker-compose.gpu.yml`（VoxCPM2/CosyVoice2 且 `/health` 可达）时返回 `True`、声纹克隆从占位变真实（Track B 已接通，可用 `CLONE_BACKEND_DISABLED=true` 强制回退预设）。默认的自我迭代演进通过 **SOP 反思 + 晋升门禁** 路径实现（见 `feedback/sop_reflection.py` + `promotion_gate.py`）；**DSPy 深度演进循环**(GEPA / BootstrapFewShot)为可选实验性路径，需单独安装未声明的 `dspy` 依赖后才可启用，默认未启用。

## S3 长期愿景功能详解（入口与用法）

> 以下为 S3 阶段（长期愿景）交付的能力入口与基本用法。**注意**：跨语言声纹克隆、CosyVoice/VoxCPM2 神经模型等能力**仅限专业显卡模式（需 GPU）**，不包含在免费资源模式中。免费模式（土豆/云端白嫖）仅提供 `Kokoro-82M` 谱质心占位特征，非真实声纹克隆。

### 跨语言声纹克隆（Multilingual Voice Clone）— 🔴 **需 GPU / 专业显卡模式**
- **语言注册表**：`src/audiobook_studio/languages.py` — 集中管理管线可端到端处理的语言及其 TTS 音色、提示词引导。
- **声纹克隆**：`src/audiobook_studio/tts/clone.py` 的 `VoiceCloner.clone_voice()` / `extract_voice_features()` / `VoicePrint`。**零样本声纹锁定与跨语言复用仅限专业显卡模式（Pro Studio，对接 `CosyVoice/VoxCPM2` 等 GPU 神经模型）**；默认土豆/云端模式走 `Kokoro-82M`，其 `extract_voice_features` 仅生成谱质心占位特征（非真实声纹，见 `clone.py` 内诚实声明），不得用于声纹比对。
- 专业显卡模式可对接 `CosyVoice/VoxCPM2`（见上方「三档变速架构 → 专业显卡模式」）。

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

# 5. 启动本地服务
docker compose up -d

# 6. 运行演示（真实 LLM，需配置 .env 中的 API Key）
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

### Q10: 遇到未知错误如何排查？
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
├─ src/                    # Python 源码
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

# Audiobook Studio

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
- 🚀 **专业显卡模式 (Pro Studio)**：针对拥有独显或云端算力的专业用户。对接 `CosyVoice/VoxCPM2` 实现零样本声纹锁定克隆。默认的自我迭代演进通过 **SOP 反思 + 晋升门禁** 路径实现（见 `feedback/sop_reflection.py` + `promotion_gate.py`）；**DSPy 深度演进循环**(GEPA / BootstrapFewShot)为可选实验性路径，需单独安装未声明的 `dspy` 依赖后才可启用，默认未启用。

## S3 长期愿景功能详解（入口与用法）

> 以下为 S3 阶段（长期愿景）交付的能力入口与基本用法。所有能力均基于**免费资源**实现（本地模型 / 免费 API 轮换池 / 诚实脚手架）。

### 跨语言声纹克隆（Multilingual Voice Clone）
- **语言注册表**：`src/audiobook_studio/languages.py` — 集中管理管线可端到端处理的语言及其 TTS 音色、提示词引导。
- **声纹克隆**：`src/audiobook_studio/tts/clone.py` 的 `VoiceCloner.clone_voice()` / `extract_voice_features()` / `VoicePrint`，支持零样本声纹锁定与跨语言复用。
- 默认走本地 `Kokoro-82M` 真合成；专业显卡模式可对接 `CosyVoice/VoxCPM2`（见上方「三档变速架构 → 专业显卡模式」）。

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

## 快速开始 (Quick Start)

> 🚀 **有 NVIDIA/AMD 独显（≥16GB VRAM）的专业用户？推荐走 Pro 一等路径**：
> ```bash
> # 一键拉起 Pro 档（GPU 检测 → 下载 VoxCPM2 → 指引 CosyVoice → 切 pro_studio 档）
> bash scripts/setup_pro.sh
> ```
> 脚本会检测 GPU 显存，**不达标时诚实降级退出**（不假装成功），详见上方「三档变速架构 → 专业显卡模式」。无独显用户请走下方通用流。
> 模型权重需手动/按指引拉取（免费资源上限：脚本不自动下载数 GB 权重），VoxCPM2 默认 `huggingface-cli`，CosyVoice 见脚本内 HF 指引。

### 通用流（无独显 / 默认 cloud_hybrid 档）
```bash
# 1. 克隆仓库
git clone <repo-url>
cd audiobook

# 2. 创建并激活 Python 虚拟环境（推荐使用 venv）
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装 pre‑commit 钩子（一次性）
pre-commit install

# 5. 激活自动检查（只需一次）
bash -c "$(curl -fsSL https://raw.githubusercontent.com/audiobook-studio/dev-tools/main/install_rules.sh)"

# 6. 运行本地开发环境（Docker）
docker compose up -d

# 7. 可选：查看 Celery Worker 日志（Celery Worker 现在默认已随 docker compose up -d 启动）
docker compose logs -f celery-worker

# 8. 打开文档站点（MkDocs）
mkdocs serve
```

> **提示**：所有操作均可通过 `./check_rules.sh` 进行自检，确保规范遵守。

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
# 部署指南

> 本指南涵盖 Audiobook Studio 的多种部署方式，从本地开发到生产环境。

## 📋 部署方式概览

| 部署方式 | 适用场景 | 复杂度 |
|---------|---------|--------|
| **本地 Python 环境** | 开发、调试 | ⭐ |
| **Docker Compose** | 单机测试、Demo | ⭐⭐ |
| **Kubernetes (Helm)** | 生产环境 | ⭐⭐⭐ |
| **GitHub Container Registry + Cloud Run** | SaaS 部署 | ⭐⭐⭐ |

---

## 一、本地开发环境

### 1.1 环境要求

- Python 3.11+（与 `.python-version` 对齐）
- FFmpeg 4.0+（用于 TTS 合成与音频后处理）
- Node.js 18+（前端开发）
- SQLite 3.30+（默认数据库）或 PostgreSQL 13+（生产推荐）

### 1.2 安装步骤

```bash
# 1. 克隆代码
git clone https://github.com/audiobook-studio/audiobook.git
cd audiobook

# 2. 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 4. 复制环境配置
cp .env.example .env
# 编辑 .env 配置 LLM API Keys

# 5. 初始化数据库
alembic upgrade head

# 6. 启动后端
uvicorn src.audiobook_studio.main:app --reload --port 8000

# 7. 启动前端（另开终端）
cd web
npm install
npm run dev
```

### 1.3 验证部署

```bash
# 后端健康检查
curl http://localhost:8000/health
# 应返回: {"status": "ok"}

# 数据库连接
curl http://localhost:8000/health/db

# 前端访问
open http://localhost:5173
```

---

## 二、Docker Compose 部署

### 2.1 快速启动

```bash
# 使用预构建镜像
docker-compose up -d

# 查看日志
docker-compose logs -f api
```

### 2.2 自定义构建

```dockerfile
# Dockerfile (项目根目录已包含)
FROM python:3.11-slim

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY src/ /app/src/
COPY config/ /app/config/
COPY prompts/ /app/prompts/

WORKDIR /app

CMD ["uvicorn", "src.audiobook_studio.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 2.3 docker-compose.yml

```yaml
version: '3.8'
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/audiobook
      - DEEPSEEK_API_KEY=${DEEPSEEK_API_KEY}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - db
      - redis
  
  db:
    image: postgres:15
    volumes:
      - pgdata:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=audiobook
      - POSTGRES_USER=user
      - POSTGRES_PASSWORD=pass
  
  redis:
    image: redis:7-alpine
    
  web:
    build: ./web
    ports:
      - "5173:80"
    depends_on:
      - api

volumes:
  pgdata:
```

---

## 三、Kubernetes 生产部署

### 3.1 Helm Chart 结构

```
charts/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment.yaml
    ├── service.yaml
    ├── ingress.yaml
    ├── configmap.yaml
    ├── secret.yaml
    └── hpa.yaml
```

### 3.2 核心 values.yaml

```yaml
api:
  replicas: 3
  image:
    repository: ghcr.io/audiobook-studio/audiobook
    tag: latest
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: 2000m
      memory: 4Gi
  autoscaling:
    minReplicas: 3
    maxReplicas: 10
    targetCPUUtilizationPercentage: 70

database:
  url: postgresql://audiobook:xxx@postgres-primary/audiobook
  poolSize: 20

redis:
  enabled: true
  url: redis://redis-master:6379
```

### 3.3 部署命令

```bash
# 添加 Helm 仓库
helm repo add audiobook https://charts.audiobook-studio.io

# 安装
helm install audiobook audiobook/audiobook \
  --values production-values.yaml \
  --namespace audiobook \
  --create-namespace

# 升级
helm upgrade audiobook audiobook/audiobook \
  --values production-values.yaml
```

---

## 四、CI/CD 部署（GitHub Actions）

### 4.1 自动部署流程

1. **PR 推送** → 运行测试 → 覆盖率 ≥75% 检查 → 合约合规率 ≥99%
2. **main 合并** → 构建 Docker 镜像 → 推送到 ghcr.io
3. **Git Tag (v*)** → 发布到 GitHub Container Registry → 触发生产滚动更新

### 4.2 镜像构建 (.github/workflows/release.yml)

```yaml
- name: Build and push Docker image
  uses: docker/build-push-action@v5
  with:
    context: .
    push: true
    tags: ${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}:${{ steps.meta.outputs.tags }}
    platforms: linux/amd64,linux/arm64
```

### 4.3 滚动更新策略

- **Blue-Green 部署**：保留版本对比环境
- **健康检查**：`/health` + `/health/db`
- **回滚窗口**：保留最近 5 个版本

---

## 五、Cloud Run 部署（Google Cloud）

### 5.1 准备工作

```bash
# 安装 gcloud CLI 并登录
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 启用 API
gcloud services enable run.googleapis.com
gcloud services enable sqladmin.googleapis.com
```

### 5.2 部署命令

```bash
# 构建并推送镜像
gcloud builds submit --tag gcr.io/YOUR_PROJECT/audiobook

# 部署到 Cloud Run
gcloud run deploy audiobook-api \
  --image gcr.io/YOUR_PROJECT/audiobook \
  --platform managed \
  --region asia-east1 \
  --allow-unauthenticated \
  --set-env-vars "DATABASE_URL=postgresql://..."
```

---

## 六、环境变量清单

### 6.1 必需变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `DATABASE_URL` | 数据库连接串 | `postgresql://user:pass@host:5432/db` |
| `SECRET_KEY` | JWT 签名密钥 | (32+ 字符随机) |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | `sk-xxx` |

### 6.2 可选变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `MOCK_LLM` | `false` | 设为 true 时使用 Mock LLM |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `FFMPEG_PATH` | `/usr/bin/ffmpeg` | FFmpeg 路径 |
| `STORAGE_PATH` | `./storage` | 文件存储路径 |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | - | OpenTelemetry 端点 |

### 6.3 LLM 池配置

支持配置多个 LLM 提供商（按权重路由）：

```bash
# DeepSeek
DEEPSEEK_API_KEY=sk-xxx
DEEPSEEK_API_BASE=https://api.deepseek.com

# OpenAI
OPENAI_API_KEY=sk-xxx

# 自定义端点（Ollama）
OLLAMA_BASE_URL=http://localhost:11434
```

---

## 七、监控与运维

### 7.1 健康检查

- `GET /health` - 基础健康检查
- `GET /health/db` - 数据库连接验证
- `GET /metrics` - Prometheus 指标

### 7.2 日志

- 结构化日志（JSON 格式）
- 集成 Langfuse 用于 LLM 调用追踪
- OpenTelemetry 用于分布式追踪

### 7.3 告警

- **钉钉告警** (`scripts/alert.py`)：合规率<99%、Fallback>5%、成本超限
- **Slack 告警**：同钉钉配置
- **Prometheus + Grafana**：CPU/内存/延迟/错误率

---

## 八、故障排查

> 常见问题请参阅 [troubleshooting.md](troubleshooting.md) 或 [faq.md](faq.md)

### 8.1 数据库连接失败

```bash
# 检查连接
pg_isready -h DB_HOST -p 5432

# 验证迁移状态
alembic current
alembic upgrade head
```

### 8.2 LLM API 限流

启用免费模型熔断器：

```yaml
# config/llm_providers.yaml
providers:
  cerebras:
    circuit_breaker:
      enabled: true
      threshold: 5
      cooldown: 60
```

### 8.3 TTS 合成失败

```bash
# 检查 ffmpeg
ffmpeg -version

# 检查 Kokoro 模型
ls assets/models/kokoro/

# 重新下载模型
python -m audiobook_studio.tts.model_downloader --model kokoro
```

### 8.4 部署后性能下降

```bash
# 性能基准
python -m pytest tests/benchmarks/test_bench_latency.py -v

# 成本基准
python -m pytest tests/benchmarks/test_bench_cost.py -v
```

---

## 九、备份与恢复

### 9.1 数据库备份

```bash
# 自动备份 (每日凌晨)
pg_dump -h localhost -U user audiobook > backup_$(date +%Y%m%d).sql

# S3 同步
aws s3 cp backup_*.sql s3://audiobook-backups/
```

### 9.2 存储备份

```bash
# 同步存储目录
aws s3 sync storage/ s3://audiobook-storage/

# 定时清理 30 天前的产物
find storage/ -type f -mtime +30 -delete
```

### 9.3 版本快照

- 使用 `version_manager.py` 创建快照
- 每个 ProcessingRun 自动快照
- A/B 测试版本自动归档

---

## 十、相关资源

- 📘 [快速开始](quick_start.md)
- 🔌 [API 参考](api.md)
- 🏗️ [架构设计](architecture.md)
- 🔧 [故障排查](troubleshooting.md)
- ❓ [FAQ](faq.md)
- 📜 [开源规范](harness_guide.md)

---

*🚀 Audiobook Studio — 自动化有声书制作平台*
## 十一、免费 GPU 算力池（VoxCPM2）

本项目组建跨平台免费 GPU 算力池来运行 [VoxCPM2](https://github.com/FunAudioLLM/VoxCPM2) TTS 模型生成音频。
配置位于 [`voxcpm2-pool/`](../voxcpm2-pool/)，架构为「拉模式（pull）」：

```
Pool API (Redis 队列调度)
        │  BLPOP tts:tasks
        ▼
┌───────────────┬───────────────┬───────────────┬───────────────┐
│  kaggle-01    │  paddle-01    │ modelscope-01 │  modal-01     │
│  T4×2 (免费)  │  V100 (免费) │ T4/V100(免费) │  T4 (按量)   │
└───────────────┴───────────────┴───────────────┴───────────────┘
        │  RPUSH tts:results (音频上传 R2)
        ▼
   Cloudflare R2 存储
```

### 节点清单（`pool/pool_config.yaml`）

| 节点 ID | 平台 | GPU | 费用 | 模式 | 参考脚本 |
|--------|------|-----|------|------|---------|
| kaggle-01 | Kaggle | T4×2 | 免费 | pull | `kaggle/kaggle_setup.py`、`kaggle_voxcpm2_test_fixed.ipynb` |
| paddle-01 | 百度云 | V100 | 免费 | pull | `paddle/paddle_job_entry.py` |
| modelscope-01 | 魔搭社区 | T4/V100 | 免费 | pull | `modelscope/modelscope_worker.py`、`modelscope_voxcpm2_turnkey.ipynb` |
| modal-01 | Modal | T4 | ~$0.73/h | push | `modal/modal_app.py` |
| lightning-01 | Lightning | T4 | ~$1.2/h | pull | `lightning/lightning_work.py` |
| colab-01 | Google Colab | T4 | 免费 | pull | `colab/colab_setup.py`、`colab/colab_worker.py` |

任一 Worker 共用同一套协议：连接 Redis (`tts:tasks` 队列) → 下载并加载 VoxCPM2 到 GPU →
`BLPOP` 拉取任务 → 合成音频上传 Cloudflare R2 → `RPUSH tts:results` 回写结果。

### 11.1 配置 ModelScope（魔搭社区免费 GPU）

魔搭社区 https://modelscope.cn 提供带免费单卡 GPU（T4/V100/A100，按当日配额）的 Notebook，
与 Kaggle/Paddle 节点对等接入算力池，成本 0。

> ⚡ 快捷验证：直接用新增的 `modelscope_voxcpm2_turnkey.ipynb`（对标已成功的 Modal T4 smoke）
> 在魔搭 GPU 笔记本中一键跑完：注入令牌→下载模型→加载→合成→存 .wav。

**步骤：**

1. 打开 https://modelscope.cn → 「我的Notebook」→ 启动 GPU 实例（镜像建议 py3.10 + CUDA 11.x/12.x）。
2. （可选但推荐）用访问令牌加速/授权模型下载——令牌由 `os.environ` 注入，**不落库（红线#5）**：
   ```python
   import os
   os.environ["MODELSCOPE_API_TOKEN"] = "<REDACTED_MODELSCOPE_TOKEN>"  # 替换为你的 ms-... 令牌
   ```
   令牌在魔搭控制台创建，仅供云端运行会话使用，用后可轮换（rotate）。
3. 在终端克隆本仓库并进入目录：
   ```bash
   git clone <repo> && cd <repo>/voxcpm2-pool/modelscope
   ```
4. 注入 Secrets（红线#5：仓库不接受真实凭据）。新建 `.env` 或在 Notebook cell 中用 `os.environ` 注入：
   ```bash
   cat > .env <<'EOF'
   REDIS_HOST=casual-sawfish-86152.upstash.io
   REDIS_PORT=6379
   REDIS_AUTH=<在 Upstash 控制台获取真值>
   R2_ENDPOINT=https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com
   R2_ACCESS_KEY_ID=<在 Cloudflare 控制台获取真值>
   R2_SECRET_ACCESS_KEY=<在 Cloudflare 控制台获取真值>
   R2_BUCKET=audiobook-assets
   R2_PUBLIC_URL=https://pub-xxx.r2.dev
   WORKER_ID=modelscope-v100-01
   VOXCPM2_MS_REPO=openbmb/VoxCPM2,OpenBMB/VoxCPM2
   MODEL_CACHE=/mnt/workspace/VoxCPM2
   VOXCPM2_PIP=voxcpm==2.0.3
   EOF
   ```
4. 一键部署：
   ```bash
   ./deploy_modelscope.sh
   ```
5. 或在 Notebook 中分步执行（先用 `modelscope_voxcpm2_test.ipynb` 单机烟测，再 `exec(open("modelscope_worker.py").read())` 转入 Worker 模式）。

**模型下载策略（`modelscope_worker.py`）：**

- 方案 A：`modelscope.snapshot_download()` 内网直连（魔搭平台最快）
- 方案 B：HF 镜像 `hf-mirror.com` requests 逐文件下载（绕过 `huggingface_hub` HEAD bug，Kaggle V5 已验证可行）

**兼容性补丁（与其它节点共用）：**

- `torch.load` 强制 `weights_only=False`（PyTorch 2.6+ 兼容）
- `torch.nn.attention.flex_attention.BlockMask` 注入 Dummy 类（PyTorch 2.5+ 与 transformers 类型提示冲突）
- `generate()` 统一包装：兼容官方 `text=` / 项目源码 `target_text=` 两种签名
- `config.json` 修复：补 `model_type=voxcpm2`、`dtype=float16`

### 11.2 全平台部署

```bash
cd voxcpm2-pool && ./deploy_all.sh    # 一键部署所有节点 + Pool API + 烟测
```

`deploy_all.sh` 依次部署 Modal / Lightning / Paddle / **ModelScope** / Pool API，
最后运行 `smoke_test.py` 对所有平台提交烟测任务并校验 WAV。

> ⚠️ 免费节点（Kaggle / Paddle / ModelScope）无持久公网 IP，重启需重新下载+加载模型，
> 适合开发与算力池的拉模式节点；生产环境建议 Modal (A10G/V100) + 固定端点。

### 11.3 相关文件

| 文件 | 说明 |
|------|------|
| `voxcpm2-pool/modelscope/modelscope_worker.py` | 自包含 Worker 入口（下载→加载→队列→合成→上传） |
| `voxcpm2-pool/modelscope/modelscope_setup.py` | 配置与 Secrets 注入脚本（占位化） |
| `voxcpm2-pool/modelscope/deploy_modelscope.sh` | 一键部署脚本 |
| `voxcpm2-pool/modelscope/requirements.txt` | 依赖清单（幂等补装） |
| `modelscope_voxcpm2_test.ipynb` | 单机 GPU 烟测 Notebook（对照 `kaggle_voxcpm2_test_fixed.ipynb`） |
| `modelscope_voxcpm2_turnkey.ipynb` | turnkey 一键验证 Notebook（含令牌下载、T4/V100 合成，对标 Modal smoke） |
| `voxcpm2-pool/pool/pool_config.yaml` | 算力池节点清单（含 modelscope-01） |
| `voxcpm2-pool/worker/worker.py` | 供 Modal/Lightning 复用的核心 Worker 逻辑 |

### 11.4 配置 Modal（model.com，GPU T4 按量节点）

Modal（[modal.com](https://modal.com)）提供 Serverless GPU（T4 16GB，约 $0.73/h，按秒计费、空闲 scale-to-zero）。
将已验证的 Kaggle / ModelScope voxcpm2 推理链路同步到 Modal T4 节点：

**参考实现：** `voxcpm2-pool/modal/modal_app.py`（完全镜像 `modelscope_worker.py` 的验证逻辑）

**依赖的选择来自 Kaggle V208 验证（非 FunASR / 非 AutoModelForCausalLM）：**
- 官方推理库 `voxcpm==2.0.3` + `VoxCPM.from_pretrained(load_denoiser=False)`
- 模型下载：ModelScope SDK 内网直连优先，`hf-mirror.com` requests 逐文件兜底（绕过 HEAD bug）
- 兼容补丁：`torch.load weights_only=False` + `flex_attention.BlockMask` Dummy
- 采样率 48kHz、`generate(text=, cfg_value=2.0, inference_timesteps=10)`

**本机一键部署（T4）：**

```bash
# 1. 安装并登录 Modal 本地 CLI
pip install -U modal
modal token set <token-id> <secret>

# 2. 部署（会注入占位 secrets 并 push）
cd voxcpm2-pool/modal
bash deploy_modal.sh

# 3. 本机冒烟（触发一次云端冷启验证）
modal run modal_app.py
```

> ⚠️ 红线#5：`deploy_modal.sh` / `secrets_setup.py` 内为占位符。
>    部署前请在 Modal 控制台创建 secret `audiobook-config` 并填入轮换后的真值，
>    或在脚本中替换 `<REDACTED_*>` 后再执行。存储、Redis、R2 需与其它节点一致
>    （Upstash Redis + Cloudflare R2）。

**与免费节点（Kaggle/ModelScope）区别：**

| 维度 | Kaggle/ModelScope | Modal |
|------|-------------------|-------|
| GPU | T4×2 / V100（免费） | T4（按秒计费） |
| 公网端点 | 无持久 IP | 固定端点 + 自动扩缩 |
| 常驻 | 需手动保活 | Serverless scale-to-zero |
| 适用 | 开发 / 免费算力 | 生产 / 突发补位（push） |

### 11.4 实测记录（modelscope-01）

**2026-08-17** 在魔搭社区 PAI DSW 免费 GPU 上实地部署 VoxCPM2 并产出音频，节点 `modelscope-01` 标记 `verified: true`。

| 项 | 值 |
|----|-----|
| 实例 | PAI DSW（魔搭免费 GPU） |
| 分配 GPU | NVIDIA A10, 23.8 GB VRAM |
| 环境 | conda `voxcpm` (Python 3.10.20) + torch 2.5.1+cu118 + voxcpm 2.0.3 |
| 模型缓存 | `/mnt/workspace/VoxCPM2` (NAS 持久化, 4.58 GB, 不随重启丢失) |
| 加载耗时 | 32.5s, `sr=48000` Hz, `dtype=bfloat16` |
| 产出 | 3 段 wav (英/中/英): 3.84s / 6.88s / 4.16s |
| 平均 RTF | 0.950 (`optimize=False`，未开 `torch.compile`) |
| 文件 | `/mnt/workspace/voxcpm2_modelscope_test_*.wav` |

**optimize=True 实测对比（2026-08-17，同 A10）——确认负优化，保持 optimize=False：**

| 配置 | 稳态 RTF | 说明 |
|------|---------|------|
| `optimize=False` | **0.784** | ✅ 默认，最优 |
| `optimize=True` warmup | 0.915（+86s 编译） | torch.compile 一次性开销 |
| `optimize=True` 稳态 | **0.914** | ✗ 比基线慢 14%（it/s 7.83→6.76） |
| 加速比 | **0.86x** | `torch.compile` 在 A10+cu118+此模型得不偿失 |

决策：worker/turnkey 默认 `optimize=False`。真正可挖的加速点是 TF32（torch 亲口提示 `TensorFloat32 tensor cores ... available but not enabled` → `torch.set_float32_matmul_precision('high')`），见 `modelscope_benchmark_tf32.py`。

**TF32 实测对比（2026-08-17，同 A10）——TF32 无收益，调速靠降步数：**

| 档 | 配置 | 稳态 RTF | vs 基线 |
|----|------|---------|--------|
| A | 默认 highest, steps=10 | 0.790 | 1.00x |
| B | TF32 high, steps=10 | 0.796 | 0.99x（TF32 无效） |
| C | TF32 high, steps=8 | 0.698 | 1.13x（增速来自降步数，非 TF32） |

决策：
- TF32 在 VoxCPM2 无收益（扩散循环非 float32 matmul 主导，bf16 主路径不走 TF32）→ **不开 `set_float32_matmul_precision`，保持默认 highest**。
- 真正的调速旋钮是 `inference_timesteps`（10→8 实测 1.13x）。worker/turnkey 均支持通过环境变量 `VOXCPM2_INFERENCE_TIMESTEPS` 或任务 `prosody.steps` 调整。质量需试听 `voxcpm2_tf32_C_*.wav` 校验。

**实测踩坑与修复（已沉淀到 `modelscope_deploy_turnkey.py`）：**

1. **Python 3.8 陷阱**：PAI DSW 默认 `/opt/conda/bin/python3` 是 3.8.16，而 `voxcpm 2.x` 要求 ≥3.10。pip 会静默 `No matching distribution`，跑到 `from voxcpm import VoxCPM` 才 `ModuleNotFoundError`。
   → turnkey 脚本顶部加 `sys.version_info < (3,10)` 硬拦截 + 打印建环境三步指引。
2. **环境命令**（实测可用，一次成功）：
   ```bash
   conda create -y -n voxcpm python=3.10
   source activate voxcpm
   pip install -q torch==2.5.1 torchaudio --index-url https://download.pytorch.org/whl/cu118
   pip install -q voxcpm==2.0.3 modelscope huggingface_hub soundfile requests numpy einops safetensors transformers accelerate
   python /mnt/workspace/modelscope_deploy_turnkey.py
   ```
3. **ModelScope SDK 版本差异**：`snapshot_download` 新版用 `local_dir`、旧版用 `cache_dir`。turnkey 已做三参数兼容降级（不带参也能跑），并 HF 镜像 requests 兜底——实测 ModelScope SDK 在该 DSW 不可用，**HF 镜像兜底是实际生效路径**。
4. **采样率**：VoxCPM2 真实 `sample_rate=48000`（非早期假设 24000）。worker/turnkey 已从 `model.tts_model.sample_rate` 动态取，fallback 改为 48000。
5. **config.json**：真实 `dtype=bfloat16`、无 `model_type` 字段。`fix_config()` 只补 `model_type`、**不强改 dtype**（强改 float16 会被官方 BF16 加载路径拒绝）。
6. **GPU 实配**：本日分配到 A10 23.8GB（优于 T4），`pool_config` 已扩充候选 `[T4,V100,A10,A100]`。

### 11.5 配置 Google Colab（免费 T4 GPU）

Colab 免费 T4（16GB VRAM）接入算力池，与已验证的 `modelscope-01` 完全同构（协议：`BLPOP tts:tasks` → 合成 → 上传 R2 → `RPUSH tts:results`）。
由 `deploy_colab.sh` 给出分步指引；`colab_worker.py` 已对标 Modelscope worker，同步了 A10 实测结论。

**步骤（在 Colab 浏览器中）：**
1. `colab.research.google.com` → New Notebook → Runtime → Change runtime type → **T4 GPU**（验证 `!nvidia-smi`）。
2. Cell 执行 `colab_setup.py` 内容（装 CUDA 依赖 + 挂载 Drive + 注入 Secrets 占位 + 下载模型）。
3. 最后一个 Cell 执行 `colab_worker.py` 内容（启动 Worker，`BLPOP` 监听 `tts:tasks`）。

**本仓库本轮对齐改动（colab_worker.py）：**
- 采样率 fallback `24000 → 48000`（对齐 A10 实测；`getattr(model.tts_model, "sample_rate", 48000)` + 源码回退路径同样 48000）。
- 新增调速环境变量入口 `VOXCPM2_INFERENCE_TIMESTEPS`（默认 10），worker/turnkey/colab 三端统一；
  任务内仍以 `prosody.steps` 优先覆盖（协议已含）。

**凭据接入（红线#5）：**
- Colab 通过 Google Drive 持久化模型（`/content/VoxCPM2`）；Upstash Redis / Cloudflare R2 真值需在 Cell 中 `os.environ` 注入，
  **不落库**。注入方式与 `modelscope_deploy_turnkey.py` / `docs §11.1` 一致。

> ⚠️ Colab 免费 Session 最多 12h（Pro 24h），断开后需重跑 Cell 2-5。
> 节点 `colab-01` 暂标 `verified: false`，与已验证的 `modelscope-01` 区分——在 Colab 实跑产出音频后可标记 `verified: true`。

### 11.5 ModelScope-Agent / MCP 生态扩展（可选）

在 PAI DSW 直跑 Worker 已验证可用的基础上，若需接入魔搭官方的 **Agent 互联 / MCP 广场**，提供两条现成脚手架，均复用已验证的 DSW 环境（模型在 NAS、voxcpm conda env 就绪）。

#### 11.5.1 MCP Server —— 让外部 Agent 通过标准协议调用 VoxCPM2

文件：`voxcpm2-pool/modelscope/modelscope_mcp_tts_server.py`（~174 行，FastAPI + mcp SDK）

暴露工具：`generate_tts(text, voice, steps, cfg)` → 返回 base64 WAV + 元信息

**在 DSW 运行**：
```bash
# 1) 装 mcp SDK（在 voxcpm 环境内）
pip install "mcp[cli]" fastapi uvicorn

# 2) 可选：调速
export VOXCPM2_INFERENCE_TIMESTEPS=10

# 3) 启动
python /mnt/workspace/modelscope_mcp_tts_server.py
# -> 监听 0.0.0.0:8000/mcp (SSE)
```

**对外暴露**（二选一）：
- DSW 自带公网 IP + 安全组放行 8000
- `ngrok http 8000` → 得到 `https://xxx.ngrok-free.app`，填入 ModelScope-Agent `mcp_servers` 配置或 MCP 广场登记

**Agent 调用示例**（JSON-RPC over MCP）：
```json
{
  "tool": "generate_tts",
  "arguments": {"text": "你好，MCP 互联测试。", "steps": 8}
}
```

#### 11.5.2 创空间 Gradio Demo —— 零运维、免费 xGPU 自动冷启动

目录：`spaces/voxcpm2/`（`app.py` + `requirements.txt` + `README.md`）

**部署步骤**：
1. 魔搭网页 → 创空间 → 新建空间 → 选 **Gradio** / **Python** / **GPU: xGPU(免费)**
2. 克隆空间仓库，推送三个文件：
   - `app.py`（Gradio 界面 + 模型加载逻辑，自动兜底下载）
   - `requirements.txt`
   - `README.md`（自动生成模型卡片）
3. **持久化模型权重**（关键，避免冷启动重下 4.58GB）：
   - 先在魔搭上传 `OpenBMB/VoxCPM2` 为私有数据集/模型
   - 空间设置 → **挂载数据集/模型** → 选该资源 → 挂载到 `/mnt/data/VoxCPM2`
   - 代码自动检测 `/mnt/data/VoxCPM2`
4. 环境变量（空间设置 → 环境变量）：
   - `VOXCPM2_INFERENCE_TIMESTEPS=10`（默认 10，8 约 1.13x 提速）
   - `HF_ENDPOINT=https://hf-mirror.com`

**本地调试**：
```bash
pip install -r requirements.txt
python app.py  # http://localhost:7860
```

**创空间自动给出固定 HTTPS 域名**，即刻可分享/嵌入。

---

> **路径选择提示**：
> - 只想**自己在 DSW 里跑 Worker、接 Redis 队列** → 已完成，无需额外操作
> - 想让**别的 Agent / 用户通过标准 MCP 协议调用** → 跑 11.5.1 的 MCP Server
> - 想**零运维对外发布一个可玩的 Web Demo** → 推 11.5.2 到创空间
> - 三者**互不冲突、可叠加**，模型权重复用同一份 NAS 缓存

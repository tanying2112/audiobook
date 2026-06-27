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
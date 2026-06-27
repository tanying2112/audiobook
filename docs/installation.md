# 安装指南

本文档提供 Audiobook Studio 的详细安装步骤，支持多种安装方式。

## 系统要求

### 最低要求
- **Python**: 3.11 或更高版本
- **内存**: 4GB RAM
- **磁盘空间**: 10GB 可用空间
- **操作系统**: Linux / macOS / Windows (WSL2 推荐)

### 推荐配置
- **Python**: 3.12+
- **内存**: 16GB RAM
- **GPU**: NVIDIA GPU (8GB+ 显存) - 用于本地 TTS
- **磁盘空间**: 50GB SSD

## 安装方式

### 方式一：从源码安装（推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/audiobook-studio/audiobook.git
cd audiobook

# 2. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows

# 3. 安装依赖
pip install -r requirements.txt

# 4. 安装预提交钩子（可选）
pre-commit install

# 5. 验证安装
python -m src.audiobook_studio --version
```

### 方式二：Docker 安装

```bash
# 1. 拉取镜像
docker pull ghcr.io/audiobook-studio/audiobook:latest

# 2. 运行容器
docker run -it --rm \
  -v $(pwd)/output:/app/output \
  -e ANTHROPIC_API_KEY=your_key \
  ghcr.io/audiobook-studio/audiobook:latest
```

### 方式三：Docker Compose（推荐用于开发）

```bash
# 1. 编辑 docker-compose.yml（如需要）
cp docker-compose.yml.example docker-compose.yml

# 2. 启动服务
docker compose up -d

# 3. 查看日志
docker compose logs -f

# 4. 停止服务
docker compose down
```

## 环境配置

### 环境变量

创建 `.env` 文件在项目根目录：

```bash
# LLM API 配置
ANTHROPIC_API_KEY=sk-ant-xxx
OPENROUTER_API_KEY=sk-or-xxx

# TTS 引擎配置
KOKORO_VOICE=default
EDGE_TTS_VOICENAME=zh-CN-XiaoxiaoNeural

# 数据库配置
DATABASE_URL=sqlite:///./audiobook.db

# Langfuse 监控（可选）
LANGFUSE_PUBLIC_KEY=pk-lf-xxx
LANGFUSE_SECRET_KEY=sk-lf-xxx
```

### 硬件配置文件

编辑 `config/hardware_profile.yaml` 选择合适的运行模式：

```yaml
# 土豆模式 - 无 GPU、断网可用
mode: potato
llm:
  provider: local
  model: Qwen2.5-3B-GGUF
tts:
  engine: kokoro-onnx

# 云端模式 - 默认配置
mode: cloud-hybrid
llm:
  provider: openrouter
  models:
    - poolside/laguna-m.1:free
    - deepseek/deepseek-chat:free
tts:
  engine: edge-tts

# 专业模式 - 独显/云算力
mode: pro-studio
llm:
  provider: anthropic
  model: claude-sonnet-4-5-20250929
tts:
  engine: cosyvoice
  voice_clone: true
```

## 验证安装

```bash
# 运行健康检查
python -m src.audiobook_studio.health

# 运行测试套件
pytest tests/unit/ -v

# 测试 TTS 引擎
python tests/e2e/test_tts.py --dry-run
```

### 预期输出

```
✓ Python 版本检查通过 (3.12.x)
✓ 依赖包版本检查通过
✓ 数据库连接正常
✓ TTS 引擎初始化成功 (kokoro)
✓ LLM 路由配置正常

安装完成！运行 `python -m src.audiobook_studio` 开始使用。
```

## 故障排查

### 常见问题

**问题 1: `ModuleNotFoundError: No module named 'xxx'`**
```bash
# 重新安装依赖
pip install -r requirements.txt --upgrade
```

**问题 2: `Could not find a version that satisfies the requirement`**
```bash
# 更新 pip
pip install --upgrade pip
# 或使用国内镜像
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**问题 3: Kokoro TTS 加载失败**
```bash
# 单独安装 Kokoro 依赖
pip install kokoro-onnx
# 或切换到 Edge TTS
export KOKORO_ENABLED=false
```

## 下一步

- [快速开始](quick_start.md) - 开始第一个项目
- [架构设计](architecture.md) - 了解系统架构
- [配置参考](quick_start.md#配置) - 详细配置说明
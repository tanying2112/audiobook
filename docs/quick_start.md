# 快速开始指南

> **🎯 5分钟内完成首个有声书制作** — 本指南提供从零开始制作你的第一个有声书的最快路径。

本指南帮助你在本地快速启动 **Audiobook Studio**，包括开发环境的搭建、数据库初始化以及运行 FastAPI 服务的完整步骤。文档假设你使用 macOS（或类 Unix 系统），如果你更倾向于 Docker 部署，也提供相应的指令。

---

## 1. 前置条件

| 条件 | 说明 |
|------|------|
| **Python** | 3.10 以上（推荐 3.11）。确保 `python3` 可在终端直接调用。 |
| **Git** | 用于克隆仓库。 |
| **Virtualenv** | 推荐使用 `venv` 或 `conda` 隔离依赖。 |
| **Docker** *(可选)* | 若想使用容器化部署，请确保已安装 Docker Desktop 并启动。 |
| **环境变量** | 项目根目录下提供了 `.env.example`，请复制为 `.env` 并根据需要填写。 |

> **提示**：如果你使用 `pyenv` 管理 Python 版本，请先执行 `pyenv install 3.11` 并在项目根目录运行 `pyenv local 3.11`。

---

## 2. 克隆仓库并准备工作目录

```bash
# 克隆代码仓库（请替换为实际的仓库地址）
git clone https://github.com/audiobook-studio/audiobook.git
cd audiobook
```

### 2.1 创建并激活虚拟环境

```bash
# 使用系统自带的 venv
python3 -m venv .venv
source .venv/bin/activate   # macOS / Linux
# Windows: .venv\Scripts\activate
```

### 2.2 安装项目依赖

```bash
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

> **注意**：`requirements.txt` 已经锁定了兼容的库版本，安装过程可能会下载约 30 MB 的依赖。

---

## 3. 环境变量配置

项目根目录下有一个示例文件 `.env.example`，请复制为实际使用的 `.env` 并根据需要修改其中的变量（如数据库路径、LLM API Key 等）。

```bash
cp .env.example .env
# 使用编辑器打开 .env 并填写你的密钥等信息
open .env   # macOS 使用默认编辑器打开
```

目前项目默认使用 SQLite 本地文件 `data/audiobook.db`，如果你想使用其他数据库，只需在 `.env` 中修改 `DATABASE_URL` 并确保相应驱动已安装。

---

## 4. 初始化数据库

项目提供了一个简单的数据库初始化函数 `init_db()`，在应用启动时会自动创建表。如果你想手动执行一次以确保表结构已经创建，可运行：

```bash
python -c "from src.audiobook_studio.database import init_db; init_db()"
```

运行后会在 `data/` 目录生成 `audiobook.db`（如果不存在）。

---

## 5. 启动 FastAPI 服务

### 5.1 开发模式（带自动重载）

```bash
uvicorn src.audiobook_studio.main:app --reload --host 0.0.0.0 --port 8000
```

启动后，打开浏览器访问 <http://127.0.0.1:8000/docs> 即可看到自动生成的 OpenAPI 文档。

### 5.2 生产模式（单进程）

```bash
uvicorn src.audiobook_studio.main:app --host 0.0.0.0 --port 8000
```

如果需要多工作进程（例如在高并发场景），可以使用 `--workers N` 参数。

---

## 6. 使用 Docker（可选）

项目已经提供了 `Dockerfile`，可以直接构建镜像并运行容器。

### 6.1 构建镜像

```bash
docker build -t audiobook-studio .
```

### 6.2 运行容器

```bash
docker run -d \
	-p 8000:8000 \
	-v $(pwd)/data:/app/data \
	--name audiobook-studio \
	audiobook-studio
```

	- `-v $(pwd)/data:/app/data` 将宿主机的 `data/` 目录挂载到容器内部，保证 SQLite 数据库持久化。
	- 访问 <http://localhost:8000/docs> 查看 API 文档。

## 7. API 使用示例

下面提供常用的 **curl** 与 **HTTPie** 示例，帮助你快速验证各接口。所有请求均返回 **JSON**，并遵循标准的 HTTP 状态码。

### 7.1 创建一本书

```bash
# 使用 curl
curl -X POST http://127.0.0.1:8000/books/ \
	-H "Content-Type: application/json" \
	-d '{"title": "示例书名", "author": "作者", "language": "zh", "isbn": "1234567890"}'

# 使用 HTTPie（更友好）
http POST http://127.0.0.1:8000/books/ title="示例书名" author="作者" language="zh" isbn="1234567890"
```

### 7.2 查询书籍列表

```bash
curl http://127.0.0.1:8000/books/?skip=0&limit=10
```

### 7.3 为段落创建 TTS 编辑

假设已有 `paragraph_id` 为 `1`，可以这样创建一个 TTS 编辑记录：

```bash
http POST http://127.0.0.1:8000/tts_edits/ paragraph_id=1 edited_text="修改后的文本" voice="zh-CN-XiaoxiaoNeural"
```

### 7.4 获取质量评估列表

```bash
curl http://127.0.0.1:8000/qualities/?skip=0&limit=5
```

> **提示**：在实际项目中，你可以把这些请求封装到脚本或前端页面中，实现完整的有声书工作流。

---

## 7. 常见问题排查

| 场景 | 可能原因 | 解决方案 |
|------|----------|----------|
| **启动报错 `ModuleNotFoundError`** | 虚拟环境未激活或依赖未安装 | 确认已 `source .venv/bin/activate` 并重新执行 `pip install -r requirements.txt` |
| **数据库文件未生成** | `data/` 目录不存在或没有写权限 | 手动创建 `mkdir -p data` 并确保当前用户拥有写权限 |
| **Docker 启动后 404** | 容器内部未映射端口或 `uvicorn` 未启动 | 检查 `docker logs audiobook-studio`，确认 `uvicorn` 正在运行并监听 `0.0.0.0:8000` |
| **API 文档为空** | `pydantic` 模型未正确导入 | 确认 `src/audiobook_studio/api/*.py` 中的 `router` 已在 `main.py` 中 `include_router` |

---

## 8. 下一步

完成本地启动后，你可以继续阅读以下文档以深入了解项目功能：

* `docs/architecture.md` – 项目整体架构概览
* `docs/api.md` – 完整的 API 参考手册
* `docs/agents.md` – 本项目使用的 AI Agent 规范
* `docs/agents/collaboration.md` – 多 Agent 协作规范、任务接手、云上 VPS 与本地 Agent 混合协作流程
* `docs/harness_specifications.md` – LLM 马具（Harness）设计规范

## 5分钟快速制作首个有声书

### 🚀 一键制作流程

**前提**: 已完成上述安装步骤

### 步骤 1: 准备文本文件

```bash
# 创建示例文本 (或者上传自己的 EPUB/TXT/Markdown)
echo "这是第一章的第一段落。这是一段测试文本，用于制作有声书演示。" > data/test_novel.txt
echo "这是第二段落。我们将从这个文本开始创作。" >> data/test_novel.txt
```

### 步骤 2: 创建项目并启动

```bash
# 启动 API 服务 (新终端)
uvicorn src.audiobook_studio.main:app --reload

# 创建书籍项目
curl -X POST http://localhost:8000/api/projects/ \
  -H "Content-Type: application/json" \
  -d '{"title": "我的第一本有声书", "author": "Audiobook Studio"}'
```

### 步骤 3: 运行完整管线 (Mock 模式, 5分钟完成)

```bash
# 设置 Mock 模式 (无需 API Key, 使用内置模拟)
export MOCK_LLM=true

# 运行完整管线
curl -X POST http://localhost:8000/api/auto-run/ \
  -H "Content-Type: application/json" \
  -d '{
    "book_path": "data/test_novel.txt",
    "target_difficulty": "B",
    "quality_threshold": 0.7
  }'
```

### 步骤 4: 下载成品

```bash
# 几分钟后, 下载 M4B 文件
curl -X POST http://localhost:8000/api/export/ \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": 1,
    "format": "m4b",
    "include_srt": true,
    "include_cover": true
  }' \
  --output my_first_audiobook.m4b
```

### 🎤 声音克隆 (可选)

要使用自定义声音:

```bash
# 准备 15秒清晰语音样本
# 上传并克隆声音
python -m audiobook_studio.tts.clone \
  --name "my_voice" \
  --sample /path/to/sample.wav
```

### 📊 检查进度

```bash
# 查看管线状态
curl http://localhost:8000/api/auto-run/1/status

# 查看质量报告
curl http://localhost:8000/api/quality/
```

**恭喜!** 你已制作完成第一本有声书! 🎉

---

## 9. 下一步

完成本地启动后，你可以继续阅读以下文档以深入了解项目功能：

* `docs/architecture.md` – 项目整体架构概览
* `docs/api.md` – 完整的 API 参考手册
* `docs/agents.md` – 本项目使用的 AI Agent 规范
* `docs/agents/collaboration.md` – 多 Agent 协作规范、任务接手、云上 VPS 与本地 Agent 混合协作流程
* `docs/harness_specifications.md` – LLM 马具（Harness）设计规范
* `docs/deployment.md` – 生产环境部署指南

祝你开发愉快 🎧
"

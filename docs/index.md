# Audiobook Studio Documentation

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/FastAPI-0.110+-green.svg" alt="FastAPI Version">
  <img src="https://img.shields.io/badge/SQLAlchemy-2.0+-orange.svg" alt="SQLAlchemy Version">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/Tests-683%20passed-brightgreen.svg" alt="Tests">
  <img src="https://img.shields.io/badge/Coverage-72%25-blue.svg" alt="Coverage">
</div>

---

## 🎯 项目概览

**Audiobook Studio** 是一站式有声书制作平台，基于 **HARNESS 三层架构**（契约层/执行层/评估层）设计，提供从文本提取到成品 M4B/SRT 的完整自动化流水线。

### 核心特性

| 模块 | 功能 | 状态 |
|------|------|------|
| **文本提取** | PDF/EPUB/TXT 多格式解析，OCR 兜底 | ✅ 完备 |
| **结构语义工程** | 角色声纹绑定、情感快照、故事线摘要 | ✅ 完备 |
| **段落分析** | 14 种情感、语速/音高/停顿/SFX 标注 | ✅ 完备 |
| **文本编辑** | TTS 友好化：断句、符号归一、敏感词过滤 | ✅ 完备 |
| **音频合成** | Kokoro/Edge TTS 路由、本地声音克隆 | ✅ 完备 |
| **质量检测** | LLM-as-Judge：情绪/卡顿/无声/截断检测 | ✅ 完备 |
| **多语言配音** | 保留角色/情绪映射、语义连贯性校验 | ✅ 完备 |
| **导出发布** | M4B(章节标记/AAC/loudnorm) + SRT/VTT + RSS + Audiobookshelf | ✅ 完备 |

### 关键指标

| 指标 | 目标 | 当前 |
|------|------|------|
| 测试覆盖率 (Pipeline) | ≥80% | **90%** |
| 测试覆盖率 (API) | ≥80% | **89%** |
| LLM 格式合规率 | ≥99% | **99%** |
| 角色音色一致性偏差 | <15% | **<10%** |
| 情感命中率 | ≥0.75 | **0.93** |
| 单本成本 (5万字) | ≤$20 | **~$0 (mock)** |
| 端到端成功率 | ≥99% | **99% (E2E通过)** |
| CI 反馈时间 | <5 min | **~3 min** |

---

## 🚀 快速开始

```bash
# 1. 克隆并进入
git clone https://github.com/audiobook-studio/audiobook.git
cd audiobook

# 2. 创建虚拟环境
python3 -m venv .venv
source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env 填入必要的 API Key

# 5. 初始化数据库
python -c "from src.audiobook_studio.database import init_db; init_db()"

# 6. 启动服务
uvicorn src.audiobook_studio.main:app --reload --host 0.0.0.0 --port 8000

# 7. 访问 API 文档
open http://127.0.0.1:8000/docs
```

> 📖 详细步骤见 [快速开始指南](quick_start.md)

---

## 📚 文档导航

| 页面 | 说明 |
|------|------|
| [快速开始](quick_start.md) | 5 分钟从零跑通本地开发环境 |
| [系统架构](architecture.md) | 6 阶段管线、数据流、存储布局、HARNESS 三层设计 |
| [API 参考](api.md) | 完整的 REST API 端点、请求/响应示例、错误码 |
| [Agent 开发指南](agents.md) | 多 Agent 协作规范、角色模型、任务状态、交接流程 |
| [马具规范](harness_specifications.md) | LLM 契约/执行/评估三层架构、提示词模版、黄金数据集、自动进化 |
| [贡献指南](contributing.md) | 代码规范、测试要求、PR 流程、发布规范 |

---

## 🏗️ 核心架构一览

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Audiobook Studio                              │
├─────────────────────────────────────────────────────────────────────┤
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐            │
│  │ Projects │  │ Chapters │  │Paragraphs│  │  Audio   │  ← DB层   │
│  │ (书籍)   │  │ (章节)   │  │ (段落)   │  │  (音频)  │             │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘            │
├─────────────────────────────────────────────────────────────────────┤
│  Pipeline: extract → analyze → annotate → edit → audio_post →       │
│            synthesize → quality  (+ translate)                      │
├─────────────────────────────────────────────────────────────────────┤
│  HARNESS: Contract(Pydantic) → Execution(Instructor+LiteLLM) →      │
│           Evaluation(LLM-as-Judge + Golden Dataset + Feedback)       │
├─────────────────────────────────────────────────────────────────────┤
│  Storage: storage/books/{id}/{raw,extracted,annotated,audio,reports}/│
│  Export: M4B(ffmpeg) + SRT/VTT + RSS + Audiobookshelf               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🧪 质量保障

- **单元测试**: 683 passed, pipeline 模块 90% 覆盖
- **黄金数据集**: 7 个阶段 × ≥3 种子用例，CI 自动回归
- **合规监控**: 契约版本管理、99% 合规率阈值、质量阈值 YAML 外部化
- **CI 质量闸门**: 覆盖率 ≥70% (核心模块) / Golden ≥95% / Compliance ≥99%

---

## 📦 部署方式

| 方式 | 适用场景 | 文档 |
|------|----------|------|
| **Docker 单机** | 开发/测试/小规模 | [Dockerfile](Dockerfile) |
| **Docker Compose** | 本地完整栈 (API+DB+前端) | `docker-compose.yml` |
| **Kubernetes** | 生产集群部署 | `k8s/` (规划中) |
| **GitHub Actions** | CI/CD 自动构建推送 | `.github/workflows/release.yml` |

---

## 🔗 相关链接

- [GitHub Repository](https://github.com/audiobook-studio/audiobook)
- [Issue Tracker](https://github.com/audiobook-studio/audiobook/issues)
- [Changelog](CHANGELOG.md)
- [项目日志](PROJECT.md)
- [开发计划](DEVELOPMENT_PLAN.md)
- [执行清单](EXECUTION_CHECKLIST.md)

---

<div align="center">
  <strong>Audiobook Studio</strong> — 让有声书制作变得简单、可控、可迭代<br>
  Built with ❤️ using FastAPI, SQLAlchemy, LiteLLM, Kokoro-ONNX
</div>
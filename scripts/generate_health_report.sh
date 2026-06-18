#!/usr/bin/env bash
# 生成项目健康报告，供 CI 引用
# 输出 PROJECT_HEALTH.md

set -euo pipefail

cat > PROJECT_HEALTH.md <<'EOF'
# Audiobook Studio — 项目健康报告

**生成时间**: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
**Git 提交**: $(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
**分支**: $(git branch --show-current 2>/dev/null || echo "unknown")

---

## 1. 代码结构

| 指标 | 数值 | 状态 |
|------|------|------|
| Python 源文件数 | $(find src -name "*.py" 2>/dev/null | wc -l | tr -d ' ') | $([ $(find src -name "*.py" 2>/dev/null | wc -l) -gt 0 ] && echo "✅" || echo "❌") |
| 测试文件数 | $(find tests -name "test_*.py" -o -name "*_test.py" 2>/dev/null | wc -l | tr -d ' ') | $([ $(find tests -name "test_*.py" -o -name "*_test.py" 2>/dev/null | wc -l) -gt 0 ] && echo "✅" || echo "❌") |
| Prompt 模板数 | $(find prompts -name "*.j2" -o -name "*.txt" 2>/dev/null | wc -l | tr -d ' ') | $([ $(find prompts -name "*.j2" -o -name "*.txt" 2>/dev/null | wc -l) -gt 0 ] && echo "✅" || echo "❌") |
| 黄金数据集用例数 | $(find tests/golden -name "*.jsonl" 2>/dev/null | wc -l | tr -d ' ') | $([ $(find tests/golden -name "*.jsonl" 2>/dev/null | wc -l) -gt 0 ] && echo "✅" || echo "⚠️") |

---

## 2. 依赖与环境

| 依赖 | 版本 | 状态 |
|------|------|------|
| Python | $(python3 --version 2>&1) | ✅ |
| FastAPI | $(pip show fastapi 2>/dev/null | grep Version | awk '{print $2}' || echo "未安装") | $([ "$(pip show fastapi 2>/dev/null | grep Version | awk '{print $2}')" != "" ] && echo "✅" || echo "❌") |
| Pydantic | $(pip show pydantic 2>/dev/null | grep Version | awk '{print $2}' || echo "未安装") | $([ "$(pip show pydantic 2>/dev/null | grep Version | awk '{print $2}')" != "" ] && echo "✅" || echo "❌") |
| SQLAlchemy | $(pip show sqlalchemy 2>/dev/null | grep Version | awk '{print $2}' || echo "未安装") | $([ "$(pip show sqlalchemy 2>/dev/null | grep Version | awk '{print $2}')" != "" ] && echo "✅" || echo "❌") |
| LiteLLM | $(pip show litellm 2>/dev/null | grep Version | awk '{print $2}' || echo "未安装") | $([ "$(pip show litellm 2>/dev/null | grep Version | awk '{print $2}')" != "" ] && echo "✅" || echo "❌") |
| Instructor | $(pip show instructor 2>/dev/null | grep Version | awk '{print $2}' || echo "未安装") | $([ "$(pip show instructor 2>/dev/null | grep Version | awk '{print $2}')" != "" ] && echo "✅" || echo "❌") |
| Edge-TTS | $(pip show edge-tts 2>/dev/null | grep Version | awk '{print $2}' || echo "未安装") | $([ "$(pip show edge-tts 2>/dev/null | grep Version | awk '{print $2}')" != "" ] && echo "✅" || echo "❌") |
| Kokoro-ONNX | $(pip show kokoro-onnx 2>/dev/null | grep Version | awk '{print $2}' || echo "未安装") | $([ "$(pip show kokoro-onnx 2>/dev/null | grep Version | awk '{print $2}')" != "" ] && echo "✅" || echo "❌") |

---

## 3. 测试覆盖率

$(cd /Users/guwj/Desktop/AI_Lab/audiobook && pytest --cov=src --cov-report=term-missing 2>&1 | tail -20)

---

## 4. 关键目录完整性

| 目录 | 存在性 | 说明 |
|------|--------|------|
| src/audiobook_studio/llm/ | $([ -d src/audiobook_studio/llm ] && echo "✅" || echo "❌") | LLM 路由/客户端/评判 |
| src/audiobook_studio/pipeline/ | $([ -d src/audiobook_studio/pipeline ] && echo "✅" || echo "❌") | 6 环节编排脚本 |
| src/audiobook_studio/schemas/ | $([ -d src/audiobook_studio/schemas ] && echo "✅" || echo "❌") | 7 个 Pydantic 契约 |
| src/audiobook_studio/tts/ | $([ -d src/audiobook_studio/tts ] && echo "✅" || echo "❌") | TTS 引擎封装 |
| src/audiobook_studio/export/ | $([ -d src/audiobook_studio/export ] && echo "✅" || echo "❌") | M4B/字幕导出 |
| tests/golden/ | $([ -d tests/golden ] && echo "✅" || echo "❌") | 黄金数据集 |
| prompts/ | $([ -d prompts ] && echo "✅" || echo "❌") | Jinja2 模板 |
| checkpoints/ | $([ -d checkpoints ] && echo "✅" || echo "❌") | 断点续传 |
| logs/ | $([ -d logs ] && echo "✅" || echo "❌") | 结构化日志 |

---

## 5. 配置文件

| 文件 | 存在性 | 说明 |
|------|--------|------|
| .env.example | $([ -f .env.example ] && echo "✅" || echo "❌") | 环境变量模板 |
| .gitignore | $([ -f .gitignore ] && echo "✅" || echo "❌") | Git 忽略规则 |
| docker-compose.yml | $([ -f docker-compose.yml ] && echo "✅" || echo "❌") | 本地编排 |
| Dockerfile | $([ -f Dockerfile ] && echo "✅" || echo "❌") | 容器构建 |
| alembic.ini | $([ -f alembic.ini ] && echo "✅" || echo "❌") | 数据库迁移 |
| mkdocs.yml | $([ -f mkdocs.yml ] && echo "✅" || echo "❌") | 文档站点 |

---

## 6. 最近 Git 提交

$(git log --oneline -10 2>/dev/null || echo "无 Git 历史")

---

*报告由 scripts/generate_health_report.sh 自动生成*
EOF

echo "✅ PROJECT_HEALTH.md 已生成"
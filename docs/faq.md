# 常见问题解答 (FAQ)

> 本页收集 Audiobook Studio 使用过程中的常见问题与解答。

## 📋 目录

- [入门必读](#入门必读)
- [安装与配置](#安装与配置)
- [LLM 与 API 配置](#llm-与-api-配置)
- [Pipeline 执行](#pipeline-执行)
- [TTS 与音频](#tts-与音频)
- [前端与多轨编辑器](#前端与多轨编辑器)
- [CI/CD 与部署](#cicd-与部署)
- [故障排查](#故障排查)
- [贡献与社区](#贡献与社区)

---

## 入门必读

### Q1. Audiobook Studio 是做什么的？

**A**: Audiobook Studio 是一款从**文本到 M4B** 完整自动化的有声书制作平台。它通过 6 阶段流水线：

1. **抽取** → **结构分析** → **段落标注** → **TTS 编辑** → **TTS 路由** → **质量检测**

将 EPUB/TXT/Markdown 文件转换为带章节标记、SRT 字幕、背景音乐的 M4B 有声书。

### Q2. 与其他 TTS 工具（如 Edge TTS、ChatTTS）相比有什么优势？

| 优势 | 说明 |
|------|------|
| **多 LLM 拼装** | 主流引擎 + 自研 Kokoro，按段落难度智能路由 |
| **角色一致性** | Voice Anchor 跨章节锚定，避免声纹漂移 |
| **闭环反馈** | 质量不达标自动重生成 + 提示词自迭代 |
| **全栈 UI** | Vue 3 + WaveSurfer 多轨编辑器，可视化编辑 |
| **批量 + 成本** | 单本 ≤$20，5 万字级别成本可控 |

### Q3. 适合谁使用？

- ✅ 个人开发者快速制作有声书
- ✅ 内容创作团队批量生产
- ✅ 出版社数字化转型
- ✅ 教育领域无障碍内容
- ⚠️ 目前不推荐：商业配音（必须人工审核）

---

## 安装与配置

### Q4. 最低系统要求？

**A**: Python 3.11+, FFmpeg 4.0+, Node.js 18 (前端开发)。macOS/Linux/Windows (WSL2) 三平台均支持。生产环境建议 4 核 CPU + 8GB RAM + 100GB SSD。

### Q5. 安装失败 - "找不到 ffmpeg"

**A**:

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt-get update && sudo apt-get install -y ffmpeg

# Windows (WSL2)
sudo apt-get install -y ffmpeg

# 验证
ffmpeg -version
```

### Q6. 如何使用 PostgreSQL 而非 SQLite？

**A**: 修改 `.env`：

```bash
# 默认
DATABASE_URL=sqlite:///./audiobook.db

# 切换到 PostgreSQL
DATABASE_URL=postgresql://user:pass@localhost:5432/audiobook
```

然后运行迁移：

```bash
alembic upgrade head
```

### Q7. 端口冲突（8000 已被占用）

**A**:

```bash
# 方案 1: 换端口
uvicorn src.audiobook_studio.main:app --port 8001

# 方案 2: 杀掉占用进程
lsof -ti:8000 | xargs kill -9
```

---

## LLM 与 API 配置

### Q8. 必须配置哪些 LLM API Key？

**A**: 推荐至少配置以下之一（系统会自动 fallback）：

| 提供商 | 适用场景 | 成本 |
|--------|---------|------|
| **DeepSeek** | 中文处理首选 | ¥1/百万 token |
| **OpenAI (gpt-4o-mini)** | 英文处理 | $0.15/百万 token |
| **Ollama (本地 qwen2.5)** | 完全离线 | $0 |
| **Gemini Flash** | 多模态 | 免费额度 |

详见 [config/llm_providers.yaml](https://github.com/audiobook-studio/audiobook/blob/main/config/llm_providers.yaml)。

### Q9. 免费模型够用吗？

**A**: 是的。我们推荐组合：
- **annotation 角色识别**: Ollama qwen2.5 (本地、零成本)
- **edit 文案优化**: DeepSeek (中文极佳)
- **routing 路由决策**: Gemini Flash (免费额度充足)

免费模型存在速率限制，已通过 `quota_registry.py` 自动规避。

### Q10. 如何接入自定义 LLM？

**A**: 在 `src/audiobook_studio/llm/` 中实现 `LLMProvider` 接口：

```python
from audiobook_studio.llm.base import LLMProvider

class MyLLMProvider(LLMProvider):
    def call(self, prompt: str, **kwargs) -> str:
        # 您的实现
        return response

# 注册到 config/llm_providers.yaml
providers:
  my_llm:
    class: src.audiobook_studio.llm.my_provider:MyLLMProvider
    api_key_env: MY_LLM_API_KEY
```

### Q11. LLM 输出合规率 < 99% 怎么办？

**A**:

1. 检查提示词版本是否升级 (per `config/contract_versions.yaml`)
2. 在 `tests/golden/{stage}/` 中添加 "bad case" 示例
3. 启用 Circuit Breaker 自动降级到上一稳定版本
4. 查看 `reports/compliance/` 历史记录

---

## Pipeline 执行

### Q12. 如何跑一次完整的 Pipeline？

**A**: 通过 API 触发：

```bash
curl -X POST http://localhost:8000/api/pipeline/run \
  -H "Content-Type: application/json" \
  -d '{
    "book_id": "hongloumeng",
    "novel_path": "data/long_novel/hongloumeng.txt",
    "max_paragraphs": 100
  }'
```

或 CLI：

```bash
python -m audiobook_studio.main run \
  --book data/long_novel/hongloumeng.txt \
  --output output/
```

### Q13. 如何从断点继续（断点续传）？

**A**: Pipeline 自动支持 CheckpointManager：

```bash
# 第一次运行
python -m audiobook_studio.main run --book novel.txt

# 中断 (Ctrl+C) 后继续
python -m audiobook_studio.main run --book novel.txt --resume
```

### Q14. 6 个阶段可以单独跑吗？

**A**: 可以，每个阶段都是独立的：

```python
from audiobook_studio.pipeline import (
    extract_text, analyze_structure, annotate_paragraph,
    edit_for_tts, synthesize_paragraphs, quality_check,
)

text = extract_text(novel_path="data/x.txt")
analysis = analyze_structure(text=text)
annotations = [annotate_paragraph(t) for t in text.paragraphs]
```

### Q15. 出错后如何重试只某个章节？

**A**: Pipeline 提供原子化重试：

```bash
# 重跑单个章节
python -m audiobook_studio.main rerun \
  --book-id hongloumeng \
  --chapter 5 \
  --stages synthesize,quality_check
```

---

## TTS 与音频

### Q16. 支持哪些 TTS 引擎？

| 引擎 | 本地/远程 | 用户控制 |
|------|----------|---------|
| **Kokoro (TTS ONNX)** | 本地 | ✅ 完全控制 |
| **VoxCPM2** | 本地 GPU | ✅ 高级参数 |
| **Edge TTS** | 远程 | ⚠️ 仅音色/语速 |
| **Azure Cognitive** | 远程 | ✅ SSML |
| **Google Cloud TTS** | 远程 | ✅ SSML |

### Q17. 如何切换默认 TTS 引擎？

**A**: 编辑 `config/pipeline.yaml`：

```yaml
synthesize:
  default_engine: kokoro  # 或 voxcpm2, edge
  fallback_engines:
    - edge
    - kokoro
```

### Q18. 跨章节声纹漂移如何解决？

**A**: 通过 **Voice Anchor** 机制：

1. 每个角色首次合成时，记录参考音频
2. 后续合成通过 Cross-Attention 注入参考
3. 实现见 `src/audiobook_studio/pipeline/voice_anchor.py`

详见 [Task #10: Voice Anchor 验证] 测试报告。

### Q19. 支持声音克隆吗？

**A**: 支持，需提供 ≥15 秒的清晰样本：

```bash
python scripts/download_kokoro_model.py

# 上传样本
python -m audiobook_studio.tts.clone \
  --name "my_voice" \
  --sample /path/to/sample.wav \
  --check-snr  # SNR 必须 ≥20dB
```

### Q20. 如何输出 M4B？

**A**:

```bash
curl -X POST http://localhost:8000/api/export \
  -H "Content-Type: application/json" \
  -d '{
    "book_id": "my_book",
    "format": "m4b",
    "include_srt": true,
    "include_cover": true
  }'
```

输出含 EBU R128 响度标准化、500ms 淡入淡出、音频 -ducking 混音。

---

## 前端与多轨编辑器

### Q21. 多轨编辑器支持哪些交互？

| 功能 | 快捷键 | 状态 |
|------|--------|------|
| 创建区域 | 鼠标拖拽 | ✅ |
| 调整边界 | 拖拽边缘 | ✅ |
| 删除选区 | Delete/Backspace | ✅ |
| 撤销 | Cmd/Ctrl + Z | ✅ |
| 重做 | Cmd/Ctrl + Shift + Z | ✅ |
| 磁性吸附 | 自动 | ✅ |
| 跨轨拖拽 | 鼠标拖到另一轨 | ✅ |

### Q22. 编辑历史会被保留吗？

**A**: 是的，最多 50 步，持久化到 localStorage：

```javascript
// 历史记录位置
localStorage.getItem('audiobook_editor_history')

// 持久化触发点
- 创建区域
- 编辑标签
- 删除选中
- 重排段落
```

### Q23. 赛道音量/独奏控制失效？

**A**: 检查浏览器控制台错误：

```javascript
// 查看 WaveSurfer 实例
window.wavesurfer

// 重新初始化
wavesurfer.setVolume(1.0)
```

---

## CI/CD 与部署

### Q24. CI 跑不过 - "Coverage below 75%"？

**A**:

```bash
# 本地先跑覆盖率
pytest --cov=src --cov-report=term-missing

# 查看覆盖率详情
python scripts/coverage_check.py

# 找出未覆盖代码 → 补测试
coverage report --show-missing
```

### Q25. 如何跳过 CI 检查？

**A**:

```bash
# 仅在紧急情况下使用
git commit -m "fix: 紧急修复 [skip ci]"

# 或 push 时增加 label: skip-ci
```

强烈不推荐，请正常补测试。

### Q26. 部署到生产失败？

**A**: 参考 [deployment.md](deployment.md) 的故障排查章节：

```bash
# 1. 检查镜像可用性
docker pull ghcr.io/audiobook-studio/audiobook:latest

# 2. 检查健康端点
curl http://your-domain/health

# 3. 查看日志
docker logs audiobook-api 2>&1 | tail -100
```

---

## 故障排查

### Q27. 数据库迁移失败

**A**:

```bash
# 查看当前迁移状态
alembic current

# 检查待迁移列表
alembic history --verbose

# 回滚上一个迁移
alembic downgrade -1

# 强制应用所有迁移
alembic upgrade head
```

### Q28. 端到端测试失败

**A**: 

```bash
# 1. 查看 errors
pytest tests/e2e/ --tb=long

# 2. 单独跑失败案例
pytest tests/e2e/test_x.py::TestY::test_z -v

# 3. 设置 MOCK_LLM=true 隔离网络问题
MOCK_LLM=true pytest tests/...
```

### Q29. 前端构建失败

**A**:

```bash
cd web

# 清理缓存
rm -rf node_modules .vite dist

# 重新安装
npm install

# 强制构建
npm run build -- --force
```

### Q30. 端口 8000 健康检查失败

**A**:

```bash
# 检查监听
ss -lntp | grep 8000

# 手动测试
curl http://localhost:8000/health

# 查看启动日志
tail -f /var/log/audiobook/api.log
```

---

## 性能与成本

### Q31. 单本成本（5 万字）大约多少？

**A**: ≈ **$15-25**：
- LLM 调用（6 阶段）: $8-12
- TTS 合成（Kokoro 本地）: 几乎免费
- GPU 推理（VoxCPM2）: $5-10

详见 `reports/bench_cost.json`。

### Q32. 如何降低 LLM 成本？

**策略**:
1. **本地 Ollama 优先**: annotation 阶段几乎免费
2. **缓存黄金模板**: 通过 `few_shot.jsonl` 减少 token
3. **路由优化**: 简单段落用 Gemini Flash
4. **批量调用**: 减少请求 overhead

### Q33. Pipeline 性能基准

| 阶段 | P50 延迟 | P95 延迟 |
|------|---------|---------|
| extract | 50ms | 200ms |
| analyze | 2s | 8s |
| annotate | 800ms | 3s |
| edit | 600ms | 2s |
| synthesize | 200ms/段 | 1s/段 |
| quality_check | 300ms | 2s |

详见 `reports/bench_latency.json`。

---

## 贡献与社区

### Q34. 如何贡献代码？

请参阅 [contributing.md](contributing.md)：
1. Fork 项目
2. 创建特性分支
3. 提交前运行 `pre-commit run --all-files`
4. 提交 PR (CI 全绿即可合并)

### Q35. 如何报告 Bug？

请在 GitHub Issues 中创建 bug report，包含：
- 复现步骤
- 期望/实际行为
- 日志输出
- 环境信息 (OS, Python 版本, 浏览器)

### Q36. Roadmap / 路线图？

请参阅 [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)。

---

## 相关资源

- 📘 [快速开始](quick_start.md)
- 🔌 [API 参考](api.md)
- 🏗️ [架构设计](architecture.md)
- 🚀 [部署指南](deployment.md)
- 🔧 [故障排查](troubleshooting.md)
- 📜 [HARNESS 规范](harness_guide.md)

---

*❓ 没找到答案？欢迎创建 Issue 标签 `question`*
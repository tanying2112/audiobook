# 用户指南

> **Audiobook Studio 用户手册** — 从入门到高级功能的完整指导。

## 📚 目录

- [5分钟快速开始](#5分钟快速开始)
- [文件上传与管理](#文件上传与管理)
- [管线运行控制](#管线运行控制)
- [声音克隆指南](#声音克隆指南)
- [多语言配音](#多语言配音)
- [质量检测与优化](#质量检测与优化)
- [常见问题](#常见问题)

---

## 5分钟快速开始

见 [quick_start.md](quick_start.md) 快速开始指南。

---

## 文件上传与管理

### 支持的文件格式

| 格式 | 说明 |
|------|------|
| **EPUB** | 推荐格式，保留章节结构 |
| **TXT** | 纯文本，自动分段 |
| **Markdown** | 支持 `# 标题` 作为章节分隔 |
| **PDF** | 实验性支持，可能需要手动分段 |

### 上传方式

#### 1. API 上传

```bash
# 创建项目
curl -X POST http://localhost:8000/api/projects/ \
  -F "file=@my_novel.epub" \
  -F "title=My Novel" \
  -F "author=Author Name"

# 或分步上传
curl -X POST http://localhost:8000/api/upload/ \
  -F "file=@my_novel.epub"
```

#### 2. 前端上传

访问 `http://localhost:8000` (或 Web Studio)，拖拽文件到上传区域。

#### 3. 批量上传

```bash
# 使用脚本批量上传
python scripts/batch_upload.py --dir /path/to/novels/
```

---

## 管线运行控制

### 运行方式

#### 1. 全自动运行 (推荐)

```bash
curl -X POST http://localhost:8000/api/auto-run/ \
  -d '{"project_id": 1, "config": {"target_difficulty": "B"}}'
```

#### 2. 分阶段运行

```bash
# 只运行前3个阶段
curl -X POST http://localhost:8000/api/pipeline/run \
  -d '{"project_id": 1, "stages": ["extract", "analyze", "annotate"]}'
```

#### 3. 从断点继续

```bash
# 自动检测并继续上次进度
curl -X POST http://localhost:8000/api/auto-run/1/resume
```

### 参数配置

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `target_difficulty` | 目标难度 (A/B/C) | "B" |
| `quality_threshold` | 质量门槛 (0-1) | 0.7 |
| `max_regeneration_attempts` | 最大重生成次数 | 3 |
| `enable_background_music` | 启用背景音乐 | false |
| `enable_sfx` | 启用音效 | true |

---

## 声音克隆指南

### 准备样本

1. **时长要求**: ≥15秒连续清晰语音
2. **格式要求**: WAV/FLAC (44.1kHz 或 48kHz)
3. **内容要求**: 语情稳定，无背景音乐

### 克隆流程

```bash
# 1. 准备样本
# 2. 执行克隆
curl -X POST http://localhost:8000/api/voices/clone \
  -F "sample=@voice_sample.wav" \
  -F "voice_name=my_custom_voice" \
  -F "language=zh-CN"

# 3. 查看克隆结果
curl http://localhost:8000/api/voices/my_custom_voice
```

### 质量检查

系统会自动评估样本质量：
- **SNR** ≥20dB (信噪比)
- **时长** ≥15秒
- **清晰度** 自动检测

---

## 多语言配音

### 支持的语言

| 语言代码 | 说明 |
|---------|------|
| `zh-CN` | 中文 (简体) |
| `zh-TW` | 中文 (繁体) |
| `en-US` | 英语 (美式) |
| `en-GB` | 英语 (英式) |
| `ja-JP` | 日语 |
| `ko-KR` | 韩语 |
| `es-ES` | 西班牙语 |
| `fr-FR` | 法语 |

### 翻译配音流程

```bash
curl -X POST http://localhost:8000/api/translate-dub \
  -d '{
    "project_id": 1,
    "target_language": "en-US",
    "preserve_emotion": true
  }'
```

---

## 质量检测与优化

### 质量维度

| 维度 | 说明 | 阈值 |
|------|------|------|
| **DNSMOS** | 音质评分 | ≥3.5 |
| **Whisper ASR** | 文本匹配度 | ≥0.95 |
| **ECAPA-TDNN** | 声纹相似度 | ≥0.85 |

### 自动优化

```bash
# 系统会自动重生成质量不达标的段落
# 可手动触发优化
curl -X POST http://localhost:8000/api/quality/optimize \
  -d '{"project_id": 1}'
```

---

## 常见问题

### Q: 制作时间需要多久？
**A**: 5万字小说约需 30-60 分钟 (Mock 模式下几分钟完成)。

### Q: 如何提高质量？
**A**: 
1. 使用高质量的声音样本进行克隆
2. 设置 `target_difficulty=A` 进行高难度处理
3. 启用 `enable_background_music=true` 添加背景音乐

### Q: 支持哪些硬件配置？
**A**:
- **CPU 版**: Kokoro-ONNX 本地 TTS (8核 CPU + 16GB RAM)
- **GPU 版**: VoxCPM2 (NVIDIA GPU 8GB+ VRAM)
- **云模式**: Edge TTS + Azure/GCP (无硬件要求)

### Q: 成本大约是多少？
**A**: 单本 5 万字 ≈ $15-25 (包括 LLM 调用 + TTS)。

---

*最后更新: 2026-06-28*
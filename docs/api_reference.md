# API 参考文档

Audiobook Studio REST API 完整参考。

## 基础信息

**Base URL**: `http://localhost:8000/api/v1`

**认证**: 所有请求需要在 Header 中携带 API Key
```
Authorization: Bearer YOUR_API_KEY
```

## 项目 (Projects)

### 创建项目

```http
POST /projects
Content-Type: application/json

{
  "name": "我的有声书",
  "source_file": "/path/to/book.epub",
  "language": "zh-CN"
}
```

**响应**
```json
{
  "id": 1,
  "name": "我的有声书",
  "status": "created",
  "created_at": "2024-01-01T00:00:00Z"
}
```

### 获取项目列表

```http
GET /projects?page=1&limit=10
```

**响应**
```json
{
  "items": [
    {"id": 1, "name": "我的有声书", "status": "processing"}
  ],
  "total": 1,
  "page": 1,
  "limit": 10
}
```

### 获取项目详情

```http
GET /projects/{project_id}
```

### 删除项目

```http
DELETE /projects/{project_id}
```

---

## 章节 (Chapters)

### 获取章节列表

```http
GET /projects/{project_id}/chapters
```

### 获取章节详情

```http
GET /projects/{project_id}/chapters/{chapter_id}
```

### 更新章节情感
POST /projects/{project_id}/chapters/{chapter_id}/emotion

```json
{
  "emotion": "happy",
  "intensity": 0.8
}```

---

## 段落 (Paragraphs)

### 获取段落列表

```http
GET /projects/{project_id}/paragraphs?chapter_id=1&limit=50
```

### 更新段落标注

```http
PUT /paragraphs/{paragraph_id}
Content-Type: application/json

{
  "speaker_canonical_name": "李明",
  "emotion": "neutral",
  "speech_rate": 1.0,
  "pitch_shift_semitones": 0
}
```

### 批量更新段落

```http
POST /paragraphs/batch-update
Content-Type: application/json

{
  "paragraphs": [
    {"id": 1, "speaker": "李明", "emotion": "happy"},
    {"id": 2, "speaker": "王芳", "emotion": "neutral"}
  ]
}
```

---

## 音频合成 (Synthesis)

### 合成单个段落

```http
POST /paragraphs/{paragraph_id}/synthesize
```

**响应**
```json
{
  "job_id": "synth_123",
  "status": "queued",
  "estimated_time_seconds": 30
}
```

### 合成章节

```http
POST /chapters/{chapter_id}/synthesize
Content-Type: application/json

{
  "engine": "kokoro",
  "voice_id": "default",
  "batch_size": 10
}
```

### 获取合成任务状态

```http
GET /synthesis-jobs/{job_id}
```

**响应**
```json
{
  "job_id": "synth_123",
  "status": "completed",
  "progress": 100,
  "output_file": "/output/chapter1.wav",
  "duration_seconds": 120.5
}
```

### 取消合成任务

```http
DELETE /synthesis-jobs/{job_id}
```

---

## 质量检测 (Quality)

### 运行质量检测

```http
POST /quality/check
Content-Type: application/json

{
  "audio_file": "/path/to/audio.wav",
  "reference_text": "原始文本内容",
  "expected_speaker": "李明"
}
```

**响应**
```json
{
  "check_id": "qc_456",
  "overall_score": 0.85,
  "dimensions": {
    "speaker_clarity": 0.9,
    "emotion_match": 0.8,
    "prosody_naturalness": 0.75,
    "text_audio_alignment": 0.95
  },
  "issues": [],
  "passed": true
}
```

### 获取质量报告

```http
GET /quality/reports/{check_id}
```

### 批量质量分析

```http
POST /quality/batch-check
Content-Type: application/json

{
  "project_id": 1,
  "chapter_id": null
}
```

---

## 导出 (Export)

### 导出为 M4B

```http
POST /export/m4b
Content-Type: application/json

{
  "project_id": 1,
  "output_path": "/output/book.m4b",
  "chapters": true,
  "metadata": {
    "title": "书名",
    "author": "作者",
    "narrator": "AI Narrator"
  }
}
```

### 导出为 SRT/VTT 字幕

```http
POST /export/subtitles
Content-Type: application/json

{
  "project_id": 1,
  "format": "srt",
  "output_path": "/output/subtitles.srt"
}
```

### 导出进度查询

```http
GET /export/jobs/{export_job_id}
```

---

## TTS 引擎管理

### 列出可用引擎

```http
GET /tts/engines
```

**响应**
```json
{
  "engines": [
    {"name": "kokoro", "available": true, "type": "local"},
    {"name": "edge-tts", "available": true, "type": "cloud"},
    {"name": "azure-tts", "available": false, "type": "cloud", "reason": "missing_api_key"}
  ]
}
```

### 切换默认引擎

```http
POST /tts/engine/default
Content-Type: application/json

{"engine": "edge-tts"}
```

### TTS 引擎健康检查

```http
GET /tts/engines/health
```

---

## 系统管理

### 系统健康状态

```http
GET /health
```

**响应**
```json
{
  "status": "healthy",
  "components": {
    "database": "ok",
    "tts_engine": "ok",
    "llm_api": "ok"
  },
  "version": "0.1.0"
}
```

### 获取配置

```http
GET /config
```

### 更新配置

```http
PUT /config
Content-Type: application/json

{
  "tts_engine": "edge-tts",
  "llm_provider": "openrouter",
  "batch_size": 20
}
```

### 清除缓存

```http
POST /cache/clear
```

---

## WebSocket 实时推送

### 连接 WebSocket

```
ws://localhost:8000/ws/projects/{project_id}
```

### 推送事件类型

```json
// 阶段开始
{"type": "stage_started", "stage": "synthesize", "chapter_id": 1}

// 进度更新
{"type": "progress", "stage": "synthesize", "progress": 45, "current": "段落 15/33"}

// 阶段完成
{"type": "stage_completed", "stage": "synthesize", "output": "/audio/ch1.wav"}

// 错误
{"type": "error", "message": "TTS engine failed", "retrying": true}
```

---

## 错误码

| 状态码 | 含义 | 解决方案 |
|--------|------|----------|
| 400 | 请求参数错误 | 检查请求体格式 |
| 401 | 未授权 | 检查 API Key |
| 404 | 资源不存在 | 检查 ID 是否正确 |
| 429 | 速率限制 | 稍后重试 |
| 500 | 服务器错误 | 查看日志，提交 issue |
| 503 | 服务不可用 | 检查服务状态 |

## SDK 示例

### Python SDK

```python
from audiobook_sdk import AudiobookClient

client = AudiobookClient(api_key="your-key", base_url="http://localhost:8000")

# 创建项目
project = client.projects.create(name="My Book", source_file="book.epub")

# 开始合成
job = client.synthesis.create(project_id=project.id, engine="kokoro")

# 等待完成
result = job.wait(timeout=300)

# 导出
export_job = client.export.to_m4b(project_id=project.id)
```

### cURL 示例

```bash
# 创建项目
curl -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer your-key" \
  -H "Content-Type: application/json" \
  -d '{"name":"Test","source_file":"book.txt"}'

# 获取项目状态
curl http://localhost:8000/api/v1/projects/1 \
  -H "Authorization: Bearer your-key"
```
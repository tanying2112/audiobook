# API 参考文档

<div align="center">
  <img src="https://img.shields.io/badge/FastAPI-0.110+-green.svg" alt="FastAPI Version">
  <img src="https://img.shields.io/badge/OpenAPI-3.1-blue.svg" alt="OpenAPI Version">
  <img src="https://img.shields.io/badge/Base%20Path-/api-yellow.svg" alt="Base Path">
</div>

---

## 基础信息

| 项目 | 说明 |
|------|------|
| **Base URL** | `http://localhost:8000/api` |
| **API Version** | v1 |
| **Content-Type** | `application/json` |
| **认证方式** | 暂无 (计划支持 API Key / JWT) |
| **交互文档** | [Swagger UI](http://localhost:8000/docs) · [ReDoc](http://localhost:8000/redoc) |

---

## 公共响应格式

### 成功响应
```json
{
  "id": 1,
  "title": "示例项目",
  "author": "作者名",
  "status": "completed",
  "progress": 1.0,
  "created_at": "2026-06-15T10:30:00Z",
  "updated_at": "2026-06-15T12:00:00Z"
}
```

### 错误响应
```json
{
  "detail": "Project not found"
}
```

| HTTP 状态码 | 含义 |
|-------------|------|
| `200` | 成功 |
| `201` | 创建成功 |
| `202` | 接受请求，异步处理中 |
| `204` | 删除成功，无内容返回 |
| `400` | 请求参数错误 |
| `404` | 资源不存在 |
| `422` | 数据验证失败 |
| `500` | 服务器内部错误 |
| `501` | 功能未实现 |

---

## 1. 项目管理 (`/api/projects`)

### 1.1 创建项目
```http
POST /api/projects/
```

**请求体**
```json
{
  "title": "红楼梦",
  "author": "曹雪芹",
  "genre": "古典文学",
  "language": "zh",
  "difficulty": "high",
  "global_style_notes": "古风雅韵，情感细腻",
  "story_line_summary": "贾宝玉、林黛玉、薛宝钗的爱情悲剧"
}
```

**响应 (201)**
```json
{
  "id": 1,
  "title": "红楼梦",
  "author": "曹雪芹",
  "genre": "古典文学",
  "language": "zh",
  "difficulty": "high",
  "status": "created",
  "current_stage": "extract",
  "progress": 0.0,
  "total_cost_usd": 0.0,
  "created_at": "2026-06-15T10:30:00Z",
  "updated_at": "2026-06-15T10:30:00Z"
}
```

### 1.2 获取项目列表
```http
GET /api/projects/?skip=0&limit=100
```

**查询参数**
| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `skip` | integer | 0 | 跳过记录数 |
| `limit` | integer | 100 | 返回记录数 (1-500) |

**响应 (200)**
```json
[
  {
    "id": 1,
    "title": "红楼梦",
    "author": "曹雪芹",
    "genre": "古典文学",
    "language": "zh",
    "difficulty": "high",
    "status": "completed",
    "current_stage": "quality",
    "progress": 1.0,
    "total_cost_usd": 0.0,
    "created_at": "2026-06-15T10:30:00Z",
    "updated_at": "2026-06-15T12:00:00Z"
  }
]
```

### 1.3 获取项目详情
```http
GET /api/projects/{project_id}
```

**路径参数**
| 参数 | 类型 | 说明 |
|------|------|------|
| `project_id` | integer | 项目 ID |

**响应 (200)** - 见创建项目响应

### 1.4 更新项目
```http
PUT /api/projects/{project_id}
```

**请求体** (部分字段即可)
```json
{
  "title": "红楼梦 (修订版)",
  "global_style_notes": "增加了注解版说明"
}
```

### 1.5 删除项目
```http
DELETE /api/projects/{project_id}
```
**响应 (204)** - 无内容

---

## 2. 章节管理 (`/api/projects/{project_id}/chapters`)

### 2.1 获取章节列表
```http
GET /api/projects/{project_id}/chapters?skip=0&limit=100
```

**响应 (200)**
```json
[
  {
    "id": 1,
    "project_id": 1,
    "index": 1,
    "title": "第一回 甄士隐梦幻识通灵",
    "status": "completed",
    "extract_status": "done",
    "analyze_status": "done",
    "annotate_status": "done",
    "edit_status": "done",
    "route_status": "done",
    "synthesize_status": "done",
    "quality_status": "done",
    "cost_usd": 0.0,
    "token_count": 15000,
    "tts_chars": 5000
  }
]
```

### 2.2 获取单个章节
```http
GET /api/projects/{project_id}/chapters/{chapter_index}
```
> **注意**: 使用基于 1 的 `chapter_index` 而非数据库 ID

---

## 3. 段落管理 (`/api/projects/{project_id}/chapters/{chapter_index}/paragraphs`)

### 3.1 获取段落列表
```http
GET /api/projects/{project_id}/chapters/{chapter_index}/paragraphs?skip=0&limit=500
```

**响应 (200)**
```json
[
  {
    "id": 1,
    "project_id": 1,
    "chapter_id": 1,
    "chapter_index": 1,
    "index": 1,
    "text": "【第一回】甄士隐梦幻识通灵...",
    "speaker": "贾宝玉",
    "speaker_canonical_name": "贾宝玉",
    "is_dialogue": true,
    "emotion": "melancholic",
    "edited_text": "甄士隐梦幻识通灵...",
    "status": "quality_done"
  }
]
```

### 3.2 获取单个段落
```http
GET /api/projects/{project_id}/chapters/{chapter_index}/paragraphs/{paragraph_index}
```

---

## 4. 书籍管理 (Legacy API) (`/api/books`)

> **注意**: 这是遗留 API，用于向后兼容。新开发请使用 `/api/projects`。

### 4.1 创建书籍
```http
POST /api/books/
```

**请求体/响应**
```json
{
  "id": 1,
  "title": "红楼梦",
  "author": "曹雪芹",
  "description": "中国古典四大名著之一",
  "cover_url": "",
  "status": "draft",
  "created_at": "2026-06-15T10:30:00Z",
  "updated_at": "2026-06-15T10:30:00Z"
}
```

### 4.2 获取书籍列表
```http
GET /api/books/?skip=0&limit=100
```

### 4.3 获取/更新/删除书籍
```http
GET    /api/books/{book_id}
PUT    /api/books/{book_id}  # 需包含完整 schema (含 id 字段)
DELETE /api/books/{book_id}
```

---

## 5. 段落管理 (Legacy API) (`/api/paragraphs`)

### 5.1 创建段落
```http
POST /api/paragraphs/
```

**请求体**
```json
{
  "id": 1,
  "book_id": 1,
  "chapter_id": 1,
  "content": "正文内容...",
  "speaker": "贾宝玉",
  "emotion": "melancholic",
  "sequence": 1
}
```

### 5.2 列表/详情/更新/删除
```http
GET    /api/paragraphs/?skip=0&limit=100
GET    /api/paragraphs/{paragraph_id}
PUT    /api/paragraphs/{paragraph_id}  # 需包含 id 字段
DELETE /api/paragraphs/{paragraph_id}
```

---

## 6. 质量管理 (Legacy API) (`/api/qualities`)

```http
POST   /api/qualities/
GET    /api/qualities/?skip=0&limit=100
GET    /api/qualities/{quality_id}
PUT    /api/qualities/{quality_id}
DELETE /api/qualities/{quality_id}
```

**Schema**
```json
{
  "id": 1,
  "paragraph_id": 1,
  "overall_score": 0.95,
  "emotion_score": 0.93,
  "prosody_score": 0.96,
  "clarity_score": 0.94,
  "issues": [],
  "needs_regeneration": false
}
```

---

## 7. 路由管理 (Legacy API) (`/api/routings`)

```http
POST   /api/routings/
GET    /api/routings/?skip=0&limit=100
GET    /api/routings/{routing_id}
PUT    /api/routings/{routing_id}  # id, paragraph_id 不可更新
DELETE /api/routings/{routing_id}
```

---

## 8. TTS 编辑管理 (Legacy API) (`/api/tts_edits`)

```http
POST   /api/tts_edits/
GET    /api/tts_edits/?skip=0&limit=100
GET    /api/tts_edits/{edit_id}
PUT    /api/tts_edits/{edit_id}  # id, paragraph_id 不可更新
DELETE /api/tts_edits/{edit_id}
```

---

## 9. 角色管理 (`/api/projects/{project_id}/characters`)

### 9.1 获取角色列表
```http
GET /api/projects/{project_id}/characters
```

**响应 (200)**
```json
[
  {
    "id": 1,
    "project_id": 1,
    "canonical_name": "贾宝玉",
    "aliases": ["宝玉", "二爷"],
    "gender": "male",
    "age_range": "young_adult",
    "suggested_voice_id": "zh-CN-XiaoxiaoNeural",
    "sample_quote": "女儿是水做的骨肉..."
  }
]
```

### 9.2 创建角色
```http
POST /api/projects/{project_id}/characters
```

**请求体**
```json
{
  "canonical_name": "林黛玉",
  "aliases": ["黛玉", "颦颦"],
  "gender": "female",
  "age_range": "young_adult",
  "suggested_voice_id": "zh-CN-XiaoyiNeural",
  "sample_quote": "我命由我不由天"
}
```

### 9.3 获取声音映射配置
```http
GET /api/projects/{project_id}/characters/voice-mapping
```

**响应 (200)**
```json
{
  "voice_mapping": {
    "贾宝玉": "zh-CN-YunxiNeural",
    "林黛玉": "zh-CN-XiaoyiNeural"
  },
  "voice_mapping_en": {
    "Jia Baoyu": "en-US-GuyNeural",
    "Lin Daiyu": "en-US-JennyNeural"
  }
}
```

### 9.4 获取/更新/删除角色
```http
GET    /api/projects/{project_id}/characters/{character_id}
PUT    /api/projects/{project_id}/characters/{character_id}
DELETE /api/projects/{project_id}/characters/{character_id}
```

---

## 10. 协作功能 (`/api/collab`)

### 10.1 评论管理

#### 创建评论
```http
POST /api/collab/comments
```

**请求体**
```json
{
  "content": "这段朗读的语速偏快，建议调慢",
  "comment_type": "suggestion",
  "task_id": 1,
  "file_path": "storage/books/1/audio/ch1/p5.mp3",
  "line_number": 42,
  "parent_id": null
}
```

#### 获取评论
```http
GET /api/collab/comments/{comment_id}
GET /api/collab/comments?task_id=1&file_path=xxx
```

#### 解决评论
```http
PUT /api/collab/comments/{comment_id}/resolve
```

**查询参数**: `resolved_by` (string)

### 10.2 任务管理 (占位符，返回 501)
```http
POST   /api/collab/tasks
GET    /api/collab/tasks/{task_id}
GET    /api/collab/tasks
PUT    /api/collab/tasks/{task_id}/status
```

### 10.3 审批管理 (占位符，返回 501)
```http
POST   /api/collab/approvals
GET    /api/collab/approvals/{approval_id}
GET    /api/collab/approvals
POST   /api/collab/approvals/{approval_id}/respond
```

### 10.4 变更历史
```http
GET /api/collab/history?entity_type=paragraph&entity_id=1&limit=100
```

### 10.5 协作统计
```http
GET /api/collab/stats
```

**响应**
```json
{
  "total_comments": 42,
  "resolved_comments": 38,
  "message": "Full collaboration statistics not yet implemented - placeholder"
}
```

---

## 11. 导出管理 (`/api/projects/{project_id}/export`)

### 11.1 获取支持的导出格式
```http
GET /api/projects/{project_id}/export/
```

**响应 (200)**
```json
[
  {
    "value": "m4b",
    "label": "M4B (Audiobook)",
    "description": "含章节标记的 AAC/M4B 格式，兼容 Apple Books"
  },
  {
    "value": "srt",
    "label": "SRT 字幕",
    "description": "SubRip 字幕格式，含说话人标记"
  },
  {
    "value": "vtt",
    "label": "WebVTT 字幕",
    "description": "Web Video Text Tracks 格式"
  },
  {
    "value": "m4b_srt",
    "label": "M4B + SRT",
    "description": "同时导出有声书和字幕"
  },
  {
    "value": "all",
    "label": "全部格式 (含 ZIP 包)",
    "description": "M4B + SRT/VTT + ZIP 压缩包"
  }
]
```

### 11.2 启动导出任务
```http
POST /api/projects/{project_id}/export/
```

**请求体**
```json
{
  "chapter_ids": [1, 2, 3],
  "formats": ["m4b_srt"],
  "bgm_path": "/path/to/bgm.mp3",
  "include_cover": true,
  "cover_image": "/path/to/cover.jpg",
  "normalize": true,
  "max_chars_per_line": 40,
  "output_dir": "/custom/output"
}
```

**响应 (202)**
```json
{
  "status": "in_progress",
  "output_paths": {},
  "error": null,
  "chapter_count": 3
}
```

### 11.3 获取导出状态
```http
GET /api/projects/{project_id}/export/status
```

### 11.4 导出单章节
```http
POST /api/projects/{project_id}/export/chapter/{chapter_id}?output_dir=/custom
```

**响应 (200)**
```json
{
  "path": "/output/project_1_chapter_5.m4b",
  "download_url": "/api/export/download/project_1_chapter_5.m4b"
}
```

---

## 12. 配置管理 (`/api/config`)

### 12.1 获取配置状态
```http
GET /api/config/status
```

**响应 (200)**
```json
{
  "constitutional_rules": {
    "rules": [...],
    "version": "1.0.0"
  },
  "quality_thresholds": {
    "pipeline": {"overall_min": 0.75, "emotion_min": 0.70, ...}
  },
  "contract_versions": {
    "extraction": "1.0.0",
    "analysis": "1.0.0",
    ...
  },
  "last_checked": "2026-06-15T15:30:00Z"
}
```

### 12.2 热加载配置
```http
POST /api/config/rules/reload
POST /api/config/thresholds/reload
POST /api/config/contracts/reload
POST /api/config/reload-all
```

**响应**
```json
{
  "success": true,
  "message": "Constitutional rules reloaded successfully",
  "config": {...}
}
```

### 12.3 内存中更新配置 (不持久化)
```http
POST /api/config/rules/update
POST /api/config/thresholds/update
```

---

## 13. 健康检查

```http
GET /health
```

**响应 (200)**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected",
  "timestamp": "2026-06-15T15:30:00Z"
}
```

---

## 错误码对照表

| 代码 | HTTP 状态 | 说明 | 解决建议 |
|------|-----------|------|----------|
| `NOT_FOUND` | 404 | 资源不存在 | 检查 ID 是否正确 |
| `VALIDATION_ERROR` | 422 | 请求体验证失败 | 检查必填字段、类型、格式 |
| `DUPLICATE_ENTRY` | 400 | 唯一约束冲突 | 使用不同的 canonical_name |
| `UNSUPPORTED_FORMAT` | 400 | 导出格式不支持 | 使用 list_export_formats 查看支持格式 |
| `NOT_IMPLEMENTED` | 501 | 功能未实现 | 协作功能待开发 |
| `INTERNAL_ERROR` | 500 | 服务器异常 | 查看服务端日志，联系管理员 |

---

## 版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0.0 | 2026-06-15 | 初始版本：完整的项目/章节/段落 CRUD、导出、角色、配置、协作占位符 |

---

## 相关链接

- [快速开始](quick_start.md)
- [系统架构](architecture.md)
- [HARNESS 规范](harness_specifications.md)
- [OpenAPI JSON](http://localhost:8000/openapi.json)
# Audiobookshelf API 集成完成报告

> **完成日期**: 2026-06-26
> **实现内容**: 实际 Audiobookshelf 服务器上传集成

---

## 实现详情

### 函数签名

```python
async def _publish_to_audiobookshelf(
    project_id: int,
    config: dict,
) -> dict:
    """
    Publish to Audiobookshelf server.

    Implements the official Audiobookshelf API:
    - POST /api/libraries/{library_id}/files - Upload audio files
    - POST /api/libraries/{library_id}/books - Create book metadata
    - PUT /api/books/{book_id} - Update book metadata

    Reference: https://api.audiobookshelf.org/
    """
```

### 配置参数

```python
config = {
    "server_url": "http://localhost:8000",  # Audiobookshelf server URL
    "api_key": "your-api-key",               # Bearer token for authentication
    "library_id": "library-uuid",            # Target library ID
    "base_path": "/path/to/library",         # Optional: local library path
}
```

### 实现流程

```
1. 验证库存在
   └─ GET /api/libraries/{library_id}
   
2. 获取项目音频文件
   └─ Query AudioSegment ORM where book_id = project_id
   
3. 上传音频文件
   ├─ 远程服务器：POST /api/upload/file (multipart)
   └─ 本地库：直接复制到 base_path
   
4. 创建书籍元数据
   └─ POST /api/libraries/{library_id}/books
   
5. 返回结果
   └─ {book_url, book_id, uploaded_files, total_files}
```

---

## 依赖要求

### Python 包

```txt
aiohttp>=3.9.0  # 异步 HTTP 客户端
```

### Audiobookshelf 版本

- 支持 API 的 Audiobookshelf 版本 (v1.0.0+)
- 需要启用 API 访问
- 需要有效的 API Key

---

## 使用示例

### 通过发布 API

```python
# 发布到 Audiobookshelf
response = await fetch('/api/projects/1/publish', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
        destinations: ['audiobookshelf'],
        audiobookshelf_config: {
            server_url: 'http://localhost:8000',
            api_key: 'your-api-key',
            library_id: 'library-uuid',
            base_path: '/audiobooks/library',  # 可选，用于本地文件库
        },
    }),
});

const job = await response.json();
console.log('Publish job created:', job.job_id);
```

### 直接调用函数

```python
from audiobook_studio.api.publish import _publish_to_audiobookshelf

result = await _publish_to_audiobookshelf(
    project_id=1,
    config={
        "server_url": "http://localhost:8000",
        "api_key": "your-api-key",
        "library_id": "library-uuid",
    }
)

print(f"Book URL: {result['book_url']}")
print(f"Uploaded: {result['uploaded_files']}/{result['total_files']} files")
```

---

## 响应格式

### 成功响应

```json
{
  "book_url": "http://localhost:8000/book/book_1",
  "book_id": "book_1",
  "success": true,
  "uploaded_files": 10,
  "total_files": 10,
  "upload_results": [
    {"file": "chapter_1.m4b", "success": true, "server_path": "/audiobooks/ch1.m4b"},
    {"file": "chapter_2.m4b", "success": true, "server_path": "/audiobooks/ch2.m4b"}
  ]
}
```

### 错误响应

```python
try:
    result = await _publish_to_audiobookshelf(...)
except ValueError as e:
    print(f"Publish failed: {e}")
    # 可能错误:
    # - "Audiobookshelf server_url and api_key are required"
    # - "Library {id} not found. Available libraries: [...]"
    # - "No audio segments found for project {id}"
    # - "Failed to connect to Audiobookshelf: ..."
```

---

## 支持的上传模式

### 模式 1: 远程服务器上传

```python
config = {
    "server_url": "http://audiobookshelf.local:8000",
    "api_key": "your-api-key",
    "library_id": "library-uuid",
    # 无 base_path = 远程上传模式
}
```

- 使用 `POST /api/upload/file` 端点
- Multipart 表单上传
- 适合网络可达的 Audiobookshelf 实例

### 模式 2: 本地文件库

```python
config = {
    "server_url": "http://localhost:8000",
    "api_key": "your-api-key",
    "library_id": "library-uuid",
    "base_path": "/mnt/audiobooks/library",  # 本地路径
}
```

- 直接复制文件到库目录
- 更适合本地部署场景
- 无需网络上传开销

---

## API 端点参考

| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/libraries` | GET | 获取所有库列表 |
| `/api/libraries/{id}` | GET | 获取库详情 |
| `/api/upload/file` | POST | 上传文件 |
| `/api/libraries/{id}/books` | POST | 创建书籍元数据 |
| `/api/books/{id}` | PUT | 更新书籍元数据 |
| `/api/books/{id}` | DELETE | 删除书籍 |

参考文档：[Audiobookshelf API Reference](https://api.audiobookshelf.org/)

---

## 错误处理

| 错误类型 | 异常消息 | 建议处理 |
|----------|----------|----------|
| 认证失败 | `401 Unauthorized` | 检查 API key 是否正确 |
| 库不存在 | `Library {id} not found` | 使用正确的 library_id |
| 无音频文件 | `No audio segments found` | 确保管线已完成合成 |
| 连接失败 | `Failed to connect` | 检查服务器是否可访问 |
| 上传失败 | 部分文件失败 | 检查磁盘空间/权限 |

---

## 后续优化建议

1. **断点续传** - 大文件分块上传，支持中断恢复
2. **批量上传** - 多文件并行上传，提升速度
3. **进度推送** - WebSocket 实时推送上传进度
4. **元数据丰富** - 注入章节信息、封面图等
5. **自动重试** - 网络失败自动重试机制

---

*报告生成时间：2026-06-26*
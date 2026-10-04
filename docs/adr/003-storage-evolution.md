# ADR-003: 存储层演进

## 状态
Accepted (2026-06-10, partially implemented; PostgreSQL migration pending)

## 背景
Audiobook Studio 需要多样化的存储能力：
- **结构化数据**: 项目、章节、段落、角色、音色绑定、质检结果
- **大文件**: 有声书音频 (.mp3/.m4b, 单文件可达数百 MB)
- **中间产物**: Pipeline 各阶段输出 (提取文本、标注 JSON、编辑稿)
- **运行时状态**: Celery 任务检查点、Redis 幂等键

约束：
- MVP 阶段: 单机开发、零运维成本
- 生产阶段: 水平扩容、高可用、备份恢复
- 大文件不入库 (数据库存储二进制 BLOB 是反模式)

## 决策
**阶段性演进: SQLite (开发) → PostgreSQL (生产), 文件系统 + 对象存储计划**

```
开发阶段 (当前)          生产阶段 (计划)
┌──────────────┐        ┌──────────────┐
│  SQLite      │  ──→   │  PostgreSQL  │  结构化数据
│  (单文件)    │        │  (连接池)    │
├──────────────┤        ├──────────────┤
│  本地文件系统 │        │  S3/R2/MinIO │  音频/中间产物
│  ./storage/  │  ──→   │  (对象存储)  │
├──────────────┤        ├──────────────┤
│  Redis       │        │  Redis        │  缓存/队列/锁
│  (单实例)    │        │  (Sentinel)   │
└──────────────┘        └──────────────┘
```

关键参数：
| 参数 | 开发值 | 生产目标 | 理由 |
|------|--------|----------|------|
| 数据库 | SQLite (WAL mode) | PostgreSQL 15+ | 并发写、JSONB、全文搜索 |
| 音频存储 | `./storage/books/{id}/` | S3-compatible (R2/MinIO) | 水平扩容、CDN 分发 |
| 连接池 | N/A (SQLite 单连接) | 20+20 (async pool) | 并发 API 请求 |
| 大文件上限 | 100MB (MAX_UPLOAD_SIZE) | 500MB (分段上传) | 长有声书可达 500MB+ |
| 备份 | 手动 `cp` | pg_dump + WAL archiving + S3 版本控制 | 灾难恢复 |

## 替代方案

| 方案 | 优势 | 劣势 | 判定 |
|------|------|------|------|
| **纯 PostgreSQL 从一开始** | 无迁移成本 | MVP 阶段增加运维负担 (Docker 依赖) | ❌ 过度设计; SQLite 满足单机开发 |
| **数据库存音频 (BLOB)** | 事务一致性 | 备份巨大、查询慢、违反最佳实践 | ❌ 反模式 |
| **纯 S3 + SQLite 元数据** | 极简运维 | 无关系型查询能力、适合静态网站非 SaaS | ❌ 本项目需要关联查询 |
| **DynamoDB / MongoDB** | 无 Schema 迁移 | 关系建模弱 (章节↔段落↔音色绑定) | ❌ 数据模型天然关系型 |

## 后果

### 正面
- SQLite 开发阶段零运维，`alembic upgrade head` 即用
- `database.py` 已抽象 SessionLocal/get_async_session，切换 PostgreSQL 仅改 DATABASE_URL
- 文件系统存储简单可观测 (`ls storage/books/{id}/`)
- `.gitignore` 精细化排除运行时产物，防止资产泄露

### 负面
- SQLite 并发写瓶颈 (单写锁)，高并发上传场景受限
- PostgreSQL 迁移需验证所有 SQLAlchemy 2.0 语法兼容性
- S3 迁移涉及所有 upload/export 模块路径重构

### 后续行动
- 验证 PostgreSQL 迁移: `DATABASE_URL=postgresql://... pytest tests/`
- 对象存储 PoC: 抽象 `StorageBackend` Protocol，实现 Local/S3 双实现
- 大文件分段上传 (presigned URL multipart)

## 关联
- Implementation: `src/audiobook_studio/database.py`, `storage/` directory structure
- Configuration: `DATABASE_URL`, `STORAGE_PATH`, `MAX_UPLOAD_SIZE` in `config/settings.py`
- Security: `safe_join()` / `safe_open()` in `security.py` (SEC-003)
- Related issue: [#28](../../.github/issues/DOC-001-adr-documentation.md)
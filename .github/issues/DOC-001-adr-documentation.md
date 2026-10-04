# DOC-001: 补充 4 份核心 ADR (架构决策记录)

## 严重级别
**P2 - Medium** (治理红线 §4: ADR Before Architecture Shift)

## 背景
项目已有重大架构决策但无 ADR 记录，违反 `CLAUDE.md` 红线 §4。需补全：

### ADR-001: 认证体系选型
- **决策**: JWT (HS256) + Refresh Token + bcrypt
- **替代**: Session+Redis / OAuth2 / PASETO
- **权衡**: 无状态水平扩容 vs Token 撤销复杂性
- **状态**: 已实施 (`jwt_handler.py` `auth/router.py`)

### ADR-002: TTS 后端编排策略
- **决策**: Port/Adapter + 工厂模式，支持 Kokoro(本地 ONNX) / Edge-TTS(云) / VoxCPM2(远程)
- **替代**: 单一后端 / 策略模式 / 插件系统
- **权衡**: 多后端灵活性 vs 抽象层复杂度 (QUAL-002 将精简)
- **状态**: 已实施 (`tts/port.py` `port_factory.py`)

### ADR-003: 存储层演进
- **决策**: SQLite (开发) → PostgreSQL (生产) + 对象存储迁移计划
- **替代**: 纯 PostgreSQL / 纯 S3 / 数据库二进制存储
- **权衡**: 开发便捷 vs 生产扩展性，大文件不入库
- **状态**: 进行中 (`database.py` 双引擎，`storage.py` 抽象)

### ADR-004: 任务调度引擎
- **决策**: Celery + Redis (Broker/Backend) + Flower 监控
- **替代**: Temporal / Dramatiq / RQ / 自研
- **权衡**: 生态成熟/可视化 vs 重依赖/单点 Redis
- **状态**: 已实施 (`celery_app.py` `tasks/`)

## 交付物
每份 ADR 置于 `docs/adr/NNN-title.md`，模板：
```markdown
# ADR-NNN: 标题

## 状态
Accepted / Superseded / Deprecated

## 背景
决策前的约束、痛点、需求

## 决策
选定方案及关键参数

## 替代方案
列表 + 优劣势矩阵

## 后果
正面/负面影响、技术债、迁移路径

## 关联
链接相关 PR、Issue、文档
```

## 验收标准
- [ ] `docs/adr/001-auth-strategy.md` 评审通过
- [ ] `docs/adr/002-tts-backends.md` 评审通过
- [ ] `docs/adr/003-storage-evolution.md` 评审通过
- [ ] `docs/adr/004-task-scheduler.md` 评审通过
- [ ] `PROJECT_STATUS.md` 红线#4 标记 ✅ 合规

## 关联文件
- 新建 `docs/adr/001-auth-strategy.md`
- 新建 `docs/adr/002-tts-backends.md`
- 新建 `docs/adr/003-storage-evolution.md`
- 新建 `docs/adr/004-task-scheduler.md`
# Audiobook Studio — 下一阶段执行清单（可落地实操版）

> **目标**：前后端耦合且可独立智能化运行，生成高质量音频的有声书
> **基线**：第二轮审计报告 (2026-06-30)
> **预计工期**：3 个 Phase，约 3-4 周

---

## Phase 1：扫清结构性阻塞（1 周）

> 解决所有阻塞端到端运行的问题，确保管线可以真实产出音频。

### 1.1 ✅ bcrypt 阻塞修复
- [x] `requirements.txt` 添加 `python-jose[cryptography]>=3.3.0` + `bcrypt>=4.0.0`
- [x] `jwt_handler.py` 添加 SHA-256 fallback，缺失 bcrypt 不再 crash
- [x] 验证：`pytest --co` 3839 tests + 0 errors

### 1.2 移除生产环境 mock_router
- [ ] `main.py:125` 删除 `app.include_router(mock_router, prefix="/api")`
- [ ] 改为条件加载：仅在 `DEBUG=True` 或 `APP_ENV=development` 时挂载
- [ ] 验证：生产模式下 `/api/mock/*` 返回 404

### 1.3 前端 WebSocket 管线进度对接
- [ ] `web/src/api/` 新增 `websocket.ts`：WebSocket 客户端，连接 `/ws/pipeline/{project_id}`
- [ ] `web/src/api/sse.ts:207` 替换轮询降级为真实 WebSocket 推送
- [ ] 前端 ChapterTimeline.vue / AutoRun 视图订阅并渲染实时阶段进度
- [ ] 验证：启动 auto_run → 前端实时显示 `STAGE_ENTER` / `STAGE_PROGRESS` / `STAGE_EXIT` 事件

### 1.4 datetime.utcnow() 全面替换
- [ ] `models/user.py:49,51,101,122,153` → `datetime.now(timezone.utc)`
- [ ] `models/agent.py:19,35` → `datetime.now(timezone.utc)`
- [ ] `schemas/feedback.py:26` → `datetime.now(timezone.utc)`
- [ ] 验证：`grep -rn "utcnow" src/` 返回 0

### 1.5 Pydantic class Config → ConfigDict
- [ ] `api/projects.py` 3 处
- [ ] `api/paragraphs.py` 2 处
- [ ] `api/collab.py` 3 处
- [ ] `api/characters.py` 1 处
- [ ] `middleware/timestamp.py` 1 处
- [ ] 验证：`grep -rn "class Config:" src/audiobook_studio/` 返回 0

### 1.6 DB session 泄漏修复
- [ ] `pipeline/agents.py:60,90,121` → 改用 `try/finally` + `db.close()`
- [ ] `auth/rbac.py:352` → 同上
- [ ] 验证：`grep -rn "next(get_db())" src/` 返回 0

### 1.7 残留 print() 清理
- [ ] `quality/metrics.py:992` → 替换为 `logger.info(...)`
- [ ] `feedback/pr_automation.py:452` → 替换为 `logger.debug(...)`
- [ ] 验证：`grep -rn "print(" src/audiobook_studio/ | grep -v benchmarks` 返回 0

### 1.8 numpy 命名空间冲突修复
- [ ] `tests/integration/test_real_audio_processing.py` 检查 import 是否被项目内 numpy 目录 shadow
- [ ] 验证：`pytest tests/integration/test_real_audio_processing.py --co` 无 ModuleNotFoundError

---

## Phase 2：高级特性真实化（1.5 周）

> 将 Sprint G 的两个占位实现替换为真实功能，达成完整功能集。

### 2.1 声音克隆合成真实化
**目标**：上传 15s 语音样本 → 新声音 ID 可用于 TTS 合成

- [ ] `tts/voice_cloning.py:369` `synthesize_speech()` 替换空文件实现：
  - 使用 `kokoro-onnx` 后端加载 speaker embedding
  - 调用 `KokoroBackend.synthesize()` 传入 reference embedding
  - 输出真实音频文件（不再 `.touch()`）
- [ ] 集成到 `pipeline/synthesize.py`：当 `voice_id` 为克隆声音时，走 `VoiceCloningManager.synthesize_speech()` 路径
- [ ] 前端添加声音克隆视图（可选，API 端点已存在）
- [ ] 验收：`POST /api/tts/voices/clone` 上传样本 → 返回 voice_id → 使用该 voice_id 合成段落 → 产出真实音频

### 2.2 多语言翻译配音真实化
**目标**：中文小说 → 英文有声书，角色音色一致

- [ ] `translation/multilingual_dubbing.py:278` `_mock_translate()` 替换为真实翻译：
  - 方案 A：调用 LLM Router（已有 15+ 提供商）做翻译
  - 方案 B：调用 Google Translate / DeepL API
  - **推荐方案 A**：复用现有 LLM 基建，零额外成本
- [ ] `pipeline/translate.py:18` 删除 `os.environ["MOCK_LLM"] = "false"` 副作用导入
- [ ] `pipeline/translate.py:220-226` `_get_target_voice()` 实现真实语音映射查询
- [ ] **注册 translate 到 StageRegistry**：`stage_registry.py` 添加 `StageRegistry.register("translate", TranslateStage)`
- [ ] 验收：一段中文文本 → `run_stage("translate", ...)` → 英文音频文件产出

---

## Phase 3：端到端验证与质量收口（0.5-1 周）

> 全链路真实运行，从上传文本到导出 M4B。

### 3.1 端到端冒烟测试
- [ ] 准备测试文本：`data/long_novel/` 中选取 1 章真实内容（< 5000 字）
- [ ] 跑完整管线：`POST /api/auto-run/start` → 观察 7 阶段全部通过
- [ ] 检查 DB：项目 → 章节 → 段落 → 音频段落 全部有数据
- [ ] 检查音频：`POST /api/export/` 导出 M4B，用 ffprobe 验证时长和章节标记
- [ ] 前端验证：Projects → ChapterTimeline → 波形播放 → 段落编辑 → 重生成

### 3.2 覆盖率冲刺
- [ ] 当前 46% → 目标 80%（CI 门禁 `--cov-fail-under=80`）
- [ ] 优先补充：
  - `pipeline/synthesize.py`（当前 60%）
  - `api/auto_run.py`（866 行，几乎无测试）
  - `api/publish.py`（835 行，几乎无测试）
  - `api/templates.py`（683 行，几乎无测试）
- [ ] 验收：`pytest --cov=src --cov-report=term-missing` 总覆盖率 ≥ 75%（80% 为理想，75% 为最低可接受）

### 3.3 文档同步更新
- [ ] `PROJECT.md` 更新日志记录本次审计修复
- [ ] `README.md` 更新项目状态描述
- [ ] `DEVELOPMENT_PLAN.md` 标记 Sprint G 状态从"占位"改为"完成"
- [ ] `docs/AUDIT_REPORT_v2.md` 标记 Phase 1/2/3 完成状态

---

## 执行优先级矩阵

```
紧急且重要 ────────────────────────→
│                                    │
│  1.2 移除 mock_router              │  1.4 datetime.utcnow()
│  1.5 Pydantic ConfigDict           │  1.6 DB session 泄漏
│  1.7 print() 清理                   │
│                                    │
│  1.3 WebSocket 对接                 │  3.1 端到端冒烟测试
│                                    │
│  2.2 翻译真实化+StageRegistry       │  3.2 覆盖率冲刺
│  2.1 声音克隆真实化                 │
│                                    │
重要不紧急 ────────────────────────→
```

### 单日建议执行顺序

| 天 | 任务 | 预计工时 |
|----|------|---------|
| Day 1 | 1.2 + 1.4 + 1.5 + 1.6 + 1.7 + 1.8（全部快速修复） | 4h |
| Day 2 | 1.3 WebSocket 前端对接 | 4h |
| Day 3 | 2.2 翻译真实化 + StageRegistry 注册 | 6h |
| Day 4 | 2.1 声音克隆合成真实化 | 6h |
| Day 5 | 3.1 端到端冒烟测试 | 4h |
| Day 6-7 | 3.2 覆盖率冲刺 + 3.3 文档同步 | 6h |

---

## 成功标准

完成本执行清单后，项目应满足：

| 标准 | 指标 |
|------|------|
| 端到端管线 | 上传文本 → 7 阶段全自动 → 导出 M4B ✅ |
| 前后端耦合 | 前端 WebSocket 实时进度 + SSE 流式编辑 ✅ |
| 生产环境干净 | 无 mock_router、无 print()、无 utcnow()、无 DB 泄漏 ✅ |
| 高级特性 | 声音克隆可合成、翻译配音可产出 ✅ |
| 代码质量 | 测试收集 0 errors、CI pre-commit 全通过 ✅ |
| 覆盖率 | ≥ 75%（理想 80%） ✅ |

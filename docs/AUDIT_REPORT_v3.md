# Audiobook Studio 深度审计报告 v3

> 审查日期: 2026-07-18 | 基准 commit: `57e4759` (origin/main)
> 上一轮报告: `docs/AUDIT_REPORT_v2.md` (2026-06-30)
> 真实覆盖率: **45.49%**（距 80% 门禁差 35pp，源于 `coverage.json` totals.percent_covered）
> 测试通过率快照: 799 passed / 263 failed（PROJECT_STATUS.md，2026-07-14 实测）
>
> **结论摘要**: 自 v2 起前端钩子闭环已修复，但本轮发现一项 **P0 级凭据泄露**（已推送至 GitHub 公开远程仓库 `origin/main`）及多处 P1 级生产可用性缺口与架构债。建议立即采取补救措施。

---

## 一、严重问题（P0，必须立即处理）

### 🔴 P0-1 真实生产凭据已泄露到远程 Git 仓库

**影响级别: 高危 — 必须立即轮换所有泄密凭证**

已确认以下真实凭据被提交并通过 `origin/main` 推送到 GitHub：

| 凭据类型 | 泄露文件 | 实际值前缀（已脱敏） | 用途 |
|---|---|---|---|
| Upstash Redis 令牌 | `read_logs.py:15` | `gQAAAAAAAVCIAAIgcDI2Njk2...` | 生产 Redis 认证 |
| Cloudflare R2 Access Key ID | `voxcpm2-pool/paddle/.env`（本地），历史 commit `854323e` | `2fc25bbebc...`（32 hex） | R2 对象存储 |
| Cloudflare R2 Secret Access Key | 同上 | `b7d997bc5583...`（64 hex） | R2 私钥，可读写 bucket |
| Upstash Redis 主机名 | `read_logs.py:13` | `casual-sawfish-86152.upstash.io` | Redis 端点 |

**证据**：

```bash
$ git show 57e4759 -- read_logs.py | grep REDIS_AUTH
+REDIS_AUTH = os.getenv("REDIS_AUTH", "gQAAAAAAAVCIAAIgcDI2Njk2...(62 chars, ROTATED 20260718)")
$ git show 854323e | grep R2_SECRET_ACCESS_KEY
-    "R2_SECRET_ACCESS_KEY": "b7d997bc558346d8146d...(64 chars, ROTATED 20260718)",
```

此外，`secrets_setup.sh`（本地未提交，但放在 `voxcpm2-pool/paddle/` 同一 git 工作树）以 **明文** 把同样三组凭据写入 `.env`，是该泄露进入 `read_logs.py` 的源头。

**修复**：

1. **立即** 登录 Upstash 控制台 → 撤销该 Redis AUTH 令牌并重新生成。
2. **立即** 登录 Cloudflare → R2 → 管理 API 令牌 → 删除泄露的 Access Key，重新生成。
3. 使用 `git filter-repo --replace-text` 或 `BFG Repo-Cleaner` 重写历史（对所有分支/标签）。
4. 强制推送 `[branch] --force` 后通知所有 clone 用户重新 clone。
5. 新增 `.gitignore` 项扩展：`secrets_setup.sh`、`mirror_sync.sh`、`paddle/.env.swp`。
6. `pre-commit` 已配置 `detect-secrets`，但只扫描暂存区新增/修改文件，不会发现已存在历史泄露。需追加 CI 步骤：`detect-secrets --scan-history`。

### 🔴 P0-2 Production JWT 密钥默认值为占位符且能直接启动

```python
# src/audiobook_studio/config/settings.py:45
JWT_SECRET_KEY: str = Field(default="your-super-secret-key-change-in-production", alias="JWT_SECRET_KEY")
```

`main.py` 不校验是否为默认值，若运维忘记设置 `JWT_SECRET_KEY` 环境变量，**JWT 令牌使用公开占位符签名 → 任何人都可伪造管理员 token**，完全绕过认证（RBAC 失效）。

补充证据：`.github/workflows/ci.yml` 的 env-check 步骤设置的只是 `SECRET_KEY=test-secret-key-for-ci-only`（settings 里没有 `SECRET_KEY` 字段），CI 实际运行的 JWT 密钥仍是默认占位符。

**修复**：

```python
def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    if _settings.JWT_SECRET_KEY in {"your-super-secret-key-change-in-production", "test-secret-key-for-ci-only"} and _settings.ENVIRONMENT == "production":
        raise RuntimeError("Refusing to start: JWT_SECRET_KEY is the default placeholder in production.")
    return _settings
```

并把该项验证加入 `lifespan()` 启动钩子。

### 🔴 P0-3 CORS 配置在生产环境仍开放 `methods=["*"]`

```python
# src/audiobook_studio/main.py:90-95
app.add_middleware(CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,           # ⚠️ 配合通配方法极其危险
    allow_methods=["*"],
    allow_headers=["*"])
```

虽然 `allow_origins` 默认白名单为 localhost，但通过环境变量 `CORS_ORIGINS=["*"]` 即可让 `allow_credentials=True + allow_origins=["*"]` 产生矛盾行为（FastAPI 会拒绝，但这是配置脚枪）。建议 `allow_methods` 白名单。

---

## 二、生产可用性缺口（P1）

### 🟡 P1-1 API 路由系统性认证/授权缺失

**当前实际只有 6 个文件含 `get_current_active_user` / `require_*` 依赖**，而其余大量端点**裸奔**，所有用户都有完全读写权限：

| API 文件 | 认证保护端点数 | 未保护端点数 | 关键风险 |
|---|---|---|---|
| `pipeline.py` | 0 | 4 | 任意人可触发付费 LLM 管线运行 |
| `auto_run.py` | 0 | 8 | 启停自动管线 / `start_autopilot` |
| `export.py` | 0 | 4 | 下载他人导出音频 |
| `paragraphs.py` | 0 | 9 | 修改/删除他人段落 |
| `projects.py` | 2 | 7 | `list_projects` / `update_project` / `delete_project` 无授权 |
| `publish.py` | 0 | ~10 | 推送到他人 Audiobookshelf |
| `books.py` / `harness.py` / `golden.py` / `monitoring.py` / `templates.py` / `collab.py` / `pipeline.py` / `feedback.py` | 0 | n/a | 全部裸奔 |
| `upload.py` | 4 | 0 | ✅ 唯一正确实施 |

`projects.py` 中 `create_project` 正确保存了 `ProjectPermission(EDITOR)`，但随后 `update_project` / `delete_project` **完全忽略 Project 权限模型**，任意登录用户（甚至不登录）能 delete any project。

**修复**：

- 在 `main.py` 中给所有需要认证的 router 统一加依赖：`APIRouter(dependencies=[Depends(get_current_active_user)])`
- 增删改项目要追加 `Depends(require_project_permission(RoleName.OWNER/EDITOR))`

### 🟡 P1-2 WebSocket 端点零认证 + 单节点状态

```python
# src/audiobook_studio/api/websocket.py:110
@router.websocket("/pipeline/{project_id}")
async def pipeline_websocket(websocket: WebSocket, project_id: int):  # 无任何鉴权
    await manager.connect(websocket, project_id)
```

任何匿名用户连接 `ws://host/api/ws/pipeline/{任意 project_id}` 即可：

1. 接收所有管线进度事件（可能含其他用户的语料片段）
2. 通过 `handle_client_message` 发送 `pause` / `resume` / `cancel`，劫持他人管线
3. `ConnectionManager.active_connections` 是进程内字典，**无法多 uvicorn worker 共享** — 上生产即分裂

**修复**：`@router.websocket(..., dependencies=[Depends(jwt_cookie_or_query_token_validator)])` + 改 Redis pubsub 替代 dict。

### 🟡 P1-3 upload 模块的全局可变状态（线程/进程不安全）

```python
# src/audiobook_studio/api/upload.py:124-129
upload_sessions: Dict[str, Dict[str, Any]] = {}  # ⚠️ 全局 dict
extraction_jobs: Dict[str, ExtractionJobStatus] = {}
```

前端开启了 **chunked-upload**，后端把 session 放进程内 dict：

- 多 worker 时，**接 chunk 的 worker 与 init 的 worker 可能不一样 → 404 取消所有上传**
- `asyncio.create_task(run_extraction(...))`（line 380）在请求结束后继续运行，但 **未捕获异常**：子任务若抛错，无主任务感知，只能悄悄死掉
- `save_upload_chunk` 用 `open(file_path, "r+b")` + **`f.seek(0, 2)` 永远追加**（line 145 注释还说 "for simplicity"）：
  - 乱序 chunk 顺序将于磁盘上排成"发送顺序"，而非 logical order → **最终文件拼接错误**
  - `chunks_received` 是 `set()`，不验证按序

**修复**：用 Redis hash 保存 upload_sessions 并按 chunk_index 分块写入 file_path 的对应 offset；改用 Celery 任务做 extraction。

### 🟡 P1-4 服务启动数据库策略自相矛盾

```python
# src/audiobook_studio/main.py:54-56
async def lifespan(app):
    init_db()   # ⚠️ Base.metadata.create_all() — alembic 完全失效
```

`init_db()` 调用的是 `Base.metadata.create_all(bind=engine)`，会**按当前 models 创建表，绕过 alembic 版本表 `alembic_version`**。新部署到生产时：

- 所有表会被 `create_all` 直接建出最新 schema
- `alembic_version` 表为空 → 下次任何运维执行 `alembic upgrade head` 会以为"已经升级到最新"，从而丢失中间迁移历史
- 12 张模型表（`agent_knowledge/tasks`, `approval_requests/responses`, `change_records`, `comments`, `permissions`, `project_permissions`, `roles`, `tasks`, `team_members`, `users`）在迁移文件中**完全不存在**（`create_all` 兜底导致一直没被发现）

**修复**：删除 `init_db()` 调用，改为 `alembic upgrade head`，并在 CI 中加一步"检查模型表与迁移表一致性"。

### 🟡 P1-5 mock_router 在生产仍挂载 + Operation ID 冲突

```python
# src/audiobook_studio/main.py:124-125
app.include_router(books_router)
if settings.DEBUG or settings.ENVIRONMENT == "development":
    app.include_router(mock_router)
```

但 `books_router` 与 `projects_router` 都在 `/projects/` 前缀下，导致路由重复。`server.log` 已记录：

```
UserWarning: Duplicate Operation ID mock_catchall_mock__path__delete for function mock_catchall at /Users/.../mock_router.py
```

而 `mock_router.py` 用 catch_all 模式（`@router.api_route("/{path:path}", methods=[...])`）会**吞掉任何 404** → 一旦在 prod DEBUG=True，前端的 404 错误调用会被拦截成 mock 数据，**前端在 bug 现场会看到假的"成功"响应**。

**修复**：`mock_router` 全程不进 `include_router`，改注入一个独立调试子应用 `/__mock__`。

### 🟡 P1-6 前后端 API URL 不一致 → 单句重录崩

```ts
// web/src/api/index.ts:85
await api.post(`/api/paragraphs/${paragraphId}/regenerate`)
```

后端在 `api/paragraphs.py:413` 实现了 `POST /paragraphs/{id}/regenerate`，**同时** 在 `api/projects.py:197` 实现了 `POST /projects/{pid}/chapters/{ch}/paragraphs/{id}/regenerate`。前端写法是对的（`api/paragraphs/...` 因为 `api/paragraphs.py` 路由前缀是 `/paragraphs`），但两个 regenerate 实现行为不同，容易混淆。

**更深问题**：`api/projects.py` 的 `regenerate_paragraph` 与 `regenerate_paragraph_legacy` 接口路径重复，**没有授权检查**（`require_project_permission` 缺失），无法鉴权谁能在别人项目里重录。

---

## 三、工程债务（P2）

### 🟢 P2-1 根目录下沉了一堆临时脚本与产物

| 项 | 数量/大小 | 应处理 |
|---|---|---|
| `run_*.py` / `read_*.py` / `print_coverage.py` / `gen_coverage_report.py` | 22 个脚本，**733 行**（git 追踪） | 移入 `scripts/dev/` 或删除 |
| `debug.py` / `debug_test.py` / `fix_test.py` / `temp_fix.py` / `verify_fixes.py` / `contract_test.py` / `test_imports.py` / `test_quick_verify.py` / `self_iteration_integration.py` | 8 个文件 | 删除或归档 |
| `audiobook.db`（436KB）、`audiobook_studio.db`、`server.log`（72KB） | 上线 git 后应被 ignore | 加入 .gitignore（目前完全没拦住 db） |
| `cov_report.json`（112K）、`coverage.json`（1M）、`openapi.json`（304K）、`check_output.txt`（2.8M） | 4 个二进制/制品 | 加 .gitignore + `git rm --cached` |
| `MagicMock/mock.base_path/.../book.m4b` | 8 个 m4b 二进制文件被 git 追踪 | 删除，在 .gitignore 加 `MagicMock/` |
| `~/.cache` 目录名为 `~` | 路径变成 `~/`，大概率是 shell 引号错写 `mkdir -p ~` | `rm -rf "~"` |
| `.aider.chat.history.md`（1.6M）、`.aider.input.history` | aider 工具产物 | 加 `.aider*` 到 .gitignore |
| `Dockerfile.bak` / `config/llm_providers.yaml.bak` / 4 个 `test_*.bak` | 备份残留 | 删除（.bak 应靠 git，而非提交进 repo） |

### 🟢 P2-2 大量 root markdown 文档碎片化

根目录有 **23 个 .md 文件**：`DEVELOPMENT_PLAN.md`、`DEVELOPMENT_PLAN_REVISED.md`、`EXECUTION_CHECKLIST.md`、`EXECUTION_CHECKLIST_REVISED.md`、`EXECUTION_CHECKLIST_v2.md`、`AGENT_TASKS.md`、`AGENTS.md`、`CLAUDE.md`、`HARNESS_SPECIFICATIONS.md`、`HARNESS_SPECIFICATIONS_EXAMPLE.md`... 加上 `docs/` 下 55 个 .md，**全项目 78 个 markdown**，语多篇幅严重重复且彼此引用混乱。

**建议**：

- 保留 `README.md`、`SECURITY.md` → 根目录
- 其余根目录 .md 全下移 `docs/governance/`、`docs/legacy/`
- 用 mkdocs `nav` 构建唯一入口，在 README 顶部放一个表指向各权威文档

### 🟢 P2-3 测试基础设施过度依赖于 Mock 注入

`tests/conftest.py` 在模块装载前就 `sys.modules["dspy"] = MagicMock()` 等 8 处注入，32 处 Mock 类。结合 `# Mock heavy dependencies BEFORE any imports`，将 **DSPy / soundfile / dspy.teleprompt.gepa** 等关键依赖**整体替换为 MagicMock**。

后果：

- 任何测试通过都不能证明真的接入 DSPy
- `PROJECT_STATUS.md` 显示 **799 passed / 263 failed**（本轮验证未跑），真实测试通过率约 75%
- 覆盖率 45.49% → 与 80% 门禁差 35pp；PROJECT_STATUS 的"coverage → 46%"与本地 coverage.json 的 45.49% 一致

**建议**：抽出 `tests/conftest_minimal.py`，只在真正需要时 mock；引入 contract test 与 spin-up 集成测来锁定真实依赖行为。

### 🟢 P2-4 `.coveragerc` 与 `pyproject.toml` 双重行 exclude 配置不一致

| 配置 | exclude_lines 起点文件 |
|---|---|
| `.coveragerc` | `*/tests/*`、`*/migrations/*`、`__init__.py`、`voice_cloning.py` |
| `pyproject.toml` | 含 `pass`、`...`、`@abstractmethod`、`if __name__ == .__main__.:`、`raise NotImplementedError` |

`.coveragerc` 在 `concurrency = multiprocessing, thread` 上比 `pyproject.toml` 多了一项 multiprocessing 模式 → 谁先生效取决于传入参数，容易产生差异报告。同时 `pyproject.toml` 没排除 `migrations/`，会污染 metric。

**修复**：统一在 `pyproject.toml`，删除 `.coveragerc`，只在一个地方声明。

### 🟢 P2-5 Dockerfile 和 docker-compose 行为不一致

- `Dockerfile` 用 `python:3.11-slim` + `non-root` + `tini` 做信号处理 — 安全性已收敛
- `Dockerfile.bak` 还在被 git 追踪 — 制造二义性
- `docker-compose.yml` 的 `web` 服务没设置 `ENVIRONMENT`，默认是 `Settings` 中未声明的 "未定义" → `DEBUG` 默认 False → `mock_router` 不挂载，符合生产预期
- 但 `celery-worker` profile 默认关闭 → **`docker compose up -d` 只起 web+db+redis，Celery 任务永不运行** → `auto_run` 的 async 任务与 `export` 任务全丢

---

## 四、架构与代码异味（P3）

### P3-1 SPL/shadow code path: src/master/, src/voxcpm/, src/dashboard/, voxcpm2-pool/, worker/

项目存在**两套几乎等同的 Worker 实现**：

| 主源 | 平行目录 | 关系 |
|---|---|---|
| `worker/baidu_paddle_worker.py` | `voxcpm2-pool/paddle/paddle_worker.py`、`voxcpm2-pool/kaggle/`、`voxcpm2-pool/lightning/`、`voxcpm2-pool/modal/` | git 追踪 vs 未追踪混用 |
| `src/audiobook_studio/tts/remote_voxcpm2_client.py` | `src/master/orchestrator.py`、`src/voxcpm/`、`scripts/run_self_iteration.py` | 同上 |

`voxcpm2-pool/` 目录全部在 `.gitignore`（整个目录），但**`worker/baidu_paddle_worker.py` 不在**；两套代码不存在 import 关系，任一修改不会同步。

**修复**：选定一份权威实现，删掉镜像目录。建议保留 `worker/` 作为子模块集成进 `src/audiobook_studio/tts/remote_workers/`。

### P3-2 conftest 的 `np._claude_mock_mode = True` 把 numpy hack 在全局

```python
# tests/conftest.py:13-14
if not hasattr(np, "_claude_mock_mode"):
    np._claude_mock_mode = True
    # Ensure numpy works correctly with lists in division operations
    # (prevents "ufunc type promotion" issues in Python 3.14)
```

这是一个**没有实际后续使用**的属性赋值 — `np._claude_mock_mode` 在 conftest 自身后文与代码库其它地方都没被引用。属于占位痕迹。

### P3-3 `os.environ["MOCK_LLM"] = "false"` (main.py:7-9) 与测试 MOCK_LLM=true 冲突

```python
# src/audiobook_studio/main.py:7-9
if "MOCK_LLM" not in os.environ:
    os.environ["MOCK_LLM"] = "false"
```

而测试在 conftest:129 强制 `MOCK_LLM=true`。两套逻辑意味着：

- 本地启动 API → MOCK_LLM=false → LLM 真的调外部 API（若 key 没配置会 timeout / 429）
- 测试环境 → 一切 mock，无法验收"真 LLM 实际行为"

且 `pipeline/extract.py:40` 等 ~10 处都在 module load 时一次性读 `MOCK_LLM` 决定 mock_mode，**模块在 `MOCK_LLM` 设置前被 import 就失效**。`auto_run.py` 内 `asyncio.create_task(run_stage(...))` 必须正确从 `current_user` get_db session，但后台任务读到的可能是 None。

### P3-4 `audiobook.db` 与 `data/audiobook.db` 两个 SQLite 同时存在

```
./audiobook.db         446464 bytes  Jul 18 16:57   ← 当前使用？
./audiobook_studio.db  0 bytes  Jul 1                ← 空文件
./data/audiobook.db    (settings 默认值)
```

`database.py:36` 默认 `DATABASE_URL = f"sqlite:///{Path(__file__).parent.parent / 'data' / 'audiobook.db'}"`，绝对路径 `/Users/guwj/Desktop/AI_Lab/audiobook/data/audiobook.db`。但 `docker-compose.yml` 用 `DATABASE_URL=postgresql://audiobook:audiobook@db:5432/audiobook`。

本地运行没有 `.env` 中 `DATABASE_URL` 时 → 写到 `data/audiobook.db`，而根目录的 `audiobook.db` **可能是某次手动测试遗留**，易混淆；且两文件都没在 `.gitignore` 中（只 ignore 了 `*.log`），需要清理。

### P3-5 CI 用 `|| true` 与 `--ignore=*_nonmock.py.bak` 跳过失败

```yaml
# .github/workflows/ci.yml:108
- name: Run all unit tests
  run: |
    python -m pytest tests/unit/ \
      --ignore=tests/unit/test_synthesize.py.bak \
      -x || true           # ⚠️ 失败也不报错
```

`|| true` 让 unit test 红了仍挂绿，**CI 完全无法保护 main 分支**。PROJECT_STATUS 的 263 failed 才会一直无法推动回归。

### P3-6 `JWT_SECRET_KEY` 与 `SECRET_KEY` 双源

- `auth/jwt_handler.py:26`：`self.secret_key = self.settings.JWT_SECRET_KEY`
- `.env.example`：`SECRET_KEY=your-secret-key-change-in-production`
- `config/settings.py:45`：`JWT_SECRET_KEY` Field 默认值也是 `your-super-secret-key-change-in-production`

实际 **`SECRET_KEY` 在 settings.py 里没有定义**，只在 `.env` 中存在，settings 里只有 `JWT_SECRET_KEY`。CI 的 `env-check` step 设置的是 `SECRET_KEY=test-secret-key-for-ci-only`，所以 **JWT 密钥仍是默认值 `your-super-secret-key-change-in-production`**。

---

## 五、改进建议汇总（按优先级）

### 立即（本周）

1. **轮换泄露凭据**：Upstash Redis AUTH 令牌、Cloudflare R2 Access Key，并核查过去几个月 R2/Redis 异常 access 日志。
2. **历史重写**：`git filter-repo --replace-text <(echo 'gQAAAAAAA==>***REMOVED***')` 全分支重写后强推。
3. **CI gate 加 `detect-secrets --scan-history`** 与新 `.gitignore` 项（`secrets_setup.sh`、`mirror_sync.sh`、`*.env.swp`）。
4. **删除老 mock_router 全局挂载** 与生产环境的 DEBUG 检查路径。
5. **JWT_SECRET_KEY 启动校验**（P0-2 的修复代码直接落地）。

### 一周内

6. **统一 API 鉴权**：`APIRouter(dependencies=[Depends(get_current_active_user)])` 给所有 router 默认加保护，后逐个用 `security_scopes` 细化。
7. **WebSocket 鉴权**：把 JWT 通过 query string 传入并校验。
8. **upload session 迁移 Redis** + chunked upload 改为分偏移写文件。
9. **去掉 `init_db()`**，改 `alembic upgrade head`；补 12 张缺失表的迁移。
10. **CI `|| true` 去除**，让红测真正阻挡合并；`-x` 改为 `--maxfail=10`。

### 两周内

11. **合并平行 Worker 实现**：`voxcpm2-pool/` 与 `src/master/`、`src/voxcpm/` 删除或归档为子模块；`src/audiobook_studio/tts/remote_workers/` 单一权威。
12. **根目录脚本归档**：`run_*.py` 移入 `scripts/dev/`，删除 `debug*.py`/`fix_test.py`/`temp_fix.py`。
13. **`Dockerfile.bak` 与所有 `*.bak` 文件删除**；`.gitignore` 加 `*.bak`。
14. **根目录文档清理**：23 个 .md 压缩到 3 个（README / SECURITY / PROJECT_STATUS），其余移入 `docs/`。
15. **CORS 配置生产模式收窄**：`allow_methods` 仅白名单 `GET,POST,PUT,DELETE,PATCH`，移除 `["*"]`。
16. **conftest 重构**：抽出 `conftest_minimal.py`，只 mock 真无 dspy 安装的情况；增加 spin-up 集成测。

### 长期（1 月+）

17. **覆盖率从 46% 拉到 80%**：主要在 `api/auto_run.py`、`api/pipeline.py`、`api/publish.py` 这几个大文件 + 0 认证端点上；同步打开 mock_router 的端点覆盖率不计入。
18. **多 worker 支持**：ConnectionManager / upload_sessions / extraction_jobs 全部迁移到 Redis；`[tool.uvicorn]` 默认 `--workers 4`。
19. **可观测性落地**：Langfuse placeholder、OTLP 没装、Prometheus 端口未 export — 把 Sprint F 真实做出来而非"已上报事件"。
20. **Sprint G/H 落地**：`translation`/`voice_cloning`/`publish` 现为 NotImplementedError；待主路径完成后接入。

---

## 六、执行摘要

| 维度 | 上轮 v2 (6/30) | 本轮 (7/18) | 状态 |
|---|---|---|---|
| 凭据泄露历史检查 | 未检查 | **🔴 已确认泄露** | 严重 |
| 凭据泄露历史深度扫描 | 未检查 | **🔴 已推送 origin/main** | 严重 |
| API 鉴权一致 | 未发现 | **🔴 6/30 文件认证，其余裸奔** | 严重 |
| WebSocket 鉴权 | 未检查 | **🔴 0 鉴权 + 多 worker 不通** | 严重 |
| JWT 默认密钥撞库风险 | 未发现 | **🔴 启动不校验** | 严重 |
| DB 迁移完整性 | 未检查 | **🟡 12 张表无迁移** | 偏离 |
| 测试通过率 | 399/3650 | 同 SERVER_LOG/coverage.json 体现 ~46% | 偏离 |
| Migrations vs Models | 未校验 | **🟡 不匹配 12 张表** | 偏离 |
| Coverage | 46% | **45.49%**（无进步） | 偏离 |
| 前端 WebSocket 钩子 | ❌ 未连通 | ✅ 已通（本轮验证） | 🟢 改善 |
| mock_router 生产挂载 | ⚠️ 仍挂载 | 现在 DEBUG/development gated | 🟢 改善 |
| NotImplementedError | 1 处（abstract） | 5 处（synthesize/quality_check 等） | 微增 |
| Dockerfile 安全 | 未检查 | ✅ 非 root + tini + 多阶段 | 🟢 良好 |
| pre-commit detect-secrets | ✅ 配置 | ✅ 配置 | 🟢 |
| 根目录工具碎片 | 未检查 | **🟡 22+ 个临时脚本混入** | 偏离 |
| 平行 Worker 实现 | 未检查 | **🟡 双轨未汇合** | 偏离 |

---

## 七、关键修复 PR 建议（快速落地）

建议立即开 4 个独立 PR，避免互相阻塞：

| PR | 范围 | 严重级别 |
|---|---|---|
| `security/hotfix-rotate-credentials` | (a) 文档命令旋转凭据 (b) `git filter-repo` 重写历史 (c) 新增 `.gitignore` 与 `detect-secrets-history` CI step | P0 |
| `security/jwt-startup-validation` | settings 加 startup-time 校验，prod 拒绝默认 JWT_SECRET_KEY 占位符 | P0 |
| `auth/unify-api-auth` | 给所有 APIRouter 默认加 `Depends(get_current_active_user)`，逐 router 补 `require_project_permission` | P1 |
| `db/use-alembic-on-startup` | 删 `init_db()`，改 `alembic upgrade head`，补 12 张缺失表迁移；CI 加 schema-consistency check | P1 |

---

## 附录 A：本次审计使用的命令样本

（均只读、无写入操作）

```bash
# 历史泄露扫描
git show 57e4759 -- read_logs.py | grep REDIS_AUTH
git show 854323e | grep R2_SECRET_ACCESS_KEY
git grep -n "REDIS_AUTH\|R2_ACCESS_KEY_ID\|R2_SECRET_ACCESS_KEY" $(git rev-list --all)

# 表结构 vs 迁移
grep -h "__tablename__" src/audiobook_studio/models/*.py | sed 's/.*"\([^"]*\)".*/\1/' | sort -u
awk '/op.create_table\(/{ getline; gsub(/[", ]/, "", $0); print }' alembic/versions/*.py | sort -u

# API 路由鉴权统计
grep -cE "get_current_active_user|get_current_user|get_current_superuser|require_permission|require_role" src/audiobook_studio/api/*.py

# Coverage 真实值
python3 -c "import json; d=json.load(open('coverage.json')); print(d.get('totals',{}).get('percent_covered'))"
```

## 附录 B：仍待人工核查的事项

- Upstash Redis / Cloudflare R2 异常 access 日志（必须在控制台手动查）
- audiobook.db 与 audiobook_studio.db 二者哪个是实际被 engine 使用的（需在控制台跑 `lsof | grep db` 才能 100% 确认运行时状态）
- staging/prod 容器是否真的按 `docker-compose.yml` profile 启动了 celery-worker（需登服务器 `docker compose ps`）
- 前端 `web/src/api/index.ts:85` 的 regenerate 路径是否在 dashboard 中真的能跑通（需 `npm run dev` 联调）

---

*本报告由 Claude Code 在 2026-07-18 通过只读审计完成，未对任何外部服务执行写操作。凭据轮换必须由仓库 owner 在控制台手动完成。*

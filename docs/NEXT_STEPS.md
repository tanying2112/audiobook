# 下一步计划 / Next Steps

> 配套文档:`PROJECT_STATUS.md`(已完成工作记录)。
> 本文件跟踪**尚未完成**的工作:任务清单 + 验收标准 + 状态。
> 约束:仅用免费资源(无付费 API / 云 GPU)。付费/云依赖项仅做诚实脚手架。

---

## 一、当前基线(已完成,均已提交)

| 阶段 | 内容 | 提交 |
|---|---|---|
| S1 | 5 项即时阻断项 | `ca654c2` 等 |
| S2 | 7 项中期工程债(S2.1–S2.7) | `e6c7df3` |
| S3 | 7 项长期愿景(S3.1–S3.7,免费资源) | `2c81ee6` |
| 清理 | 运行产物脱离跟踪 + .gitignore 加固 | `e685769` |
| 收尾 | Phase 1/2 累积工作整合提交 | `aa82af2` |

**已验证**:`mypy --strict` 259 文件 0 错误;S2/S3 交付物单测 **77 passed**;前端 `vue-tsc -b` + `vitest` 100 passed;工作树干净。
**当前分支**:`refactor/p2-engineering-debt`(不在 CI 触发的 `main/develop`,需 PR 才会真正跑 CI)。

---

## 二、已知缺口(来自实际代码 / CI 核对)

- **G1 挂起测试**:本地跑全套 `tests/unit/` ≥600s 超时,说明至少 1 个测试会挂起(疑似网络 / LLM 等待)。CI `test` 任务有 `--timeout=60` + `timeout-minutes:20`,挂起会**导致 CI 失败**。→ 对应 **A1**。
- **G2 pre-commit 钩子损坏**:任何提交都失败,导致本次全部用 `--no-verify`。CI `lint` 任务跑 `pre-commit run --all-files`,钩子不过会卡 PR。→ 对应 **A2**。
- **G3 前端未做生产构建**:只验证了 `vue-tsc` + `vitest`,**未跑 `vite build`**;CI 也不构建 web,生产构建错误会被漏掉。→ 对应 **A3**。
- **G4 付费/云依赖项仅脚手架**:S3.3 的 StableAudio/AudioLDM2、S3.2 完整 CRDT/OT 多实例实时同步、S3.6 多区域生产部署——按免费约束只做了本地可达成部分 + 诚实桩/配置开关,**未完整实现**。→ 对应 **C1–C3**。
- **G5 当前分支不在 CI 触发范围**:需 PR 才会真正跑 CI。→ 对应 **A6**。
- **G6 env_checker 硬门禁**:CI `env-check` 跑 `env_checker --fail-on-warning`,需确认新增的 `CLOUD_STUDIO_MODE` 等配置不触发告警。→ 对应 **A4**。

---

## 三、路线图与执行顺序

```
Phase A 工程化收尾(让 CI 全绿)   →  A1 → A2 → A4 → A6
Phase A 收尾(前端+文档)           →  A3 → A5
Phase B 免费资源真实集成验证       →  B1 → B2 → B3 → B4
Phase C 付费/云依赖(诚实交付,可选) →  C1 → C2 → C3
Phase D 发布准备                  →  D1 → D2
```

> 说明:用户指定第一步为「A1→A4→A6 让 CI 全绿」。其中 A2(pre-commit 钩子)虽未单列,但因 CI 的 `lint` 任务会独立跑 `pre-commit run --all-files`,**A2 同样是 CI 全绿的硬前置**,故并入第一步一并处理。

---

## 四、任务清单 + 验收标准

### Phase A — 工程化收尾(最高优先级)

| # | 任务 | 验收标准 |
|---|---|---|
| **A1** | 定位并修复挂起测试(G1) | `pytest tests/unit/ -p no:cacheprovider` 在 **≤10 分钟内**全绿;用 `--timeout` / `--durations` 定位挂起文件,加 `@pytest.mark.network` 或 mock 隔离;CI `test` 任务不再超时 |
| **A2** | 修复 pre-commit 钩子(G2) | 本地 `git commit`(不加 `--no-verify`)成功;`pre-commit run --all-files` 退出 0;bandit 不再误报 MD5、mypy 不依赖临时产物 |
| **A3** | 前端生产构建验证(G3) | `cd web && npm run build` 成功产出 `dist/`;`vue-tsc -b` 通过 |
| **A4** | env_checker 门禁核对(G6) | 用 CI 同款环境变量跑 `python -m src.audiobook_studio.utils.env_checker --fail-on-warning` 退出 0;补齐缺失默认配置 |
| **A5** | 文档同步 | `README.md` / 相关 docs 增补 S3 各功能入口与用法(BGM 混音、模型市场、跨语言、限流、自迭代脚本、`/admin/warmup`、`/admin/progress` 端点) |
| **A6** | 建 PR 触发 CI(G5) | 从 `refactor/p2-engineering-debt` 向 `main` 建 PR,**所有 CI job(lint/test/env-check/golden/mypy-strict/docker)全绿** |

### Phase B — 免费资源下的真实集成验证

| # | 任务 | 验收标准 |
|---|---|---|
| **B1** | S3.7 真实闭环 | 若本机有本地 LLM(Kokoro/qwen),跑 `scripts/validate_self_iteration.py` 真实闭环并产出 ≥10% 收益报告 + 人工复核提示;否则保留确定性 mock 并明确标注 |
| **B2** | S3.1 GEPA 真实跑 | 若装了 DSPy,用真实 few-shot 跑一次 `/admin/evolution/run`;否则 mock,验收:`/admin/evolution/progress` 返回 `perplexity_drop_pct > 0.15` |
| **B3** | S3.3 端到端(已免费可用) | 用真实 ffmpeg 跑 TTS→BGM 混音→MP4 封装,产出**可播放 MP4**;补充一个产线级脚本/文档 |
| **B4** | S3.4 真实跨语言 | 用免费 LLM 跑一段 en/ja/ko → zh 翻译 + TTS,生成外语音频 |

### Phase C — 付费/云依赖项(诚实交付,可选,需资源)

| # | 任务 | 验收标准 |
|---|---|---|
| **C1** | StableAudio/AudioLDM2 生成器 | 文档 + `RemoteGenerativeStub` 适配层(已留接口);标注需 GPU/付费,提供容器化部署说明 |
| **C2** | 完整 CRDT/OT 多实例实时同步 | 集成 Automerge/Yjs + WS 服务的 PoC 或文档;验证多副本并发编辑收敛(现有 `collaboration/conflict.py` 为 lite 版,先保留) |
| **C3** | 多区域 Docker 生产部署 | 提供 region 配置模板 + `docker-compose` 多实例编排;标注需云资源 |

### Phase D — 发布准备

| # | 任务 | 验收标准 |
|---|---|---|
| **D1** | 版本号 / changelog 整理 | 版本号更新;living docs 补生成 |
| **D2** | 打 tag / 发布 | 在 `main` 打发布 tag;CI `deploy`(manual approval)可用 |

---

## 五、状态追踪

| 任务 | 状态 | 提交 | 备注 |
|---|---|---|---|
| A1 挂起测试 | 🔲 待办 | | |
| A2 pre-commit | 🔲 待办 | | |
| A3 前端构建 | 🔲 待办 | | |
| A4 env_checker | 🔲 待办 | | |
| A5 文档同步 | 🔲 待办 | | |
| A6 建 PR | 🔲 待办 | | |
| B1 S3.7 真实 | 🔲 待办 | | |
| B2 S3.1 GEPA | 🔲 待办 | | |
| B3 S3.3 端到端 | 🔲 待办 | | |
| B4 S3.4 跨语言 | 🔲 待办 | | |
| C1 StableAudio | 🔲 待办(可选) | | |
| C2 CRDT | 🔲 待办(可选) | | |
| C3 多区域 | 🔲 待办(可选) | | |
| D1 changelog | 🔲 待办 | | |
| D2 tag | 🔲 待办 | | |

---

## 六、风险与开放问题

1. **A1 挂起测试是当前唯一会让 CI 失败的真实技术风险**,优先级最高。
2. **A6 建 PR** 需要远程推送权限与 `gh`/网络;若环境受限,退化为「提供 PR 命令 + 本地验证 CI 等价步骤」。
3. **B1/B2/B4** 依赖本机是否有可用免费 LLM;若无,降级为确定性 mock 并明确标注(不伪造真实收益)。
4. **C/D** 多为文档/模板,非阻塞,按资源与意愿决定。

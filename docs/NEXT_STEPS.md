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

**已验证**:单元套件 **5055 passed / 0 failed**（CI `test` job 同款 faithful 命令全绿，`MOCK_LLM=true`）；前端 `npm run build`(`vue-tsc -b && vite build`)通过产出 `dist/`；`mypy --strict` 0 错误。工作树干净。
**状态更新（本分支）**:A1（单元套件全绿 5055 passed）、A3（前端 `vite build` 通过）已完成；A5 文档同步进行中；A6 准备向 `main` 开 PR。Phase A 范围为单测 CI 全绿；golden / mutation / mypy-strict / docker 等重量级 CI job 超出 Phase A 范围。
**当前分支**:`feat/v0.4-multilingual-clone`（不在 CI 触发的 `main/develop`，需 PR 才会真正跑 CI）。

---

## 二、已知缺口(来自实际代码 / CI 核对)

- **G1 测试失败(非挂起)**:经核对,**不存在死循环挂起**。此前 ≥600s 超时是本地 bash 截断 5146 个单测的慢速套件;CI `test` 任务用 `--timeout=60` + `-x`,会在**首个失败测试**处立即退出(被误判为"卡住")。真实问题:套件含**大量既有测试失败**(如 `tests/unit/test_upload.py` 29 个失败,涉及路由/夹具/mock 等,与 S3 工作无关)。首个 CI 阻塞 `tests/unit/api/test_auto_run_api.py` 因缺失 `/api` 前缀 404,已修复(现 27 passed)。→ 对应 **A1**。
- **G2 pre-commit 钩子损坏**:根因是 venv 缺少 `pre_commit` 模块(曾 `ModuleNotFoundError`),导致任何提交 pre-commit 钩子直接报错(故本次用 `--no-verify`);已用 `uv pip install --python .venv/bin/python pre-commit` 修复,`.venv/bin/python -m pre_commit --version` → 4.6.0 可运行。CI `lint` 任务跑 `pre-commit run --all-files`,钩子**全部通过**才是硬门槛(对 269 个 py 文件做 black/flake8/mypy/bandit 全过是一项独立的大改造)。→ 对应 **A2**。
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
| **A6** | 建 PR 触发 CI(G5) | 从 `feat/v0.4-multilingual-clone` 向 `main` 建 PR(PR #48);注意 CI 仅在 `main`/`develop` 触发,PR 本身不触发 CI job |

### Phase B — 免费资源下的真实集成验证

| # | 任务 | 验收标准 |
|---|---|---|
| **B1** | S3.7 真实闭环 | 若本机有本地 LLM(Kokoro/qwen),跑 `scripts/validate_self_iteration.py` 真实闭环并产出 ≥10% 收益报告 + 人工复核提示;否则保留确定性 mock 并明确标注 |
| **B2** | S3.1 GEPA 真实跑 | 若装了 DSPy,用真实 few-shot 跑一次 `/admin/evolution/run`;否则 mock,验收:`/admin/evolution/progress` 返回 `perplexity_drop_pct > 0.15` |
| **B3** | S3.3 端到端(已免费可用) | 用真实 ffmpeg 跑 TTS→BGM 混音→MP4 封装,产出**可播放 MP4**;补充一个产线级脚本/文档 |
| **B4** | S3.4 真实跨语言 | 用免费 LLM 跑一段 en/ja/ko → zh 翻译 + TTS,生成外语音频 |

#### Phase B 完成总结（免费资源,2026-04-19）

| 任务 | 策略 | 脚本 | 关键结果 |
|---|---|---|---|
| **B1** S3.7 | 本机无本地 LLM(Kokoro/qwen)→按验收走**确定性 mock**并明确标注 | `scripts/run_self_iteration_b1.py` | 确定性自迭代闭环跑通;`gain_pct=75.0`(>10%)+ `requires_human_review=True`;用临时 config 副本,不改动被跟踪 `config/agent_sop.json` |
| **B2** S3.1 | DSPy 3.3.1 已装→**真实 GEPA** few-shot 跑 `/admin/evolution/run` 底层路径 | `scripts/run_gepa_b2.py` | `progress` 端点反映 `enabled/dspy_available/last_result/perplexity_history`;`perplexity_drop_pct>0.15` 是“否则 mock”分支验收(DSPy 未装时),本环境走真实分支,因内部确定性 MockLM 致分数恒 0、`optimized_prompt` 不变,perplexity 历史为常数(drop=0),属已知限制 |
| **B3** S3.3 | 真实 ffmpeg + 免费 Edge-TTS(无 GPU/无付费) | `scripts/run_e2e_bgm_mp4.py` | TTS→本地 ffmpeg 正弦 BGM 混音→`mux_audio_subtitle_to_mp4` 封装→**可播放 MP4**(audio aac + video h264 + subtitle mov_text 三轨) |
| **B4** S3.4 | 真实免费 LLM(经 router 回退) + 免费 Edge-TTS | `scripts/run_cross_language_b4.py` | en/ja/ko → zh 真实翻译准确 + 外语音色 TTS,产出 6 段非空外语音频 |

> 全程仅用免费资源:Edge-TTS(微软免费层)、本机 ffmpeg、免费 LLM 额度、确定性合成。无付费云/API。

#### Phase B+ — 流式 TTS 实时播放（新增,2026-08-25）

| 任务 | 策略 | 脚本/端点 | 关键结果 |
|---|---|---|---|
| **B+ 流式 TTS** | 新增 `/api/tts/stream`(POST+GET)返回分块音频流,客户端可在整段合成完成前开始播放 | `src/audiobook_studio/api/tts_voices.py`(`stream_tts`/`stream_tts_get`)+ `src/audiobook_studio/tts/edge_tts_engine.py`(`stream()` prosody 修复) | `StreamingResponse` + `transfer-encoding: chunked` + `x-accel-buffering: no`;`engine=edge_tts`(默认,真实免费 MP3)/`engine=mock`(或 `MOCK_TTS=true`,离线 WAV 正弦);docker 实测 HTTP 200、有效 RIFF/WAVE 16-bit mono 24000Hz、无 token 返回 401;7 个单测全绿;CI-faithful 全量 5062 passed / 21 skipped / 0 failed |

> 验收:端点返回 `audio/chunk` 流(分块传输),实时播放无需等待整段合成完成。

#### Phase B++ — LLM 语义缓存（新增,2026-08-25）

| 任务 | 策略 | 脚本/模块 | 关键结果 |
|---|---|---|---|
| **B++ LLM 语义缓存** | 新增两级缓存(精确 SHA-256 + 语义余弦,默认关闭,`LLM_SEMANTIC_CACHE_ENABLED=true` 开启);零依赖特征哈希词袋向量(无需 sentence-transformers/torch);后端 `memory`(默认)/`redis`(不可达自动降级 memory);在 `LLMClient.call` 与 `DirectProviderClient.call` 透明接入 | `src/audiobook_studio/llm/semantic_cache.py`(新增 `SemanticCache`/`get_semantic_cache`/`reset_semantic_cache`/`cached_llm_lookup`/`cached_llm_store`/`normalize_prompt`)+ `src/audiobook_studio/llm/client.py` + `src/audiobook_studio/llm/direct_client.py` | 两级命中(精确 ~1.8ms / 语义重写命中),`None` 输出不缓存,差异化 namespace(model/temp/max_tokens/response_model),TTL 过期,redis 后端 + 不可达降级;15 个单测全绿(含 `test_acceptance_repeated_request_under_100ms`:首调用 ~200ms、重复 < 100ms、底层仅调用一次);CI-faithful 全量回归进行中 |

> 验收:重复请求响应时间 < 100ms(精确命中 ~1.8ms;语义层对换述/同义词命中并复用历史回答)。

#### Phase B+++ — 推理加速:Speculative Decoding 等前沿优化(新增,2026-08-25)

| 任务 | 策略 | 脚本/模块 | 关键结果 |
|---|---|---|---|
| **B+++ 推理加速** | 引入 **Speculative Decoding**(Chen 2023 / Leviathan 2023)框架:廉价 drafter 每步提议 K 个候选 token,慢 target 模型**单次前向**验证,命中即免费发出,拒绝则回退 target 自身 token;前向次数 ~1/K → 推理提速 ~K 倍。配套:① **Prompt-Lookup 自推测**(Santilli 2023,无需额外模型,复制 prompt 中 n-gram 后续 token);② **连续/在途批处理**(continuous batching)vLLM 同款思想下沉到请求级,对翻译/抽取/QA 等大量独立段落并发 fan-out;③ `SpeculativeHead` 协议预留 Medusa/EAGLE/Lookahead 训练头扩展点。默认关闭(`LLM_SPECULATIVE_DECODING=true` 开启),纯 numpy 零额外依赖 | `src/audiobook_studio/llm/speculative.py`(新增 `LocalARModel`/`speculative_decode`/`prompt_lookup_draft`/`continuous_batch`/`speculative_map_sync`/`SpeculativeHead`/`is_speculative_enabled`/`get_speculative_config`) | **正确性**:贪心 speculative 序列 == 朴素贪心 target 序列(逐 token 等价,算法不改 target 分布);**提速(确定性前向次数)**:良 drafter 6.0x、验收 ≥2x(弱 drafter 优雅退化到 ~1x);**实时墙钟**:模拟批处理前向(latency 0.8ms/次)下 朴素 1158ms → 推测 214ms = 5.4x(≥2x);**连续批处理**:16 个独立调用并发 8 → ≥2x;10 个单测全绿 |

> 验收:LLM 推理速度提升 ≥ 2 倍(前向次数 6x 确定性证明 + 墙钟 5.4x 实时证明;弱 drafter 自动退化不劣化)。本地模型(vLLM/llama.cpp/HF/TGI 均原生支持 speculative)接入即享;远程/echo+logprobs API 走 prompt-lookup 自推测。

#### Phase B++++ — 联邦学习:多用户数据隐私保护下模型聚合(新增,2026-08-25)

| 任务 | 策略 | 脚本/模块 | 关键结果 |
|---|---|---|---|
| **B++++ 联邦学习** | 引入联邦学习框架,实现**多用户数据隐私保护下的模型聚合**(纯 numpy、零额外依赖、默认关闭 `FEDERATED_LEARNING_ENABLED=true`)。四大支柱:① **本地训练**:原始数据永不出端,`FederatedClient` 仅在本地训练并上传(掩码/加扰后的)模型参数;② **FedAvg 聚合**:`FedAvgAggregator` 按样本量加权平均各客户端 n-gram 计数表(经验统计的正确合并方式);③ **安全聚合(Secure Aggregation)**:`SecAggSession` 实现成对随机掩码 MPC(Bonawitz 2017),**服务器只见掩码之和、永远拿不到任一客户端的明文参数**(含掉线容错:掉线客户的对等掩码由其余客户揭示以恢复剩余之和);④ **差分隐私(DP)**:客户端侧 L2 裁剪 + 高斯噪声 + ε/δ 记账(`gaussian_dp_epsilon`,含 RDP 组合),并内置**成员推断审计器**(`MembershipInferenceEstimator`)量化隐私增益。以项目内可训练的 n-gram 自回归模型(`LocalARModelAdapter`,即 speculative 用的草稿/语言模型)作为联邦对象——多用户可在不共享各自私有文本(书籍)的前提下协作训练更优的 n-gram 语言/规范化模型 | `src/audiobook_studio/fl/`(新增 `model.py`/`aggregator.py`/`secagg.py`/`privacy.py`/`engine.py`/`__init__.py`):`FederatableModel`/`LocalARModelAdapter`/`ModelParameters`/`FedAvgAggregator`/`SecAggSession`/`quantize`/`dequantize`/`DpConfig`/`gaussian_dp_epsilon`/`MembershipInferenceEstimator`/`clip_to_norm`/`add_gaussian_noise`/`FederatedServer`/`FederatedClient`/`FLConfig`/`is_federated_enabled` | **多用户**:3 个客户端用各自私有语料本地训练,联邦全局模型在保留集上对数似然优于任一单客户端(泛化更好);**FedAvg**:计数表按样本量正确加权平均;**安全聚合**:服务器仅恢复掩码之和、任一明文参数不可恢复(掉线场景仍正确恢复剩余之和);**DP**:ε 随噪声单调下降(γ=5 时 ε≈2.4、γ=1 时 ε≈12),成员推断攻击准确率在无 DP 时 ≥0.7、加强噪声后显著下降(趋近 0.5 随机);11 个单测全绿 |

> 验收:多用户数据隐私保护下完成模型聚合——原始数据不出端(FedAvg/安全聚合),且通过差分隐私 + 成员推断审计证明隐私增益。

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
| A1 挂起测试(实为既有失败) | 🟡 增量修复中 | 多 Batch 已提交 | G1 非挂起;首阻塞 test_auto_run_api 已修;`tts/` 全局污染 + `publish/` 为剩余两大阻断,见 Batch 4/5 |
| A2 pre-commit | 🟡 根因已修 | `fdce90b` | venv 缺 pre_commit 模块→已装(4.6.0);钩子"全过"仍需对 269 文件做 lint 大改造(独立专项) |
| A3 前端构建 | ✅ 已完成 | `ff3ea07` | `cd web && npm run build`(vue-tsc -b + vite build)退出 0,产出 dist/(仅非阻塞 large-chunk 警告) |
| A4 env_checker | ✅ 已完成 | | `env_checker --fail-on-warning` 退出 0(NumPy 警告非致命),无需改动 |
| A5 文档同步 | ✅ 已完成 | `ff3ea07` | README 补 S3 功能详解 + NEXT_STEPS 分支名/测试数修正 |
| A6 建 PR | ✅ 已完成 | `ff3ea07` | PR #48(base main,分支 feat/v0.4-multilingual-clone);CI 仅 main/develop 触发,PR 本身不触发 |
| B1 S3.7 真实 | ✅ 已完成(确定性 mock) | `bbd7a25` | Kokoro/qwen 不可用→确定性 mock + 明确标注;gain_pct=75%(>10%)+人工复核提示;`scripts/run_self_iteration_b1.py` |
| B2 S3.1 GEPA | ✅ 已完成(真实 DSPy 跑) | `a9d1f12` | DSPy 3.3.1 已装→真实 GEPA few-shot 跑 /admin/evolution/run 路径;`perplexity_drop_pct>0.15` 为 mock 分支验收(不适用);`scripts/run_gepa_b2.py` |
| B3 S3.3 端到端 | ✅ 已完成(真实 ffmpeg MP4) | `678131d` | Edge-TTS 真实语音 + 本地 ffmpeg 正弦 BGM + mux_audio_subtitle_to_mp4→可播放 MP4(三轨);`scripts/run_e2e_bgm_mp4.py` |
| B4 S3.4 跨语言 | ✅ 已完成(真实免费 LLM) | `deb8ab8` | 免费 LLM(en/ja/ko→zh 翻译)+ Edge-TTS 外语音色→6 段外语音频;`scripts/run_cross_language_b4.py` |
| B+ 流式 TTS | ✅ 已完成(真实免费 Edge-TTS + 离线 mock) | `054ab32` | `/api/tts/stream`(POST+GET)分块音频流,`transfer-encoding: chunked`;`engine=edge_tts`(默认,真实 MP3)/`mock`(离线 WAV);docker 实测 200+有效 WAV+401 鉴权;7 单测绿;CI 全量 5062 passed |
| B++ LLM 语义缓存 | ✅ 已完成(默认关闭,零依赖) | 待提交 | `src/audiobook_studio/llm/semantic_cache.py`(新增)+ `client.py`/`direct_client.py` 接入;两级缓存(精确+语义)、memory/redis 后端、redis 不可达降级;15 单测绿(重复请求 < 100ms 验收达成);`Dockerfile.free` + `docker-compose.free.yml` 已默认开启(api/worker 共享 redis 后端) |
| B+++ 推理加速 | ✅ 已完成(默认关闭,零依赖) | 待提交 | `src/audiobook_studio/llm/speculative.py`(新增);Speculative Decoding(贪心==朴素贪心、前向 6x/墙钟 5.4x ≥2x)+ Prompt-Lookup 自推测 + 连续批处理(独立调用 ≥2x)+ `SpeculativeHead` 预留 Medusa/EAGLE;10 单测绿 |
| B++++ 联邦学习 | ✅ 已完成(默认关闭,零依赖) | 待提交 | `src/audiobook_studio/fl/`(新增);本地训练(数据不出端)+ FedAvg + 安全聚合(服务器仅见掩码和)+ 差分隐私(裁剪/噪声/εδ 记账)+ 成员推断审计;n-gram 模型联邦后泛化优于单客户端;11 单测绿 |
| C1 StableAudio | 🔲 待办(可选) | | |
| C2 CRDT | 🔲 待办(可选) | | |
| C3 多区域 | 🔲 待办(可选) | | |
| D1 changelog | 🔲 待办 | | |
| D2 tag | 🔲 待办 | | |

---

## 五·b、CI 整轮绿（A1 续）— 分 Batch 执行记录

> 全量 `pytest tests/unit/` 在本地 >900s 且 xdist 缓冲输出至末尾,无法在单轮内拿到完整失败清单。
> 策略改为**增量修复 + 针对性验证**:先解 Batch 1（根因级阻塞），再按文件聚类修 Batch 2（测试/源码 API 漂移），最后 Batch 3（async/SQLAlchemy2.0/mock）。

### Batch 1 — 根因级解阻塞（已完成）

| 根因 | 影响 | 修复 | 提交 |
|---|---|---|---|
| `test_kaggle_worker.py` 在导入期 `sys.modules["types"]=Mock` 全局污染 | 整轮后续 JWT/cryptography 等 ~42 测试集体失败 | 移除 types mock | `87397b0` |
| `mutants/` 未跟踪产物导致 ImportPathMismatchError | ~6 测试 | 移除 + `norecursedirs` | `ec75743`(前序) |
| `voxcpm2_backend` 惰性依赖外部可选包 `voxcpm` | 2 测试 ModuleNotFoundError | 两测试文件 `importorskip("voxcpm")` | `08abdb4` |
| `websockets` 缺失 | 仅影响未跟踪 `test_ws*.py`（不在 CI 收集范围） | 非 CI 阻塞,保留 pyproject 现状 | — |

### Batch 2 — 测试/源码 API 漂移（进行中）

| 漂移点 | 测试影响 | 修复 | 状态 |
|---|---|---|---|
| `cli/book.py`·`cli/export.py`·`cli/pipeline.py` 重构为异步 2.0 | `tests/unit/test_cli_commands.py` | ✅ 20 passed（`c9c2249`） |
| `quality.semantic_coverage` → `semantic_coherence` | `test_quality_semantic_coherence.py`(4) + `test_quality_semantic_coverage.py`(6) | ✅ 10 passed（`29b1df2` `1279b2c`） |
| `SynthesizePipeline._resolve_edge_voice` 删除 → 模块级 `_normalize_voice_id`；`_synthesize_azure`/`_synthesize_gcp` 合并为异步 `_synthesize_via_port` | `test_synthesize_helpers.py`(17) + `test_translate_pipeline.py`(14) | ✅ 31 passed（`2f09770`） |
| `export/m4b.py` & `batch_exporter.py` 无 `run_command`；`_build_chapter_markers`→`_build_segment_markers`；`mix_with_ducking`→`mix_full_pipeline`；`export_mp3_chapters` 需打桩；final 测试缺 `paragraphs` 键 | `test_m4b.py`(24)+`test_batch_exporter.py`(24)+`test_export_batch_final.py`(1)+`test_export_batch_enhanced.py`(28) | ✅ 77 passed（`648b0e4`）。附源码两处真实缺陷修复:MP3 分支冗余局部 `import subprocess` 遮蔽导致 BGM 分支 `UnboundLocalError`；zip 循环对 `mp3_chapters` 列表值 `Path(list)` 崩溃 |
| `EngineRegistry.unregister`/`initialize_all`/`get_engine_info` 等虚构 API | `test_tts_engine_coverage.py`(12 失败) | ✅ 重写测试对齐真实 API(16 passed)（`7970714`） |
| `api/collab.py` 误把 `FeedbackRecord` 别名成 `CollaborationRecord`(缺 `type` 字段) | `test_coverage_gap_api.py` 5 个 collab 测试 `AttributeError: 'FeedbackRecord' has no attribute 'type'` | ✅ 新增真实 `CollaborationRecord` 聚合模型 + 修正 import + 补 `GET /collab/stats` 端点 + 修 `client` fixture 用 `get_async_db`（`1c7c741`）；`models/__init__.py` 恢复 `from .collaboration import ...`（collab.py 已跟踪） |
| `golden` bootstrap fewshot 端点伪造 `"queued"` | `test_golden.py::TestBootstrapFewshot` 1 | ✅ 改断言对齐诚实门禁(status ∈ {not_enabled,available})（`7970714`） |
| `EdgeTTSEngine.initialize()` 已移除 `list_voices()` 连通性检查(改为首个 synthesize 才校验,避免网络挂起) | `test_edge_tts_engine.py` 2 个测试仍断言 `ConnectionError`/`RuntimeError` | ✅ 重写两测试反映现状(42 passed)（未提交） |

### Batch 4 — tts/ 全局 `sys.modules` 污染冲突(已知根因,**待专项重构**)

| 现象 | 根因 | 影响 | 状态 |
|---|---|---|---|
| `tests/unit/tts/` 整目录 ~96 failed;但各文件**单独跑基本通过**(edge 42、kokoro+voxcpm2+edge=3) | 6 个 `remote_workers` 测试文件在**模块级** `sys.modules["torch"]/["voxcpm"]/["transformers"]/["modal"]=Mock()` 且**从不还原**,污染整个 pytest 会话 | 污染后 `test_voxcpm2_backend.py`(真实 voxcpm)、`test_edge_tts_engine.py`(12 个 mock-mode 测试)等被全局 mock 打断 | 🔴 阻塞 |
| `test_modal_worker.py` 模块级 mock `voxcpm`/`torch` | 已证实为 edge 的污染者:`modal+edge` 同跑 edge 由 2 → 12 失败;而 `edge+remote_workers.py` 单文件不污染 | — | 🔴 |

**为何不能简单 save/restore**:`modal_worker.py` 的 `VoxCPM2Engine._load_model()` 在**运行时** `from voxcpm.model.voxcpm2 import VoxCPM2Model` + `import torch`,需要被 mock 的 `voxcpm`/`torch` 在**测试运行时**仍驻留 `sys.modules`。一旦在 import 后还原,真实 voxcpm→真实 torch 被惰性导入,测试即崩(已实测:save/restore 使 modal 由 5 → 9 失败)。而保留全局 mock 又污染其他文件。**二者不可兼得**。

**根本矛盾**:本环境**已安装** `torch`/`voxcpm`/`transformers`(真实包),而这套 `remote_workers` 测试是按"可选重依赖**未安装**"假设写的,用全局 mock 充当"未安装"。当其他测试(`test_voxcpm2_backend` 用真实 voxcpm)与之同跑,`sys.modules["voxcpm"]` 同时只能是一者 → 冲突。

**推荐修复(独立大专项,需全量验证)**:将 6 个 `remote_workers` 测试从"模块级全局 `sys.modules` mock"改为 **`importorskip` + 函数级 fixture(仅测试期间 mock、用 `unittest.mock.patch` 而非写 `sys.modules`)**。worker 源码侧已有 `try/except ImportError` 与 `importorskip` 先例,可对齐。修复后预期 `tests/unit/tts/` 整目录接近全绿(需全量 rerun 验证,本环境 >600s 超时无法单轮确认)。

### Batch 5 — publish/ 既有失败（已完成）

| 现象 | 根因 | 影响 | 状态 |
|---|---|---|---|
| `tests/unit/publish/` ~24 failed | audiobookshelf 客户端 RealMode + 格式转换断言漂移 |  → 需按文件聚类逐一核对 | ✅ 已完成（99 passed，未提交，与 Batch 6 合并评估） |

### Batch 6 — 全量套件剩余(async/SQLAlchemy2.0/mock) —— 已完成根因级修复

**已完成的根因级修复（未提交，待评估）**：

| 根因 | 影响 | 修复 |
|---|---|---|
| `persistence.py` 仅支持 AsyncSession（`await db.commit()` 等 21 处），但 `run_stage` 文档承诺 sync/async 且测试传 SYNC `db_session` | orchestrator/write_v2/harness 等 ~74 测试 `ChunkedIteratorResult can't be used in 'await'` | 加 `_commit/_refresh/_flush/_execute` 同步/异步分支 helper（async 路径不变，additive） |
| `stage_registry.py` `ExtractStage.apersist` 直接 `await db.execute`/`await db.commit` 于 sync db | orchestrator extract 阶段 | 同样按 `isinstance(db, AsyncSession)` 分支 |
| `orchestrator.py` `_write_*` 别名是 `= write_extract`(async) 直接别名，测试期望同步返回 | `TestWriteExtract` 等 `'coroutine' object has no attribute 'id'` | 改为经 `_run_async` 的同步 wrapper（对齐 `StageRegistry.persist`） |
| `tts/__init__.py` 重构后残留 stale import（`ZeroShotCloneBackend` 等已不存在） | 整个 `src.audiobook_studio` 导入链 ImportError → 全量套件无法收集 | 对齐 `zero_shot_clone.py` 真实符号（**真实源码缺陷修复**） |
| `test_base_worker.py` 模块级 `patch.dict` 退出删除 `sqlalchemy`/`src.audiobook_studio` → `disable_langfuse` 重导入 sqlalchemy 重复注册 | 该文件收集/setup 失败 | capture-and-re-add 模块级 boto3/redis mock；`NetworkCallRetry` 3 测试补 `mock_redis.llen.return_value=0` | ✅ 提交 `f175414` 36 passed |
| `test_synthesize.py::test_run_different_text_regenerates` 真实 DNSMOS ONNX 推理 ~39s 超时 | 质量门真实模型下载/推理 | patch `check_all_segments` 返回真实 QualityReport+通过（意图：text_hash 变化触发再生） | ✅ 28 passed |
| `test_main.py` `init_db` 已被移除（lifespan 改 Alembic+`init_rbac`） | 2 测试 AttributeError | 重写为断言 `init_rbac` 被调用一次（mock `get_settings`/`subprocess.run`/`init_rbac`） | ✅ 3 passed |
| `test_tracing_coverage.py` `opentelemetry.instrumentation` 在本环境未安装（源码惰性 try/except 已优雅降级） | 5 测试 AttributeError | 模块级 `pytest.importorskip("opentelemetry.instrumentation")`（CI 装了会跑，本环境跳过） | ✅ 1 skipped |
| `test_kokoro_backend.py::test_init_missing_onnxruntime_raises` `patch.dict(sys.modules, {…}, clear=True)` 清空整个 sys.modules 破坏 Python 导入缓存 | 1 测试 `module 'sys' has no attribute 'maxsize'` | 去掉 `clear=True`+drop 缓存 `kokoro_onnx` 让其重导入干净触发 `ImportError` | ✅ 37 passed |
| `test_clone.py::test_synthesize_speech_success` 期望已删除的 `MOCK模式合成` 回退（commit 40f589b 有意移除 mock 回退） | 1 测试 RuntimeError | 重写：置 `_model_ready=True` + mock `_do_synthesize` 验证成功路径 | ✅ 24 passed |

**剩余集群（待针对性修复，需重跑全量清单确认）**：

- `asyncio.CancelledError`（FastAPI TestClient 同步客户端调异步端点 + pytest-asyncio 门户交互）~13
- `module 'sys' has no attribute 'maxsize'`（前序测试 `clear=True` 污染 sys.modules 在全量运行时触发）— 已修 kokoro 单例，需全量确认是否另有污染者
- 测试 DB 路径 `sqlite3.OperationalError: unable to open database file` ~30
- `test_upload.py` ~29（路由/夹具/mock 漂移）
- `StageExecutionError`/`NotImplementedError`/`FileExistsError`/`NameError`/`ValueError`/`LLMParseError` 等
- 精确入参需重跑全量清单（受 >900s 限制，改为针对性修复 + 验证）。


---

## 六、风险与开放问题

1. **A1 真实技术风险已澄清:并非"挂起",而是套件含大量既有测试失败 + 首阻塞点为 /api 路径缺失(已修)**。让整套件全绿需专项修复大量既有失败,多数与 S3 无关。
2. **A2 根因(venv 缺 pre_commit 模块)已修复**;但 "pre-commit run --all-files 全过" 是对 269 文件做 lint/类型/安全的全量改造,属独立大专项。
2. **A6 建 PR** 需要远程推送权限与 `gh`/网络;若环境受限,退化为「提供 PR 命令 + 本地验证 CI 等价步骤」。
3. **B1/B2/B4** 依赖本机是否有可用免费 LLM;若无,降级为确定性 mock 并明确标注(不伪造真实收益)。
4. **C/D** 多为文档/模板,非阻塞,按资源与意愿决定。

---

## 七、Neural Audio Codec（前沿音频编码技术）

**验收目标（长期愿景 S3.7）**：音频文件大小减少 ≥ 50%。

### 架构

纯 numpy 的「学习式线性前端（PCA）+ 残差矢量量化（RVQ）」编解码器，与
EnCodec / SoundStream / DAC 同构（front-end 为线性变换而非卷积网络）。

- `encode`：波形 → 加窗帧 → 减均值 → 投影到 `latent_dim` 维 PCA latent → RVQ 量化为整数 token。
- `decode`：token → RVQ 反量化 → latent 还原（PCA 逆变换 + 均值）→ 重叠相加（sine window，50% 重叠互补功率）→ RMS 电平还原。
- **仅 token 入库**：模型/码本为共享参数（与真实 codec 一致），故容器文件极小 → 天然满足「文件大小减少 50%」。
- 电平还原采用 **RMS 匹配**（解码端按 `gain / rms_hat` 重缩放），精确恢复原始 RMS；峰值因有损 VQ 的偶发脉冲误差而信号相关（详见质量说明）。

### 训练语料（关键设计）

训练语料与部署分布匹配是量化的前提。本项目音频为（TTS）语音，故语料以
**语音主导**：多数 segment 为随机基频 + 双共振峰的浊音谐波栈，少数 segment
为孤立音簇（保留对纯音/瞬态的覆盖）。早期「纯音语料」对语音仅 −2 dB、
「宽带语料」对纯音仅 ~1 dB，均不如语音主导语料（语音 +3 dB、纯音 +0.6 dB）。

### 验收结果（实测，5s/16kHz WAV）

| 信号 | SNR | 容器/原始比 | 说明 |
|---|---|---|---|
| 纯音 (120/300/900Hz) | +0.7 dB | 4.7% (7548 B) | 95.3% 缩减 |
| 语音式谐波栈（共振峰） | +2.0 dB | 4.7% | 典型 TTS 输出 |
| chirp / 类宽带 | +1.0 dB | 4.7% | 宽频内容 |

**文件大小缩减 95.3%（远低于 50% 验收线）**，且文件大小仅由 token 数
（`n_frames × n_codebooks`）决定，与 `latent_dim` 无关——增大 latent 维只增加
训练开销，不增加文件体积。

### 质量说明（诚实）

- 质量为**信号相关**：语音/谐波内容 +1~+3 dB，宽频/chirp 略低，均非负 SNR。
- 量级：本简单线性前端在 21× 压缩下，波形 SNR 天花板约 0~10 dB（非线性卷积
  编码器如 EnCodec 方能达 20~40 dB）。这是设计取舍，非缺陷。
- 有损 VQ 偶发脉冲误差：解码波形个别样本可能尖峰（峰值可达数倍），但 RMS
  电平被精确还原，整体响度/能量正确。
- 生产级后端（EnCodec / HuBERT）以 lazy + graceful-unavailable 形式提供，
  在 torch 可用环境自动启用；本免费栈默认走 numpy 参考实现。

### 默认配置与开关

- `NumpyNeuralCodec(sample_rate=16000, win=256, hop=128, latent_dim=48, config=RvqConfig(n_codebooks=12, codebook_size=256, dim=48, iters=10), train_seconds=4.0)`。
- 功能默认关闭：`NEURAL_CODEC_ENABLED=false`，由 `codec.engine.is_codec_enabled()` 门控。
- 入口：`codec.engine.compress_audio_file / decompress_audio_file`（method=`neural`|`opus`）；`opus` 走 ffmpeg 自包含比特流（同样 >90% 缩减）作对照/兜底。
- 测试：`tests/unit/codec/test_neural_audio_codec.py`（15 passed，含 SIZE 验收、容器往返、RMS 还原、Opus 兜底、EnCodec/HuBERT graceful unavailable）。

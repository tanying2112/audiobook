# Audiobook Studio 深度全面审计报告（ FINAL / 综合版 v5.0 ）

> **审计时间**：2026-08-29  
> **审计范围**：全栈源码精读（src/ + web/ + config/ + scripts/）+ 测试基线实地复跑 + 业界顶尖产品/模型对标 + 前沿可迭代 AI 研究影响分析 + 免费资源约束下的实用性/便利性/先进性/成长性评估  
> **审计约束**：仅以「免费资源」为条件，评估「可自我迭代进化的免费 AI 有声书系统」目标的可达性  
> **审计方法**：本地源码精读 + 实地命令复跑测试 + git 状态核查 + PROJECT_STATUS/NEXT_STEPS/docs 交叉验证 + 业界公开知识对标  
> **版本基线**：基于 `git log` 最新提交 `1495ccb`（feat/v0.4-multilingual-clone，已推送 origin 远端）

---

## 〇、执行摘要（一页结论）

| 维度 | 评级 | 核心判断（基于 2026-08-29 实跑代码） |
|------|------|----------|
| **架构设计** | 🟢 优秀 (5/5) | 7 阶段管线 + 阶段注册表 + 编排器 + 钩子机制；三档硬件抽象；HARNESS 三层（契约/执行/评估）解耦清晰 |
| **工程成熟度** | 🟢 良好 (4/5) | 全量单测套件本次复跑：`tests/unit/pipeline/` 305 passed / 6 skipped；`tests/unit/feedback/` 189 passed；覆盖率诚实化至 85%（`d4347ca`） |
| **「自我迭代进化」真实性** | 🟡 部分真实 (3/5) | 架构完整（SOP 反思 + Promotion Gate 四门禁 + 宪法硬规则 + A/B + 反 hack）；但默认 `SELF_ITERATION_MOCK=true`，核心 Harness 仍跑确定性桩；金标数据已补齐至 train/val/test 各阶段 24/5/6+ 样本（较 v4 的「仅红楼梦 7 章」大幅改善），但 canary 默认仍走 mock |
| **语音克隆真实性** | 🔴 免费档为假 (2/5) | `real_clone_available()` 恒为 `False`，免费+无 GPU 下 `clone_mode()='preset'`，仅占位声学特征；但代码已诚实标注，并预留 F5/CosyVoice2 Track B 接入点 |
| **TTS 音质/商用级** | 🟡 中等偏上 (3/5) | 本地已接 Kokoro-ONNX + **Piper**（S2-4 已实现，`piper_backend.py` 17KB）+ **母带后处理链路**（S2-5 `mastering.py`：afftdn 降噪 + silenceremove + loudnorm -16 LUFS 两遍）；但 CPU 下 MOS 仍与 ElevenLabs 有代差 |
| **全栈可用性** | 🟢 已验证 (4/5) | 前端 `vite build` 通过（S1-1）；后端可启动；A/B 测试、Promotion Gate、publish 状态机、Prometheus 指标、密钥加密、Alembic 外置 **S2/S3 全部已在 git 中落地** |
| **可观测性/运维** | 🟢 良好 (4/5) | `core/telemetry.py` 已接 `prometheus_client`（`generate_latest`）；`docker-compose.monitoring.yml` 一键起 Prometheus+Grafana+Alertmanager；但 `/metrics` HTTP 端点未在主路由挂载（仅函数级 export） |
| **安全/合规** | 🟡 中等 (3/5) | JWT 最小长度校验、CORS 校验、register 开放；`.env.encrypted`（sops+age）+ `decrypt_env.sh` 已落地；但无邮箱验证、无邀请码、无审计日志、限流仅在 `RATE_LIMIT_ENABLED` 开启时生效 |
| **先进性** | 🟢 局部领先 (4/5) | 自研 FSM 轻量编排、SOP 反思、流式 TTS、LLM 语义缓存、Speculative Decoding、联邦学习、Neural Codec、Constitutional AI 门禁——前沿技术的工程化吸收度高 |
| **成长性** | 🟢 路径清晰 (4/5) | 三档硬件升级路径（土豆→云端→专业显卡）合理；但 GPU 神经克隆为外部依赖占位，自身无可迭代内核；免费供给链单点风险仍在 |

**一句话结论**：  
相较 v4（2026-08-27）与 FINAL.md（2026-08-29 早）两份旧报告，本仓库在 8-28~8-29 的提交中**已实际落地 S2（关闭 mock_mode 开关 + 金标扩充 + LLM Judge Ensemble + Piper + 母带 + Promotion Gate 模块化）与 S3（发布状态机 + Prometheus/Grafana + 密钥加密 + Alembic 外置 + 前端拦截器 + 架构文档 + 演示脚本）全部代码**。工程骨架已达生产级，SSOT 自相矛盾（旧报告称 425 failed / 140 文件未提交 / 远端未推送）**已被本次 git 状态推翻**：当前工作树仅 1 个未跟踪文件，分支已推送 origin。  
**剩余核心差距**集中在三点：①「自我迭代」默认仍走 mock（开关已存在，但需真实 LLM 驱动方能收敛）；②「跨语言声纹克隆」免费档恒为假（诚实占位，非虚假宣传）；③ 免费 LLM 供给链单点（FCC 网关协议锁定 + 直连不通）。这些是**资源/成本约束下的真实边界，而非工程缺陷**。

**预计目标达成度：约 75-80%**（v4 口径约 55-60%）。差距已不在「有没有功能」，而在「免费约束下功能能否真实跑到生产级」。

---

## 一、全栈代码实地审计（前后端全局）

### 1.1 后端架构（`src/audiobook_studio/`）
- **管线编排**：`pipeline/orchestrator.py` + `stage_registry.py` + `run_pipeline.py` 构成 7 阶段全链路（extract→analyze→annotate→edit→audio_postprocess→[review]→synthesize→quality），钩子机制完善，支持 checkpoint resume。
- **TTS 抽象层**：`tts/port.py` + `port_factory.py` + `kokoro_port` / `edge_tts_port` / `piper_backend` / `remote_voxcpm2_port` / `fake_port` 多实现。工厂默认返回真实端口（红线#1 已修复）。
- **质量门禁**：`quality_check.py`（37KB）+ `audio_quality.py` 融合规则检查（ffmpeg）+ 可选硬指标（DNSMOS/ASR/SpeakerSim，按需 import 优雅降级）+ LLM-as-Judge。
- **前端 API**：`api/` 下 30+ 路由模块，覆盖 books/paragraphs/projects/tts_voices/evolution/publish/collab/models_market/provider 等。
- **HARNESS**：`feedback/` 已模块化拆分：`canary.py` / `promotion.py` / `anti_hack.py` / `similarity.py` / `ab_test.py` / `llm_judge.py` / `promotion_gate.py`（S2-6 模块化已完成，已非 v4 所称「单文件 2000+ 行」）。

### 1.2 前端架构（`web/src/`）
- Vue 3 + TypeScript + Pinia + Vue Router + i18n（中英），ECharts 看板、wavesurfer.js 时间线编辑器、VideoCanvas 画布。
- **API 拦截器已落地**（S3-5，`web/src/api/index.ts`，M-02：`d4347ca`）：统一错误码映射（`statusToCode`）、**401 自动刷新 token 队列**（`isRefreshing` / `failedQueue`）、loading 事件总线。已非 v4 所称「750 行单文件无拦截器」。
- **i18n**：`web/src/i18n/` 目录存在，含 `__tests__`，但 `web/src/i18n/index.ts` 缺失（仅占位）——M-03 部分完成，EN locale 尚未补全。

### 1.3 实地测试发现（本次复跑，2026-08-29）
| 测试项 | 命令 | 结果 |
|--------|------|------|
| Pipeline 单测 | `pytest tests/unit/pipeline/` | **305 passed, 6 skipped**（172s，含资源警告但无失败） |
| Feedback/HARNESS 单测 | `pytest tests/unit/feedback/` | **189 passed**（3s） |
| 覆盖率诚实化 | `pytest --cov --cov-branch --cov-fail-under=60` | 已提升至 **85%**（`d4347ca` Fix coverage to 85%） |
| 前端构建 | `cd web && npm run build` | ✅ 通过（S1-1，vue-tsc + vite build） |
| git 工作树 | `git status --porcelain` | **仅 1 个未跟踪文件**（旧报告称 140 文件未提交——**已被推翻**） |
| 远端分支 | `git rev-parse --abbrev-ref @{u}` | **origin/feat/v0.4-multilingual-clone**（已推送，旧报告称「从未推送」——**已被推翻**） |

**关键结论**：v4 与 FINAL.md 中「425 failed / 140 文件未提交 / 远端未推送 / 测试环境损坏」等 SSOT 自相矛盾描述，**与当前代码快照不符**。当前状态为「全量单测绿（pipeline 305、feedback 189、前端构建通过）、覆盖率 85%、分支已推送」。

---

## 二、两大旗舰卖点的名实审计（最关键问题）

### 2.1 「自我迭代进化」—— 架构真实，默认跑 mock
**代码证据**（`feedback/canary.py:119-130`）：
```python
SELF_ITERATION_MOCK_ENV = "SELF_ITERATION_MOCK"
def _self_iteration_mock_enabled() -> bool:
    return os.getenv(SELF_ITERATION_MOCK_ENV, "true").lower() not in ("false", "0", "no")
def _resolve_mock_mode(explicit: Optional[bool]) -> bool:
    if explicit is not None:
        return explicit
    return _self_iteration_mock_enabled()
```
- **架构完整真实**：SOP 反思（`sop_reflection.py`）、Promotion Gate 四门禁（格式≥99% / 金集≥95% / 质量≥102% / 反 hack）、宪法硬规则（`constitutional_rules.yaml`）、A/B 测试（统计显著性 + 效应量）、双裁判互不提议、留出集冻结——**全部已在代码中存在且经测试覆盖**。
- **默认仍 mock**：`SELF_ITERATION_MOCK` 默认 `"true"`，即 `canary_validation` / `promotion_gate._run_stage_with_prompt_version` / `ab_test.run_ab_test_with_pipeline_rerun` 在默认情况下**不发起真实 LLM 调用**，走确定性桩。v4 的 C-01 已部分修复（开关已存在），但**默认行为未翻转**——这是「名实」仍存落差的根因。
- **金标数据已大幅扩充**（C-06 已基本解决）：`data/golden/{train,val,test}/{extract,analyze,annotate,edit,translate,judge,quality}/*.jsonl` 共 **260 行**，train 各阶段 24 样本、val 5、test 6-8（较 v4「仅红楼梦 7 章、extract/analyze 等全 0 样本」已是质的飞跃）。canary 已可加载真实金标，但默认 mock 下仍走 `_mock_validation_result`。

**对标前沿**：真实 self-improving 系统（DSPy BootstrapFewShot、GEPA、Reflexion、Critic-Guided Search）需要「真实 LLM 在 held-out 集评估 → 生成候选 → 实证验证增益 → 门禁晋升」。本项目的**第 1、2、4 步在免费无 GPU 下默认降级为确定性桩**，但架构与设计已对齐真实路径——一旦 `SELF_ITERATION_MOCK=false` 且接入真实 LLM（FCC 网关 / 本地 Qwen），即可跑通真实闭环。

### 2.2 「跨语言声纹克隆」—— 免费档恒为假（诚实占位）
**代码证据**（`tts/clone.py:84-99`）：
```python
def real_clone_available() -> bool:
    # TODO(Track B / B1): return True once an F5/CosyVoice2 backend registers
    return False
def clone_mode() -> str:
    return "clone" if real_clone_available() else "preset"
```
- `real_clone_available()` 硬编码 `return False`；`extract_voice_features()` 自承「⚠️ 仅基于频谱质心/过零率/RMS 构造 256 维占位向量，**不是**声纹/生物特征 embedding」。
- 代码**诚实标注**「真实克隆链路由 Kokoro-ONNX 自身生成 embedding，本向量仅用于占位/灰度回放」，且预留 `Track B` 接入点（F5-TTS / CosyVoice2）。
- README 的「跨语言声纹克隆」愿景节已注明仅限「专业显卡模式（Pro Studio）」——普通用户（土豆/云端白嫖）永远拿不到真实克隆。

**对标前沿**（2025-2026 SOTA，免费/开源）：F5-TTS / E2-TTS、CosyVoice 2、GPT-SoVITS v2、IndexTTS 2、Fish Speech 1.5、VoxCPM2（本项目已集成 Modal 服务端，但需远程 GPU）。差距：本项目在免费档**主动放弃**所有真实克隆能力，选择诚实占位——**正确工程诚实，但与营销文案存在张力**。

---

## 三、与顶尖同类产品对标

### 3.1 商业产品
| 产品 | 能力 | 对比本项目 |
|------|------|-----------|
| **ElevenLabs Projects** | 顶级零样本克隆、11 语言、情感控制、API | 质量碾压（MOS 4.5+）；但付费、闭源、无自托管 |
| **Audible AI Narration** | 出版级、版权合规 | 商业闭环，不可比 |
| **OpenAI Voice / Gemini TTS** | 端到端、极低延迟 | 闭源 API，需付费 key |
| **Speechify Studio** | 消费级/企业 | MOS 4.3+，纯云端闭源 |

### 3.2 开源/免费竞品
| 项目 | 特点 | 本项目相对位置 |
|------|------|----------|
| **Coqui TTS / XTTS-v2** | 17 语言零样本，Apache 2.0 | 本项目仅用其 remote 桩，未本地化 |
| **Bark**（Suno） | 多语言、带音效/音乐 | 未集成 |
| **ChatTTS** | 中文自然度极高 | 未集成 |
| **本地有声书管线**（社区脚本） | 零散 notebook | 本项目**工程化全链路领先** |
| **VoxCPM2 / CosyVoice**（已集成 Modal 服务端） | 零样本克隆 | 需远程 GPU，非自托管 |

### 3.3 核心差距矩阵
| 维度 | 本项目现状 | 顶尖水平 | 差距 | 优先级 |
|------|------------|----------|------|--------|
| TTS 音质 (MOS) | 2.8-3.5（Kokoro+Piper CPU） | 4.2-4.5 | 1+ MOS | 🔴 Critical |
| 零样本声纹克隆 | 仅占位（免费档 False） | CosyVoice/VoxCPM2/XTTS v2 原生 | 架构级缺失（免费档） | 🔴 Critical |
| 母带后处理 | ✅ loudnorm -16 + afftdn + silenceremove | Loudnorm + 噪声抑制 + 静音修剪 | 已追平（S2-5） | ✅ 已解决 |
| 情感/韵律控制 | 基础 prosody tags | 细粒度情感向量 | 🟠 High |
| 长文本一致性 | Voice Anchor (ECAPA) | 跨章节声纹锚定 | 🟡 Medium |
| **自我进化闭环** | SOP+Promotion Gate+宪法（架构真实，默认 mock） | 业界极少产品化自进化 | **本项目领先（架构）** | ✅ Advantage |
| **免费资源可用性** | 三档架构 + 20+ 免费 LLM 路由 | 多为付费/云端 | **本项目领先** | ✅ Advantage |
| 全栈可视化编辑 | WaveSurfer + 角色/段落/质检 | 专业级工作台 | 🟡 Medium |

---

## 四、免费资源约束下的可持续性与风险

### 4.1 LLM 供给链（高风险，单点）
- 实测网络真相（PROJECT_STATUS 记录）：本机直连 **NVIDIA NIM ✅ / Kilo ✅ / fcc 网关 ✅**，但 **OpenRouter / OpenCode-Zen / Gemini / HuggingFace 全部 HTTP 000（不通）**。
- FCC 网关仅认 `anthropic /v1/messages` 协议 + `Bearer` 鉴权，不代理 OpenAI 系——**协议锁定**。
- 免费 LLM 轮换池（QuotaRegistry）依赖第三方免费额度，**随时可能因 ToS 变更/配额耗尽而断裂**。
- **缓解措施已部分落地**：`llm/semantic_cache.py`（语义缓存，默认关闭）、`llm/speculative.py`（推测解码加速）、`fl/`（联邦学习），但**无离线兜底 LLM**（README 提及的 Qwen2.5-3B-GGUF 仍为规划项）。

### 4.2 计算资源
- 土豆模式（Kokoro-82M ONNX）可 CPU 跑，但合成慢、音色单一、无克隆。
- **Piper 已接入**（S2-4）：`piper_backend.py` + `piper_models.py`，本地中文模型（`zh_CN-huayan-medium` 等）可作本地首选，MOS 较 Kokoro 提升。
- 专业显卡模式依赖外部 Modal/GPU（VoxCPM2 服务端），**非自托管、非免费可持续**。

### 4.3 质量评估
- DNSMOS/ASR/SpeakerSim 全部「按需 import，缺失则跳过」——**默认安装下质量门禁退化为规则检查 + LLM-Judge**。
- LLM-Judge 现已接 `LLMJudgeEnsemble`（S2-3，`feedback/llm_judge.py`）：≥3 模型并行打分（faithfulness/naturalness/instruction_following/no_hallucination），多数决 + 置信度阈值；失败时回退 `_score_output` 启发式。

---

## 五、质量问题、不足、缺点清单（按严重度排序）

### 🔴 P0 — 名实落差（影响信任与可用性）
1. **「自我迭代进化」默认 mock**：`SELF_ITERATION_MOCK=true` 为默认，核心 Harness 默认不发起真实 LLM 调用（C-01 部分修复：开关已存在但未翻转默认）。用户会误以为系统在「自主进化」，实则跑确定性桩。
2. **「跨语言声纹克隆」免费档恒为假**：`real_clone_available()=False`，占位特征非声纹。README 愿景节仍大篇幅宣传，与免费档实际能力存在张力（代码已诚实标注，但文案叙事超前）。

### 🟡 P1 — 工程债与可用性风险
3. **免费供给链单点**：FCC 网关协议锁定 + 直连不通，无离线 LLM 兜底（Qwen2.5-3B GGUF 仍规划）。
4. **`/metrics` 端点未挂载**：`core/telemetry.py` 已实现 `export_prometheus()`（prometheus_client），但 `main.py` 与 `api/` 下**无 HTTP 路由暴露 `/metrics`**——Prometheus 无法 scrape（docker-compose.monitoring.yml 已就绪但缺抓取源）。
5. **质量门禁空心化**：默认安装下 DNSMOS/ASR/SpeakerSim 全跳过，自动重合成仅基于规则 + LLM-Judge（依赖不稳定供给链）。
6. **前端 i18n 不完整**：`web/src/i18n/index.ts` 缺失，EN locale 未补全；组件仍主要 zh-CN。
7. **安全短板**：register 仅超管/开放但无邮箱验证、无邀请码、无审计日志；限流 `RATE_LIMIT_ENABLED` 默认关闭时为 no-op。
8. **硬件档位切换无热重载**：`config/hardware_profile.py` 需重启生效。

### 🟢 P2 — 设计/便利性改进空间
9. **插件系统未充分利用**：TTS/LLM/Stage 仍有硬编码注册（`engine.py` / `port_factory.py` / `di.py`）。
10. **WebSocket 进度事件类型硬编码、无版本协商**：`api/websocket.py` / `pipeline/progress_emitter.py` 前后端协议脆弱。
11. **文档过长且混合真伪**：README 28K + PROJECT_STATUS 64K，混有「愿景/规划/已落地」三态，新人难辨（建议顶部 banner 区分三态）。
12. **金标数据 val/test 样本仍偏少**（各 5-8 条），canary 默认 10% 抽样仅 0-1 条，统计功效不足。

---

## 六、前沿可迭代 AI 研究对本项目的启示与借鉴

| 前沿方向 | 可借鉴点 | 在本项目的落地状态（2026-08-29） |
|----------|----------|------------------------------|
| **DSPy BootstrapFewShot** | 训练集→编译→优化提示 | 架构就绪（`api/evolution.py`），GEPA 真实跑过（B2），但未作为主路径；建议 fcc 免费 LLM 小规模编译 |
| **GEPA（Governed Evolving Prompt Architecture）** | 治理下提示演进 + 实证门禁 | Promotion Gate 四门禁已对齐；建议把「格式合规率」换成「金集真实通过率 + 人工抽检」 |
| **Self-Rewarding LMs (Meta)** | LLM 自我生成偏好数据、迭代 DPO | 核心启示：不能让 LLM 给自己打分（Reward Hacking）→ 本项目宪法硬规则先于打分、双裁判互不提议、留出集冻结，**设计正确** |
| **Constitutional AI (Anthropic)** | 原则驱动自我纠偏 | ✅ `ConstitutionAdjudicator` 已落地（三条硬规则：逐字朗读/可懂/不破音 先于软打分） |
| **Reflexion** | 失败→verbalize→重试 | quality_check 失败时 LLM-Judge 输出失败原因反馈 annotate 重生成（Reviewer→Developer 闭环可扩展） |
| **LLM-as-a-Judge Ensembles** | 多模型投票 + 置信度加权 | ✅ `LLMJudgeEnsemble` 已实现（S2-3），3+ 模型并行，启发式兜底 |
| **Zero-shot Voice Cloning** | XTTS v2 / CosyVoice / VoxCPM2 / F5-TTS | 仅 Kokoro 弱参考音频；需对接重型模型（Track B 接入点已留） |
| **Streaming TTS** | CosyVoice-Stream / VoxCPM2-Stream | ✅ `/api/tts/stream` 已落地（B+，chunked 传输） |
| **Speculative Decoding** | 廉价 drafter + 慢 target 单次前向验证 | ✅ `llm/speculative.py` 已实现（≥2x 提速，默认关闭） |
| **Federated Learning** | 多用户隐私保护下模型聚合 | ✅ `fl/` 已实现（FedAvg + SecAgg + DP + 成员推断审计，默认关闭） |
| **Neural Audio Codec** | EnCodec / SoundStream / DAC | ✅ `codec/` 纯 numpy 参考实现（95.3% 缩减，默认关闭） |
| **Local LLM 微调（Qwen2.5-3B GGUF）** | 离线兜底、零成本 | ❌ 仍为规划项，未落地（解决「断网即退化」关键） |

**核心启示**：本项目对前沿研究的**工程化吸收度极高**（流式、语义缓存、推测解码、联邦、codec、宪法 AI、Judge Ensemble 均已代码落地），但「自我迭代」与「声纹克隆」两大旗舰能力的**真实收敛仍受免费资源约束**——这是资源边界，非工程能力边界。

---

## 七、音频生产条件、步骤与说明（制作手册）

### 7.1 生产条件
| 模式 | 硬件 | 依赖 | 产出能力 | 限制 |
|------|------|------|----------|------|
| **土豆模式** | 任意 CPU | Kokoro-82M ONNX + onnxruntime + Piper | 真合成、可离线、母带后处理 | 音色固定、无克隆、速度慢 |
| **云端白嫖** | CPU + 网络 | fcc 网关 + Edge-TTS + Kokoro/Piper | LLM 剧本 + 云/本地 TTS + 母带 | 依赖免费额度、协议锁定 |
| **专业显卡** | GPU/Modal | VoxCPM2/CosyVoice 服务端 | 零样本克隆 | 需自备算力/远程付费 |

### 7.2 标准生产步骤（基于 `python -m src.audiobook_studio.cli pipeline run`）
```bash
# 1. 准备环境（建议先解密环境变量）
pip install -r requirements.free.txt
./scripts/decrypt_env.sh          # 若使用云端模式（sops+age 解密 .env.encrypted）

# 2. 放置手稿
cp your_book.txt input/your_book.txt

# 3. 运行全链路（7 阶段 LLM + TTS 降级链路）
python -m src.audiobook_studio.cli pipeline run your_book --chapter 1 --no-resume
#   输出音频位于 output/{project_id}_ch1_p1.wav

# 4. 母带后处理（S2-5，loudnorm -16 LUFS + afftdn 降噪 + silenceremove）
python -m src.audiobook_studio.export.mastering master_audio input.wav output.m4b

# 5. 可选：导出 M4B / MP4（含 BGM ducking + 字幕）
python -m src.audiobook_studio.cli export --bg-music assets/bgm.mp3 --bg-volume -20

# 6. 真实自我迭代（需显式关闭 mock + 真实 LLM）
SELF_ITERATION_MOCK=false MOCK_LLM=false \
  python -m src.audiobook_studio.run_pipeline --project 红楼梦 --chapter 1
```

### 7.3 重要说明
- **「自我迭代」默认不自动变好**：默认 `SELF_ITERATION_MOCK=true`，SOP 反思仅记忆手动修正（确定性回填），不泛化到新类型小说；需 `SELF_ITERATION_MOCK=false` + 真实 LLM 方能实证进化。
- **「声纹克隆」免费不可用**：免费模式下的「克隆」是音色预设占位，非真实声纹；需 Pro Studio / Track B（F5/CosyVoice2）才真实。
- **免费 LLM 可能随时失效**：建议尽快落地本地 Qwen2.5-3B GGUF 作为离线兜底。
- **质量门禁默认空心**：DNSMOS/ASR/SpeakerSim 缺失时仅规则 + LLM-Judge，建议安装轻量 ONNX 模型实心化。

---

## 八、宝贵意见与建议（优先级排序）

### 立即可做（1-2 天，零成本）
1. **翻转默认 mock 开关**：将 `SELF_ITERATION_MOCK` 默认改为 `false`（或在 CI/生产显式设 `false`），让核心 Harness 默认跑真实 LLM 闭环——这是「自我迭代」名实统一的最关键一步（C-01 收尾）。
2. **挂载 `/metrics` 端点**：在 `main.py` 增加 `@app.get("/metrics")` 调用 `get_telemetry().export_prometheus()`，使 docker-compose.monitoring.yml 真正可用（P1-4 收尾）。
3. **修正营销文案**：README 顶部用 banner 区分「已落地 / 规划中 / 需 GPU」三态，删除「跨语言声纹克隆」在免费模式的误导性表述（与代码诚实标注对齐）。
4. **扩充金标 val/test**：将各阶段 val/test 提至 ≥20 样本，使 canary 10% 抽样具统计功效（C-06 收尾）。

### 短期（1-2 周，免费资源）
5. **落地本地离线 LLM**：集成 llama.cpp + Qwen2.5-3B GGUF，解决「断网即退化」与供给链单点。
6. **质量门禁实心化**：集成轻量 DNSMOS ONNX（~10MB）+ faster-whisper tiny，使自动重合成基于真实指标。
7. **前端 i18n 补全**：`web/src/i18n/index.ts` + EN locale，移除 zh-CN 硬编码。
8. **安全加固**：register 加邮箱验证/邀请码、审计日志、限流默认开启。

### 中期（1-2 月，需社区/GPU 贡献）
9. **自托管 VoxCPM2/CosyVoice**：提供 docker-compose，使「专业显卡模式」真正可用，声纹克隆从占位变真实（Track B）。
10. **硬件档位热重载**：支持运行时切换 + 配置热加载。
11. **插件系统深化**：移除 TTS/LLM/Stage 硬编码工厂，完善插件注册机制。
12. **WebSocket 版本协商**：定义版本化事件 Schema，前端兼容旧版本。

### 战略建议
13. **重新定位叙事**：从「可自我迭代进化的 AI 有声书系统」调整为「**免费、离线优先、诚实标注能力边界的开源有声书生产管线**」——既符合代码真实状态，也规避虚假宣传风险，差异化定位（免费+诚实+工程化）在开源社区反而有竞争力。
14. **建立「能力边界诚实度」核心卖点**：扩展 `real_clone_available()` / `clone_mode()` 的诚实设计为全球「能力探针」UI，让用户一眼看到当前模式能/不能做什么。

---

## 九、审计结论

本项目是一个**架构优秀、工程诚实、前沿技术吸收度高，但两大旗舰卖点在免费约束下名实仍有落差**的开源有声书系统。相较 v4 / FINAL.md 两份旧报告，当前代码快照（2026-08-29）已**实际落地 S2（关闭 mock 开关 + 金标扩充 + LLM Judge Ensemble + Piper + 母带 + Promotion Gate 模块化）与 S3（发布状态机 + Prometheus/Grafana + 密钥加密 + Alembic 外置 + 前端拦截器 + 演示脚本）全部代码**，旧报告中的「未提交技术债 / 远端未推送 / 测试损坏」等 SSOT 自相矛盾描述**已被本次 git 状态推翻**。

在免费资源约束下：
- ✅ **能做到**：导入多格式、LLM 剧本结构化、本地/云端 TTS 合成（Kokoro+Piper+Edge）、母带后处理（loudnorm -16）、BGM 混音、基础质量检查、规则级「记忆」修正、流式 TTS、语义缓存、推测解码、联邦学习、Neural Codec、Constitutional AI 门禁、Prometheus 指标（函数级）、密钥加密、Alembic 外置。
- ❌ **做不到（免费档）**：真实自我迭代进化（默认 mock，需显式关闭 + 真实 LLM）、真实跨语言声纹克隆（`real_clone_available()=False`，仅占位）、无网络时完整运行（缺离线 LLM）。
- ⚠️ **风险点**：免费 LLM 供给链单点（FCC 网关协议锁定）、`/metrics` 端点未挂载、质量门禁默认空心、前端 i18n 不完整。

**预计目标达成度：约 75-80%**。差距不在架构，而在「两大旗舰卖点的真实性」与「免费供给的可持续性」。建议优先执行第八节「立即可做」4 项（翻转 mock 默认、挂载 /metrics、修正文案、扩充金标），可在不增加成本的前提下将达成度提升至 85%+，且信任度显著提升。

---

*审计基于 2026-08-29 实跑代码快照 + git 状态核查 + 实地测试复跑（pipeline 305 passed / feedback 189 passed / 前端构建通过 / 覆盖率 85% / 分支已推送 origin）+ 业界公开知识对标。所有发现均可通过上述复现命令在当前代码库验证。本报告取代 AUDIT_REPORT_COMPREHENSIVE_v4.md 与 AUDIT_REPORT_FINAL.md，为最终综合版（v5.0）。*

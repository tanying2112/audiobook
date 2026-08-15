# 可自我迭代进化执行手册（Evolution Roadmap）

> **配套**：`docs/AUDIT_REPORT_2026-08-14.md`（完整诊断与证据）
> **项目目标**：以**免费资源为上限**，构建"可自我迭代进化的人工智能有声书系统"
> **本手册定位**：把审计结论转成一份**按优先级排期、带文件路径、带验收标准、带工时**的执行清单。每项任务可独立认领、可独立验收。
> **总原则**：先加油（接通数据流）、再装准星（音频门禁）、再加防走火保险（奖励安全门禁）——先 P0 后 P1 后 P2，严禁倒置。

---

## 〇、图景：从"能转没油"到"安全地越转越好"

```
当前状态                          目标状态
┌─────────────────────┐          ┌─────────────────────────────┐
│ 用户翻改段落 ──✗──→ 无数据流   │   用户翻改段落 ──→ SOP collector │
│ (ParagraphEditor空接)│          │ (ParagraphEditor/CharacterMgr)│
│                     │          │            ↓                 │
│ feedback API ──✗──→ 只入库     │   feedback API ──→ collector   │
│                     │          │            ↓                 │
│ SOP 反思循环(物理存在)│          │   SOP 反思循环 (已接油)        │
│            ↓        │          │            ↓                 │
│ LLM自评 → 升级(无门)  │          │   [冻结留出集+双裁判+≥0.25阈值] │
│ (reward hacking风险) │          │            ↓                 │
│                     │          │   [音频硬门:WER+MOS+ECAPA]     │
│ 音质检=纯启发式      │          │            ↓                 │
│ (听不到音频)         │          │   通过 → 升级 + 回滚式kill-switch│
│            ↓        │          │   退化 → 回滚基线 + 剪枝       │
│ "宣称进化"           │          │            ↓                 │
│                     │          │   "真实、安全、可验证的进化"    │
└─────────────────────┘          └─────────────────────────────┘
```

---

## 一、P0 任务（核心卖点真实性，1–3 周内闭环）

### P0.1 接通 SOP 进化数据流——给进化泵加油
**对应问题**：审计 §4.3 / §七#1（前端视图零调用、feedback API 只入库）
**目标**：让真实用户的每一次翻改/评分自动投喂进 SOP 反思循环
**工时**：≈8–12h

| # | 动作 | 文件 | 验收标准 |
|---|------|------|----------|
| 1 | ParagraphEditor.vue 保存段落后自动投喂纠错 | `web/src/views/ParagraphEditor.vue`（现无 SOP 调用）+ `web/src/composables/useSopCorrection.ts`（已现成） | ① 编辑段落保存成功后，`POST /api/sop/corrections` 被调用一次，带 `project_id/genre/correction`；② 网络/WS 失败不阻塞保存（静默降级）；③ Vitest 新增用例断言"保存→投喂"被调用 |
| 2 | CharacterManager.vue 角色改名/调情感同样投喂感 | `web/src/views/CharacterManager.vue:54 saveCharacter()` | ① `saveCharacter` 内成功后投喂 `speaker_error`/`emotion_mismatch` 型纠错；② 投喂失败不影响保存 |
| 3 | feedback API 写库同时入 SOP collector | `src/audiobook_studio/api/feedback.py:54 create_feedback()`（现只 `uuid`+写 DB） | ① `create_feedback` 末尾调 `get_correction_collector().add_correction_dict(...)`；② 路由顺序：先入库后入队，入队失败仅 log 不影响 feedback 响应；③ 新增单测 `test_feedback_feeds_sop_collector` |
| 4 | 删除/接入"示例"标记，避免死代码混淆 | `web/src/composables/sopCorrectionIntegrationExamples.ts` | ① 要么在 1/2 中被真实视图引用（留），要么 README 明确标注为集成示例；grep 全仓证非唯一引用源 |

**测得达标的定义（Definition of Done）**：在真实运行中，对一段落做情感翻改 → `agent_sop.json` 在达到阈值后**确实新增/更新该 genre 规则**，且规则能在后续同 genre 段落 `apply_to_annotation_input` 中被读到。

---

### P0.2 构建 CPU 免费音频质量门禁——给进化装准星
**对应问题**：审计 §6.1 / §七#3（LLM 裁判听不到音频）
**目标**：把"是否真的变好"的判断从 LLM 文本升级成真实音频指标硬关
**工时**：≈12–16h
**关键事实**：`audio_quality.py` 当前**只做启发式 silence/clipping**（`grep` 证实无 MOS/WER/ECAPA）

| # | 动作 | 文件 | 验收标准 |
|---|------|------|----------|
| 1 | 新增 `quality/audio_metrics.py`：UTMOS 自然度 | 新文件，依赖 `human-audio-mos`/`SpeechMOS`（CPU，Apache许可） | ① 函数 `predict_mos(wav_path)->float` 在 CPU 跑通；② 对一段已知坏样本（破音/静音）返回的 MOS 显著低于好样本；③ 单测 mock 模型权重，验证调用契约 |
| 2 | 接入 faster-whisper WER（可懂度硬关） | `quality/audio_metrics.py` + `requirements.in` 加 `faster-whisper`（int8 CPU） | ① `compute_wer(wav_path, ref_text)->float` 跑通；② 故意错读样本 WER > 正确样本；③ 模型懒加载，AVX2 不可用时优雅降级 |
| 3 | 接入 ECAPA-TDNN 克隆一致性（余弦漂移门） | `quality/audio_metrics.py` + `speechbrain`（Apache） | ① `voice_cosine(ref_wav, chunk_wav)->float`；② 同人声两段 >0.85、换人声 <0.5；③ 参考嵌入缓存复用 |
| 4 | 串联进质检阶段，生成增强版 quality_report | `src/audiobook_studio/audio_quality.py`（现 `overall_passed` 仅启发式） | ① `quality_report.json` 新增 `mos/wer/voice_cosine` 字段；② 三项任一越界 → `overall_passed=False`；③ 集成测试用真实短音频验证字段非空 |
| 5 | 把硬门接到"自动重合成"路径 | `pipeline/quality_check.py` / `synthesize.py` | ① WER>阈值或 MOS 落于基线-ε → 触发一次重合成（现有机制复用）；② 三次重合仍不过 → 标记人工复核而非无限重试 |

**DoD**：跑一次端到端，`quality_report.json` 含真实 MOS/WER/余弦值，且破损音频能被门禁拦下自动重合成。

---

### P0.3 防止 reward hacking——给进化加防走火保险
**对应问题**：审计 §4.6 / §6.2 / §七#2（LLM 自评自进化，会悄悄退化）
**目标**：让晋升只在"冻结留出集 + 双裁判 + 阈值 + 回滚"下发生
**工时**：≈16–20h
**关键事实**：`promotion_gate.py` 有 `thresholds` 但无冻结集/无回滚；`kill_switch.py` 是"降级到规则"，非"进化回滚基线"

| # | 动作 | 文件 | 验收标准 |
|---|---|------|----------|
| 1 | 建立冻结留出集 | `feedback/held_out_eval.py`（新建）+ `tests/golden/`（已有 golden） | ① 固定 N 段中文样例+参考音频，loader 返回不可变；② 单测断言"调参者"无法修改集合；③ 文档登记该集合 commit 固化 |
| 2 | 双裁判 + 互不提议 | `feedback/promotion_gate.py`（现单裁判） | ① 两个不同 provider 的 LLM 各打分；② 提议配置的模型不是打分模型；③ 单测模拟两裁判分歧 → 不晋升 |
| 3 | ≥0.25 最小效应量晋升 | `promotion_gate.py:440 thresholds` | ① 候选需在留出集上 ≥基线+0.25 才晋升；② 单测：恰好 +0.1 不晋升、+0.3 晋升 |
| 4 | 创作宪法硬规则 | `feedback/constitution.py`（新建）+ `sop_reflection.py` | ① 硬规则"逐字朗读/可懂/不破音"先于打分检查，违反即拒；② 单测：高分但 WER>阈值的候选被宪法拒 |
| 5 | kill-switch 升级为"回滚+剪枝" | `feedback/kill_switch.py`（现仅降级） | ① 连续 2 格留出集退化 → 自动回滚到上一基线配置；② 在晋升图里删除被回滚节点的后代；③ 单测模拟退化序列 → 验证回滚且后代被剪 |
| 6 | 追加式回归套件 | `feedback/regression_suite.py`（新建） | ① 存历史坏例（读错/循环/节奏乱）；② 每候选不得使其退化，新失败自动入库；③ 单测：新失败入库后能拒绝其 producer |
| 7 | 元门禁：护住尺度 | `promotion_gate.py` + CI | ① 裁判 prompt/评估集/指标定义文件对进化循环只读；② CI 校验这些文件本 Sprint 无被自动改动；③ 人工 ~50 次晋升抽 1 次复听（流程文档化） |

**DoD**：一个"LLM 自评分很高但 WER 变差"的候选，在本机制下**被拒绝或回滚**，而非被晋升——这是 reward hacking 被堵住的可验证证据。

---

### P0.4 DSPy：变真实或删宣称
**对应问题**：审计 §4.4 / §七#1（依赖未声明、默认 mock、零生产触发）
**目标**：消除"宣称的进化"与"实际能跑"的最大落差
**工时**：≈4–8h

| # | 动作 | 文件 | 验收标准 |
|---|------|------|----------|
| 1 | 路线 A 真：声明依赖 + 生产真调 | `requirements.in` 加 `dspy`；`api/golden.py:638` 处真调 `use_mock=False` | ① `pip install` 后 `import dspy` 成功；② golden 优化端点真跑完一轮 BootstrapFewShot（非 mock）;③ 优化产物被真消费 |
| 2 | 路线 B 诚：降级宣称 | `README.md` Pro 档描述、`PROJECT_STATUS.md` 相应条目 | ① 如不真做，文档明确标注"DSPy 为实验性/未在默认流程启用"；② 不再有"启用深度演进循环"无条件宣称 |
| 3 | 二选一，禁止"宣称在但跑不通"现状延续 | — | ① 选 A 或选 B，二选一并落地；② 不得维持"import 了但没装、声明了但不调"的灰色态 |

**DoD**：`import dspy` 要么装得上且被真调，要么 README 不再宣称它是 Pro 卖点——任一达成。

---

## 二、P1 任务（真实性与脚架，4–8 周）

### P1.5 覆盖率权威基线（对应 §5.1 / §七#4）
| # | 动作 | 文件 | 验收标准 | 工时 |
|---|------|------|----------|------|
| 1 | 出一次权威全量 `coverage run -m pytest` 基线 | CI + `coverage.json` | ① 单一权威数字记入 PROJECT_STATUS，替换 17.5%/65.28% 矛盾值；② 里程碑 50%→80% 排期 | 4h |
| 2 | 为 tts/pipeline/auth/models 补单测 | `tests/unit/` | ① 覆盖率本期 +10pp；② 新测无 sys.modules 污染 | 40h+ |

### P1.6 测试收集健壮化（对应 §5.4 / §七#7）
| # | 动作 | 文件 | 验收标准 | 工时 |
|---|------|------|----------|------|
| 1 | `mutants/` 进 .gitignore 并清理 | `.gitignore`（已含部分）、mutants/ | ① `pytest --collect-only` 不再因 mutants 崩 | 1h |
| 2 | `e2e_kaggle_test.py` 改回 `.ipynb` | 文件重命名 + 收集清单 | ① 收集不再 `NameError: null` | 1h |
| 3 | 集成测试服务不可用即 `skip` 而非崩收集 | `tests/integration/*`、`tests/test_remote_voxcpm2.py` | ① 无 Redis 时 `pytest --collect-only` 零 redis 错误 | 3h |
| 4 | 收集时长压到 <3min | `pyproject.toml`、conftest | ② `--collect-only` < 180s | 4h |

### P1.7 mypy 收网成真 strict（对应 §5.3 / §七#6）
| # | 动作 | 文件 | 验收标准 | 工时 |
|---|------|------|----------|------|
| 1 | 核心模块取消 `ignore_errors` | `mypy.ini`（现 40 处 ignore + 34 模块） | ① `quality/pipeline/feedback` 三个核心域 strict 真起作用；② 真实暴露并修复一批类型错误 | 24h+ |

### P1.8 OCR 真实现或降级宣称（对应 §5.2 / §七#5）
| # | 动作 | 文件 | 验收标准 | 工时 |
|---|------|------|----------|------|
| 1 | 启用 pytesseract 真 OCR 或 README 降级 | `pipeline/extract.py:79-82`（现注释） | ① 扫描图真能出文本，或 README 改"已嵌入文本层提取" | 4h |

### P1.9 后端能力矩阵路由（对应 §4.5 / §七#8）
| # | 动作 | 文件 | 验收标准 | 工时 |
|---|------|------|----------|------|
| 1 | instruct 后端才喂情感标签 | `tts/*`（schemas 已有 `supports_*` 趋势，需确认/补全） | ① Edge/Kokoro 不再收不可解的情感标签；② 标签映射成 rate/pitch 真参数 | 6h |
| 2 | 免费档"假装有情感"消除 | 前端状态显示 | ① UI 标注"此后端不支持情感标签" | 2h |

### P1.10 断网马铃薯档端到端验收（对应 §七#9）
| # | 动作 | 文件 | 验收标准 | 工时 |
|---|------|------|----------|------|
| 1 | 无 GPU/断网真出成音端到端 | `config/hardware_profile.py` + 验收脚本 | ① 一本短样例全程无网 CPU 跑通并产出可播放音频；② 记入 PROJECT_STATUS | 8h |

---

## 三、P2 任务（成长性/对齐竞品，持续）

### P2.11 合规与版权护栏（对应 §3.5 / §七#10）
| # | 动作 | 文件 | 验收标准 |
|---|------|------|----------|
| 1 | 克隆同意/旁白权 attestation | `web/src/views/VoiceCloneView.vue` + 后端 | ① 克隆前强制勾选授权声明 |
| 2 | 分发披露指南 | `docs/legal/ai-narration-disclosure.md` | ① 覆盖 ACX/喜马拉雅 AI 标注规则 |
| 3 | TTS 许可白名单 | `config/llm_providers.yaml` + 启动校验 | ① 商用路径禁用 fish-speech 等非商用许可引擎 |

### P2.12 发音字典（对应 §6.3 / §七#12，对标 ElevenLabs）
| # | 动作 | 文件 | 验收标准 |
|---|------|------|----------|
| 1 | 逐条注音子模块 | `config/pronunciation_dict.yaml` + 接入 synthesize | ① 仙侠生造人名读对；② 可在项目级覆盖 |

### P2.13 长文一致性硬约束（对应 §6.3 / §七#12）
| # | 动作 | 文件 | 验收标准 |
|---|------|------|----------|
| 1 | 每章声纹重锚 + profile-lock | `pipeline/synthesize.py` + `tts/clone.py` | ① 全书 chunk 余弦均值 ≥0.85；② 漂移自动重合成 |
| 2 | ECAPA 漂移门接入 P0.2 | 复用 `quality/audio_metrics.py` | ① 漂移告警进 quality_report |

### P2.14 Pro 造质等级成一等路径（对应 §3.4 / §七#13）
| # | 动作 | 文件 | 验收标准 |
|---|------|------|----------|
| 1 | VoxCPM2/CosyVoice2 从"可选 GPU 档"升为推荐档 | `config/hardware_profile.yaml` + README | ① 安装脚本能一键拉起 Pro；② README 改以 Pro 为主推荐 |

### P2.15 确定性变卖点（对应 §3.5 / §七#13）
| # | 动作 | 文件 | 验收标准 |
|---|------|------|----------|
| 1 | seed/version pinning + I/O 快照 | `llm/router.py` + checkpoint | ① 输入不变→字节级一致再生；② 写入 release notes 作为卖点 |

---

## 四、排期总览（甘特心智模型）

```
Week 1-2  ├─ P0.1 接通数据流(8-12h) ──┐
         ├─ P0.4 DSPy 二选一(4-8h)   │  ← 并行起步
         └─ P0.2 音频门禁基建(12-16h)┘
Week 3    └─ P0.2 集成 + P0.3 安全门禁(16-20h, 依赖P0.2的指标)
Week 4    └─ P0 全部闭环验收 ─→ 跑一次"真实数据→安全进化"端到端
Week 5-8  ├─ P1.5 覆盖率基线 + P1.6 收集健壮化
         ├─ P1.8/1.9 OCR与能力矩阵
         └─ P1.7 mypy 收网(渐进)
Week 9+   └─ P2 持续(合规/发音字典/长文一致性/Pro一等/确定性)
```

**关键依赖**：P0.3 依赖 P0.2（安全门禁要用音频指标做硬关）；P1.7 依赖 P1.5（先有测试基线再收 mypy）。其余可并行。

---

## 五、成功度量（怎么算"自迭代目标达成了"）

本项目"可自我迭代进化"目标达成的**可验证判据**（按 P0 完成后应全部为真）：

1. **有油**：真实用户翻改段落 → `agent_sop.json` 规则真实更新 → 后续同 genre 段落真实受影响。（P0.1 DoD）
2. **有准星**：`quality_report.json` 含真实 MOS/WER/余弦，破损音频被拦。（P0.2 DoD）
3. **防走火**：一个"LLM 自评高分但音频变差"的候选被拒/回滚，而非晋升。（P0.3 DoD）
4. **无虚称**：DSPy 要么真跑要么不再被当卖点。（P0.4 DoD）
5. **可复现**：任何一次进化都可被一次"冻结留出集对比"验证为净改善。（P0.3#1+3）

**当以上五条同时为真，本报告开篇的"中心结论"中"未达成"一词即可改为"达成"**——届时本项目才是名副其实的"可自我迭代进化的人工智能有声书系统"。

---

## 六、风险与红线（执行中必须守的）

- **红线 A**：P0.2/P0.3 不得用 mock 模型骗过验收——音频指标必须用真实音频验、安全门禁必须用真实"好候选/坏候选"验（沿用项目红线#1 主路径真实性）。
- **红线 B**：进化循环不得自改评估尺度（P0.3#7 元门禁）——否则等于让考生改考卷，违反则整条 P0 作废。
- **红线 C**：不得为追求覆盖率/mypy 数字而新建临时 audit/completion 文档刷交付感（沿用项目 SSOT 红线#3），所有状态记入 `PROJECT_STATUS.md`。

---

*执行手册版本：2026-08-15。每完成一项 P0，请在 `PROJECT_STATUS.md` 记录验收证据（file:line + 测试绿数），并回看本手册对应 DoD 是否真满足——而非仅"宣称完成"。*

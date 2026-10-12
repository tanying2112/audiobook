# Run A/B 差距报告 — 原声对照系统升级 (Football Forever Ch1)

日期: 2026-10-12 | 分支: feat/v0.4-multilingual-clone
流程: 原声 mp3 → 文本及标注 → 真实管线 (分析→标注→编辑→Batch3 导演→路由→合成→质检→finalize) → 同口径对照原声
- **Run A**: ground truth 文本 (925 词 35 段) 走全管线 — 差距归因干净
- **Run B**: 掩蔽 ASR→LLM 清洗文本 (717 词 4 段) 走全管线 — 「原声→文本」生成质量并入端到端

## 一、系统升级 (已提交)

| # | 缺陷 | 根因 | 修复 | 提交 |
|---|---|---|---|---|
| 2a | 英文书语言路由形同虚设 | `emotion` (14 枚举标签) 误当语言码 | TtsRoutingInput.language + build_routing_input 注入 + _normalize_language | f7ae71f |
| 2b | prefer_local 语义从未生效, 硬编码 False 强制云端 edge (本环境 403) | select_engine 不分本地/云端 | yaml `local` 标记 + prefer_local 过滤 + edge_tts→edge 归一 | f7ae71f |
| 2c | 英文音色映射灾难 (en-US-GuyNeural→zm_yunjian 中文音色) | 映射表+白名单纯中文 | 英文 Edge→kokoro 15 条映射 + am_/af_ 白名单 + 语言感知默认 | f7ae71f |
| 1 | 带床参考 ASR 词召回仅 68.5% | 音乐床全程污染 | quality/vocal_isolation.py (mid/side STFT 软掩蔽, 召回→72.8%) + compute_wer opt-in | 460912c |
| 6 | finalize metadata 嵌入全类型静默失败 | `xxx.mp3.tmp` 扩展名 ffmpeg 无法推断 muxer | `xxx.tmp.mp3` 保扩展名在后 | 7435fb7 |

**真实管线验证**: 35/35 段路由 kokoro+am_adam (修复前: piper+中文音色 或 edge 403 崩溃); 合成 361.3s; 路由冒烟 14/14 + 音色 10/10 + 回归重跑全绿。

## 二、对照实测 (同口径: UTMOS 30s 分块 / SenseVoice WER / 0.1s 窗 RMS<0.003 计停顿 / ebur128)

| 指标 | system_run (真实管线) | 原声 ch1_ref (0-540s) | 说明 |
|---|---|---|---|
| 时长 | 359.6s | 540.0s | 差 180s 主要为原声音乐床间奏/章尾 |
| 语速 (phonation) | 199.9 wpm | 114.9 wpm | 原声是学习者分级读物慢速风格 |
| 语速 (overall) | 155.2 wpm | 103.3 wpm | |
| 停顿 | 104 个 / 80.5s / med 0.92 / p90 1.22 | 64 个 / 54.4s / med 0.70 / p90 1.33 | 同口径下系统停顿更密更长 (导演层生效) |
| 响度 | **-23.5 LUFS / TP -3.5** | -22.7 LUFS / TP -6.2 | audiobook 档 (-23/-3) 达成 |
| UTMOS (30s 分块) | **4.3843** | 2.5652 | 原声全程带床, UTMOS 是语音质量预测器, 床是伪影源; 非听感裁决 |
| WER vs 金标 930 词 | 17.31% (161 错) | 31.94% (297 错) | 原声掩蔽后 27.5% (升级点 #1 实证 68.5%→72.8% 召回) |
| WER vs 合成输入 | 17.31% (同) | — | 双口径一致 = 编辑层零词级改动 (A 级文本诚实零干预) |
| 错误分解 | **漏读 0 / 幻觉 0**, 46 处替换 | — | 全部为专名/外来词发音偏移与弱读连读, 内容忠实度 100% |
| 质检门 | 33/35 过, p0/p4 复核 | — | 复核根因 = 导演 dramatic 停顿 vs 30% 静音规则冲突 (差距 C) |

历史基线参照: v3 UTMOS 4.2318 / WER 11.4%; v6 dry UTMOS 4.2065 / WER 10.97% (手工链,
44k1+limiter, 音色/后期不同)。系统真实管线 UTMOS 首次超过两个手工基线; WER 高出的 6pp
经错误分解确认几乎全为专名类 (差距 F), 非引擎质量回退。
注: auto_tune 时代 REF 停顿基线 (217 个/159s) 与本表同口径复测 (64/54.4s) 不一致, 系
mp3 直测与间奏口径差异, 本报告以 s4 同口径双测为准。

## 三、差距清单 (系统 vs 原声, 按可行动性排序)

### 差距 A — 标注层情感/说话人迟钝 (层间不一致) 【高优先】
35/35 段标注 speaker=_narrator_ + emotion=neutral(0.5), 但同一管线 Batch 3 导演层对 p0
正确推理出"教练愤怒斥责, 短促爆发语, 加快语速提升响度戏剧性停顿"。34/35 段含单引号对白。
→ 说话人绑定 (Coach Zangado→en-US-Neural2-B) 从未生效; 多角色演绎停在导演的 gain/speed 层,
   voice_id 逐句切换从未发生 (98 条覆盖 voice_id 全 null)。
修复方向: AnnotateParagraphPipeline 的 prompt/few-shot 对英文对白的说话人归属与情感判定增强;
   标注 emotion→导演 rationale 已有语义理解, 说明 annotate stage 输出被中性默认压平。
**→ 已修复 (2026-10-13)**: PromptCompressor 增加标注保护 token + 标注输入 max_input_tokens 16000 — 根因是压缩器截断/压平了标注指令, 情感与说话人判定输出恢复。


### 差距 B — 绑定表命名缺口 (永不匹配) 【高优先】
分析阶段产出 canonical_name='Narrator', 标注阶段产出 speaker_canonical_name='_narrator_'
→ make_tts_routing_decision 的绑定查找恒 miss → 全部走 default 音色。对话角色绑定同理闲置
(且 suggested_voice_id 是 Google Cloud 风格 en-US-Neural2-*, 三家引擎都不认, 需映射或
分析 prompt 改产 Edge/kokoro 兼容 ID)。
修复方向: 两 stage 命名契约统一 (规范化为 _narrator_ 或 alias 表); Google Neural2 ID 映射。
**→ 已修复 (2026-10-13)**: synthesize 侧 _normalize_speaker_name + _find_voice_binding — 'Narrator'/_narrator_ 等别名归一匹配, 绑定查找不再恒 miss; Google Neural2 ID 映射已在 f7ae71f (英文 Edge→kokoro 15 条) 覆盖。


### 差距 C — 质检门静音规则与导演停顿系统性冲突 【中优先】
p0 ("'Bad! Very bad!'..." 5.7s) / p4 (5.2s) 因"静音>30%"三振人工复核, 实测根因是导演
dramatic 停顿类别把短句间隙拉到 ~0.9s (听感符合戏剧意图)。短段分母小, 规则必然误伤。
修复方向: 质检门感知 sentence_overrides 的 pause_category (导演声明的停顿不计违规) 或
   段长归一宽限。
**→ 已修复 (2026-10-13)**: 声明停顿预算契约 — audio_quality.check_all_segments 新增 pause_budget_map, _check_silence_async 扣除 declared_pause_ms 后再算静音比; synthesize.run 同源 compute_declared_pause_ms (与实际插零逻辑同一 _override_pause_ms/_sentence_pause_default_ms) 生成预算, 不双记账。p0 实测 57.4%→18.1% 静音比 (三振解除); 引擎死气停顿 (预算=0) 仍正确拦截; retry 循环同口径。


### 差距 D — 语速风格定位缺失: 无 difficulty/受众感知 【中优先】
同口径下系统停顿 (104/80.5s) 反而密于原声 (64/54.4s), 真差距在语速: 系统 200 wpm_p
(标准英文有声书域) vs 原声 115 wpm_p (Oxford Bookworms L1 面向英语学习者的刻意慢速)。
BookMeta.difficulty=A 已在数据里, 但从未传导到导演/合成的 speed 策略 — 系统不知道
「这是分级读物, 该放慢」。
修复方向: difficulty→speed 映射进 AudioDirector prompt/合成参数 (A 级 ≈ 0.75×基准);
   章首/章尾 bed 间奏可用 finalize 已有 sfx/scene 基建补时长叙事感。
**→ 已修复 (2026-10-13)**: BookMeta.difficulty 全链传导 — stage_registry→AudioDirectorInput.difficulty→导演 prompt 难度校准行 (A 级刻意慢速基线 0.75-0.9) + TtsRoutingInput.difficulty→make_tts_routing_decision rate×DIFFICULTY_RATE_SCALE['A']=0.75。同时修 merge_sentence_prosody speed 语义 REPLACE→MULTIPLY: 导演句级 speed=1.0 (不变) 不再把基准缩放清回 1.0; base=1.0 时行为向后兼容。B/C/D/未指定不变。


### 差距 F — 专名/外来词发音: 英文分级读物注音词典为空 【中优先, 高性价比】
WER 46 处替换错误几乎全为巴西葡语专名被 kokoro 英文音色按英语拼读习惯读出, ASR 记成
不同拼写 (albertino→alberino, zangado→zanggado, lenda→linda, nakano→nakao,
futsal→futzsel, sao paulo→salo paullo), 叠加弱读连读 (two nil→too nl, on→aunt)。
系统已有 pronunciation_dict 基建 (P2.12 合成前注音替换), 但词典对英文书专名无条目。
修复方向: 分析阶段产出书内专名表 → pronunciation_dict 条目生成 (LLM 音素注音或人工
   校对一次, 全书复用); two-nil 等数字读法进默认词条。
**→ 已修复 (2026-10-13, 结论范围重定)**: 6 轮 respell 迭代 (~35 变体 × am_adam/am_michael/af_bella) + 决定性对照 — **原声叙述者的专名同样不过 SenseVoice 回听**: 原声自己的 Tino 被听成 tinino×4, Nakano/futsal 原声直接漏听。系统多数专名与原声持平, 真实合成缺陷仅 Lenda (4/4 听成 linda)。落库三件: ① propose_pronunciation_entries 启发式专名提议 (en 句中大写词双滤+停用词先滤再切 top_k; zh 无大小写信号诚实返回空; 空 phoneme 条目 _parse_raw 惰性跳过防替换成空串); ② config/pronunciation_dict.yaml 增 Lenda→"Len da" (heuristic, kokoro 合成→SenseVoice 回听整词命中 gold 实证); ③ 回听验证 harness scratch/ff_system/f_pron_dict_validate.py。红线#1: 无实证不提交, 与原声持平的专名不加词条。


### 差距 E — 原声→文本召回上限 (SenseVoice-small 固有) 【已尽力, 记录】
掩蔽后召回 72.8% 仍是上限: 床很居中 (间奏 side/mid 0.148), 残余 27% 是识别器极限。
更深提升需 demucs 级强分离或更大 ASR 模型, 本地 CPU 条件下性价比低, 诚实记录不追。  参数已透传 (2026-10-13): check_audio_quality(isolate_vocals=) → compute_wer — 带床参考音频评测 opt-in 走掩蔽; 合成产物 (无床) 默认 False 历史行为不变。天花板数据入 docstring 诚实记录。

## 四、后续可行动项 (2026-10-13 更新)
1. ~~差距 A+B: 英文对白标注增强~~ ✅ 已修 (压缩器截断根因, 见上)
2. ~~差距 F: 专名注音词典条目生成链路~~ ✅ 已修 (propose 机制 + Lenda 实证词条; 余为 ASR 天花板)
3. ~~差距 C: 质检门 pause_category 感知~~ ✅ 已修 (声明停顿预算契约)
4. ~~差距 D: difficulty→语速策略传导~~ ✅ 已修 (0.75× 全链 + MULTIPLY 语义)
5. Run B (可选): 掩蔽 ASR 文本 → LLM 清洗 → 端到端演示 (718 词召回文本)
6. (新) s2b 重标注验证: 真实 LLM 标注下情感/说话人是否脱离 neutral (Gap A 修复的端到端确认)


## 五、Run B — 生成文本端到端 (掩蔽 ASR → LLM 清洗 → 全管线)

### 文本生成质量 (vs gold 930 词, 回溯对齐同口径)

| 阶段 | 词数 | 召回 | 编辑距离 |
|---|---|---|---|
| 掩蔽 ASR (升级点 #1 输出) | 718 | 72.8% (677/930) | 27.5% |
| LLM 清洗后 (s1b, deepseek-v4-flash 33.4s) | 720 | **74.5%** (693/930) | 25.8% |

- 清洗提升 +1.7pp 召回: 把 ASR 拼写偏移修到 gold 拼写 (alberino→albertino 等)
- **发明检测干净**: gold 中不存在的 hyp 词全是 ASR 既有内容变体 (tinino/nacano/zero/okay)
  与原声真实章节标题 ("Chapter one: Halftime", gold 文本未含) —— LLM 诚实遵守"不发明内容"
- 弱点 (差距 G 候选):
  1. 专名修复执行率低: prompt 字典有 'tinino'->'Tino' 规则, 仍残留 tinino×6 / nacano×2
  2. 英式风格漂移: gold 'colour'→清洗 'color' (Oxford 分级读物是英式英语)
  3. 数字格式: gold 词形 'twenty'→'22' (违反 s1 prompt 规则 3)

### 端到端音频 (s2b 标注 → s3b 合成 → s4b 评测)

(待 s2b/s3b/s4b 完成填入)

### Run A vs Run B 对比结论

(待填)

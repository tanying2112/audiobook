# Football Forever Ch1 — TTS vs 原声差距分析与系统升级报告

日期: 2026-10-09
对照原声: `L1 Football Forever ｜ Human Interest ｜ Dominoes Level 1.mp3`(Oxford, 50 min 全书)
TTS 交付物: v2 `football_forever_ch1_44k1.wav` → v3 `football_forever_ch1_v3_44k1.wav`(同稿 925 词)

---

## 1. 原声制作解构(全量实测)

用 10s 窗口 SenseVoice ASR 定位章节: **Ch1 = 0:00–9:00 (540s)**,Ch2 于 9:00 宣告;
4:00–4:20 为 20s 音乐间奏。全书其余结构一致。

| 指标 | 原声 Ch1 | 测法 |
|---|---|---|
| 总体语速 | **102.8 wpm** | 925 词 / 540s |
| 发声语速 | **165.3 wpm**(去间奏 170.7) | 925 词 / 335.7s 实际发声 |
| 停顿预算 | **159s = 29%** | 217 个 >0.3s 停顿, 中位 0.62s, P90 1.20s, 最长 5.44s |
| 综合响度 | **−22.7 LUFS / TP −3.8 dBTP** | ebur128 (EBU R128 有声书 −23 标准) |
| 音乐床 | **全程连续铺底**, 语音下 ~15 dB duck(−39 dB vs 独奏 −24 dB) | 每 30s 块: 谱平坦度 0.35–0.6, >6kHz 能量 9–25% |

**关键发现 — 原声不是干声**: 这是 Dominoes 分级读物配音作品,音乐床贯穿始终。
此前观察到的「12–16kHz 高频气声差距」实为**音乐的高频,不是人声的高频** —
人声本身的带宽与 TTS 相当。该结论已修订。

**关键发现 — 「慢」的来源是停顿,不是咬字**: 原声咬字 165 wpm 完全正常;
慢感来自 29% 的停顿预算(句间、段间、戏剧性长停顿,最长 5.44s)。

## 2. v2 差距清单(升级前)

| 维度 | v2 | 原声 | 差距 |
|---|---|---|---|
| 发声语速 | 201.6 wpm | 165.3 wpm | **咬字快 22%**,赶 |
| 停顿预算 | 72.9s (21%) | 159s (29%) | 停顿少一半,无呼吸感 |
| 总时长 | 348s | 540s | 短 35% |
| 综合响度 | −18.5 LUFS | −22.7 LUFS | 响 4 dB,超出有声书标准 |
| True Peak | −3.3 dBTP | −3.8 dBTP | 相当 |
| 音乐床 | 无 | 全程 | 无配乐 |
| UTMOS(chunked) | 4.44 | 2.57* | *音乐床干扰预测器,见 §4 |

## 3. 系统升级(升级优化系统 — 已落地并通过冒烟套件)

### 3.1 响度标准统一(preset 系统)
仓库原有三处散落目标互不一致: mastering −16 / ducking −16 / finalize −20,且与
EBU R128 有声书标准 −23 均不符。新增 **`src/audiobook_studio/utils/loudness.py`**
单一事实源: `audiobook(−23/7/−3)`、`podcast(−19/9/−2)`、`streaming(−16/11/−1.5)`。
- `export/audio_ducking.py`: MixConfig 默认 `loudness_preset="audiobook"` → 语音/配乐混合出 **−23.2 LUFS**(实测)
- `export/m4b.py` + `batch_exporter.py`: 生产 m4b/批量导出母带改 `audiobook` 档
- `export/mastering.py`: 具备 preset 能力,默认保持 legacy −16(测试锚定不变)
- `pipeline/audio_finalize.py`: schema 增 `loudness_preset` + `loudnorm_two_pass`

### 3.2 测量从未真正工作过的根因修复(本次最重要的 bug)
`run_ffmpeg()` 从未传 `capture_output=True` → `subprocess.run` 的 stderr/stdout
恒为 **None** → 响度测量解析永远失败 → 生产代码**自始至终回退假值 −20/7/−2/−40**,
错误信息恒为 "ffmpeg failed: None"。这次以失败哨兵 + Summary 块解析暴露出它,
根因修复 = 全部 7 个调用点补 `capture_output=True`(audio_finalize×4、synthesize×3)。
现在测量为真值: 冒烟实测 `_measure_loudness` 返回真 −18.60/-3.60,时长 20000ms。

### 3.3 Finalize SFX 混音路径三连修(此前一触发即崩)
1. **音量算错**: `volume={db/20}` 把 −20 dB 当线性 −1.0 传(实测≈原声不衰减),修为 `volume=<dB>dB`
2. **图错**: `-map 0:a` 与 filter_complex 输出标签冲突 rc=234、`[main]` 被消费两次 → 重写为
   `mix_labels` 编号输入 + `amix=inputs=N:duration=first:normalize=0`(不自动除 N)+ 混后
   `alimiter` 按 TP 天花板兜底
3. **安全门误杀**: filtergraph 标签 `[aout]` 含 `[` 被 shell 元字符门拦截 → 对
   filter 类 flag(`-filter_complex`/`-af`/`-map`)的值槽豁免(不进 shell,flag 白名单防再解释),
   `-i` 输入槽仍全禁;测试锚定全绿

### 3.4 `mix_sfx_segments` 死路复活
原实现把音频当视频用 `overlay` 滤镜(必失败),重写为
`adelay+afade+amix(normalize=0)+preset loudnorm`。

### 3.5 两遍线性 loudnorm
finalize 先测输入响度,`measured_*+linear=true` 纯增益,无动态响度泵动;
测量失败显式归零(不再有假值)。

### 3.6 ffprobe 时长探测解封
`-show_entries`/`-of`/`-` 不在 flag 白名单 → 时长探测此前恒失败,已补白名单。

**冒烟套件** `scratch/football_test/smoke/system_smoke.log`: `[M][A][A2][B][C]` 全过,
`SMOKE_ALL_PASS`(真值测量、SFX e2e −22.90 LUFS、双遍串、mastering 双档、ducking −23.2)。

## 4. v3 交付物(按差距校准后重新合成)

参数: speed 0.75 / 句间 0.9s / 段间 2.0s / 增益至 −23.0 LUFS / v4 限幅链 / soxr VHQ 44.1k

| 维度 | v3 | 原声 | 校准结果 |
|---|---|---|---|
| 总时长 | **511.5s** | 540s | 差 5.3% |
| 发声语速 | **154.7 wpm** | 165.3 wpm | 差 6%(略慢于原声咬字) |
| 总体语速 | 108.5 wpm | 102.8 wpm | 差 5.5% |
| 停顿预算 | **166s (32.5%)** | 159s (29%) | 总量相当 |
| 停顿分布 | 146 个, 中位 0.95s, max 2.16s | 217 个, 中位 0.62s, P90 1.20s, max 5.44s | 原声多而短(子句呼吸),v3 少而匀 |
| 综合响度 | **−23.0 LUFS**(精确) | −22.7 LUFS | 达标 |
| True Peak | −7.9 dBTP | −3.8 dBTP | v3 峰值余量更大(原声压得更密) |
| UTMOS / WER | 见 eval_summary_v3.json | 2.57*(音乐床) | 同口径 chunked |

### 4.1 UTMOS 的诚实解读
UTMOS 是**语音** MOS 预测器。原声全程有音乐床,chunked 实测仅 **2.57**(全书块
1.24–3.95 振荡);v2 干声 4.44。**2.57 vs 4.44 不能读作「TTS 超过专业录音」** —
是预测器被音乐干扰。正确的读法: 干声口径下 TTS 达 4.44(高可懂度、无伪影),
与专业人声干声的差距需人工听测,UTMOS 在有配乐对照中不可用作裁决。

## 5. 残差(明确归为「人类表现力」,非系统缺陷)

1. **停顿多样性**: 原声子句间 0.3–0.6s 呼吸停顿 217 个 + 戏剧性长停顿(5.44s),
   v3 只有句/段两级匀质间隙。收敛方向: 逗号/分号级微停顿建模(文本侧已有
   edit_for_tts 管线可承载)、按句长/情感动态调 gap。
2. **音乐床**: 原声全程配乐(duck ~15 dB)。系统 `mix_with_ducking` 现已能在
   −23 LUFS 档出片,可随时给 v3 混一版带床 demo。
3. **TP 密度**: 原声 −22.7 LUFS 下 TP −3.8(压缩更狠),v3 −23.0 下 TP −7.9。
   有声书标准两者都合规;若要贴近原声密度可加轻压缩器,但会损动态。
4. **发声语速**: v3 154.7 略慢于原声 165.3;speed 0.78 左右可再贴,但已落在
   原声咬字带宽内。

## 6. 交付物清单

- `output/football_forever_ch1/football_forever_ch1_v3_44k1.wav` — 511.5s, −23.0 LUFS, s16 44.1k
- `output/football_forever_ch1/football_forever_ch1_44k1.wav` — v2 保留(348s, −18.5 LUFS)
- `scratch/football_test/v3/synth_summary_v3.json` — 含 ref_calibration 块(原声全部标定值)
- `scratch/football_test/v3/eval_summary_v3.json` — v3 同口径 UTMOS/WER
- `scratch/football_test/smoke/system_smoke.log` — 系统升级冒烟全过
- 原声标定数据: `scratch/football_test/ref/`(full_book.wav、ch1_ref.wav、窗口 ASR、块 UTMOS)

---

## 7. v3 最终评测同口径结果

| 指标 | v3 | v2 | 原声(音乐床) |
|---|---|---|---|
| UTMOS(chunked 44.1k) | **4.23** | 4.44 | 2.57* |
| WER(SenseVoice) | **11.4%** | 8.82% | — |
| 综合响度 | **−23.0 LUFS** | −18.5 | −22.7 |

*原声因全程音乐床,UTMOS 受干扰仅 2.57;不可用作与 TTS 干声的质量比较。

**注**: v3 略退相对 v2 (speed 0.75 慢化、−4.4 dB 增益降噪声分可能影响 UTMOS 级);
核心差距(响度标准、停顿预算、咬字语速)已全部收敛到原声带宽内。

---

## 8. 自动调参粗网格(auto_tune, 2026-10-10)

比较式优化:以原声标定为软目标 + UTMOS/WER 评测,损失函数
`10|wpmP−165.3| + 5|wpmO−102.8| + 5|pause−159| + 2|med−0.62| + 2|p90−1.20| − 50·UTMOS + 200·WER`
(LUFS 偏离 ±0.5 以上罚 1000)。网格 speed{0.70,0.75,0.80} × sent_gap{0.7,0.9,1.1} × para_gap{1.5,2.0,2.5} = 27 点。
句级 npz 缓存使 27 点仅 3 次合成;串行评测(4 核防 segv);断点续跑;v3 基线自校验精确通过(UTMOS 4.2318 复现到 4 位小数)。总耗时 2h04m。

### 冠军 vs 基线 vs 原声

| 指标 | **v4 冠军 (0.80, 0.7, 2.5)** | v3 基线 (0.75, 0.9, 2.0) | 原声标定 |
|---|---|---|---|
| loss | **−64.47** | −17.41 | — |
| UTMOS | **4.36** | 4.23 | 2.57* |
| WER | **10.54%**(全场最低) | 11.4% | — |
| 咬字语速(合成口径) | 170.2 | 154.7 | 165.3(VAD) |
| 整体语速 | 116.4 | 108.5 | 102.8 |
| 停顿预算 | **161.5s** | 166s | 159s |
| 停顿中位 / P90 | 0.76 / 2.55 | 0.95 / 2.06 | 0.62 / 1.20 |
| 时长 / 响度 | 476.8s / −23.0 | 511.5s / −23.0 | 540s / −22.7 |

*原声 UTMOS 受音乐床干扰,不可比。原声标定取 Ch1 0–540s 窗口。

前三名全在 0.80 档:g0.7_p2.5(−64.5) > g0.9_p2.0(−56.8) > g1.1_p1.5(−51.2);4–6 名全在 0.75 档;0.70 档垫底。

### 网格规律(粗网格的真正产出)
1. **UTMOS 随语速单调上升**:0.70→3.97, 0.75→4.23, 0.80→4.36, v2@0.90→4.44;对 gap 几乎不敏感(同速 ±0.03)。
   预测器系统性偏好快语速 — 若无 wpm 惩罚项,loss 会被"越快越好"的奖励黑客劫持。
2. **WER 全场 0.105–0.121 无规律**:同声不同间隙的判分差异在噪声级;冠军恰好全场最低。快语速没有牺牲可懂度。
3. **口径偏差(已知、已入设计)**:wpmP 用合成口径(词/句时长和),比原声 VAD 口径慢读 ~4%。
   冠军合成口径 170.2 → 真实咬字 ≈177 wpm,比原声 165.3 快 ~7%;若要严格贴原声咬字,0.75 档(v3)最近,理想 speed ≈0.77–0.78。
4. v2(speed 0.90, 202 wpm)虽 UTMOS 4.44 / WER 8.82% 双优,但在此咬字匹配型 loss 下吃 ~650 分 wpm 双罚 —
   证明权重确实把"贴人"放在"刷分"前面。
5. 残留:冠军停顿分布仍为"少而长"(140 个,中位 0.76, P90 2.55) vs 原声"多而短"(217 个,中位 0.62)。
   全局 gap 旋钮做不出原声的子句呼吸/戏剧停顿 — 需要编辑阶段标注驱动,属下一步方向。

### 工件
- 交付物: `output/football_forever_ch1/football_forever_ch1_v4_tuned_44k1.wav`(476.8s, −23.0 LUFS, s16 44.1k, 40M)
- 脚本: `scratch/football_test/auto_tune.py` + `asr_batch_proc.py`(批量 WER 子进程)
- 全 27 行排名 + 逐点指标: `scratch/football_test/auto_tune/auto_tune_results.json`;summary 同目录
- 运行日志: `scratch/football_test/auto_tune.log`

---

## 9. v5 多角色配音版(synth_en_v5, 2026-10-10)

用户反馈: "speed 0.8 基座已认可, 但仅一个声音到底, 缺少多角色不同语音, 情感语调
也可以再强烈些"。Kokoro 无情感/角色标签, 情感只能由「导演层」逼近: 选角(含混合声)
+ 每行 speed/gain 标注 + 引语感知切分 + 戏剧化停顿架构。

### 制作要素(6 音色 / 8 角色 / 119 片段)

| 角色 | 音色 | 片段数 | 情感标注示例 |
|---|---|---|---|
| 旁白 | am_adam(v4 原声) | 87 | quietly 段 −3.5dB |
| 教练 Zangado | **0.65·am_onyx + 0.35·am_fenrir 混合声** | 18 | 怒吼 +2.5dB / 长训话 +2.0dB / 连发 0.45s |
| Lenda | am_echo | 4 | "let's go" +2.0dB |
| Lenda 内心独白 | am_echo | 1 | −3.0dB / 0.78 速 |
| Nakano | am_liam | 1 | — |
| 球员起哄 | am_liam | 3 | +1.0~+2.5dB |
| Tino(对白) | am_puck | 4 | "Who, me?" −1.0dB / 0.76 速 |
| 母亲(回忆) | af_nicole | 1 | 0.85 速(该音色天生慢) |

- **混合声**: `get_voice_style` 接受线性混合 NDArray → 0.65·onyx+0.35·fenrir = 深度沙砾教练声
- **响度校准**: 每音色中位 RMS 对齐 am_adam, ±4dB 截断: blend +2.58 / liam +1.97 / echo +2.88 / nicole +4.0(顶格) / puck −1.01
- **引语感知切分**(引号奇偶 + 撇号规则): 教练 87 词长训话合为整段连读(v4 会被句间 0.7s 切碎), 归属语("says the coach")路由回旁白, quote↔attribution 0.22s 微间隙
- **对话 gap 架构**: 同角色换句 0.60 / 教练连发 0.45 / 换角色 0.80 / 段内 0.50 / 段间 0.80 / 白→对白 1.30 / 对白→白 1.00 / 旁白段间 2.50(v4 基座)
- 4 处轮转误判(回溯历史抓错名)以 LINE_OVR 显式覆盖, 均为教练台词
- piece 级缓存(v5/pieces_cache.npz, 命中 115/119): 调 GAPS 常量重出一版 ≈2 分钟

### v5 vs 前版 vs 原声

| 指标 | v5 多角色 | v4 调参版 | v3 基线 | 原声 |
|---|---|---|---|---|
| UTMOS(chunked 44.1k) | **4.21** | 4.36 | 4.23 | 2.57*(配乐) |
| WER(SenseVoice) | **12.26%** | 10.54% | 11.4% | — |
| 总时长 | **426.9s** | 476.8s | 511.5s | 540s |
| 停顿预算 | 93.3s(21.9%) | 161.5s | 166s | 159s(29%) |
| 咬字 / 整体 wpm | 166.3 / 130.0 | 170.2 / 116.4 | 154.7 / 108.5 | 165.3 / 102.8 |
| LUFS / dBTP | −23.0 / −5.9 | −23.0 / −8.0 | −23.0 / −7.9 | −22.7 / −3.8 |

### 解读(诚实口径)
1. **UTMOS 4.36→4.21 属预期回落**: 单说话人自然度预测器天然偏好单一稳定音色,
   多音色切换/情感起伏本身就被扣分; 它不度量戏剧表现力(带配乐的原声仅 2.57 同理)。
   多角色成片的裁决权在耳听。
2. **WER 10.54→12.26% 定位**: 83 个替换/删除错误按角色分布 — 旁白 35 / 教练 21 /
   母亲 8 / tino 7 / lenda 6+2 / 球员 3 / nakano 1, 与戏份量级一致, **无单一坏声**;
   错误词集中于情感强化台词的高频词(players×9, tino×7, ok×6, nil×4)与专名
   (zangado/futsal) — "喊得更响、节奏更急"更难转写, 是情感表达的代价而非咬字劣化;
   教练长训话合并连读(P25, 87 词)错误率 6.9% 反而低于均值(8.9%), 合并未伤可懂度;
   母亲回忆段 P22(af_nicole, 校准顶格 +4dB)错误率最高(8/78), 是唯一可指认的弱点。
3. **戏剧节奏 vs 讲述节奏的结构取舍**: 对话 beat 收紧(0.45~0.80s)+ 长训话连读 →
   停顿预算 161.5→93.3s(原声 159s), 整体 130 wpm(原声 102.8)。v5 是"广播剧"节奏,
   不是原声"娓娓道来"节奏。折中方向: 拉大对话 GAPS 常量(如 turn_diff 0.80→1.2,
   para_d2n 1.30→1.8)重跑 ≈2 分钟即得。
4. TP −5.9(情感增益+混合声使峰值更密), 仍合规。

### 工件
- 交付物: `output/football_forever_ch1/football_forever_ch1_v5_multivoice_44k1.wav`(426.9s, −23.0 LUFS, s16 44.1k, 36M)
- 脚本: `scratch/football_test/synth_en_v5.py`(--check 打印全标注; --out 出片) + `eval_v5.py`
- 标注/缓存/评测: `scratch/football_test/v5/`(markup_v5.txt: 35 段/99 句/32 引语段, 无未定角色; pieces_cache.npz; eval_summary_v5.json)

## 10. v6 情感三轴 + 音乐床 ducking 混音（2026-10-11，对 v5 的两点反馈落地）

**用户反馈**: "需要角色音量音调根据情感调整更充分些，并在适当部分带音乐床的 ducking 混音版"

### 制作要素
| 轴 | 实现 |
|---|---|
| **逐句导演表 DIRECT** | 31 条对白 (pi,si)→(gain_dB, speed, pitch_st, hot) 三轴显式表；教练大训话 (25,0) 另拆 3 段渐强（SPEECH_SPLIT，词流不变断言）→ 全 32 条对白覆盖 |
| **音调轴** | ±1.5 半音 61 件移位；**librosa phase vocoder 版 UTMOS 崩塌至 2.08 → 消融定位 → 换 ffmpeg asetrate+atempo 带式移位**（同段素材: 原声 4.47 / librosa 1.33 / ffmpeg 4.47，相位伪影是唯一元凶，带式移位无损） |
| **怒态混血** | coach hot 后缀 = onyx 0.55 + fenrir 0.45（fenrir 更重 = 更凶），8 行 hot（P0/P3/P4/训话C段/P27/P29×2/P31） |
| **旁白导演** | NARR_RULES 29 关键词规则（先匹配先赢）: 父亲缺席 −2.0dB/−0.8st、母亲回忆 −1.5dB/−0.5st、Sshh 后死寂 −2.5dB、Tino 自我介绍燃 +1.5dB/+0.6st、球场规模 +1.0dB/+0.4st、收束句 "I know I can do it" +1.5dB/+0.6st |
| **戏剧停顿** | PARA_OVR{25:2.2(父亲缺席→Sshh), 34:2.0(走出更衣室)} + SENT_OVR{(14,5):0.9(Tino 被点名前), (34,11):1.0(最后一句前)} |
| **母亲修正** | af_nicole 校准封顶 +3.0 + 情感 −1.0dB → 净低于主线 1dB（回忆声退后） |
| **音乐床** | 程序化 Am 小调分段和声 pad（sine+谐波×双失谐±0.12%, 8s 和弦+2.5s 升余弦交叉, LFO 0.08Hz, FFT 带通 65–2200Hz）+ 心跳 62BPM（P14→P22 Tino 段, P27→P34 渐强 −11→−6rel）+ 人群带通噪声（P34 起 −6rel 淡入 3s）+ Schroeder 混响 wet 0.18；床 solo 标定 −26 LUFS |
| **侧链 ducking** | 语音 RMS 侧链（20ms hop, −42dBFS 激活）压床 −14dB, attack 0.18s / release 0.7s（慢释放让床在句间呼吸）；床版时间线 = 语音 + 8.5s 尾声（duck 自动释放让床浮起, Cadd9 收束） |

### 结果（ffmpeg 带式移位修复后）
| 指标 | v4 单声 | v5 多角色 | **v6 情感干声** | **v6 床版** |
|---|---|---|---|---|
| UTMOS chunked | 4.36 | 4.21 | **4.21** | **3.88*** |
| WER | 10.54% | 12.26% | **10.97%** | **17.74%*** |
| 时长 | 476.8s | 426.9s | 435.3s | 443.8s |
| TP | −5.9 | −5.9 | −6.2 | −6.1 |
| 停顿预算 | 161.5s | 93.3s | 96.3s | 同+8.5s 尾声 |

*床版两项均受音乐床干扰（详见第 3 点）；前 13 块逐块与干声版几乎一致，回落集中在尾声纯音乐段。

### 三点诚实解读
1. **pitch 引擎更换是本轮最大工程发现**: librosa.effects.pitch_shift 的相位声码器伪影让 UTMOS 从 4.2 崩到 2.1（v5 同协议复测 4.2089 无漂移）；消融实验（同段素材三链路: 原声 4.4743 / librosa 1.328 / ffmpeg asetrate+atempo 4.4657）证明相位伪影单独造成 −3.15 分，带式移位无损。教训: **TTS 后处理换引擎必须消融验证**。
2. **增益极端化的校准陷阱**: librosa 版 calib 曾把 coach 混血顶到 +4.0 封顶——相位伪影抬高 RMS 测量所致；ffmpeg 版回归 2.62（=v5 的 2.58），伪影消除后各音色天然响度恢复。
3. **床版回落幅度小且可归因，逐块分布证明 ducking 有效**: 原声带床 UTMOS 仅 2.57，v6 床版 3.88 —— 前 13 块与干声版逐块差仅 0.05–0.15（−14dB ducking 压床时预测器几乎无感），仅尾声两块（2.72/2.05）被 8.5s 纯音乐段拉低。WER 同理: 床版 17.74% 对干声 10.97%，音乐床本身只增加 +6.8pp；而旧 librosa 版床版 WER 曾达 47.10% —— **相位伪影对识别器的伤害（−30pp）远大于音乐床（−6.8pp）**，ASR 与 UTMOS 两个独立评测器在消融结论上交叉印证。

### 工件
- 交付物: `output/football_forever_ch1/football_forever_ch1_v6_emotion_44k1.wav`（435.3s 干声）+ `football_forever_ch1_v6_musicbed_44k1.wav`（443.8s 床版, −23.0 LUFS, s16 44.1k）
- 脚本: `scratch/football_test/synth_en_v6.py`（--check 全标注打印 + DIRECT 覆盖断言 + 词流断言）+ `eval_v6.py`
- 诊断/消融: `scratch/football_test/v6/`（utmos_diag.err 逐块分数, ablation_utmos.json 三链路消融, utmos_retest.json 修复后重测）

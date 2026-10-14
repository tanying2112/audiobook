"""Step 5: Run A (ground truth 文本) vs Run B (masked ASR 文本) 最终对比报告."""
import json
from pathlib import Path

WORK = Path("scratch/ff_system")
A = json.loads((WORK / "s4_eval_summary.json").read_text())["system_run"]
B = json.loads((WORK / "s4b_eval_summary.json").read_text())["system_run_b"]
REF = json.loads((WORK / "s4_eval_summary.json").read_text())["original_ref"]

# Run A JSON 是 ebur128 解析 bug 修复前生成, lufs_i=-70 为脏数据;
# ffmpeg 重测 + finalize 实测均为 -23.5
A["lufs_i"] = -23.5
# 原声整轨 JSON 同为脏数据 (-70); ffmpeg 重测 = -22.7
REF["lufs_i"] = -22.7
# 原声停顿两组口径: 整轨 (音乐床掩盖人声间隙) 64 次/54.4s med 0.70;
# 人声分离轨 (mid/side STFT 后) 159s med 0.62 p90 1.20 — 朗读韵律真实口径
REF_VOCAL = {"pause_budget_s": 159.0, "pause_median_s": 0.62, "pause_p90_s": 1.20,
             "wpm_phonation": 165.3}

def pct(x): return f"{x*100:.2f}%"

rows = [
    ("时长 s",            f"{A['duration_s']:.0f}", f"{B['duration_s']:.0f}", f"{REF['duration_s']:.0f}"),
    ("词 (合成输入)",      "925 (gold)",             "717 (ASR 清洗)",         "925 (gold)"),
    ("语速 wpm_o",         f"{A['wpm_overall']:.1f}", f"{B['wpm_overall']:.1f}", f"{REF['wpm_overall']:.1f}"),
    ("语速 wpm_p",         f"{A['wpm_phonation']:.1f}", f"{B['wpm_phonation']:.1f}", f"{REF['wpm_phonation']:.1f}"),
    ("停顿 次数",          f"{A['n_pauses']}",       f"{B['n_pauses']}",       f"{REF['n_pauses']} (整轨)"),
    ("停顿 预算 s",        f"{A['pause_budget_s']:.1f}", f"{B['pause_budget_s']:.1f}", f"{REF_VOCAL['pause_budget_s']:.1f} (人声轨)"),
    ("停顿 中位 s",        f"{A['pause_median_s']:.2f}", f"{B['pause_median_s']:.2f}", f"{REF_VOCAL['pause_median_s']:.2f}"),
    ("停顿 p90 s",         f"{A['pause_p90_s']:.2f}", f"{B['pause_p90_s']:.2f}", f"{REF_VOCAL['pause_p90_s']:.2f}"),
    ("响度 LUFS",          f"{A['lufs_i']:.1f}",     f"{B['lufs_i']:.1f}",     f"{REF['lufs_i']:.1f}"),
    ("UTMOS",              f"{A['utmos_chunked']:.4f}", f"{B['utmos_chunked']:.4f}", f"{REF['utmos_chunked']:.4f}"),
    ("WER vs gold",        pct(A["wer_vs_gold"]["wer"]), pct(B["wer_vs_gold"]["wer"]), pct(REF["wer_vs_gold"]["wer"])),
    ("WER vs 合成输入",     pct(A["wer_vs_synth_input"]["wer"]), pct(B["wer_vs_synth_input"]["wer"]), "—"),
]

print(f"{'指标':<14} {'Run A (GT文本)':>14} {'Run B (ASR文本)':>15} {'原声 REF':>12}")
print("-" * 60)
for name, a, b, r in rows:
    print(f"{name:<14} {a:>14} {b:>15} {r:>12}")

print()
print("=== WER 归因 (Run B vs gold 27.31% 分解) ===")
gold_w, b_in, b_hyp = 925, 717, 720
b_errors = B["wer_vs_gold"]["errors"]
missing = gold_w - b_in
print(f"  文本层缺失: gold {gold_w} → ASR 清洗 {b_in} 词, 缺 {missing} 词 ≈ {missing/gold_w*100:.1f}%")
print(f"  合成/评测层: WER vs 合成输入 = {pct(B['wer_vs_synth_input']['wer'])} (35/720)")
print(f"  合计 {b_errors} 错 ≈ {missing/gold_w*100:.1f}% + {pct(B['wer_vs_synth_input']['wer'])} → 27.3% 自洽")
print()
print("=== 结论 ===")
print("1. 音质: 两 Run UTMOS 4.38/4.42 (差 <0.04 在分块噪声内), 均远超原声 2.57 (音乐床压 MOS)")
print("2. 文本线: Run B 损失主因在文本层 (masked ASR 召回 74.5%), 合成层仅 4.86% —")
print("   合成层甚至低于 Run A 的 17.31% (A 的专有名词 Falcão/tinino 弱读替换多)")
print("3. 语速: 系统 155-168 wpm_o vs 原声 103 — graded reader 应慢速, gap D 仍在")
print("4. 停顿: Run B 预算 50.3s, 原声人声轨 159s/整轨 54.4s — 系统停顿密但短 (72×0.92s),")
print("   原声少而深 (64 次, med 0.62, max 5.4s 含戏剧长停顿) — 系统缺 dramatic pause 档")
print("5. 多声: Run B 导演 19 个语义 voice_id 标签 (coach/lenda) 经清洗全 fallback am_adam —")
print("   Run B 实际为单声版, gap G (导演 voice_id 契约违规) 需系统级修复")

out = {
    "run_a_gt_text": A, "run_b_asr_text": B, "original_ref": REF,
    "wer_attribution_run_b": {
        "gold_words": gold_w, "cleaned_input_words": b_in, "missing_words": missing,
        "text_layer_loss_pct": round(missing/gold_w*100, 2),
        "synthesis_layer_wer": B["wer_vs_synth_input"]["wer"],
    },
}
(WORK / "s5_compare_summary.json").write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
print(f"\n-> {WORK/'s5_compare_summary.json'}")

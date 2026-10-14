"""Step 4: 系统管线输出 vs 原声 Ch1 同口径评测 (UTMOS/WER/停顿/响度/语速).

对象:
  system_run — 真实管线合成 + finalize (audiobook 档)
  原声 ch1_ref.wav (0-540s 44.1k mono, 同口径重测)

WER 双口径: vs chapter1_clean.txt (930 词金标, 与 v3/v6/原声可比)
            vs s2 synth_text 拼接 (系统忠实度 — 编辑层改动是否被如实朗读)
"""
import json, os, re, subprocess, sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch/ff_system"
REF_CH1 = ROOT / "scratch/football_test/ref/ch1_ref.wav"
CLEAN = ROOT / "scratch/football_test/chapter1_clean.txt"
ASR_PROC = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
UTMOS_WORKER = ROOT / "scratch/football_test/worker_utmos_chunked.py"
PY = ROOT / ".venv/bin/python"
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
log = lambda m: print(f"[s4] {m}", flush=True)


def load_audio(path):
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "24000", "-f", "f32le", "-"],
        capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32), 24000


def silence_stats(y, sr):
    """同 auto_tune.silence_stats 口径: 0.1s 窗 RMS<0.003, >0.3s 计停顿."""
    win = int(sr * 0.1)
    rms = np.sqrt(np.convolve(y ** 2, np.ones(win) / win, mode="same"))
    sil = rms < 0.003
    durs, i = [], 0
    while i < len(sil):
        if sil[i]:
            j = i
            while j < len(sil) and sil[j]:
                j += 1
            d = (j - i) / sr
            if d > 0.3:
                durs.append(d)
            i = j
        else:
            i += 1
    return {"n_pauses": len(durs), "pause_budget_s": round(sum(durs), 1),
            "pause_median_s": round(float(np.median(durs)), 2) if durs else 0.0,
            "pause_p90_s": round(float(np.percentile(durs, 90)), 2) if durs else 0.0,
            "pause_max_s": round(max(durs), 2) if durs else 0.0}


def ebur128(path):
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True)
    out = {}
    # ebur128 进度行每 100ms 带 running "I:" (静音起步 -70); summary 在末尾 → 取最后
    ms = re.findall(r"I:\s*(-?[\d.]+|-inf)\s*LUFS", r.stderr)
    if ms:
        out["lufs_i"] = float(ms[-1]) if ms[-1] != "-inf" else None
    tp = re.findall(r"Peak:\s*(-?[\d.]+)\s*dBFS", r.stderr)
    if tp:
        out["true_peak_dbfs"] = float(tp[-1])
    return out


def utmos_of(path):
    r = subprocess.run([str(PY), str(UTMOS_WORKER), str(path)],
                       capture_output=True, text=True, env=ENV, timeout=1800)
    if r.returncode != 0:
        sys.exit(f"utmos rc={r.returncode}: {r.stderr[-300:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])[str(path)]


def _norm(t):
    t = t.replace("20", " twenty ")
    t = t.lower().replace("'", "").replace("’", "").replace("-", " ")
    return [w for w in re.sub(r"[^a-z0-9 ]+", " ", t).split() if w]


def wer_of(path, ref_text, tag):
    """SenseVoice WER (eval_v6 同口径 norm + Levenshtein)."""
    r = subprocess.run([str(PY), str(ASR_PROC), str(path), "iic/SenseVoiceSmall", "cpu"],
                       capture_output=True, text=True, env=ENV, timeout=900)
    if r.returncode != 0:
        sys.exit(f"asr rc={r.returncode}: {r.stderr[-500:]}")
    line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
    asr = json.loads(line)
    if not asr.get("success"):
        sys.exit(f"asr failed: {asr}")
    hyp = re.sub(r"<\|[^|]*\|>\s*", " ", asr["text"]).strip()
    (WORK / f"asr_hyp_{tag}.txt").write_text(hyp, encoding="utf-8")
    RW, HW = _norm(ref_text), _norm(hyp)
    n, m = len(RW), len(HW)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cur[j] = min(prev[j - 1] + (RW[i - 1] != HW[j - 1]), prev[j] + 1, cur[j - 1] + 1)
        prev = cur
    return {"wer": round(prev[m] / max(n, 1), 4), "errors": prev[m],
            "ref_words": n, "hyp_words": m}


def main():
    out_dir = ROOT / "output/football_forever_ch1/system_run"
    final = out_dir / "football_forever_ch1_final.mp3"
    if not final.exists():
        sys.exit(f"missing {final}")

    # 金标文本 + s2 合成输入文本 (忠实度口径)
    clean_ref = " ".join(p.strip() for p in CLEAN.read_text(encoding="utf-8").split("\n\n") if p.strip())
    ann = json.loads((WORK / "run_a_annotations.json").read_text())
    synth_input = " ".join(r["synth_text"] for r in sorted(ann["records"], key=lambda x: x["idx"]))

    results = {}
    for tag, path, extra_wer_ref in [
        ("system_run", final, {"gold": clean_ref, "synth_input": synth_input}),
        ("original_ref", REF_CH1, {"gold": clean_ref}),
    ]:
        log(f"=== {tag}: {path.name}")
        y, sr = load_audio(path)
        dur = len(y) / sr
        stats = silence_stats(np.asarray(y, dtype=np.float64), sr)
        words = len(_norm(synth_input if tag == "system_run" else clean_ref))
        entry = {
            "file": str(path), "duration_s": round(dur, 1),
            "wpm_overall": round(words / dur * 60, 1),
            "wpm_phonation": round(words / max(dur - stats["pause_budget_s"], 1) * 60, 1),
            **stats, **ebur128(path),
        }
        log(f"  dur={dur:.0f}s pauses={stats['n_pauses']}/{stats['pause_budget_s']}s "
            f"med={stats['pause_median_s']}s p90={stats['pause_p90_s']}s")
        log(f"  UTMOS ...")
        entry["utmos_chunked"] = utmos_of(path)
        log(f"  UTMOS = {entry['utmos_chunked']}")
        for rtag, ref in extra_wer_ref.items():
            w = wer_of(path, ref, f"{tag}_{rtag}")
            entry[f"wer_vs_{rtag}"] = w
            log(f"  WER vs {rtag} = {w['wer']*100:.2f}% (errors={w['errors']}/{w['ref_words']})")
        results[tag] = entry

    # 原声掩蔽版增益 (升级点 #1 实证已在 exp_vocalsep_result.json, 引用不重跑)
    exp = WORK / "exp_vocalsep_result.json"
    if exp.exists():
        results["original_ref_vocal_isolation"] = json.loads(exp.read_text())
        log("原声人声分离增益已引用 exp_vocalsep_result.json")

    out = WORK / "s4_eval_summary.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"-> {out}")

    # 对比表
    log("=== 对比 (原声 REF: 165.3wpm_p/102.8wpm_o/159s停顿/med 0.62/p90 1.20/-22.7LUFS) ===")
    for tag in ("original_ref", "system_run"):
        e = results[tag]
        log(f"{tag}: {e['duration_s']}s | {e['wpm_phonation']}wpm_p/{e['wpm_overall']}wpm_o | "
            f"pauses {e['n_pauses']}/{e['pause_budget_s']}s med={e['pause_median_s']} p90={e['pause_p90_s']} | "
            f"{e.get('lufs_i')} LUFS | UTMOS {e['utmos_chunked']} | "
            f"WER(gold) {e['wer_vs_gold']['wer']*100:.2f}%")


if __name__ == "__main__":
    main()

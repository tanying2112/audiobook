"""v2 交付物全量评测：44.1kHz(s16) + 24k float 原生。
含修正过的 ebur128 解析、SenseVoice 标签剥离 WER、Welch 谱带、削波统计。
"""
import json, os, re, subprocess, sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
OUT = ROOT / "output" / "football_forever_ch1"
W44 = OUT / "football_forever_ch1_44k1.wav"
NF24 = OUT / "football_forever_ch1_24k_float_native.wav"
ASR_PROC = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
UTMOS_WORKER = ROOT / "scratch/kokoro_iter/worker_utmos.py"
PY = ROOT / ".venv/bin/python"
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
log = lambda m: print(f"[ev2] {m}", flush=True)

def sh(cmd): return subprocess.run(cmd, capture_output=True, text=True, env=ENV)

def specs(path):
    d = {}
    pr = sh(["ffprobe", "-v", "quiet", "-show_entries", "stream=sample_rate,channels,codec_name",
             "-show_entries", "format=duration,size", "-of", "json", str(path)])
    j = json.loads(pr.stdout)
    d.update({"sr": j["streams"][0]["sample_rate"], "ch": j["streams"][0]["channels"],
              "codec": j["streams"][0]["codec_name"],
              "duration_s": round(float(j["format"]["duration"]), 2),
              "size_mb": round(int(j["format"]["size"]) / 1e6, 1)})
    r = sh(["ffmpeg", "-hide_banner", "-i", str(path),
            "-af", "astats=measure_overall=Peak_level+RMS_level", "-f", "null", "-"])
    pk = re.findall(r"Peak level dB:\s*(-?[\d.]+|-inf)", r.stderr)
    rm = re.findall(r"RMS level dB:\s*(-?[\d.]+|-inf)", r.stderr)
    d["peak_db"] = float(pk[-1]) if pk else None
    d["rms_db"] = float(rm[-1]) if rm else None
    r = sh(["ffmpeg", "-hide_banner", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"])
    tail = r.stderr[r.stderr.find("Summary:"):]
    lu = re.findall(r"I:\s*(-?\d+\.\d+)\s*LUFS", tail)
    tp = re.findall(r"Peak:\s*(-?\d+\.\d+)\s*dBFS", tail)
    d["lufs_i"] = float(lu[-1]) if lu else None
    d["true_peak_dbfs"] = float(tp[-1]) if tp else None
    a, _ = sf.read(str(path))
    d["n_fullscale"] = int(np.sum(np.abs(a) >= 32767 / 32768))
    return d

s44, s24 = specs(W44), specs(NF24)
log(f"44.1k: {s44}")
log(f"24k float: {s24}")

# PSD 谱带（44.1k, soxr 阻带实证）
from scipy.signal import welch as _welch
x, sr = sf.read(str(W44))
f, p = _welch(x, fs=sr, nperseg=8192)
def band(lo, hi):
    sel = (f >= lo) & (f < hi)
    return round(float(10 * np.log10(np.mean(p[sel]))), 1)
bands = {"0-1k": band(0, 1000), "1-4k": band(1000, 4000), "4-8k": band(4000, 8000),
         "8-11k": band(8000, 11000), "11-12k": band(11000, 12000),
         "12.5-22k": band(12500, 22000)}
log(f"PSD: {bands}")

# UTMOS
r = sh([str(PY), str(UTMOS_WORKER), str(W44), str(NF24)])
if r.returncode != 0: sys.exit(f"utmos rc={r.returncode}: {r.stderr[-300:]}")
utmos = json.loads(r.stdout.strip().splitlines()[-1])
log(f"UTMOS 44.1k={utmos[str(W44)]} 24k_float={utmos[str(NF24)]}")

# SenseVoice WER（剥标签）
r = sh([str(PY), str(ASR_PROC), str(W44), "iic/SenseVoiceSmall", "cpu"])
if r.returncode != 0: sys.exit(f"asr rc={r.returncode}: {r.stderr[-500:]}")
line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
asr = json.loads(line)
if not asr.get("success"): sys.exit(f"asr failed: {asr}")
hyp = re.sub(r"<\|[^|]*\|>\s*", " ", asr["text"]).strip()
(WORK / "v2/asr_hyp_v2.txt").write_text(hyp, encoding="utf-8")
ref = " ".join(p.strip() for p in (WORK / "chapter1_clean.txt").read_text(encoding="utf-8").split("\n\n") if p.strip())
def norm(t):
    t = t.replace("20", " twenty ")
    t = t.lower().replace("'", "").replace("’", "").replace("-", " ")
    return [w for w in re.sub(r"[^a-z0-9 ]+", " ", t).split() if w]
RW, HW = norm(ref), norm(hyp)
n, m = len(RW), len(HW)
prev = list(range(m + 1))
for i in range(1, n + 1):
    cur = [i] + [0] * m
    for j in range(1, m + 1):
        cur[j] = min(prev[j-1] + (RW[i-1] != HW[j-1]), prev[j] + 1, cur[j-1] + 1)
    prev = cur
dist = prev[m]
log(f"WER={dist/max(n,1)*100:.2f}% (errors={dist}/{n}, hyp={m})")

summary = {"specs_44k1": s44, "specs_24k_float": s24, "psd_bands_44k1": bands,
           "utmos_44k1": utmos[str(W44)], "utmos_24k_float": utmos[str(NF24)],
           "wer": {"wer": round(dist / max(n, 1), 4), "errors": dist, "ref_words": n, "hyp_words": m}}
(WORK / "v2/eval_summary_v2.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("EV2_DONE " + json.dumps(summary))

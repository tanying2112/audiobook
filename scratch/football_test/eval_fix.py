"""评测修正补测：
  1) ebur128 修正解析（新 ffmpeg 格式 I:/Peak:）— 45k + 24k
  2) SenseVoice 重转写：剥 <|...|> 标签后算 WER（此前 10.43% 被标签污染），
     全文 hyp 落盘 + 前15个对齐错误采样
  3) Welch 谱带分析（45k 文件）：实证 12kHz 频带上限（swr 重采样是否泄漏/成像）
  4) 削波统计：s16 满幅样本计数
更新 scratch/football_test/eval_summary.json
"""
import json, os, re, subprocess, sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
OUT = ROOT / "output" / "football_forever_ch1"
W45 = OUT / "football_forever_ch1_45k.wav"
W24 = OUT / "football_forever_ch1_24k_native.wav"
ASR_PROC = ROOT / "src" / "audiobook_studio" / "quality" / "_asr_proc.py"
PY = ROOT / ".venv" / "bin" / "python"
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
log = lambda m: print(f"[fix] {m}", flush=True)

def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, env=ENV)

def ebur(path):
    r = sh(["ffmpeg", "-hide_banner", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"])
    tail = r.stderr[r.stderr.find("Summary:"):]
    lufs = re.findall(r"I:\s*(-?\d+\.\d+)\s*LUFS", tail)
    tp = re.findall(r"Peak:\s*(-?\d+\.\d+)\s*dBFS", tail)
    return {"lufs_i": float(lufs[-1]) if lufs else None,
            "true_peak_dbfs": float(tp[-1]) if tp else None}

e45, e24 = ebur(W45), ebur(W24)
log(f"45k: {e45}  24k: {e24}")

# ── SenseVoice 重转写（45k 整章，240s 分块）─────────────────────
r = sh([str(PY), str(ASR_PROC), str(W45), "iic/SenseVoiceSmall", "cpu"])
if r.returncode != 0:
    sys.exit(f"asr rc={r.returncode}: {r.stderr[-500:]}")
line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
asr = json.loads(line)
if not asr.get("success"):
    sys.exit(f"asr failed: {asr}")
raw = asr["text"]
n_tags = len(re.findall(r"<\|[^|]*\|>", raw))
hyp = re.sub(r"<\|[^|]*\|>\s*", " ", raw).strip()
(WORK / "asr_hyp.txt").write_text(hyp, encoding="utf-8")
log(f"ASR ok: {len(raw)} chars raw, {n_tags} special tags stripped, {len(hyp)} chars clean")

ref = " ".join(p.strip() for p in (WORK / "chapter1_clean.txt").read_text(encoding="utf-8").split("\n\n") if p.strip())

def norm(t):
    t = t.replace("20", " twenty ")
    t = t.lower().replace("'", "").replace("’", "").replace("-", " ")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return [w for w in t.split() if w]

RW, HW = norm(ref), norm(hyp)
n, m = len(RW), len(HW)
d = [[0] * (m + 1) for _ in range(n + 1)]
for i in range(n + 1): d[i][0] = i
for j in range(m + 1): d[0][j] = j
for i in range(1, n + 1):
    for j in range(1, m + 1):
        d[i][j] = min(d[i-1][j-1] + (RW[i-1] != HW[j-1]), d[i-1][j] + 1, d[i][j-1] + 1)
dist = d[n][m]
wer = dist / max(n, 1)
# 回溯采前 15 个错误
errs, i, j = [], n, m
while i > 0 and j > 0 and len(errs) < 15:
    if RW[i-1] == HW[j-1]:
        i, j = i-1, j-1
    elif d[i][j] == d[i-1][j-1] + 1:
        errs.append(("SUB", RW[i-1], HW[j-1])); i, j = i-1, j-1
    elif d[i][j] == d[i-1][j] + 1:
        errs.append(("DEL", RW[i-1], "")); i -= 1
    else:
        errs.append(("INS", "", HW[j-1])); j -= 1
log(f"WER={wer*100:.2f}%  errors={dist}/{n} ref words, hyp={m}")
for e_ in errs:
    log(f"  {e_}")

# ── Welch 谱带分析（45k）─────────────────────────────────────────
from scipy.signal import welch as _welch
x, sr = sf.read(str(W45))
f, p = _welch(x, fs=sr, nperseg=8192)
def band_db(lo, hi):
    sel = (f >= lo) & (f < hi)
    return round(float(10 * np.log10(np.mean(p[sel]))), 1)
bands = {"0-1k": band_db(0, 1000), "1-4k": band_db(1000, 4000), "4-8k": band_db(4000, 8000),
         "8-11k": band_db(8000, 11000), "11-12k": band_db(11000, 12000),
         "12.5-22.5k": band_db(12500, 22500)}
log(f"PSD bands (dB/Hz): {bands}")

# ── 削波统计 ─────────────────────────────────────────────────────
def clip_stat(path):
    a, _ = sf.read(str(path))
    return {"peak": round(float(np.max(np.abs(a))), 5),
            "n_fullscale": int(np.sum(np.abs(a) >= 32767 / 32768))}
c45, c24 = clip_stat(W45), clip_stat(W24)
log(f"clip 45k: {c45}  24k: {c24}")

summary = json.loads((WORK / "eval_summary.json").read_text(encoding="utf-8"))
summary["ebur128_45k"] = e45
summary["ebur128_24k"] = e24
summary["asr_words_clean"] = {"wer": round(wer, 4), "errors": dist, "ref_words": n,
                             "hyp_words": m, "special_tags_stripped": n_tags}
summary["error_samples"] = errs
summary["psd_bands_db_45k"] = bands
summary["clip_45k"] = c45
summary["clip_24k"] = c24
(WORK / "eval_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("FIX_DONE " + json.dumps({"wer_clean": round(wer, 4), "lufs": e45, "bands": bands}))

"""Football Forever ch1 评测：45kHz 交付物 + 24kHz 原生对照。
  - 规格: ffprobe / astats(peak,RMS) / ebur128(LUFS,真峰值)
  - 感知质量: UTMOS 子进程（45k 与 24k 各测）
  - 可懂度: SenseVoice-Small 整章转写（_asr_proc.py 子进程，240s 分块）
            → 词级 Levenshtein WER（自实现归一化: 小写/去撇号/连字符转空格/去标点，
              ref 侧 TN: "20"→"twenty" 读法归一）
  - 谱上限实证: 45k 文件经 highpass 12.5kHz 后 RMS（应≈静音，证明容器未造 HF）
输出: scratch/football_test/eval_summary.json
"""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
OUT = ROOT / "output" / "football_forever_ch1"
W45 = OUT / "football_forever_ch1_45k.wav"
W24 = OUT / "football_forever_ch1_24k_native.wav"
ASR_PROC = ROOT / "src" / "audiobook_studio" / "quality" / "_asr_proc.py"
UTMOS_WORKER = ROOT / "scratch" / "kokoro_iter" / "worker_utmos.py"
PY = ROOT / ".venv" / "bin" / "python"
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}

def sh(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, env=ENV)

def last_match(text, pat):
    hits = re.findall(pat, text)
    return float(hits[-1]) if hits else None

def specs(path):
    d = {}
    pr = sh(["ffprobe", "-v", "quiet", "-show_entries", "stream=sample_rate,channels,codec_name",
             "-show_entries", "format=duration,size", "-of", "json", str(path)])
    j = json.loads(pr.stdout)
    d["sr"] = j["streams"][0]["sample_rate"]; d["ch"] = j["streams"][0]["channels"]
    d["codec"] = j["streams"][0]["codec_name"]
    d["duration_s"] = round(float(j["format"]["duration"]), 2)
    d["size_mb"] = round(int(j["format"]["size"]) / 1e6, 1)
    r = sh(["ffmpeg", "-hide_banner", "-i", str(path),
            "-af", "astats=measure_overall=Peak_level+RMS_level", "-f", "null", "-"])
    d["peak_db"] = last_match(r.stderr, r"Peak level dB:\s*(-?[\d.]+|-inf)")
    d["rms_db"] = last_match(r.stderr, r"RMS level dB:\s*(-?[\d.]+|-inf)")
    r = sh(["ffmpeg", "-hide_banner", "-i", str(path), "-filter_complex", "ebur128=peak=true", "-f", "null", "-"])
    d["lufs_i"] = last_match(r.stderr, r"Integrated loudness I:\s*(-?[\d.]+) LUFS")
    d["true_peak_dbtp"] = last_match(r.stderr, r"True peak:\s*(-?[\d.]+) dBTP")
    return d

def wer(ref_text, hyp_text):
    def norm(t):
        t = t.replace("20", " twenty ")          # ref TN: 数字读法归一
        t = t.lower().replace("'", "").replace("’", "").replace("-", " ")
        t = re.sub(r"[^a-z0-9 ]+", " ", t)
        return [w for w in t.split() if w]
    ref, hyp = norm(ref_text), norm(hyp_text)
    n, m = len(ref), len(hyp)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cur[j] = min(prev[j - 1] + (ref[i - 1] != hyp[j - 1]), prev[j] + 1, cur[j - 1] + 1)
        prev = cur
    dist = prev[m]
    return {"wer": round(dist / max(n, 1), 4), "errors": dist, "ref_words": n, "hyp_words": m}

log = lambda m: print(f"[eval] {m}", flush=True)

s45, s24 = specs(W45), specs(W24)
log(f"45k: {s45}")
log(f"24k: {s24}")

# 谱上限实证：>12.5kHz 能量
r = sh(["ffmpeg", "-hide_banner", "-i", str(W45), "-af", "highpass=f=12500,astats=measure_overall=RMS_level", "-f", "null", "-"])
hf_rms = last_match(r.stderr, r"RMS level dB:\s*(-?[\d.]+|-inf)")
log(f"HF(>12.5kHz) RMS of 45k file: {hf_rms} dB")

# UTMOS（45k 与 24k）
r = sh([str(PY), str(UTMOS_WORKER), str(W45), str(W24)])
if r.returncode != 0:
    sys.exit(f"utmos rc={r.returncode}: {r.stderr[-300:]}")
utmos = json.loads(r.stdout.strip().splitlines()[-1])
log(f"UTMOS: 45k={utmos[str(W45)]} 24k={utmos[str(W24)]}")

# SenseVoice 英文转写（整章 45k 文件，内部 240s 分块）
r = sh([str(PY), str(ASR_PROC), str(W45), "iic/SenseVoiceSmall", "cpu"])
if r.returncode != 0:
    sys.exit(f"asr rc={r.returncode}: {r.stderr[-500:]}")
line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
asr = json.loads(line)
if not asr.get("success"):
    sys.exit(f"asr failed: {asr}")
hyp = asr["text"]
log(f"ASR hyp ({len(hyp)} chars): {hyp[:180]}...")

ref = " ".join(p.strip() for p in (WORK / "chapter1_clean.txt").read_text(encoding="utf-8").split("\n\n") if p.strip())
w = wer(ref, hyp)
log(f"WER={w['wer']*100:.2f}%  (errors={w['errors']}/{w['ref_words']} ref words, hyp={w['hyp_words']})")

summary = {
    "file_45k": s45, "file_24k_native": s24,
    "hf_above_12k5_rms_db": hf_rms,
    "utmos_45k": utmos[str(W45)], "utmos_24k_native": utmos[str(W24)],
    "asr_words": w, "asr_hyp_head": hyp[:300],
}
(WORK / "eval_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("EVAL_DONE " + json.dumps(summary, ensure_ascii=False))

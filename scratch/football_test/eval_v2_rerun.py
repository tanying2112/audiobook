"""v2 补测（轻量版）：只跑被中断的两项 — UTMOS + SenseVoice WER。
与 eval_v2.py 前半完全一致的规格测量已在前次完成，不重复。
结果合并进 scratch/football_test/v2/eval_summary_v2.json
"""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
OUT = ROOT / "output" / "football_forever_ch1"
W44 = OUT / "football_forever_ch1_44k1.wav"
NF24 = OUT / "football_forever_ch1_24k_float_native.wav"
ASR_PROC = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
UTMOS_WORKER = ROOT / "scratch/football_test/worker_utmos_chunked.py"
PY = ROOT / ".venv" / "bin" / "python"
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
log = lambda m: print(f"[ev2r] {m}", flush=True)

def sh(cmd, timeout=None):
    return subprocess.run(cmd, capture_output=True, text=True, env=ENV, timeout=timeout)

# ── 1) UTMOS（44.1k 交付物 + float 原生对照）─────────────────────
log("UTMOS: loading SpeechMOS worker...")
r = sh([str(PY), str(UTMOS_WORKER), str(W44), str(NF24)], timeout=1800)
if r.returncode != 0:
    sys.exit(f"utmos rc={r.returncode}: {r.stderr[-300:]}")
utmos = json.loads(r.stdout.strip().splitlines()[-1])
log(f"UTMOS 44.1k={utmos[str(W44)]} 24k_float={utmos[str(NF24)]}")

# ── 2) SenseVoice WER（44.1k 整章，剥 <|...|> 标签）──────────────
log("ASR: SenseVoice transcription...")
r = sh([str(PY), str(ASR_PROC), str(W44), "iic/SenseVoiceSmall", "cpu"], timeout=900)
if r.returncode != 0:
    sys.exit(f"asr rc={r.returncode}: {r.stderr[-500:]}")
line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
asr = json.loads(line)
if not asr.get("success"):
    sys.exit(f"asr failed: {asr}")
hyp = re.sub(r"<\|[^|]*\|>\s*", " ", asr["text"]).strip()
(WORK / "v2/asr_hyp_v2.txt").write_text(hyp, encoding="utf-8")
log(f"ASR ok: {len(hyp)} chars clean")

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
log(f"WER={dist/max(n,1)*100:.2f}%  (errors={dist}/{n} ref words, hyp={m})")

# ── 合并进既有 summary ──────────────────────────────────────────
summ = WORK / "v2/eval_summary_v2.json"
merged = {"utmos_44k1": utmos[str(W44)], "utmos_24k_float": utmos[str(NF24)],
          "wer": {"wer": round(dist / max(n, 1), 4), "errors": dist, "ref_words": n, "hyp_words": m}}
if summ.exists():
    merged = {**json.loads(summ.read_text(encoding="utf-8")), **merged}
summ.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
print("EV2R_DONE " + json.dumps(merged))

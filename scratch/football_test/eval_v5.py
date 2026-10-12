"""v5 交付物同口径评估: chunked UTMOS + SenseVoice WER (镜像 eval_v2_rerun 协议)."""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
W44 = ROOT / "output" / "football_forever_ch1" / "football_forever_ch1_v5_multivoice_44k1.wav"
ASR_PROC = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
UTMOS_WORKER = ROOT / "scratch/football_test/worker_utmos_chunked.py"
PY = ROOT / ".venv" / "bin" / "python"
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
log = lambda m: print(f"[ev5] {m}", flush=True)

r = subprocess.run([str(PY), str(UTMOS_WORKER), str(W44)], capture_output=True, text=True, env=ENV, timeout=1800)
if r.returncode != 0:
    sys.exit(f"utmos rc={r.returncode}: {r.stderr[-300:]}")
utmos = json.loads(r.stdout.strip().splitlines()[-1])
log(f"UTMOS chunked 44.1k = {utmos[str(W44)]}")

r = subprocess.run([str(PY), str(ASR_PROC), str(W44), "iic/SenseVoiceSmall", "cpu"], capture_output=True, text=True, env=ENV, timeout=900)
if r.returncode != 0:
    sys.exit(f"asr rc={r.returncode}: {r.stderr[-500:]}")
line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
asr = json.loads(line)
if not asr.get("success"):
    sys.exit(f"asr failed: {asr}")
hyp = re.sub(r"<\|[^|]*\|>\s*", " ", asr["text"]).strip()
(WORK / "v5/asr_hyp_v5.txt").write_text(hyp, encoding="utf-8")
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
wer = dist / max(n, 1)
log(f"WER={wer*100:.2f}%  (errors={dist}/{n} ref words, hyp={m})")

out = {"utmos_chunked_44k1": utmos[str(W44)], "wer": {"wer": round(wer, 4), "errors": dist, "ref_words": n, "hyp_words": m}}
(WORK / "v5/eval_summary_v5.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("EV5_DONE " + json.dumps(out))

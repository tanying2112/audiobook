"""v6 双交付物同口径评估: chunked UTMOS + SenseVoice WER (镜像 eval_v5 协议, dry+bed 两版)."""
import json, os, re, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
OUTD = ROOT / "output" / "football_forever_ch1"
W_DRY = OUTD / "football_forever_ch1_v6_emotion_44k1.wav"
W_BED = OUTD / "football_forever_ch1_v6_musicbed_44k1.wav"
ASR_PROC = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
UTMOS_WORKER = ROOT / "scratch/football_test/worker_utmos_chunked.py"
PY = ROOT / ".venv" / "bin" / "python"
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
log = lambda m: print(f"[ev6] {m}", flush=True)

def utmos_of(path):
    r = subprocess.run([str(PY), str(UTMOS_WORKER), str(path)], capture_output=True, text=True, env=ENV, timeout=1800)
    if r.returncode != 0:
        sys.exit(f"utmos rc={r.returncode}: {r.stderr[-300:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])[str(path)]

def wer_of(path, tag):
    r = subprocess.run([str(PY), str(ASR_PROC), str(path), "iic/SenseVoiceSmall", "cpu"],
                       capture_output=True, text=True, env=ENV, timeout=900)
    if r.returncode != 0:
        sys.exit(f"asr rc={r.returncode}: {r.stderr[-500:]}")
    line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
    asr = json.loads(line)
    if not asr.get("success"):
        sys.exit(f"asr failed: {asr}")
    hyp = re.sub(r"<\|[^|]*\|>\s*", " ", asr["text"]).strip()
    (WORK / f"v6/asr_hyp_v6_{tag}.txt").write_text(hyp, encoding="utf-8")
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
    return round(dist / max(n, 1), 4), dist, n, m

out = {}
for tag, path in [("dry", W_DRY), ("bed", W_BED)]:
    log(f"UTMOS {tag} ...")
    u = utmos_of(path)
    log(f"UTMOS {tag} = {u}")
    log(f"WER {tag} ...")
    w = wer_of(path, tag)
    log(f"WER {tag} = {w[0]*100:.2f}%  (errors={w[1]}/{w[2]} ref words)")
    out[tag] = {"utmos_chunked_44k1": u, "wer": {"wer": w[0], "errors": w[1], "ref_words": w[2], "hyp_words": w[3]}}
    out[f"deliverable_{tag}"] = str(path)

out["note"] = ("bed 版 UTMOS/WER 受音乐床干扰会回落(预测器/识别器伪影, 参照: 原声带床 UTMOS 仅 2.57); "
               "dry 版为真实语音质量信号。bed 版 WER 还包含 8.5s 尾声纯音乐段可能产生的识别幻觉。")
(WORK / "v6/eval_summary_v6.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("EV6_DONE " + json.dumps(out))

"""整本原声 SenseVoice 转写（_asr_proc.py 内部 ≤240s 分块）→ 定位各章边界。"""
import json, re, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
REF = ROOT / "scratch/football_test/ref/full_book.wav"
ASR = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
PY = ROOT / ".venv/bin/python"
OUT = ROOT / "scratch/football_test/ref/full_transcript.txt"
ENV = {**dict(__import__("os").environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
print("[asr_full] transcribing 3009s full book...", flush=True)
r = subprocess.run([str(PY), str(ASR), str(REF), "iic/SenseVoiceSmall", "cpu"],
                   capture_output=True, text=True, env=ENV, timeout=3000)
if r.returncode != 0:
    sys.exit(f"rc={r.returncode}: {r.stderr[-500:]}")
line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
d = json.loads(line)
if not d.get("success"):
    sys.exit(f"asr failed: {d}")
hyp = re.sub(r"<\|[^|]*\|>\s*", " ", d["text"]).strip()
OUT.write_text(hyp, encoding="utf-8")
print(f"[asr_full] {len(hyp)} chars -> {OUT}")
print("ASR_FULL_DONE")

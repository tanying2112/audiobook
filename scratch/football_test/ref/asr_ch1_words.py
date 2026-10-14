"""Ch1 窗口(0-11:00) SenseVoice 带词时间戳转写 → 定位章界/节奏/停顿。"""
import json, re, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
WAV = ROOT / "scratch/football_test/ref/ch1_window.wav"
ASR = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
PY = ROOT / ".venv/bin/python"
ENV = {**dict(__import__("os").environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
r = subprocess.run([str(PY), str(ASR), str(WAV), "iic/SenseVoiceSmall", "cpu"],
                   capture_output=True, text=True, env=ENV, timeout=1200)
if r.returncode != 0:
    sys.exit(f"rc={r.returncode}: {r.stderr[-500:]}")
line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
d = json.loads(line)
if not d.get("success"):
    sys.exit(f"asr failed: {d}")
out = ROOT / "scratch/football_test/ref/ch1_words.json"
out.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
print(f"words={len(d['words'])} text={len(d['text'])} chars -> {out}")
print("CH1_WORDS_DONE")

#!/bin/zsh
# 对旧版 v2 MP3（espeak 路径，用户投诉的文件）做同口径全章打分 → 对照数字
cd /Users/guwj/Documents/audiobook
export KMP_DUPLICATE_LIB_OK=TRUE
.venv/bin/python - <<'PYEOF' > scratch/kokoro_iter/v2_score.log 2>&1
import json, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from scratch.kokoro_iter.iterate_30 import PARAS
import re

def apply_textnorm(text, both=True):
    text = re.sub(r"^•\s*", "", text)
    text = re.sub(r"[「」『』“”]", "", text)
    return text.strip()

full_ref = "".join(apply_textnorm(p) for p in PARAS)
v2 = "output/howtolivebetter_ch23/23_学什么技能划算_kokoro.mp3"
py = ".venv/bin/python"

r = subprocess.run([py, "scratch/kokoro_iter/worker_utmos.py", v2], capture_output=True, text=True)
utmos = json.loads(r.stdout.strip().splitlines()[-1])[v2] if r.returncode == 0 else None
r2 = subprocess.run([py, "scratch/kokoro_iter/worker_asr.py", json.dumps({v2: full_ref}, ensure_ascii=False)],
                    capture_output=True, text=True)
asr = json.loads(r2.stdout.strip().splitlines()[-1])[v2] if r2.returncode == 0 else None
print(f"V2_FULL utmos={utmos} cer={asr['cer'] if asr else None} score={utmos - 3*asr['cer'] if asr and utmos else None}")
PYEOF

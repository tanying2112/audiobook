#!/bin/zsh
set -e
cd /Users/guwj/Documents/audiobook
export KMP_DUPLICATE_LIB_OK=TRUE
PY=.venv/bin/python

echo "=== [1] v4 链 + 编码 ==="
$PY scratch/roadmap_p0/v4_build.py

echo "=== [2] 全章裁判（SenseVoice + Paraformer + UTMOS 30s 分块）==="
$PY - <<'PYEOF'
import json
old = json.load(open("scratch/kokoro_iter/ref_full.json"))
ref = next(iter(old.values()))
refs = {"output/howtolivebetter_ch23/23_学什么技能划算_kokoro_v4.mp3": ref,
        "output/howtolivebetter_ch23/23_学什么技能划算_kokoro_v4.opus": ref}
json.dump(refs, open("scratch/roadmap_p0/v4_refs.json", "w"), ensure_ascii=False)
print("refs built")
PYEOF
$PY scratch/kokoro_iter/worker_funasr.py sensevoice scratch/roadmap_p0/v4_refs.json > scratch/roadmap_p0/sv_v4.json 2> scratch/roadmap_p0/sv_v4.err
$PY scratch/kokoro_iter/worker_funasr.py paraformer scratch/roadmap_p0/v4_refs.json > scratch/roadmap_p0/pf_v4.json 2>> scratch/roadmap_p0/sv_v4.err
mkdir -p scratch/roadmap_p0/u30_mp3 scratch/roadmap_p0/u30_opus
ffmpeg -y -v error -i output/howtolivebetter_ch23/23_学什么技能划算_kokoro_v4.mp3 -f segment -segment_time 30 -ar 24000 -ac 1 scratch/roadmap_p0/u30_mp3/c%03d.wav
ffmpeg -y -v error -i output/howtolivebetter_ch23/23_学什么技能划算_kokoro_v4.opus -f segment -segment_time 30 -ar 24000 -ac 1 scratch/roadmap_p0/u30_opus/c%03d.wav
$PY scratch/kokoro_iter/worker_utmos.py scratch/roadmap_p0/u30_mp3/*.wav > scratch/roadmap_p0/utmos_v4_mp3.json 2>> scratch/roadmap_p0/sv_v4.err
$PY scratch/kokoro_iter/worker_utmos.py scratch/roadmap_p0/u30_opus/*.wav > scratch/roadmap_p0/utmos_v4_opus.json 2>> scratch/roadmap_p0/sv_v4.err
echo V4_JUDGE_DONE

#!/bin/zsh
cd /Users/guwj/Documents/audiobook
export KMP_DUPLICATE_LIB_OK=TRUE
PY=.venv/bin/python
$PY scratch/kokoro_iter/worker_funasr.py sensevoice scratch/roadmap_p0/judge_codec_refs.json > scratch/roadmap_p0/sv_codecs.json 2> scratch/roadmap_p0/sv_codecs.err
$PY scratch/kokoro_iter/worker_utmos.py scratch/roadmap_p0/codecs/*.wav > scratch/roadmap_p0/utmos_codecs.json 2>> scratch/roadmap_p0/sv_codecs.err
echo CODECS_JUDGE_DONE

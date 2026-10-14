#!/bin/zsh
cd /Users/guwj/Documents/audiobook
export KMP_DUPLICATE_LIB_OK=TRUE
PY=.venv/bin/python
echo "=== sensevoice ==="
$PY scratch/kokoro_iter/worker_funasr.py sensevoice scratch/roadmap_p0/judge_refs.json > scratch/roadmap_p0/sv_chains.json 2> scratch/roadmap_p0/sv_chains.err
echo "=== utmos ==="
$PY scratch/kokoro_iter/worker_utmos.py scratch/roadmap_p0/chains/*.wav > scratch/roadmap_p0/utmos_chains.json 2>> scratch/roadmap_p0/sv_chains.err
echo "=== eval_base ==="
$PY scratch/kokoro_iter/worker_utmos.py scratch/roadmap_p0/eval_base/*.wav >> scratch/roadmap_p0/utmos_chains.json.tmp 2>> scratch/roadmap_p0/sv_chains.err
echo CHAINS_JUDGE_DONE

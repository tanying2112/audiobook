#!/bin/zsh
cd /Users/guwj/Documents/audiobook
export KMP_DUPLICATE_LIB_OK=TRUE
PY=.venv/bin/python
for M in sensevoice paraformer; do
  echo "=== $M ==="
  $PY scratch/kokoro_iter/worker_funasr.py $M scratch/kokoro_iter/ref_full.json
done
echo REJUDGE_DONE

#!/bin/zsh
cd /Users/guwj/Documents/audiobook
mkdir -p scratch/roadmap_p0/u30_v3mp3
ffmpeg -y -v error -i "output/howtolivebetter_ch23/23_学什么技能划算_kokoro_v3.mp3" -f segment -segment_time 30 -ar 24000 -ac 1 scratch/roadmap_p0/u30_v3mp3/c%03d.wav
.venv/bin/python scratch/kokoro_iter/worker_utmos.py scratch/roadmap_p0/u30_v3mp3/*.wav > scratch/roadmap_p0/utmos_v3_mp3.json 2> scratch/roadmap_p0/utmos_v3_mp3.err
echo V3MP3_UTMOS_DONE

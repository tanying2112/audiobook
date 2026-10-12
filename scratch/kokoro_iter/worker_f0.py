"""F0 韵律打分子进程：librosa yin 基频轨迹统计（声调丰富度代理）。
输入: JSON {"path": null, ...} 或路径列表  输出: {"path": {"f0_std": f, "f0_range": f, "f0_cv": f, "pause_ratio": f}}"""
import json, sys
import librosa
import numpy as np

paths = list(json.loads(sys.argv[1]).keys())
out = {}
for p in paths:
    y, sr = librosa.load(p, sr=24000, mono=True)
    f0 = librosa.yin(y, fmin=60, fmax=400, sr=sr, frame_length=1024)
    voiced = f0[(f0 > 65) & (f0 < 380)]
    rms = librosa.feature.rms(y=y, frame_length=1024)[0]
    if len(voiced) < 10:
        out[p] = {"f0_std": 0.0, "f0_range": 0.0, "f0_cv": 0.0, "pause_ratio": 1.0}
        continue
    out[p] = {
        "f0_std": round(float(voiced.std()), 3),
        "f0_range": round(float(voiced.max() - voiced.min()), 3),
        "f0_cv": round(float(voiced.std() / voiced.mean()), 4),
        "pause_ratio": round(float((rms < 1e-4).mean()), 4),
    }
print(json.dumps(out))

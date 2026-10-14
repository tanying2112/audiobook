"""听感主张定量验证：45k 文件回降 24k 后与原生 24k 逐样本比对。
用户听感「无差别」→ 数学检验：若两文件信息相同，回降差异应仅为
重采样+量化舍入（约 -80dB 级），远低于可闻阈（~ -50dB）。
"""
import json, subprocess, sys
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
W45 = ROOT / "output/football_forever_ch1/football_forever_ch1_45k.wav"
W24 = ROOT / "output/football_forever_ch1/football_forever_ch1_24k_native.wav"
RT = WORK / "rt_45to24.wav"

r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(W45), "-ar", "24000",
                    "-ac", "1", "-c:a", "pcm_s16le", str(RT)], capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"resample failed: {r.stderr[-300:]}")
a, _ = sf.read(str(W24))     # 原生 24k
b, _ = sf.read(str(RT))      # 45k 回降 24k
n = min(len(a), len(b))
d = a[:n] - b[:n]
res = {
    "n_samples": int(n),
    "max_abs_diff": float(np.max(np.abs(d))),
    "max_diff_dbfs": round(float(20 * np.log10(max(np.max(np.abs(d)), 1e-12))), 1),
    "rms_diff_db": round(float(10 * np.log10(np.mean(d ** 2) + 1e-24)), 1),
    "rms_signal_db": round(float(10 * np.log10(np.mean(a[:n] ** 2) + 1e-24)), 1),
}
res["snr_db"] = round(res["rms_signal_db"] - res["rms_diff_db"], 1)
print(json.dumps(res))
(WORK / "verify_rt.json").write_text(json.dumps(res, indent=2))

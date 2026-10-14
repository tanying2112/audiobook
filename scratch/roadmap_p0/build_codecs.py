"""c1 链音频 × 5 种 48kbps 编码器 → 解码回 wav 供裁判 + 测真峰过冲。"""
import json, re, subprocess
from pathlib import Path

P0 = Path(__file__).resolve().parent
CH = P0 / "chains"
CD = P0 / "codecs"
CD.mkdir(exist_ok=True)

CODECS = {
    "mp3":   ["-c:a", "libmp3lame", "-b:a", "48k"],
    "aac":   ["-c:a", "aac", "-b:a", "48k"],
    "aac_at":["-c:a", "aac_at", "-b:a", "48k"],
    "opus":  ["-c:a", "libopus", "-b:a", "48k"],
    "opus_voip": ["-c:a", "libopus", "-b:a", "48k", "-application", "voip"],
}
EXT = {"mp3": ".mp3", "aac": ".m4a", "aac_at": ".m4a", "opus": ".opus", "opus_voip": ".opus"}

def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True)

def tp(path):
    r = sh("ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    return round(float(json.loads(m.group(0))["input_tp"]), 2)

out = {}
for w in sorted(CH.glob("*_c1.wav")):
    stem = w.stem[:-3]
    for name, args in CODECS.items():
        enc = CD / f"{stem}_{name}{EXT[name]}"
        if sh("ffmpeg", "-y", "-i", str(w), *args, str(enc)).returncode != 0:
            print("ENC FAIL", name, stem, flush=True); continue
        dec = CD / f"{stem}_{name}.wav"
        if sh("ffmpeg", "-y", "-i", str(enc), "-ar", "24000", "-ac", "1", str(dec)).returncode != 0:
            print("DEC FAIL", name, stem, flush=True); continue
        out[str(dec)] = {"codec": name, "para": stem, "tp_dec_dbtp": tp(dec),
                         "bytes": enc.stat().st_size}
    print(stem, "done", flush=True)
json.dump(out, open(P0 / "codec_meta.json", "w"), indent=1)
agg = {}
for name in CODECS:
    rows = [v for v in out.values() if v["codec"] == name]
    agg[name] = {"tp_dec_max": max(r["tp_dec_dbtp"] for r in rows),
                 "kbps_mean": round(sum(r["bytes"] for r in rows) * 8 / 222.1 / 1000, 1)}
print(json.dumps(agg, indent=1))

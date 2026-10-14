"""v4 = 冠军合成（同 v3）+ 峰值限幅链（−3.8 dBFS）+ 双编码交付。"""
import json, re, subprocess
from pathlib import Path

ROOT = Path("/Users/guwj/Documents/audiobook")
SRC = ROOT / "scratch/kokoro_iter/final_wav/final_raw.wav"
OUTD = ROOT / "output/howtolivebetter_ch23"
CHAIN = "alimiter=limit=0.6457:attack=5:release=100:level=disabled"  # −3.8 dBFS

def sh(*a):
    return subprocess.run(list(a), capture_output=True, text=True)

def loud(path):
    r = sh("ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-")
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', r.stderr, re.S)
    return json.loads(m.group(0))

def rms(path):
    r = sh("ffmpeg", "-hide_banner", "-i", str(path), "-af",
           "astats=measure_overall=RMS_level:measure_perchannel=none", "-f", "null", "-")
    m = re.findall(r"RMS level dB:\s*(-?[\d.]+|-inf)", r.stderr)
    return float(m[-1]) if m and m[-1] != "-inf" else None

assert SRC.exists()
wav = ROOT / "scratch/roadmap_p0/v4_chain.wav"
assert sh("ffmpeg", "-y", "-i", str(SRC), "-af", CHAIN, "-ar", "24000", "-ac", "1", str(wav)).returncode == 0
mp3 = OUTD / "23_学什么技能划算_kokoro_v4.mp3"
opus = OUTD / "23_学什么技能划算_kokoro_v4.opus"
assert sh("ffmpeg", "-y", "-i", str(wav), "-c:a", "libmp3lame", "-b:a", "48k", str(mp3)).returncode == 0
assert sh("ffmpeg", "-y", "-i", str(wav), "-c:a", "libopus", "-b:a", "48k", str(opus)).returncode == 0

meta = {}
for tag, p in (("chain_wav", wav), ("mp3", mp3), ("opus", opus)):
    lm = loud(p)
    probe = sh("ffprobe", "-v", "quiet", "-show_entries", "format=duration,size,bit_rate", "-of", "json", str(p))
    pv = json.loads(probe.stdout)["format"]
    meta[tag] = {"lufs": round(float(lm["input_i"]), 2), "tp_dbtp": round(float(lm["input_tp"]), 2),
                 "lra": round(float(lm["input_lra"]), 2), "rms_db": rms(p),
                 "mb": round(int(pv["size"]) / 1e6, 2), "dur_s": round(float(pv["duration"]), 1),
                 "kbps": round(int(pv["bit_rate"]) / 1000, 1)}
json.dump(meta, open(ROOT / "scratch/roadmap_p0/v4_specs.json", "w"), indent=1)
print(json.dumps(meta, ensure_ascii=False, indent=1))

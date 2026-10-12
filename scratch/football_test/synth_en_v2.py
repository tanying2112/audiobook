"""Football Forever ch1 v2 — 三处修正实测：
  1) speed 1.0→0.9（211→~195 wpm，分级读物降速）
  2) 原生输出 float32 落盘（不再被 s16 写盘削掉 >±1.0 的样本），
     再挂 P0.1 v4 同款限幅链 alimiter=limit=0.6457:attack=5:release=100:level=disabled（−3.8 dBFS）
  3) 重采样 swr→soxr VHQ（python soxr wheel，本机已装 libsoxr），24k→44.1kHz 标准采样率
输出:
  output/football_forever_ch1/football_forever_ch1_44k1.wav          交付物(s16)
  output/football_forever_ch1/football_forever_ch1_24k_float_native.wav  未削波 float 参考
  scratch/football_test/v2/synth_summary_v2.json
"""
import json, re, subprocess, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
V2 = WORK / "v2"; V2.mkdir(exist_ok=True)
OUT = ROOT / "output" / "football_forever_ch1"
VOICE, LANG, SPEED = "am_adam", "en-gb", 0.9
SENT_GAP, PARA_GAP = 0.45, 0.90
CHAIN = "alimiter=limit=0.6457:attack=5:release=100:level=disabled"  # P0.1 v4 链原样

def log(m): print(f"[v2] {m}", flush=True)

def split_sents(p):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]

PARAS = [p.strip() for p in (WORK / "chapter1_clean.txt").read_text(encoding="utf-8").split("\n\n") if p.strip()]
WORDS = sum(len(p.split()) for p in PARAS)

from kokoro_onnx import Kokoro
kokoro = Kokoro(str(ROOT / "models/kokoro-v1.0.onnx"), str(ROOT / "models/voices-v1.0.bin"))

t0 = time.time()
pieces, n_sents, sr, n_para_gap = [], 0, 24000, 0
for pi, para in enumerate(PARAS):
    sents = split_sents(para)
    for si, s in enumerate(sents):
        a, sr = kokoro.create(text=s, voice=VOICE, speed=SPEED, lang=LANG)
        pieces.append(a.astype(np.float32)); n_sents += 1
        if si < len(sents) - 1:
            pieces.append(np.zeros(int(sr * SENT_GAP), dtype=np.float32))
    if pi < len(PARAS) - 1:
        pieces.append(np.zeros(int(sr * PARA_GAP), dtype=np.float32)); n_para_gap += 1
    if (pi + 1) % 10 == 0:
        log(f"  para {pi+1}/{len(PARAS)}")
synth_secs = time.time() - t0
audio = np.concatenate(pieces)
audio_sec = len(audio) / sr
n_intra = n_sents - len(PARAS)
gap_sec = n_intra * SENT_GAP + n_para_gap * PARA_GAP
speech_sec = audio_sec - gap_sec
wpm = WORDS / speech_sec * 60
rtf = synth_secs / audio_sec
log(f"synth: {n_sents} sents, {audio_sec:.1f}s (speech {speech_sec:.1f}s), RTF={rtf:.3f}, {wpm:.0f} wpm")

# 1) float 原生落盘（不削波）
native_f = OUT / "football_forever_ch1_24k_float_native.wav"
sf.write(str(native_f), audio, sr, subtype="FLOAT")
peak_float = float(np.max(np.abs(audio)))
n_over = int(np.sum(np.abs(audio) > 1.0))
log(f"native float peak={peak_float:.4f}, >1.0 samples={n_over}")

# 2) v4 限幅链（float in/out, 24k）
lim_f = V2 / "lim_24k_float.wav"
r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(native_f), "-af", CHAIN,
                    "-c:a", "pcm_f32le", "-ar", "24000", str(lim_f)], capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"limiter failed: {r.stderr[-300:]}")
lim, _ = sf.read(str(lim_f))
log(f"limited peak={float(np.max(np.abs(lim))):.4f} (target ceiling {0.6457})")

# 3) soxr VHQ 24k → 44.1k → s16 交付物
import soxr
y = soxr.resample(lim.astype(np.float32), 24000, 44100, quality="VHQ")
w44 = OUT / "football_forever_ch1_44k1.wav"
sf.write(str(w44), y, 44100, subtype="PCM_16")
log(f"44.1k deliverable: {len(y)} samples, {len(y)/44100:.1f}s, peak={float(np.max(np.abs(y))):.4f}")

summary = {
    "speed": SPEED, "voice": VOICE, "lang": LANG,
    "sent_gap_s": SENT_GAP, "para_gap_s": PARA_GAP,
    "paragraphs": len(PARAS), "sentences": n_sents, "words": WORDS,
    "synth_wall_secs": round(synth_secs, 1), "audio_sec": round(audio_sec, 1),
    "speech_sec": round(speech_sec, 1), "rtf_synth": round(rtf, 3), "wpm": round(wpm, 1),
    "native_float_peak": round(peak_float, 5), "native_over_unity_samples": n_over,
    "limiter_chain": CHAIN, "limited_peak": round(float(np.max(np.abs(lim))), 5),
    "resampler": "soxr VHQ (python-soxr 1.1.0)",
    "deliverable": {"path": str(w44), "sr": 44100, "subtype": "PCM_16",
                    "peak": round(float(np.max(np.abs(y))), 5)},
}
(V2 / "synth_summary_v2.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("V2_DONE " + json.dumps(summary))

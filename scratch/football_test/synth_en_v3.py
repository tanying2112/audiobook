"""Football Forever ch1 v3 — 同稿原声对照后三处升级实测（2026-10-09）：
  原声 Ch1 (0:00-9:00, 540s) 实测解构：
    - 音素率 165-171 wpm（925 词 / 335.7s 音素）—— 不慢！慢感来自停顿预算
    - 停顿预算 159s（29%）：217 个 >0.3s 停顿, 中位 0.62s, P90 1.20s
    - 综合响度 -22.7 LUFS / TP -3.8（EBU R128 有声书档, 系统新 preset）
  v3 对应三处升级：
    1) speed 0.9→0.75（201.6→~168 wpm 音素率对齐原声）
    2) 停顿 sent 0.45→0.90s / para 0.90→2.00s（对齐原声中位/P90 停顿分布）
    3) 响度 -18.5→-23.0 LUFS（测量后精确增益, EBU R128 audiobook 档;
       下行 4.5dB 后 TP -3.3→-7.8, 无需重限幅）
输出:
  output/football_forever_ch1/football_forever_ch1_v3_44k1.wav
  scratch/football_test/v3/synth_summary_v3.json
"""
import json, re, subprocess, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
V3 = WORK / "v3"; V3.mkdir(exist_ok=True)
OUT = ROOT / "output" / "football_forever_ch1"
VOICE, LANG, SPEED = "am_adam", "en-gb", 0.75
SENT_GAP, PARA_GAP = 0.90, 2.00
TARGET_LUFS = -23.0
CHAIN = "alimiter=limit=0.6457:attack=5:release=100:level=disabled"  # P0.1 v4 链原样

def log(m): print(f"[v3] {m}", flush=True)

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
wpm_phon = WORDS / speech_sec * 60
wpm_total = WORDS / audio_sec * 60
rtf = synth_secs / audio_sec
log(f"synth: {n_sents} sents, {audio_sec:.1f}s (speech {speech_sec:.1f}s), RTF={rtf:.3f}")
log(f"phonation {wpm_phon:.0f} wpm (原声 165-171), overall {wpm_total:.0f} wpm (原声 103)")

# 1) float 原生落盘
native_f = V3 / "native_24k_float.wav"
sf.write(str(native_f), audio, sr, subtype="FLOAT")
log(f"native float peak={float(np.max(np.abs(audio))):.4f}")

# 2) v4 限幅链
lim_f = V3 / "lim_24k_float.wav"
r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(native_f), "-af", CHAIN,
                    "-c:a", "pcm_f32le", "-ar", "24000", str(lim_f)], capture_output=True, text=True)
if r.returncode != 0:
    sys.exit(f"limiter failed: {r.stderr[-300:]}")
lim, _ = sf.read(str(lim_f))

# 3) soxr VHQ → 44.1k
import soxr
y = soxr.resample(lim.astype(np.float32), 24000, 44100, quality="VHQ")

# 4) 响度对齐: 测量 → 精确增益到 -23 LUFS（线性, 无动态处理）
tmp44 = V3 / "pre_gain_44k1.wav"
sf.write(str(tmp44), y, 44100, subtype="FLOAT")
r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(tmp44),
                    "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
err = r.stderr[r.stderr.find("Summary:"):]
mi = re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err)
mtp = re.search(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", err)
if not mi:
    sys.exit(f"ebur128 parse fail:\n{err[-400:]}")
lufs_pre = float(mi.group(1))
gain_db = TARGET_LUFS - lufs_pre
y = y * (10 ** (gain_db / 20))
log(f"loudness: {lufs_pre:.1f} LUFS + {gain_db:+.2f} dB → target {TARGET_LUFS}")

w44 = OUT / "football_forever_ch1_v3_44k1.wav"
sf.write(str(w44), y, 44100, subtype="PCM_16")
# 复测确认
r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(w44),
                    "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
err = r.stderr[r.stderr.find("Summary:"):]
lufs_post = float(re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err).group(1))
tp_post = float(re.search(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", err).group(1))
log(f"deliverable: {len(y)/44100:.1f}s, {lufs_post:.1f} LUFS, TP {tp_post:.1f} dBTP, peak {float(np.max(np.abs(y))):.4f}")

summary = {
    "speed": SPEED, "voice": VOICE, "lang": LANG,
    "sent_gap_s": SENT_GAP, "para_gap_s": PARA_GAP,
    "target_lufs": TARGET_LUFS, "lufs_pre_gain": lufs_pre, "gain_db": round(gain_db, 2),
    "paragraphs": len(PARAS), "sentences": n_sents, "words": WORDS,
    "synth_wall_secs": round(synth_secs, 1), "audio_sec": round(audio_sec, 1),
    "speech_sec": round(speech_sec, 1), "rtf_synth": round(rtf, 3),
    "wpm_phonation": round(wpm_phon, 1), "wpm_overall": round(wpm_total, 1),
    "limiter_chain": CHAIN, "resampler": "soxr VHQ (python-soxr 1.1.0)",
    "deliverable": {"path": str(w44), "sr": 44100, "subtype": "PCM_16",
                    "lufs": lufs_post, "tp_dbtp": tp_post,
                    "peak": round(float(np.max(np.abs(y))), 5)},
    "ref_calibration": {"ref_ch1_extent_s": [0, 540], "ref_wpm_overall": 102.8,
                        "ref_wpm_phonation": 165.3, "ref_pause_budget_s": 159,
                        "ref_lufs": -22.7, "ref_tp_dbtp": -3.8},
}
(V3 / "synth_summary_v3.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("V3_DONE " + json.dumps(summary))

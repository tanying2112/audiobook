"""Football Forever ch1 英文实测 — kokoro_onnx v1.0 直调：
  1) 音色筛选：4 英语音色 × 第2-3段前4句 → UTMOS(子进程) 择优
  2) 全章合成：句级切分 create()，句间 0.45s / 段间 0.9s 静音，speed 1.0, lang en-gb
  3) 24kHz 原生 → ffmpeg soxr 重采样 45kHz pcm_s16le（失败回退 swr）
输出:
  output/football_forever_ch1/football_forever_ch1_24k_native.wav  (原生 24k 参考)
  output/football_forever_ch1/football_forever_ch1_45k.wav         (45kHz 交付物)
  scratch/football_test/screen/*.wav  scratch/football_test/synth_summary.json
"""
import json, re, subprocess, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
OUT = ROOT / "output" / "football_forever_ch1"
MODEL = ROOT / "models" / "kokoro-v1.0.onnx"
VOICES_BIN = ROOT / "models" / "voices-v1.0.bin"
UTMOS_WORKER = ROOT / "scratch" / "kokoro_iter" / "worker_utmos.py"

SCREEN_VOICES = ["am_michael", "am_adam", "bm_george", "af_bella"]
LANG = "en-gb"          # Oxford 分级读物，英音
SENT_GAP, PARA_GAP = 0.45, 0.90
SPEED = 1.0

def log(m):
    print(f"[ff] {m}", flush=True)

def split_sents(p):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]

PARAS = [p.strip() for p in (WORK / "chapter1_clean.txt").read_text(encoding="utf-8").split("\n\n") if p.strip()]
log(f"paragraphs={len(PARAS)} words={sum(len(p.split()) for p in PARAS)}")

from kokoro_onnx import Kokoro
t_load = time.time()
kokoro = Kokoro(str(MODEL), str(VOICES_BIN))
load_secs = time.time() - t_load
log(f"model loaded in {load_secs:.1f}s")

# ── 1. 音色筛选 ──────────────────────────────────────────────
screen_sents = split_sents(PARAS[1])[:3] + [split_sents(PARAS[2])[0]]
screen_dir = WORK / "screen"; screen_dir.mkdir(parents=True, exist_ok=True)
paths = []
for v in SCREEN_VOICES:
    pieces = []
    for i, s in enumerate(screen_sents):
        a, sr = kokoro.create(text=s, voice=v, speed=SPEED, lang=LANG)
        pieces.append(a.astype(np.float32))
        if i < len(screen_sents) - 1:
            pieces.append(np.zeros(int(sr * SENT_GAP), dtype=np.float32))
    p = screen_dir / f"screen_{v}.wav"
    sf.write(str(p), np.concatenate(pieces), sr)
    paths.append(str(p))
    log(f"screen {v}: {len(screen_sents)} sents, {len(np.concatenate(pieces))/sr:.1f}s")

env = {**dict(__import__('os').environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
r = subprocess.run([str(ROOT / ".venv/bin/python"), str(UTMOS_WORKER), *paths],
                   capture_output=True, text=True, env=env)
if r.returncode != 0:
    sys.exit(f"UTMOS worker rc={r.returncode}: {r.stderr[-300:]}")
scores = json.loads(r.stdout.strip().splitlines()[-1])
winner = max(SCREEN_VOICES, key=lambda v: scores[str((screen_dir / f'screen_{v}.wav'))])
for v in SCREEN_VOICES:
    log(f"  UTMOS {v}: {scores[str(screen_dir / f'screen_{v}.wav')]}")
log(f"winner voice: {winner}")

# ── 2. 全章合成（句级，RTF=合成墙钟/音频时长）──────────────────
t0 = time.time()
all_pieces, n_sents, sr_out = [], 0, 24000
for pi, para in enumerate(PARAS):
    sents = split_sents(para)
    for si, s in enumerate(sents):
        a, sr_out = kokoro.create(text=s, voice=winner, speed=SPEED, lang=LANG)
        all_pieces.append(a.astype(np.float32))
        n_sents += 1
        if si < len(sents) - 1:
            all_pieces.append(np.zeros(int(sr_out * SENT_GAP), dtype=np.float32))
    if pi < len(PARAS) - 1:
        all_pieces.append(np.zeros(int(sr_out * PARA_GAP), dtype=np.float32))
    if (pi + 1) % 10 == 0:
        log(f"  para {pi+1}/{len(PARAS)} done")
synth_secs = time.time() - t0
audio = np.concatenate(all_pieces)
audio_sec = len(audio) / sr_out
native = OUT / "football_forever_ch1_24k_native.wav"
sf.write(str(native), audio, sr_out)
rtf = synth_secs / audio_sec
log(f"synth: {n_sents} sents, {audio_sec:.1f}s audio, wall {synth_secs:.1f}s, RTF={rtf:.3f}")

# ── 3. 45kHz 重采样（soxr → swr 回退）─────────────────────────
w45 = OUT / "football_forever_ch1_45k.wav"
soxr_cmd = ["ffmpeg", "-y", "-v", "warning", "-i", str(native),
            "-af", "aresample=resampler=soxr", "-ar", "45000", "-ac", "1",
            "-c:a", "pcm_s16le", str(w45)]
r1 = subprocess.run(soxr_cmd, capture_output=True, text=True)
resampler = "soxr"
if r1.returncode != 0 or not w45.exists():
    log(f"soxr failed (rc={r1.returncode}): {r1.stderr[-200:]}; falling back to swr")
    resampler = "swr"
    r2 = subprocess.run(["ffmpeg", "-y", "-v", "warning", "-i", str(native),
                         "-ar", "45000", "-ac", "1", "-c:a", "pcm_s16le", str(w45)],
                        capture_output=True, text=True)
    if r2.returncode != 0:
        sys.exit(f"swr resample failed: {r2.stderr[-300:]}")
probe = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                        "stream=sample_rate,channels,codec_name,duration",
                        "-of", "json", str(w45)], capture_output=True, text=True)
info = json.loads(probe.stdout)["streams"][0]

summary = {
    "book": "Football Forever (Dominoes Level 1), Chapter One",
    "paragraphs": len(PARAS), "sentences": n_sents, "words": sum(len(p.split()) for p in PARAS),
    "lang": LANG, "speed": SPEED, "sent_gap_s": SENT_GAP, "para_gap_s": PARA_GAP,
    "screen_voices": SCREEN_VOICES, "screen_scores": scores, "winner_voice": winner,
    "model_load_secs": round(load_secs, 1), "synth_wall_secs": round(synth_secs, 1),
    "audio_sec": round(audio_sec, 1), "rtf_synth": round(rtf, 3),
    "native_sr": sr_out, "resampler": resampler,
    "out_45k": {"path": str(w45), **info},
    "out_native": str(native),
}
(WORK / "synth_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print("SYNTH_DONE " + json.dumps(summary))

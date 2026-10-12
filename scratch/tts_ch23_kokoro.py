"""Kokoro-82M ONNX 本地合成第 23 节「正文版」（ch23_body.txt，已去元数据行+朗读向规范化）。
男声 zm_yunxi（对应 Edge 的 zh-CN-YunxiNeural，与 v1 同系音色），speed=1.25 提高语速，
lang=cmn。库内部按 510 音素自批处理（0.6.1 _split_phonemes，已在最长段 432 字实测），
段间插 0.45s 静音（与 Edge v1 一致）。输出 WAV 后经 ffmpeg 转 MP3。"""
import sys, time
import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

SRC = "output/howtolivebetter_ch23/ch23_body.txt"
WAV = "output/howtolivebetter_ch23/ch23_kokoro_raw.wav"
VOICE = "zm_yunxi"
SPEED = 1.25
SR = 24000
PARA_PAUSE = 0.45
RETRIES = 3

paras = [p.strip() for p in open(SRC, encoding="utf-8").read().split("\n\n") if p.strip()]
total_chars = sum(len(p) for p in paras)
print(f"[kokoro] {len(paras)} paras, {total_chars} chars, voice={VOICE}, speed={SPEED}", flush=True)

k = Kokoro("models/kokoro-v1.0.onnx", "models/voices-v1.0.bin")
print("[kokoro] model loaded", flush=True)

def synth(text: str):
    last = None
    for attempt in range(RETRIES):
        try:
            audio, sr = k.create(text=text, voice=VOICE, speed=SPEED, lang="cmn")
            if len(audio) / sr >= 0.05:
                return audio, sr
            last = RuntimeError(f"too short: {len(audio)/sr:.3f}s")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(2.0 * (attempt + 1))
    raise RuntimeError(f"failed after {RETRIES} tries: {last}")

pause = np.zeros(int(SR * PARA_PAUSE), dtype=np.float32)
pieces, t0 = [], time.time()
for i, p in enumerate(paras):
    a, sr = synth(p)
    assert sr == SR
    pieces.append(a)
    if i < len(paras) - 1:
        pieces.append(pause)
    done_s = sum(len(x) for x in pieces) / SR
    if (i + 1) % 5 == 0 or i == 0 or i == len(paras) - 1:
        rate = done_s / (time.time() - t0)
        eta = (total_chars - sum(len(q) for q in paras[: i + 1])) / max(7.2, 1) / 1 * 0
        eta = ( (len(paras) - i - 1) / (i + 1) ) * (time.time() - t0) if i else 0
        print(f"[kokoro] {i+1}/{len(paras)} paras, audio {done_s/60:.1f}min, "
              f"elapsed {(time.time()-t0)/60:.1f}min, eta {eta/60:.1f}min", flush=True)

full = np.concatenate(pieces)
sf.write(WAV, full, SR)
print(f"[kokoro] wrote {WAV}: {len(full)/SR/60:.2f} min audio, peak={np.abs(full).max():.3f}, "
      f"total synth {(time.time()-t0)/60:.1f} min", flush=True)

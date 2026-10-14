#!/usr/bin/env python3
"""Batch 2.2 端到端: KokoroZeroShotCloneEngine 真实克隆 (本地 CPU)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
PASS, FAIL = [], []


def check(name, fn):
    try:
        detail = fn()
        PASS.append(name)
        print(f"[PASS] {name}" + (f" — {detail}" if detail else ""), flush=True)
    except Exception as e:
        FAIL.append(name)
        print(f"[FAIL] {name} — {e}", flush=True)


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def t_real_clone():
    """真实克隆: football 英文片段为参考 → 克隆合成一句话."""
    from audiobook_studio.tts.zero_shot_clone import (
        create_zero_shot_clone_engine, ZeroShotCloneConfig,
    )
    ref_bytes = Path("/tmp/ref_clip_en_8s.wav").read_bytes()
    eng = create_zero_shot_clone_engine(ZeroShotCloneConfig(
        engine="kokoro_zeroshot", language="en", sample_rate=24000,
    ))
    t0 = time.time()
    res = eng.clone(
        "This voice is cloned from a local reference sample.",
        reference_audio=ref_bytes,
        language="en",
    )
    dt = time.time() - t0
    print(f"       latency={res.latency_ms}ms ({dt:.1f}s wall) sr={res.sample_rate} "
          f"blend={res.metadata.get('blend_voice')} pitch={res.metadata.get('pitch_st')}st "
          f"speed={res.metadata.get('speed')} sim={res.voice_similarity}")
    expect(len(res.audio_data) > 24000, f"音频过短: {len(res.audio_data)} bytes")
    expect(res.sample_rate == 24000, f"采样率异常: {res.sample_rate}")
    expect(res.metadata.get("blend_voice"), "blend_voice 缺失")
    # 落盘验证可播放
    import soundfile as sf
    import numpy as np
    audio = np.frombuffer(res.audio_data, dtype=np.int16).astype(np.float32) / 32767
    out = Path("/tmp/kokoro_zeroshot_e2e_out.wav")
    sf.write(str(out), audio, res.sample_rate)
    dur = len(audio) / res.sample_rate
    expect(dur > 1.0, f"时长过短: {dur:.2f}s")
    expect(float(np.sqrt((audio ** 2).mean())) > 0.01, "输出近静音")
    return f"{dur:.2f}s PCM, rms={float(np.sqrt((audio**2).mean())):.3f}"


if __name__ == "__main__":
    print("=" * 60)
    print("Batch 2.2 KokoroZeroShot 真实克隆 E2E")
    print("=" * 60)
    check("真实克隆 (英文参考)", t_real_clone)
    print("=" * 60)
    print(f"汇总: {len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)

"""Smoke test for v6 engine capabilities incorporated into system TTS layer.

Tests (no pytest — direct script per repo hard constraints):
  1. pitch_shift: 1s 440Hz sine @24kHz -> +2.0 st -> FFT peak ~494-495Hz
     -> -2.0 st back -> ~440Hz; duration drift < 50ms.
  2. parse_blend_voice: "am_onyx*0.65+am_fenrir*0.35" -> exact weights;
     "a+b+c" -> equal normalized weights.
  3. kokoro_backend import/wiring check; optional real synthesis with a blend
     voice + pitch=1.0 (skipped if model load fails/slow).
  4. engine.py _build_output_path filename sanitization for blend voice ids.

Usage:
  /Users/guwj/Documents/audiobook/.venv/bin/python scratch/v6_incorporation/smoke_p1_engine.py
  add --real  to attempt real Kokoro synthesis (loads ~325MB ONNX model)
"""
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {name} {detail}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {detail}")


def dominant_freq(audio, sr):
    spec = np.abs(np.fft.rfft(audio * np.hanning(len(audio))))
    freqs = np.fft.rfftfreq(len(audio), 1 / sr)
    return float(freqs[int(np.argmax(spec))])


def main():
    from audiobook_studio.utils.pitch_shift import shift_semitones_path, shift_semitones_array

    print("=== Test 1: pitch shift (ffmpeg band-shift) ===")
    sr = 24000
    t = np.arange(sr) / sr  # 1 second
    sine = (0.5 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)

    tmp = Path(tempfile.mkdtemp(prefix="v6_smoke_"))
    src_wav = tmp / "src.wav"
    up_wav = tmp / "up.wav"
    back_wav = tmp / "back.wav"
    sf.write(str(src_wav), sine, sr, subtype="FLOAT")

    ok = shift_semitones_path(src_wav, up_wav, 2.0, sr)
    check("shift +2.0 path returns True", ok)
    y_up, sr_up = sf.read(str(up_wav), dtype="float32")
    f_up = dominant_freq(y_up, sr_up)
    check("FFT peak after +2.0 st", 493.0 <= f_up <= 496.0, f"(got {f_up:.1f} Hz, expect ~494-495)")

    ok2 = shift_semitones_path(up_wav, back_wav, -2.0, sr)
    check("shift -2.0 path returns True", ok2)
    y_back, sr_back = sf.read(str(back_wav), dtype="float32")
    f_back = dominant_freq(y_back, sr_back)
    check("FFT peak after round-trip", 438.0 <= f_back <= 442.0, f"(got {f_back:.1f} Hz, expect ~440)")

    drift_ms = abs(len(y_up) / sr_up - len(sine) / sr) * 1000
    check("duration drift < 50ms", drift_ms < 50.0, f"(drift={drift_ms:.1f}ms)")

    # array variant round-trip
    arr_up = shift_semitones_array(sine, sr, 2.0)
    f_arr = dominant_freq(arr_up, sr)
    check("array variant +2.0 st peak", 493.0 <= f_arr <= 496.0, f"(got {f_arr:.1f} Hz)")
    arr_back = shift_semitones_array(arr_up, sr, -2.0)
    f_arr_back = dominant_freq(arr_back, sr)
    check("array variant round-trip peak", 438.0 <= f_arr_back <= 442.0, f"(got {f_arr_back:.1f} Hz)")
    drift2 = abs(len(arr_up) / sr - len(sine) / sr) * 1000
    check("array variant drift < 50ms", drift2 < 50.0, f"(drift={drift2:.1f}ms)")

    # zero-shift: copy semantics
    zero_wav = tmp / "zero.wav"
    ok0 = shift_semitones_path(src_wav, zero_wav, 0.0, sr)
    y0, _ = sf.read(str(zero_wav), dtype="float32")
    check("zero-shift copy returns True & preserves audio", ok0 and abs(dominant_freq(y0, sr) - 440.0) < 2.0)

    print("=== Test 2: blend voice parsing ===")
    from audiobook_studio.tts.kokoro_backend import parse_blend_voice, KOKORO_BLEND_VOICES, _kokoro_voice_lang

    r1 = parse_blend_voice("am_onyx*0.65+am_fenrir*0.35")
    check(
        "parse 'am_onyx*0.65+am_fenrir*0.35'",
        r1 is not None and len(r1) == 2
        and r1[0][0] == "am_onyx" and abs(r1[0][1] - 0.65) < 1e-9
        and r1[1][0] == "am_fenrir" and abs(r1[1][1] - 0.35) < 1e-9,
        f"(got {r1})",
    )

    r2 = parse_blend_voice("a+b+c")
    exp = 1.0 / 3.0
    check(
        "parse 'a+b+c' equal-normalized",
        r2 is not None and len(r2) == 3 and all(abs(w - exp) < 1e-9 for _, w in r2),
        f"(got {r2})",
    )

    r3 = parse_blend_voice("am_onyx+am_fenrir")
    check(
        "parse 'am_onyx+am_fenrir' default 0.5/0.5",
        r3 is not None and abs(r3[0][1] - 0.5) < 1e-9 and abs(r3[1][1] - 0.5) < 1e-9,
        f"(got {r3})",
    )

    r4 = parse_blend_voice("am_adam")
    check("non-blend id returns None", r4 is None, f"(got {r4})")

    r5 = parse_blend_voice("bad+")
    check("malformed blend returns None", r5 is None, f"(got {r5})")

    check("blend lang resolves via first component", _kokoro_voice_lang("am_onyx+am_fenrir") == "en")
    check("zh blend lang resolves", _kokoro_voice_lang("zf_xiaoxiao+zm_yunxi") == "zh")
    check("KOKORO_BLEND_VOICES non-empty", len(KOKORO_BLEND_VOICES) >= 1)

    print("=== Test 3: engine wiring (imports + filename sanitization) ===")
    from audiobook_studio.tts.engine import TTSProsody, TTSVoiceAnchor
    from audiobook_studio.tts.kokoro_backend import KokoroBackend
    from audiobook_studio.tts.piper_backend import PiperBackend

    check("TTSProsody.pitch exists", hasattr(TTSProsody(), "pitch"))
    anchor = TTSVoiceAnchor(voice_id="am_onyx*0.65+am_fenrir*0.35")
    check("TTSVoiceAnchor accepts blend voice_id", anchor.voice_id == "am_onyx*0.65+am_fenrir*0.35")

    be = KokoroBackend(mock_mode=True, output_dir=str(tmp / "out"))
    p = be._build_output_path("task1", "am_onyx*0.65+am_fenrir*0.35")
    check("_build_output_path sanitizes blend id", "*" not in p.name and "+" not in p.name, f"(name={p.name})")

    voices = be.get_voices()
    blend_ids = {v.voice_id for v in voices if "+" in v.voice_id}
    check("get_voices lists blend voices", len(blend_ids) >= 1, f"(blends={sorted(blend_ids)})")

    pp = PiperBackend(mock_mode=True, output_dir=str(tmp / "out"))
    check("PiperBackend imports & instantiates", pp.engine_name == "piper")

    print("=== Test 4: real Kokoro synthesis (blend voice + pitch) ===")
    if "--real" in sys.argv:
        try:
            import asyncio

            async def _real():
                kb = KokoroBackend(
                    model_path=str(ROOT / "models/kokoro-v1.0.onnx"),
                    voices_path=str(ROOT / "models/voices-v1.0.bin"),
                    output_dir=str(tmp / "out"),
                )
                await kb.initialize()
                payload_mod = None
                from audiobook_studio.tts.engine import TTSTaskPayload
                payload = TTSTaskPayload(
                    text="Hello world, this is a blend voice test.",
                    voice_anchor=TTSVoiceAnchor(voice_id="am_onyx*0.65+am_fenrir*0.35", language="en-US"),
                    prosody=TTSProsody(pitch=1.0),
                )
                out = tmp / "out" / "blend_pitch_test.wav"
                result = await kb.synthesize(payload, out)
                cached = "am_onyx*0.65+am_fenrir*0.35" in kb._blended_voices
                await kb.close()
                return result, out, cached

            result, out, cached = asyncio.run(_real())
            check("real synthesis status DONE", result.status == "DONE", f"(status={result.status}, err={result.error_message})")
            check("output file exists", Path(result.audio_path).exists())
            info = sf.info(result.audio_path)
            check("duration > 0", (result.duration_ms or 0) > 0, f"(dur={result.duration_ms}ms, sr={info.samplerate})")
            check("blend tensor cached", cached)
        except Exception as e:
            print(f"  [SKIP] real synthesis failed: {e}")
    else:
        print("  [SKIP] real synthesis (pass --real to enable)")

    print(f"\n=== SUMMARY: {PASS} passed / {FAIL} failed ===")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

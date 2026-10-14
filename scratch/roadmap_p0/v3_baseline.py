"""P1.1 对照基线: v3 champion (zm_yunxi, v1.0) 在 eval 10 段上重渲 + 数字感知口径重判。

iter27 的 eval WAV 已清理, 且 records.jsonl 里的 cer=0.165 是旧剥数字口径。
重渲给出与 v1.1-zh A/B 完全同口径的基线: 同 textnorm=both / 句切 0.6s / speed 1.0 /
无后处理, 同 judge 栈 (worker_utmos + worker_funasr 数字感知 norm)。
"""
import asyncio, json, re, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.audiobook_studio.tts.kokoro_backend import KokoroBackend
from src.audiobook_studio.tts.engine import TTSTaskPayload, TTSVoiceAnchor, TTSProsody

EVAL_IDX = [0, 7, 9, 14, 24, 34, 49, 70, 76, 85]
OUT = ROOT / "scratch/roadmap_p0/v11_ab/v3_baseline"
ENV = {**dict(__import__("os").environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
PARAS = [p.strip() for p in open(ROOT / "output/howtolivebetter_ch23/ch23_body.txt",
                                 encoding="utf-8").read().split("\n\n") if p.strip()]

def textnorm_both(t):
    t = re.sub(r"^•\s*", "", t)
    t = re.sub(r"[「」『』“”]", "", t)
    return t.strip()

async def main():
    import subprocess
    OUT.mkdir(parents=True, exist_ok=True)
    b = KokoroBackend(output_dir=str(OUT), zh_g2p="misaki")
    await b.initialize()
    t0 = time.time()
    paths, refs = [], {}
    for idx in EVAL_IDX:
        text = textnorm_both(PARAS[idx])
        sents = [s for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
        pieces, sr = [], 24000
        for si, s in enumerate(sents):
            tmp = OUT / f"p{idx:03d}_s{si}.wav"
            r = await b.synthesize(
                TTSTaskPayload(text=s, voice_anchor=TTSVoiceAnchor(voice_id="zm_yunxi", language="zh"),
                               prosody=TTSProsody(rate=1.0)), tmp)
            assert r.status == "DONE", r.error_message
            a, sr = sf.read(str(tmp))
            pieces.append(a.astype(np.float32))
            if si < len(sents) - 1:
                pieces.append(np.zeros(int(sr * 0.6), dtype=np.float32))
            tmp.unlink()
        out = OUT / f"p{idx:03d}.wav"
        sf.write(str(out), np.concatenate(pieces), sr)
        paths.append(str(out)); refs[str(out)] = text
    synth_secs = time.time() - t0
    dur = sum(sf.info(p).duration for p in paths)

    py = str(ROOT / ".venv/bin/python")
    wk = ROOT / "scratch/kokoro_iter"
    r = subprocess.run([py, str(wk / "worker_utmos.py"), *paths], capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr[-300:]
    utmos = json.loads(r.stdout.strip().splitlines()[-1])
    rf = OUT / "refs.json"
    rf.write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([py, str(wk / "worker_funasr.py"), "sensevoice", str(rf)],
                       capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, r.stderr[-300:]
    asr = json.loads(r.stdout.strip().splitlines()[-1])
    us = [utmos[p] for p in paths]; cs = [asr[p]["cer"] for p in paths]
    m = {"utmos_mean": round(float(np.mean(us)), 4), "utmos_min": round(float(np.min(us)), 4),
         "cer_mean": round(float(np.mean(cs)), 4), "cer_max": round(float(np.max(cs)), 4),
         "audio_sec": round(dur, 1), "rtf": round(synth_secs / max(dur, 0.1), 3),
         "score": round(float(np.mean(us)) - 3.0 * float(np.mean(cs)), 4)}
    rec = {"voice": "zm_yunxi(v1.0 champion)", "n_para": 10, "metrics": m,
           "synth_secs": round(synth_secs, 1)}
    with open(ROOT / "scratch/roadmap_p0/v11_ab/records_v3_baseline.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"[v3base] utmos={m['utmos_mean']:.3f} cer={m['cer_mean']:.3f} rtf={m['rtf']:.2f} "
          f"score={m['score']:.3f} ({synth_secs:.0f}s synth / {dur:.0f}s audio)")

if __name__ == "__main__":
    asyncio.run(main())

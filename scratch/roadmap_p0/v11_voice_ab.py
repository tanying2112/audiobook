"""P1.1: Kokoro v1.1-zh 100 音色包 A/B 试点筛（12 音色 × 10 eval 段）。

对齐 v3 champion 配置（iter27）: speed=1.0, textnorm=both, 句级切分 0.6s 间隙, 无后处理。
音素: misaki ZHG2P(version='1.1') — 注音+声调数字, 与 v1.1-zh 172-token vocab 对齐
     (覆盖率 99.60%, 仅 16/4022 unk)。
判分: UTMOS (worker_utmos.py) + SenseVoice 数字感知 CER (worker_funasr.py),
     与 30 轮迭代口径一致; v3 基线 eval 集 utmos=3.428 / cer(旧口径)=0.165。

用法:
  .venv/bin/python scratch/roadmap_p0/v11_voice_ab.py --smoke   # 2 音色 × 3 段
  .venv/bin/python scratch/roadmap_p0/v11_voice_ab.py            # 12 音色 × 10 段
"""
import argparse, json, re, subprocess, sys, time
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
V11 = ROOT / "models/kokoro_v11_zh"
WORK = ROOT / "scratch/roadmap_p0/v11_ab"
EVAL_IDX = [0, 7, 9, 14, 24, 34, 49, 70, 76, 85]
SMOKE_IDX = [0, 9, 49]
VOICES = ["zf_001", "zf_039", "zf_051", "zf_078", "zf_092", "zf_084", "zf_099",
           "zm_009", "zm_034", "zm_062", "zm_091", "zm_100"]
SMOKE_VOICES = ["zf_001", "zm_062"]
SAMPLE_RATE = 24000
ENV = {**dict(__import__("os").environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}

PARAS = [p.strip() for p in open(ROOT / "output/howtolivebetter_ch23/ch23_body.txt",
                                 encoding="utf-8").read().split("\n\n") if p.strip()]

def textnorm_both(t: str) -> str:
    t = re.sub(r"^•\s*", "", t)
    t = re.sub(r"[「」『』“”]", "", t)
    return t.strip()

def build_assets():
    """合并 12 个 raw float32 音色 dump → npz; tokenizer.json → vocab config。幂等。"""
    npz = V11 / "voices_v11.npz"
    if not npz.exists():
        bank = {}
        for v in VOICES:
            arr = np.fromfile(V11 / "voices" / f"{v}.bin", dtype=np.float32)
            assert arr.size == 510 * 256, f"{v}: {arr.size}"
            bank[v] = arr.reshape(510, 1, 256)
        np.savez(npz, **bank)
    cfg = V11 / "vocab_config.json"
    if not cfg.exists():
        tj = json.load(open(V11 / "tokenizer.json"))
        json.dump({"vocab": tj["model"]["vocab"]}, open(cfg, "w", encoding="utf-8"),
                  ensure_ascii=False)
    return npz, cfg

def synth_para(k, g, text, voice):
    """句级切分合成 + 0.6s 间隙, 对齐 iterate_30 的 v3 路径。"""
    sents = [s for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
    pieces = []
    for si, s in enumerate(sents):
        ph, _ = g(s)
        ph = " ".join(ph.split())
        if not ph.strip("?.!,"):
            raise RuntimeError(f"empty phonemes: {s[:30]}")
        audio, _sr = k.create(text=ph, voice=voice, speed=1.0, is_phonemes=True)
        pieces.append(audio.astype(np.float32))
        if si < len(sents) - 1:
            pieces.append(np.zeros(int(SAMPLE_RATE * 0.6), dtype=np.float32))
    return np.concatenate(pieces)

def judge(paths, refs):
    py = str(ROOT / ".venv/bin/python")
    wk = ROOT / "scratch/kokoro_iter"
    r = subprocess.run([py, str(wk / "worker_utmos.py"), *paths],
                       capture_output=True, text=True, env=ENV)
    if r.returncode != 0:
        raise RuntimeError(f"utmos rc={r.returncode}: {r.stderr[-300:]}")
    utmos = json.loads(r.stdout.strip().splitlines()[-1])
    refs_file = WORK / "refs_tmp.json"
    refs_file.write_text(json.dumps(refs, ensure_ascii=False), encoding="utf-8")
    r = subprocess.run([py, str(wk / "worker_funasr.py"), "sensevoice", str(refs_file)],
                       capture_output=True, text=True, env=ENV)
    if r.returncode != 0:
        raise RuntimeError(f"asr rc={r.returncode}: {r.stderr[-300:]}")
    asr = json.loads(r.stdout.strip().splitlines()[-1])
    us = [utmos[p] for p in paths]
    cs = [asr[p]["cer"] for p in paths]
    dur = sum(sf.info(p).duration for p in paths)
    chars = sum(len(refs[p]) for p in paths)
    return {
        "utmos_mean": round(float(np.mean(us)), 4),
        "utmos_min": round(float(np.min(us)), 4),
        "cer_mean": round(float(np.mean(cs)), 4),
        "cer_max": round(float(np.max(cs)), 4),
        "chars_per_sec": round(chars / max(dur, 0.1), 2),
        "audio_sec": round(dur, 1),
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    args = ap.parse_args()
    voices = SMOKE_VOICES if args.smoke else VOICES
    indices = SMOKE_IDX if args.smoke else EVAL_IDX
    tag = "smoke" if args.smoke else "full"
    outdir = WORK / tag
    outdir.mkdir(parents=True, exist_ok=True)

    npz, cfg = build_assets()
    from kokoro_onnx import Kokoro
    from misaki.zh import ZHG2P
    print(f"[v11] loading model onnx (fp32) ...", flush=True)
    t0 = time.time()
    k = Kokoro(str(V11 / "model.onnx"), str(npz), vocab_config=str(cfg))
    print(f"[v11] session ready {time.time()-t0:.1f}s", flush=True)
    g = ZHG2P(version="1.1")

    records_path = WORK / f"records_{tag}.jsonl"
    for v in voices:
        t0 = time.time()
        paths, refs = [], {}
        vdir = outdir / v
        vdir.mkdir(exist_ok=True)
        for idx in indices:
            text = textnorm_both(PARAS[idx])
            out = vdir / f"p{idx:03d}.wav"
            audio = synth_para(k, g, text, v)
            peak = float(np.max(np.abs(audio)))
            sf.write(str(out), audio, SAMPLE_RATE)
            paths.append(str(out))
            refs[str(out)] = text
        synth_secs = time.time() - t0
        dur = sum(sf.info(p).duration for p in paths)
        m = judge(paths, refs)
        m["rtf"] = round(synth_secs / max(dur, 0.1), 3)
        m["peak"] = round(peak, 3)
        m["score"] = round(m["utmos_mean"] - 3.0 * m["cer_mean"], 4)
        rec = {"voice": v, "n_para": len(indices), "metrics": m,
               "synth_secs": round(synth_secs, 1)}
        with open(records_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(f"[v11] {v}: utmos={m['utmos_mean']:.3f} cer={m['cer_mean']:.3f} "
              f"rtf={m['rtf']:.2f} peak={m['peak']:.2f} cps={m['chars_per_sec']} "
              f"({synth_secs:.0f}s synth)", flush=True)
    print("[v11] ALL_DONE" if not args.smoke else "[v11] SMOKE_DONE")

if __name__ == "__main__":
    main()

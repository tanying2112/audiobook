"""30 轮自主迭代：优化 audiobook 系统 Kokoro-82M ONNX 引擎的中文合成音质。

引擎：src.audiobook_studio.tts.kokoro_backend.KokoroBackend（系统引擎本体，
含本轮新增的 opt-in misaki zh G2P 与韵律参数）。
评分（子进程隔离，规避 torch 2.2.2 段错误组合）：
  - UTMOS (tarepan/SpeechMOS, 权重已缓存) — 感知质量 MOS 1-5
  - CER   (faster-whisper base zh + zhconv 简繁归一 + 字级 Levenshtein) — 可懂度/发音
  - F0    (librosa yin) — 声调丰富度/停顿比
综合分 = utmos_mean − 3.0 × cer_mean
迭代计划（自适应，后一阶段基于当前最优）：
  A 1-8   g2p{espeak,misaki} × voice{zm_yunjian,yunxi,yunxia,yunyang} @1.25
  B 9-13  最优A 的语速 {1.0,1.1,1.15,1.2,1.3}
  C 14-17 句级切分合成 × 句间停顿 {0.2,0.3,0.45,0.6}
  D 18-19 文本规范 {去 bullet 符号, 去「」引号}
  E 20-23 后处理链 {limiter, loudnorm, loudnorm+limiter, highpass+limiter}
  G 24-30 次优/三优音色、文本规范组合、top-2 配置在留出集(10 段新文本)上验证
记录：scratch/kokoro_iter/records.jsonl（每轮一行）
"""
import asyncio, json, re, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().resolve().parents[2]
sys.path.insert(0, str(ROOT))
WORK = ROOT / "scratch" / "kokoro_iter"
RECORDS = WORK / "records.jsonl"

EVAL_IDX = [0, 7, 9, 14, 24, 34, 49, 70, 76, 85]
HOLDOUT_IDX = [1, 10, 15, 20, 30, 50, 75, 90, 95, 96]

from src.audiobook_studio.tts.kokoro_backend import KokoroBackend
from src.audiobook_studio.tts.engine import TTSTaskPayload, TTSVoiceAnchor, TTSProsody
import numpy as np
import soundfile as sf

PARAS = [p.strip() for p in open(ROOT / "output/howtolivebetter_ch23/ch23_body.txt", encoding="utf-8").read().split("\n\n") if p.strip()]

def apply_textnorm(text: str, cfg: dict) -> str:
    if "nobullet" in cfg.get("textnorm", ""):
        text = re.sub(r"^•\s*", "", text)
    if "noquote" in cfg.get("textnorm", ""):
        text = re.sub(r"[「」『』“”]", "", text)
    return text.strip()

def post_chain(cfg: dict):
    p = cfg.get("post", "none")
    return {
        "none": None,
        "limiter": "alimiter=limit=0.985:attack=5:release=50:level=disabled",
        "loudnorm": "loudnorm=I=-16:TP=-1.5:LRA=11",
        "loudnorm_lim": "loudnorm=I=-16:TP=-1.5:LRA=11,alimiter=limit=0.985:attack=5:release=50:level=disabled",
        "hp_lim": "highpass=f=80,alimiter=limit=0.985:attack=5:release=50:level=disabled",
    }[p]

async def synth_eval(cfg: dict, indices, outdir: Path):
    """用系统引擎合成评测段 → 每段一个 WAV。返回 (paths, refs)。"""
    outdir.mkdir(parents=True, exist_ok=True)
    b = KokoroBackend(output_dir=str(outdir), zh_g2p=cfg["g2p"])
    await b.initialize()
    paths, refs = [], {}
    for idx in indices:
        text = apply_textnorm(PARAS[idx], cfg)
        ref = text
        out = outdir / f"p{idx:03d}.wav"
        if cfg.get("split") == "sent":
            sents = [s for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
            pieces, sr = [], 24000
            for si, s in enumerate(sents):
                tmp = outdir / f"p{idx:03d}_s{si}.wav"
                r = await b.synthesize(
                    TTSTaskPayload(text=s, voice_anchor=TTSVoiceAnchor(voice_id=cfg["voice"], language="zh"),
                                   prosody=TTSProsody(rate=cfg["speed"])), tmp)
                if r.status != "DONE":
                    raise RuntimeError(f"sent synth failed p{idx} s{si}: {r.error_message}")
                a, sr = sf.read(str(tmp))
                pieces.append(a.astype(np.float32))
                if si < len(sents) - 1:
                    pieces.append(np.zeros(int(sr * cfg["sent_gap"]), dtype=np.float32))
                tmp.unlink()
            audio = np.concatenate(pieces)
            sf.write(str(out), audio, sr)
        else:
            r = await b.synthesize(
                TTSTaskPayload(text=text, voice_anchor=TTSVoiceAnchor(voice_id=cfg["voice"], language="zh"),
                               prosody=TTSProsody(rate=cfg["speed"])), out)
            if r.status != "DONE":
                raise RuntimeError(f"para synth failed p{idx}: {r.error_message}")
        # 后处理链
        chain = post_chain(cfg)
        if chain:
            post = outdir / f"p{idx:03d}_post.wav"
            rc = subprocess.run(["ffmpeg", "-y", "-i", str(out), "-af", chain, "-ar", "24000", "-ac", "1",
                                 str(post)], capture_output=True)
            if rc.returncode != 0:
                raise RuntimeError(f"post chain failed: {rc.stderr.decode()[:200]}")
            out.unlink()
            out = post
        paths.append(str(out))
        refs[str(out)] = ref
    return paths, refs

def score(paths, refs):
    """三个打分子进程，聚合指标。"""
    env = {**dict(__import__("os").environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
    py = str(ROOT / ".venv/bin/python")
    # UTMOS
    r = subprocess.run([py, str(WORK / "worker_utmos.py"), *paths], capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"utmos worker rc={r.returncode}: {r.stderr[-300:]}")
    utmos = json.loads(r.stdout.strip().splitlines()[-1])
    # ASR CER
    r = subprocess.run([py, str(WORK / "worker_asr.py"), json.dumps(refs, ensure_ascii=False)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"asr worker rc={r.returncode}: {r.stderr[-300:]}")
    asr = json.loads(r.stdout.strip().splitlines()[-1])
    # F0
    r = subprocess.run([py, str(WORK / "worker_f0.py"), json.dumps({p: None for p in paths})],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise RuntimeError(f"f0 worker rc={r.returncode}: {r.stderr[-300:]}")
    f0 = json.loads(r.stdout.strip().splitlines()[-1])

    us = [utmos[p] for p in paths]
    cs = [asr[p]["cer"] for p in paths]
    fs = [f0[p] for p in paths]
    total_audio = sum(sf.info(p).duration for p in paths)
    total_chars = sum(len(refs[p]) for p in paths)
    m = {
        "utmos_mean": round(float(np.mean(us)), 4),
        "utmos_min": round(float(np.min(us)), 4),
        "cer_mean": round(float(np.mean(cs)), 4),
        "cer_max": round(float(np.max(cs)), 4),
        "f0_cv_mean": round(float(np.mean([x["f0_cv"] for x in fs])), 4),
        "pause_ratio_mean": round(float(np.mean([x["pause_ratio"] for x in fs])), 4),
        "chars_per_sec": round(total_chars / max(total_audio, 0.1), 2),
        "audio_sec": round(total_audio, 1),
    }
    m["score"] = round(m["utmos_mean"] - 3.0 * m["cer_mean"], 4)
    return m

def log(msg):
    print(f"[iter] {msg}", flush=True)

def save_record(rec):
    with open(RECORDS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

def load_records():
    if not RECORDS.exists():
        return []
    return [json.loads(l) for l in RECORDS.read_text(encoding="utf-8").splitlines() if l.strip()]

def best_config(records, phase_prefix=None, exclude_key=None):
    """当前最优配置（按 score），可限定阶段前缀。"""
    cands = [r for r in records if r.get("metrics")]
    if phase_prefix:
        cands = [r for r in cands if r["phase"] in set(phase_prefix)]
    cands = [r for r in cands if 4.5 <= r["metrics"]["chars_per_sec"] <= 11.5]
    if not cands:
        raise RuntimeError("no qualifying records")
    cands.sort(key=lambda r: -r["metrics"]["score"])
    return cands[0]

async def run_iter(n, phase, cfg, indices, note=""):
    t0 = time.time()
    outdir = WORK / f"iter{n:02d}"
    paths, refs = await synth_eval(cfg, indices, outdir)
    m = score(paths, refs)
    rec = {"iter": n, "phase": phase, "config": cfg, "metrics": m, "note": note,
           "secs": round(time.time() - t0, 1)}
    save_record(rec)
    log(f"{n:02d}/30 [{phase}] score={m['score']:.3f} utmos={m['utmos_mean']:.3f} cer={m['cer_mean']:.3f} "
        f"f0cv={m['f0_cv_mean']:.3f} cps={m['chars_per_sec']} cfg={note} ({rec['secs']}s)")
    return rec

async def main():
    records = load_records()
    done = {r["iter"] for r in records}
    log(f"resuming: {len(done)} records exist" if done else "starting fresh 30 iterations")

    # ── Phase A: g2p × voice @1.25 ──
    voices = ["zm_yunjian", "zm_yunxi", "zm_yunxia", "zm_yunyang"]
    n = 0
    for g2p in ["espeak", "misaki"]:
        for v in voices:
            n += 1
            if n in done: continue
            await run_iter(n, "A", {"g2p": g2p, "voice": v, "speed": 1.25, "textnorm": "raw", "post": "none"},
                           EVAL_IDX, f"{g2p}/{v}@1.25")
    records = load_records()
    bestA = best_config(records, "A")

    # ── Phase B: speed sweep on best A ──
    for sp in [1.0, 1.1, 1.15, 1.2, 1.3]:
        n += 1
        if n in done: continue
        cfg = {**bestA["config"], "speed": sp}
        await run_iter(n, "B", cfg, EVAL_IDX, f"speed={sp} on {bestA['note']}")
    records = load_records()
    bestB = best_config(records, "AB")

    # ── Phase C: sentence-split × gap ──
    for gap in [0.2, 0.3, 0.45, 0.6]:
        n += 1
        if n in done: continue
        cfg = {**bestB["config"], "split": "sent", "sent_gap": gap}
        await run_iter(n, "C", cfg, EVAL_IDX, f"sent-split gap={gap}")
    records = load_records()
    bestC = best_config(records, "ABC")

    # ── Phase D: textnorm ──
    for tn in ["nobullet", "noquote"]:
        n += 1
        if n in done: continue
        cfg = {**bestC["config"], "textnorm": tn}
        await run_iter(n, "D", cfg, EVAL_IDX, f"textnorm={tn}")
    records = load_records()
    bestD = best_config(records, "ABCD")

    # ── Phase E: post chains on best-so-far ──
    for post in ["limiter", "loudnorm", "loudnorm_lim", "hp_lim"]:
        n += 1
        if n in done: continue
        cfg = {**bestD["config"], "post": post}
        await run_iter(n, "E", cfg, EVAL_IDX, f"post={post}")
    records = load_records()

    # ── Phase G: exploration + holdout validation ──
    ranked = sorted([r for r in records if r.get("metrics") and 4.5 <= r["metrics"]["chars_per_sec"] <= 11.5],
                    key=lambda r: -r["metrics"]["score"])
    voice_rank = {}
    for r in ranked:
        v = r["config"]["voice"]
        if v not in voice_rank:
            voice_rank[v] = r
    others = [r for v, r in list(voice_rank.items())[1:4]]  # 次优/三优/四优音色（各自最好记录）
    for r in others:
        n += 1
        if n in done: continue
        cfg = {**bestD["config"], "voice": r["config"]["voice"]}
        await run_iter(n, "G", cfg, EVAL_IDX, f"alt-voice={r['config']['voice']}")
    # 文本规范组合
    n += 1
    if n not in done:
        cfg = {**bestD["config"], "textnorm": "nobullet,noquote"}
        await run_iter(n, "G", cfg, EVAL_IDX, "textnorm=both")
    records = load_records()
    top2 = sorted([r for r in records if r.get("metrics")], key=lambda r: -r["metrics"]["score"])[:2]
    # top-2 留出集验证（新 10 段）
    for r in top2:
        n += 1
        if n in done: continue
        await run_iter(n, "H", {**r["config"]}, HOLDOUT_IDX, f"holdout of {r['note']}")
    # 最终确认：全 30 轮里最优配置 + 最优后处理组合在留出集再验一次
    best_all = best_config(records)
    n += 1
    if n not in done:
        await run_iter(n, "H", {**best_all["config"]}, HOLDOUT_IDX, f"final confirm {best_all['note']}")

    records = load_records()
    ranked = sorted([r for r in records if r.get("metrics")], key=lambda r: -r["metrics"]["score"])
    log("=== TOP 5 ===")
    for r in ranked[:5]:
        log(f"  score={r['metrics']['score']:.3f} utmos={r['metrics']['utmos_mean']:.3f} "
            f"cer={r['metrics']['cer_mean']:.3f} [{r['phase']}] {r['config']}")
    log("DONE_ALL_30")

if __name__ == "__main__":
    asyncio.run(main())

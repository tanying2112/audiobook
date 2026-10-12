"""终版渲染：用马拉松最优配置跑完整章 97 段 → 48kbps MP3。

用法：.venv/bin/python scratch/kokoro_iter/render_final.py [--verify]
- 从 records.jsonl 选出 A-G 阶段 score 最高的配置（cps 门禁 4.5-11.5）
- 系统引擎 KokoroBackend 全章合成（同 synth_eval 代码路径）
- 段间停顿 0.45s；句级配置沿用其 sent_gap；胜出后处理链
- MP3 48kbps（用户约束不变）→ 23_学什么技能划算_kokoro_v3.mp3
- --verify: 全章 UTMOS + CER 打分（对 v2 的对照数字）
"""
import asyncio, json, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scratch.kokoro_iter.iterate_30 import (ROOT, WORK, PARAS, apply_textnorm, post_chain,
                                            load_records)
from src.audiobook_studio.tts.kokoro_backend import KokoroBackend
from src.audiobook_studio.tts.engine import TTSTaskPayload, TTSVoiceAnchor, TTSProsody
import numpy as np
import soundfile as sf

OUT_DIR = ROOT / "output/howtolivebetter_ch23"
FINAL_MP3 = OUT_DIR / "23_学什么技能划算_kokoro_v3.mp3"
VERIFY = "--verify" in sys.argv


def pick_winner():
    recs = load_records()
    cands = [r for r in recs if r.get("metrics") and not r["phase"].startswith("H")
             and 4.5 <= r["metrics"]["chars_per_sec"] <= 11.5]
    cands.sort(key=lambda r: -r["metrics"]["score"])
    print(f"[render] winner: iter{cands[0]['iter']:02d} score={cands[0]['metrics']['score']} "
          f"cfg={cands[0]['config']}")
    # top-5 一并列出供报告
    for r in cands[:5]:
        m = r["metrics"]
        print(f"[render]   top: iter{r['iter']:02d} [{r['phase']}] score={m['score']} "
              f"utmos={m['utmos_mean']} cer={m['cer_mean']} cps={m['chars_per_sec']}")
    # 留出集验证情况
    for r in recs:
        if r["phase"].startswith("H") and r.get("metrics"):
            print(f"[render]   holdout: iter{r['iter']:02d} score={r['metrics']['score']} cfg={r['config']}")
    return cands[0]["config"]


async def render(cfg: dict):
    t0 = time.time()
    tmp = WORK / "final_wav"
    tmp.mkdir(parents=True, exist_ok=True)
    b = KokoroBackend(output_dir=str(tmp), zh_g2p=cfg["g2p"])
    await b.initialize()
    pieces, sr = [], 24000
    gap = int(24000 * 0.45)
    n = len(PARAS)
    for i, para in enumerate(PARAS):
        text = apply_textnorm(para, cfg)
        out = tmp / f"p{i:03d}.wav"
        if cfg.get("split") == "sent":
            import re
            sents = [s for s in re.split(r"(?<=[。！？；])", text) if s.strip()]
            sp, sr = [], 24000
            for si, s in enumerate(sents):
                tp = tmp / f"p{i:03d}_s{si}.wav"
                r = await b.synthesize(
                    TTSTaskPayload(text=s, voice_anchor=TTSVoiceAnchor(voice_id=cfg["voice"], language="zh"),
                                   prosody=TTSProsody(rate=cfg["speed"])), tp)
                if r.status != "DONE":
                    raise RuntimeError(f"sent synth failed p{i} s{si}: {r.error_message}")
                a, sr = sf.read(str(tp))
                sp.append(a.astype(np.float32))
                if si < len(sents) - 1:
                    sp.append(np.zeros(int(sr * cfg["sent_gap"]), dtype=np.float32))
                tp.unlink()
            sf.write(str(out), np.concatenate(sp), sr)
        else:
            r = await b.synthesize(
                TTSTaskPayload(text=text, voice_anchor=TTSVoiceAnchor(voice_id=cfg["voice"], language="zh"),
                               prosody=TTSProsody(rate=cfg["speed"])), out)
            if r.status != "DONE":
                raise RuntimeError(f"para synth failed p{i}: {r.error_message}")
        a, sr = sf.read(str(out))
        pieces.append(a.astype(np.float32))
        if i < n - 1:
            pieces.append(np.zeros(gap, dtype=np.float32))
        out.unlink()
        if (i + 1) % 10 == 0 or i == n - 1:
            audio_min = sum(len(p) for p in pieces) / sr / 60
            el = (time.time() - t0) / 60
            eta = el / (i + 1) * (n - i - 1)
            print(f"[render] {i+1}/{n} paras, audio {audio_min:.1f}min, elapsed {el:.1f}min, eta {eta:.1f}min", flush=True)
    raw = tmp / "final_raw.wav"
    sf.write(str(raw), np.concatenate(pieces), sr)
    print(f"[render] raw wav: {sum(len(p) for p in pieces)/sr/60:.2f} min")

    # 后处理链
    src_wav = raw
    chain = post_chain(cfg)
    if chain:
        post = tmp / "final_post.wav"
        rc = subprocess.run(["ffmpeg", "-y", "-i", str(raw), "-af", chain, "-ar", "24000",
                             "-ac", "1", str(post)], capture_output=True)
        if rc.returncode != 0:
            raise RuntimeError(f"post chain failed: {rc.stderr.decode()[:300]}")
        src_wav = post
        print(f"[render] post chain applied: {chain}")

    # 48kbps MP3（用户约束）
    rc = subprocess.run(["ffmpeg", "-y", "-i", str(src_wav), "-b:a", "48k", "-ar", "24000",
                         "-ac", "1", str(FINAL_MP3)], capture_output=True)
    if rc.returncode != 0:
        raise RuntimeError(f"mp3 encode failed: {rc.stderr.decode()[:300]}")
    print(f"[render] wrote {FINAL_MP3.name}")
    return src_wav


def verify(src_wav: Path):
    """全章 UTMOS + CER（对照 v2 的 0.63/3.3）。"""
    import os
    env = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}
    py = str(ROOT / ".venv/bin/python")
    cfg = None
    recs = load_records()
    cands = [r for r in recs if r.get("metrics") and not r["phase"].startswith("H")
             and 4.5 <= r["metrics"]["chars_per_sec"] <= 11.5]
    cands.sort(key=lambda r: -r["metrics"]["score"])
    cfg = cands[0]["config"]
    full_ref = "".join(apply_textnorm(p, cfg) for p in PARAS)
    r = subprocess.run([py, str(WORK / "worker_utmos.py"), str(src_wav)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(f"[verify] utmos worker failed: {r.stderr[-200:]}"); return
    utmos = json.loads(r.stdout.strip().splitlines()[-1])[str(src_wav)]
    r = subprocess.run([py, str(WORK / "worker_asr.py"),
                        json.dumps({str(src_wav): full_ref}, ensure_ascii=False)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print(f"[verify] asr worker failed: {r.stderr[-200:]}"); return
    asr = json.loads(r.stdout.strip().splitlines()[-1])[str(src_wav)]
    print(f"[verify] FULL CHAPTER: utmos={utmos:.3f} cer={asr['cer']:.4f} "
          f"score={utmos - 3*asr['cer']:.3f}")


if __name__ == "__main__":
    cfg = pick_winner()
    src_wav = asyncio.run(render(cfg))
    pr = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                         "format=duration,bit_rate", "-of", "json", str(FINAL_MP3)],
                        capture_output=True, text=True)
    info = json.loads(pr.stdout)["format"]
    print(f"[render] ffprobe: duration={float(info['duration'])/60:.2f}min bitrate={info['bit_rate']}bps")
    if VERIFY:
        verify(src_wav)
    print("[render] DONE_FINAL")

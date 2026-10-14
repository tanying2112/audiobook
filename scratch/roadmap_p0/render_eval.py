"""重渲染冠军配置 10 段评测集（champion = iter27），记录 RTF 基线。"""
import asyncio, json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scratch" / "kokoro_iter"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import iterate_30 as it

CHAMPION = {"g2p": "misaki", "voice": "zm_yunxi", "speed": 1.0,
            "textnorm": "nobullet,noquote", "post": "none", "split": "sent", "sent_gap": 0.6}

async def main():
    outdir = Path(__file__).parent / "eval_base"
    t0 = time.time()
    paths, refs = await it.synth_eval(CHAMPION, it.EVAL_IDX, outdir)
    wall = time.time() - t0
    import soundfile as sf
    audio = sum(sf.info(p).duration for p in paths)
    meta = {"paths": paths, "refs": refs, "wall_s": round(wall, 1),
            "audio_s": round(audio, 1), "rtf_render": round(wall / audio, 3)}
    json.dump(meta, open(Path(__file__).parent / "eval_render.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("RENDER_DONE wall", round(wall, 1), "audio", round(audio, 1), "rtf", round(wall / audio, 3), flush=True)

asyncio.run(main())

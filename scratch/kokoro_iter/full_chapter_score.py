"""全章打分（分块版）：UTMOS 30s 分块均值 + whisper 全章 CER。
对 v3(胜出配置) 与 v2(旧 espeak 版) 同口径对照。"""
import json, subprocess, sys, os
from pathlib import Path

ROOT = Path("/Users/guwj/Documents/audiobook")
sys.path.insert(0, str(ROOT))
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
from scratch.kokoro_iter.iterate_30 import PARAS  # noqa: E402
import re

def full_ref() -> str:
    t = "".join(PARAS)
    t = re.sub(r"^•\s*", "", t, flags=re.M)
    t = re.sub(r"[「」『』“”]", "", t)
    return t

def chunk(src: Path, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    # 30s 无重叠分块（wav 24k 单声道，供 UTMOS）
    subprocess.run(["ffmpeg", "-y", "-i", str(src), "-f", "segment",
                    "-segment_time", "30", "-ar", "24000", "-ac", "1",
                    str(outdir / "c%03d.wav")], capture_output=True, check=True)
    return sorted(outdir.glob("c*.wav"))

def utmos_mean(chunks):
    r = subprocess.run([".venv/bin/python", "scratch/kokoro_iter/worker_utmos.py",
                        *[str(c) for c in chunks]], capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-200:]
    d = json.loads(r.stdout.strip().splitlines()[-1])
    vals = list(d.values())
    return round(sum(vals) / len(vals), 4), None

def chapter_cer(path: Path, ref: str):
    r = subprocess.run([".venv/bin/python", "scratch/kokoro_iter/worker_asr.py",
                        json.dumps({str(path): ref}, ensure_ascii=False)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None, r.stderr[-200:]
    d = json.loads(r.stdout.strip().splitlines()[-1])
    return round(d[str(path)]["cer"], 4), None

if __name__ == "__main__":
    which = sys.argv[1]  # v3 | v2
    ref = full_ref()
    if which == "v3":
        src = ROOT / "scratch/kokoro_iter/final_wav/final_raw.wav"
    else:
        src = ROOT / "output/howtolivebetter_ch23/23_学什么技能划算_kokoro.mp3"
    chunks = chunk(src, ROOT / f"scratch/kokoro_iter/{which}_chunks")
    print(f"[{which}] {len(chunks)} chunks of 30s", flush=True)
    u, err = utmos_mean(chunks)
    print(f"[{which}] utmos_chunk_mean={u}" + (f" (ERR {err})" if err else ""), flush=True)
    c, err2 = chapter_cer(src, ref)
    print(f"[{which}] full_chapter_cer={c}" + (f" (ERR {err2})" if err2 else ""), flush=True)
    if u is not None and c is not None:
        print(f"[{which}] SCORE utmos={u} cer={c} composite={round(u - 3*c, 4)}", flush=True)
    print(f"[{which}] DONE_SCORE", flush=True)

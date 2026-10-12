"""《高性价比人生指南》第 23 节 Edge-TTS 合成：分段合成→静音间隔→拼接。

沿用 convert_daodejing.py 的既定链路（zh-CN-YunxiNeural、60s 超时、3 次重试、
失败段落跳过），改进：并发 4 提速 135 段；段间插 0.45s 静音（ffmpeg 生成
24kHz mono 48k，与 edge-tts 输出同参数，字节拼接即可）。"""
import asyncio
import os
import re
import subprocess

import edge_tts

VOICE = "zh-CN-YunxiNeural"
IN_TXT = "output/howtolivebetter_ch23/ch23_clean.txt"
OUT_DIR = "output/howtolivebetter_ch23/paras"
FINAL = "output/howtolivebetter_ch23/23_学什么技能划算.mp3"
MAX_RETRY = 3
CONCURRENCY = 4

os.makedirs(OUT_DIR, exist_ok=True)

# 0.45s 静音（与 edge-tts 输出同参数：24kHz mono 48kbps mp3）
SILENCE = "output/howtolivebetter_ch23/gap.mp3"
subprocess.run(
    ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
     "-i", "anullsrc=r=24000:cl=mono", "-t", "0.45",
     "-ar", "24000", "-ac", "1", "-b:a", "48k", SILENCE],
    check=True,
)
gap_bytes = open(SILENCE, "rb").read()
print(f"silence gap: {len(gap_bytes)} bytes")

paras = [p.strip() for p in re.split(r"\n\s*\n", open(IN_TXT, encoding="utf-8").read()) if p.strip()]
paras = [p for p in paras if len(re.findall(r"[一-鿿A-Za-z]", p)) >= 4]
print(f"{len(paras)} paragraphs to synthesize")


async def synth_one(i: int, text: str) -> str | None:
    out = os.path.join(OUT_DIR, f"para_{i:03d}.mp3")
    if os.path.exists(out) and os.path.getsize(out) > 500:
        return out
    for attempt in range(MAX_RETRY):
        try:
            await asyncio.wait_for(edge_tts.Communicate(text, VOICE).save(out), timeout=90)
            if os.path.exists(out) and os.path.getsize(out) > 500:
                return out
        except Exception as e:
            if attempt == MAX_RETRY - 1:
                print(f"  [{i}] SKIP ({e.__class__.__name__}: {str(e)[:80]})", flush=True)
            await asyncio.sleep(2.0)
    return None


async def main():
    sem = asyncio.Semaphore(CONCURRENCY)
    results: list[str | None] = [None] * len(paras)
    done = 0

    async def worker(i: int):
        nonlocal done
        async with sem:
            results[i] = await synth_one(i, paras[i])
        done += 1
        if done % 20 == 0:
            print(f"  progress {done}/{len(paras)}", flush=True)

    await asyncio.gather(*(worker(i) for i in range(len(paras))))

    ok = [r for r in results if r]
    skipped = len(paras) - len(ok)
    print(f"synthesized: {len(ok)}, skipped: {skipped}")

    with open(FINAL, "wb") as out:
        first = True
        for r in results:
            if r is None:
                continue
            if not first:
                out.write(gap_bytes)
            out.write(open(r, "rb").read())
            first = False

    size = os.path.getsize(FINAL)
    print(f"FINAL: {FINAL} ({size/1024/1024:.1f} MB)")
    return len(ok) > 0


if __name__ == "__main__":
    import sys
    sys.exit(0 if asyncio.run(main()) else 1)

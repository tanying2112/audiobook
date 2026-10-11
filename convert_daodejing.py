"""Convert Daodejing chapters 1-2 to audio via Edge TTS (zh-CN).

Robust version: filters degenerate OCR fragments, retries failures,
skips segments that still fail, and concatenates per-paragraph MP3s.
"""

import asyncio
import os
import re
import sys

import edge_tts

VOICE = "zh-CN-YunxiNeural"
IN_DIR = "output/daodejing_chapters"
MAX_RETRY = 3


def clean_para(p: str) -> str:
    """Drop OCR noise that TTS can't speak; return '' if nothing speakable."""
    # Remove page-header/footer lines like 《老子》正文解读《道经》 | 075
    lines = []
    for ln in p.splitlines():
        ln = ln.strip()
        if re.search(r"\|\s*\d{2,4}\s*$", ln):
            continue
        if re.match(r"^\d{2,4}\s*\|", ln):
            continue
        lines.append(ln)
    text = " ".join(lines).strip()
    # Need at least a few CJK chars to be speakable
    if len(re.findall(r"[一-鿿]", text)) < 2:
        return ""
    return text


async def synth_one(text: str, out: str) -> bool:
    for attempt in range(MAX_RETRY):
        try:
            # edge_tts streams can hang silently without a timeout
            await asyncio.wait_for(edge_tts.Communicate(text, VOICE).save(out), timeout=60)
            return os.path.exists(out) and os.path.getsize(out) > 500
        except Exception as e:
            if attempt == MAX_RETRY - 1:
                print(f"    SKIP (failed {MAX_RETRY}x): {e.__class__.__name__}", flush=True)
            await asyncio.sleep(1.5)
    return False


async def convert(chapter: str):
    txt_path = os.path.join(IN_DIR, f"chapter_{chapter}.txt")
    mp3_path = os.path.join(IN_DIR, f"chapter_{chapter}.mp3")
    text = open(txt_path, encoding="utf-8").read()
    paras = [clean_para(p) for p in re.split(r"\n\s*\n", text)]
    paras = [p for p in paras if p]
    print(f"Chapter {chapter}: {len(paras)} speakable paragraphs", flush=True)

    tmp_files = []
    ok, skipped = 0, 0
    for i, para in enumerate(paras):
        tmp = f"/tmp/ddj_{chapter}_{i:03d}.mp3"
        if await synth_one(para, tmp):
            tmp_files.append(tmp)
            ok += 1
        else:
            skipped += 1
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(paras)} done (skipped {skipped})", flush=True)

    with open(mp3_path, "wb") as out:
        for tmp in tmp_files:
            out.write(open(tmp, "rb").read())
            os.remove(tmp)
    size = os.path.getsize(mp3_path)
    print(f"  -> {mp3_path} ({size/1024:.0f} KB, {ok} ok / {skipped} skipped)", flush=True)


async def main():
    for ch in ("01", "02", "03"):
        if os.path.exists(os.path.join(IN_DIR, f"chapter_{ch}.mp3")):
            print(f"Chapter {ch}: already done, skipping")
            continue
        await convert(ch)
    print("ALL DONE")


if __name__ == "__main__":
    asyncio.run(main())

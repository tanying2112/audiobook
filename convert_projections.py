#!/usr/bin/env python3
"""Convert 《照亮破碎之心》(Karl Deisseroth, "Projections") epub to an audiobook.

Stages (run in order, each resumable on its own):
  extract : parse epub xhtml -> cleaned per-chapter text under output/projections_zh/text/
  tts     : text -> per-chapter MP3 under output/projections_zh/audio/ (chunk-cached,
            safe to re-run: finished chunks are skipped, failures retried)
  merge   : chapter MP3s -> one full-book MP3

The epub is untrusted downloaded data: it lives in /tmp/epub_work, this script
never executes anything from it, and only text nodes are read.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import unicodedata
from pathlib import Path

from lxml import etree

EPUB_DIR = Path("/tmp/epub_work")
OUT_DIR = Path("output/projections_zh")
TEXT_DIR = OUT_DIR / "text"
AUDIO_DIR = OUT_DIR / "audio"
CACHE_DIR = OUT_DIR / "cache"
MANIFEST = OUT_DIR / "manifest.txt"

VOICE = "zh-CN-YunxiNeural"
MAX_RETRY = 3
TIMEOUT_S = 120
CONCURRENCY = 4
MAX_CHUNK = 500  # chars per TTS request

BOOK_TITLE = "照亮破碎之心"
BOOK_AUTHOR = "卡尔·戴瑟罗思"

# front matter that should not become audio
SKIP_FILES = {"titlepage.xhtml", "cover.xhtml", "Copyright.xhtml"}
FALLBACK_TITLE = {"chapter0.xhtml": "献词", "chapter0_0001.xhtml": "题词"}

XH = "http://www.w3.org/1999/xhtml"
OPF = "http://www.idpf.org/2007/opf"


def q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


# ---------------------------------------------------------------- extract

def spine_files() -> list[str]:
    """Reading order from content.opf spine, minus skipped front matter."""
    opf = etree.parse(str(EPUB_DIR / "content.opf"))
    href = {it.get("id"): Path(it.get("href")).name for it in opf.iter(q(OPF, "item"))}
    return [
        href[ref.get("idref")]
        for ref in opf.iter(q(OPF, "itemref"))
        if href[ref.get("idref")] not in SKIP_FILES
    ]


def clean_text(s: str) -> str:
    """Drop control/invisible chars, collapse runs of horizontal whitespace."""
    s = "".join(ch for ch in s if unicodedata.category(ch)[0] != "C")
    s = re.sub(r"[ \t 　]+", " ", s)
    return s.strip()


def extract_chapter(path: Path) -> tuple[str, list[str]]:
    """Return (title, paragraphs) for one chapter file."""
    root = etree.parse(str(path)).getroot()
    # remove footnotes (aside) and in-paragraph footnote refs (sup)
    for bad in list(root.iter(q(XH, "aside"), q(XH, "sup"))):
        parent = bad.getparent()
        if parent is not None:
            parent.remove(bad)
    titles = [
        t
        for h1 in root.iter(q(XH, "h1"))
        if (t := re.sub(r"\s+", "", "".join(h1.itertext())))
    ]
    title = " ".join(titles) or FALLBACK_TITLE.get(path.name, path.stem)
    paras = [t for p in root.iter(q(XH, "p")) if (t := clean_text("".join(p.itertext())))]
    return title, paras


def safe_name(s: str) -> str:
    return re.sub(r"[/\\:*?\"<>|\s]+", "_", s)[:80]


def do_extract() -> None:
    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    bases = [f"00_{safe_name(f'{BOOK_TITLE}_{BOOK_AUTHOR}')}"]
    # spoken opening: book title + author
    (TEXT_DIR / f"{bases[0]}.txt").write_text(
        f"{BOOK_TITLE}。作者,{BOOK_AUTHOR}。", encoding="utf-8"
    )
    print(f"[00] {BOOK_TITLE}·{BOOK_AUTHOR} (开场播报)")
    for i, name in enumerate(spine_files()):
        title, paras = extract_chapter(EPUB_DIR / "EPUB/xhtml" / name)
        base = f"{i + 1:02d}_{safe_name(title)}"
        (TEXT_DIR / f"{base}.txt").write_text(
            title + "\n\n" + "\n\n".join(paras), encoding="utf-8"
        )
        n_chars = sum(len(p) for p in paras)
        print(f"[{i + 1:02d}] {title}  ({len(paras)} 段, {n_chars} 字)")
        bases.append(base)
    MANIFEST.write_text("\n".join(bases), encoding="utf-8")
    total = sum(
        len(p.read_text(encoding="utf-8")) for p in TEXT_DIR.glob("*.txt")
    )
    print(f"\n提取完成: {len(bases)} 个音频单元, 共约 {total} 字 -> {TEXT_DIR}/")


# ---------------------------------------------------------------- tts

def split_chunks(text: str, max_len: int = MAX_CHUNK) -> list[str]:
    """Split long paragraph into TTS-sized chunks at sentence enders."""
    if len(text) <= max_len:
        return [text]
    sentences = re.split(r"(?<=[。!?!?;…])", text)
    chunks: list[str] = []
    buf = ""
    for s in sentences:
        if not s:
            continue
        if len(buf) + len(s) <= max_len:
            buf += s
            continue
        if buf:
            chunks.append(buf)
        while len(s) > max_len:  # a single sentence with no enders
            chunks.append(s[:max_len])
            s = s[max_len:]
        buf = s
    if buf:
        chunks.append(buf)
    return chunks


async def synth_one(text: str, out: Path, sem: asyncio.Semaphore) -> bool:
    import edge_tts

    async with sem:
        for attempt in range(MAX_RETRY):
            try:
                await asyncio.wait_for(
                    edge_tts.Communicate(text, VOICE).save(str(out)),
                    timeout=TIMEOUT_S,
                )
                return out.exists() and out.stat().st_size > 500
            except Exception:
                await asyncio.sleep(1.5 * (attempt + 1))
        return False


def concat(files: list[Path], out: Path) -> None:
    with open(out, "wb") as fo:
        for f in files:
            fo.write(f.read_bytes())


async def synth_chapter(base: str, sem: asyncio.Semaphore) -> bool:
    """Synthesize one chapter; returns True if every chunk succeeded."""
    text = (TEXT_DIR / f"{base}.txt").read_text(encoding="utf-8")
    units = [u.strip() for u in text.split("\n\n") if u.strip()]
    # speak the chapter title (first unit) with a comma pause between h1 parts
    units[0] = units[0].replace(" ", ",")

    jobs: list[tuple[Path, str]] = []
    unit_chunks: list[list[Path]] = []
    for pi, unit in enumerate(units):
        chunk_files = []
        for ci, chunk in enumerate(split_chunks(unit)):
            cache = CACHE_DIR / f"{base}_{pi:04d}_{ci:02d}.mp3"
            if not (cache.exists() and cache.stat().st_size > 500):
                jobs.append((cache, chunk))
            chunk_files.append(cache)
        unit_chunks.append(chunk_files)

    if jobs:
        done = 0
        results = await asyncio.gather(
            *(synth_one(t, p, sem) for p, t in jobs)
        )
        failed = [p for p, ok in zip(jobs, results) if not ok]
        done = sum(1 for r in results if r)
        if failed:
            print(f"  ❌ {base}: {len(failed)}/{len(jobs)} 块合成失败", flush=True)
            return False
        print(f"  ✅ {base}: {done} 块新合成", flush=True)
    else:
        print(f"  ⏭️  {base}: 缓存完整,跳过", flush=True)

    ordered = [f for chunks in unit_chunks for f in chunks]
    missing = [f for f in ordered if not (f.exists() and f.stat().st_size > 500)]
    if missing:
        print(f"  ❌ {base}: {len(missing)} 块缺失,章节不完整", flush=True)
        return False
    concat(ordered, AUDIO_DIR / f"{base}.mp3")
    return True


async def do_tts(only: str | None) -> None:
    import edge_tts  # noqa: F401  (fail fast if missing)

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    bases = MANIFEST.read_text(encoding="utf-8").splitlines()
    if only:
        bases = [b for b in bases if only in b]
        if not bases:
            print(f"没有匹配 “{only}” 的章节")
            return
    sem = asyncio.Semaphore(CONCURRENCY)
    ok_all = True
    for i, base in enumerate(bases):
        print(f"[{i + 1}/{len(bases)}] {base}", flush=True)
        ok_all &= await synth_chapter(base, sem)
    if not ok_all:
        print("\n部分章节不完整: 重跑本命令即可续传失败块")
        return
    print("\n全部章节合成完成 -> " + str(AUDIO_DIR))
    do_merge(auto=True)


# ---------------------------------------------------------------- merge

def do_merge(auto: bool = False) -> None:
    bases = MANIFEST.read_text(encoding="utf-8").splitlines()
    files = [AUDIO_DIR / f"{b}.mp3" for b in bases]
    missing = [f.name for f in files if not f.exists()]
    if missing:
        print(f"缺少章节音频,无法合并: {missing}")
        return
    out = OUT_DIR / f"{BOOK_TITLE}_全书.mp3"
    concat(files, out)
    size = out.stat().st_size / 1024 / 1024
    print(f"✅ 全书合并: {out} ({size:.0f} MB, {len(files)} 章节)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage", choices=["extract", "tts", "merge"])
    ap.add_argument(
        "--chapter", help="tts: 只合成文件名包含该子串的章节 (断点续跑)"
    )
    args = ap.parse_args()
    if args.stage == "extract":
        do_extract()
    elif args.stage == "tts":
        asyncio.run(do_tts(args.chapter))
    else:
        do_merge()


if __name__ == "__main__":
    main()

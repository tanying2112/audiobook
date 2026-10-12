#!/usr/bin/env python
"""Gap F 迭代2: 多 respell 变体实证 (只留 ASR 整词命中 gold 的变体)."""
import asyncio
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
PY = ROOT / ".venv/bin/python"
ASR_PROC = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
OUT = ROOT / "scratch/ff_system/f_pron_validation"
OUT.mkdir(parents=True, exist_ok=True)
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}

# 每词多变体 (第一轮失败的 5 词 + 基线对照)
VARIANTS = {
    "Tino": ["Teeno", "Tee noh", "Tee-noh", "Tea no"],
    "Zangado": ["Zan-gah-doo", "Zangahdoh", "Zan-gar-doh", "Zang-ah-doh"],
    "Lenda": ["Lehnda", "Lenn-dah", "Lenda", "Lehn-dah"],
    "Nakano": ["Nah-kah-no", "Nakahnno", "Nah-kan-oh", "Nuh-kah-no"],
    "futsal": ["footsall", "futsall", "footzall", "fut-sahl"],
}
SENTENCES = {
    "Tino": "My friends call me Tino, and I play football.",
    "Zangado": "They call him Zangado, angry in Portuguese.",
    "Lenda": "The second is Lenda, the captain of Stars.",
    "Nakano": "Nakano, are you ready, asks the coach.",
    "futsal": "We played futsal when we were children.",
}

log = lambda m: print(f"[f2] {m}", flush=True)

_backend = None


def synth(text: str, path: Path) -> None:
    from audiobook_studio.tts.kokoro_backend import KokoroBackend

    async def _run(p, t):
        global _backend
        if _backend is None:
            _backend = KokoroBackend()
            await _backend.initialize()
        await _backend._synthesize_internal(
            text=t, voice_id="am_adam", output_path=p, prosody={"rate": 1.0}
        )

    asyncio.run(_run(path, text))


def asr(path: Path) -> str:
    r = subprocess.run(
        [str(PY), str(ASR_PROC), str(path), "iic/SenseVoiceSmall", "cpu"],
        capture_output=True, text=True, env=ENV, timeout=900,
    )
    if r.returncode != 0:
        sys.exit(f"asr rc={r.returncode}: {r.stderr[-400:]}")
    line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
    a = json.loads(line)
    if not a.get("success"):
        sys.exit(f"asr failed: {a}")
    return re.sub(r"<\|[^|]*\|>\s*", " ", a["text"]).strip()


def word_hit(hyp: str, gold: str) -> bool:
    words = re.sub(r"[^a-z0-9 ]+", " ", hyp.lower()).split()
    gw = gold.lower().split()
    n = len(gw)
    return any(words[i:i + n] == gw for i in range(len(words) - n + 1))


def main() -> None:
    for gold, variants in VARIANTS.items():
        sent = SENTENCES[gold]
        for v in variants:
            p = OUT / f"it2_{gold.replace(' ', '_')}_{v.replace(' ', '_').replace('-', '_')}.wav"
            synth(sent.replace(gold, v), p)
            hyp = asr(p)
            hit = word_hit(hyp, gold)
            log(f"{gold:8s} | {v:12s} → {'✓ HIT ' if hit else '✗'} {hyp[:60]!r}")


if __name__ == "__main__":
    main()

# 迭代3附加: 追加变体 (基于迭代2听感规律 — 单词形合并、双写辅音稳定)
VARIANTS3 = {
    "Tino": ["Tinnoh", "Tino ", "Tee-nohw"],
    "Zangado": ["Zangadoh", "Zan gad oh", "Zahngado"],
    "Lenda": ["Lendah", "Landah", "Lenda "],
    "Nakano": ["Nakanoh", "Nahcano", "Nacano"],
    "futsal": ["footsal", "futsahl", "futsahl"],
}

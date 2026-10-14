#!/usr/bin/env python
"""Gap F: 专名发音词典条目实证验证 (kokoro 合成 → SenseVoice 回听).

对每个候选 respell 条目:
  1. 用 kokoro am_adam (Run A 同音色) 合成含该词的句子
  2. SenseVoice ASR 回听
  3. 对照 gold 拼写 (整词命中) — 命中者进 config/pronunciation_dict.yaml

对照基线: 原拼写直接合成 → 回听 (证明词条必要性)。
红线#1: 只提交实证过的条目, source 标注派生方式 (heuristic=回听验证的规则化 respell)。
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
PY = ROOT / ".venv/bin/python"
ASR_PROC = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
OUT = ROOT / "scratch/ff_system/f_pron_validation"
OUT.mkdir(parents=True, exist_ok=True)
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}

# 候选条目: gold 拼写 → respell (kokoro 英文 G2P 修正)
# respell 目标 = 原声叙述者 (英化葡语) 的实际读法, 让 ASR 听回 gold 拼写
CANDIDATES = {
    "Tino":      "Tee-no",        # 现: 听成 tinino (G2P 把 Ti 读 3 音节)
    "Albertino": "Al-ber-tee-no",  # 现: alberino (t 被吞)
    "Zangado":   "Zan-gah-doh",   # 现: zanggado (ŋg 聚簇)
    "Lenda":     "Len-dah",       # 现: linda (末元音漂移)
    "Nakano":    "Nah-kah-noh",   # 现: nakao (末音节弱化)
    "futsal":    "foot-sal",      # 现: futzsel/futzel (sal 读 /səl/)
    "Sao Paulo": "Sow pow-loh",   # 现: salo paullo (Sao 读 /sæoʊ/)
    "Talita":    "Tah-lee-tah",   # 预验: 防 lita 漂移
    "Junior":    "Joo-nyor",     # 预验: 葡语读法 /ʒuˈnioʁ/
}
# 载入句 (与 ch1 上下文同型, 提供句内韵律)
SENTENCES = {
    "Tino":      "My friends call me Tino, and I play football.",
    "Albertino": "I am Albertino, or Tino to my friends.",
    "Zangado":   "They call him Zangado, angry in Portuguese.",
    "Lenda":     "The second is Lenda, the captain of Stars.",
    "Nakano":    "Nakano, are you ready, asks the coach.",
    "futsal":    "We played futsal when we were children.",
    "Sao Paulo": "He comes from Sao Paulo, a very big city.",
    "Talita":    "My little sister Talita is here today.",
    "Junior":    "The first is my friend Junior, a good player.",
}

log = lambda m: print(f"[f] {m}", flush=True)


def synth(text: str, path: Path) -> None:
    """kokoro am_adam 合成一句 (Run A 同引擎同音色)."""
    from audiobook_studio.tts.kokoro_backend import KokoroBackend

    async def _run():
        backend = KokoroBackend()
        await backend.initialize()
        await backend._synthesize_internal(
            text=text, voice_id="am_adam", output_path=path, prosody={"rate": 1.0}
        )
        await backend.close()

    asyncio.run(_run())


def asr(path: Path) -> str:
    """SenseVoice 回听, 返回规范化小写文本."""
    r = subprocess.run(
        [str(PY), str(ASR_PROC), str(path), "iic/SenseVoiceSmall", "cpu"],
        capture_output=True, text=True, env=ENV, timeout=900,
    )
    if r.returncode != 0:
        sys.exit(f"asr rc={r.returncode}: {r.stderr[-400:]}")
    line = [l for l in r.stdout.strip().splitlines() if l.strip().startswith("{")][-1]
    asr = json.loads(line)
    if not asr.get("success"):
        sys.exit(f"asr failed: {asr}")
    return re.sub(r"<\|[^|]*\|>\s*", " ", asr["text"]).strip()


def word_hit(hyp: str, gold: str) -> bool:
    """ASR 听回的句子里是否整词命中 gold 拼写 (规范化小写后)."""
    words = re.sub(r"[^a-z0-9 ]+", " ", hyp.lower()).split()
    gold_words = gold.lower().split()
    n = len(gold_words)
    return any(words[i:i + n] == gold_words for i in range(len(words) - n + 1))


def main() -> None:
    results = {}
    for gold, respell in CANDIDATES.items():
        sent = SENTENCES[gold]
        base_path = OUT / f"{gold.replace(' ', '_')}_base.wav"
        fix_path = OUT / f"{gold.replace(' ', '_')}_fix.wav"
        # 基线: 原拼写
        synth(sent, base_path)
        hyp_base = asr(base_path)
        # 词条: respell 拼写
        synth(sent.replace(gold, respell), fix_path)
        hyp_fix = asr(fix_path)
        b, f_ = word_hit(hyp_base, gold), word_hit(hyp_fix, gold)
        results[gold] = {
            "respell": respell, "hyp_base": hyp_base, "base_hit": b,
            "hyp_fix": hyp_fix, "fix_hit": f_,
        }
        mark = lambda x: "✓" if x else "✗"
        log(f"{gold:10s} → {respell:14s} 基线{mark(b)} ({hyp_base[:48]!r}) "
            f"词条{mark(f_)} ({hyp_fix[:48]!r})")

    keep = {g: r for g, r in results.items() if r["fix_hit"]}
    regress = {g: r for g, r in results.items() if r["base_hit"] and not r["fix_hit"]}
    log(f"\n词条有效 {len(keep)}/{len(CANDIDATES)}; 词条负收益 {len(regress)}")
    (OUT / "validation.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log(f"明细 → {OUT / 'validation.json'}")


if __name__ == "__main__":
    main()

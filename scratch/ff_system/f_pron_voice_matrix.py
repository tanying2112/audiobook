#!/usr/bin/env python
"""Gap F 行动项 #7: 词条音色矩阵回听验证 (5 词 × 10 英文 kokoro 音色).

背景: config/pronunciation_dict.yaml 英文词条 Lenda→"Len da" 只在 am_adam 单音色
验证过; Run B (段落路由 am_onyx) 中被 SenseVoice 听成 "le da" — 词条音色敏感。

矩阵: 每词 2 条件 (base 原拼写 / respell 词条拼写) × 10 音色, kokoro 合成载句 →
SenseVoice 子进程回听 → word_hit 整词命中 → voice_matrix.json (resume 逐格)。

Stage 2 变体搜索: respell 失败格 (含 unstable) × 每词 it2-it5 变体池, 首个命中停,
预算 PHASE2_MAX_CELLS。Stage 3 补全: unique winners × 未测音色 → universal 判定。

裁判循环性 (诚实声明, 写进 meta 与报告): SenseVoice 亦是差距 E 中连原声叙述者都
判不过的同一裁判 — 单格 fail ≠ 合成缺陷, 只等于裁判不识别。词条硬红线「不伤害」:
base 命中而 respell 失败的音色 = 回归 (no_harm_violation), 该音色可走恒等变体
(variant 填原拼写)。

决策分支 (summary 自动计算):
  A = 现词条 10/10 全过      → 词条保持, 矩阵入档
  B = 某变体 10/10 全过      → 更新词条 phoneme (无 schema 变更)
  C = 无通用体, 分音色 winner → per-voice variants (DictEntry.voice_variants)
      全池失败音色 = respell 不可修, 诚实降级默认 phoneme
"""
import asyncio
import json
import os
import re
import subprocess
import sys
from datetime import date as _date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
PY = ROOT / ".venv/bin/python"
ASR_PROC = ROOT / "src/audiobook_studio/quality/_asr_proc.py"
OUT = ROOT / "scratch/ff_system/f_pron_validation/matrix"
OUT.mkdir(parents=True, exist_ok=True)
JSON_PATH = OUT / "voice_matrix.json"
ENV = {**dict(os.environ), "KMP_DUPLICATE_LIB_OK": "TRUE"}

# 10 个唯一英文 kokoro 音色 (同源: synthesize.py list_engine_voices("en","kokoro")
# / _EDGE_TO_KOKORO values 去重; 硬编码避免把 pipeline 导入图拉进本进程)
VOICES = (
    "af_bella", "af_sarah", "af_nicole", "af_sky",
    "am_adam", "am_onyx", "am_liam", "am_michael", "am_puck", "am_fenrir",
)

# 词表: gold → 现词条/Gap-F 候选 respell + it2-it5 变体池 (去 hack 变体:
# 尾空格/重复注入会污染替换语义; 已证实的排前; ≤8)
CARRIERS = {  # 与 f_pron_dict_validate.py SENTENCES 同句, 保证证据可比
    "Lenda":   "The second is Lenda, the captain of Stars.",
    "Tino":    "My friends call me Tino, and I play football.",
    "Zangado": "They call him Zangado, angry in Portuguese.",
    "Nakano":  "Nakano, are you ready, asks the coach.",
    "futsal":  "We played futsal when we were children.",
}
WORDS = {
    "Lenda": {
        "respell": "Len da",  # 现词条 (it4 am_adam 实证)
        "pool": ["Lenn da", "Lendah", "Lehnda", "Lenn-dah", "Lehn-dah", "Landah"],
    },
    "Tino": {
        "respell": "Tee-no",  # Gap-F it1 候选
        "pool": ["Tee no", "Tee noh", "Teeno", "Tea no", "Tinnoh", "Tin oh"],
    },
    "Zangado": {
        "respell": "Zan-gah-doh",
        "pool": ["Zan-gah-doo", "Zangadoh", "Zan Gado", "Zangahdoh", "Zan-gar-doh"],
    },
    "Nakano": {
        "respell": "Nah-kah-noh",
        "pool": ["Nah-kah-no", "Nakanoh", "Naka no", "Nakahnno"],
    },
    "futsal": {
        "respell": "foot-sal",
        "pool": ["footsal", "footsall", "futsall", "fut sal", "fut SAW", "footzall"],
    },
}

PHASE2_MAX_CELLS = 96   # stage 2 (失败格变体搜索) 新格预算
PHASE3_MAX_CELLS = 96   # stage 3 (winner 补全扫描) 新格预算

log = lambda m: print(f"[fm] {m}", flush=True)

_backend = None


def synth(text: str, voice_id: str, path: Path) -> None:
    """kokoro 合成一句到指定音色 (iter2 全局 backend 缓存模式)."""
    from audiobook_studio.tts.kokoro_backend import KokoroBackend

    async def _run(p, t, v):
        global _backend
        if _backend is None:
            _backend = KokoroBackend()
            await _backend.initialize()
        await _backend._synthesize_internal(
            text=t, voice_id=v, output_path=p, prosody={"rate": 1.0}
        )

    asyncio.run(_run(path, text, voice_id))


def asr(path: Path) -> str:
    """SenseVoice 子进程回听 (funasr 须子进程隔离), 返回规范化小写文本."""
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
    """ASR 回听句子里是否整词命中 gold 拼写 (规范化小写后)."""
    words = re.sub(r"[^a-z0-9 ]+", " ", hyp.lower()).split()
    gw = gold.lower().split()
    n = len(gw)
    return any(words[i:i + n] == gw for i in range(len(words) - n + 1))


def _fname(word: str, cond: str, voice: str) -> str:
    return f"{word}_{cond}_{voice}.wav"


# ── JSON 载入/回写 (resume: 每格完成即整文件重写, 文件小) ──────────────────


def load_state() -> dict:
    if JSON_PATH.exists():
        try:
            return json.loads(JSON_PATH.read_text(encoding="utf-8"))
        except Exception as e:  # 损坏则从头 (wav 可复用, 合成很快)
            log(f"state 损坏, 重建: {e}")
    return {
        "meta": {
            "date": str(_date.today()),
            "asr_model": "iic/SenseVoiceSmall",
            "engine": "kokoro",
            "voices": list(VOICES),
            "asr_runs": "1 (Lenda respell 失败格追加 confirm 2 次, 不一致标 unstable 按失败计)",
            "judge_circularity_note": (
                "SenseVoice 亦是差距 E 中连原声叙述者都判不过的同一裁判; "
                "单格 fail != 合成缺陷, 只等于裁判不识别"
            ),
        },
        "matrix": {},
        "variant_search": {},
        "completion": {},
        "summary": {},
        "budget": {},
    }


def save_state(st: dict) -> None:
    JSON_PATH.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


# ── Stage 1: base/respell × 10 音色矩阵 ──────────────────────────────────


def run_matrix(st: dict, words: list[str], voices: list[str]) -> None:
    m = st["matrix"]
    for word in words:
        respell = WORDS[word]["respell"]
        wm = m.setdefault(word, {"respell": respell, "carrier": CARRIERS[word], "voices": {}})
        done = wm["voices"]
        for voice in voices:
            r = done.get(voice, {}).get("respell", {})
            # respell 已终判才跳过: 命中 / 有 confirm (unstable 已判) / synth_error;
            # respell 失败但 confirm 未跑 → 不跳, 内层补跑 confirm
            if r.get("hit") is True or "confirm" in r or "synth_error" in r:
                continue
            cell = done.setdefault(voice, {})
            for cond, spelling in (("base", word), ("respell", respell)):
                if cell.get(cond, {}).get("hit") is not None:
                    continue
                text = CARRIERS[word] if cond == "base" else CARRIERS[word].replace(word, spelling)
                wav = OUT / _fname(word, cond, voice)
                try:
                    synth(text, voice, wav)
                except Exception as e:
                    cell[cond] = {"synth_error": f"{type(e).__name__}: {e}"}
                    log(f"{word} {cond} {voice}: synth_error {e}")
                    continue
                hyp = asr(wav)
                cell[cond] = {"hit": word_hit(hyp, word), "hyp": hyp}
                mark = "✓" if cell[cond]["hit"] else "✗"
                log(f"{word:8s} {cond:7s} {voice:10s} {mark} {hyp[:52]!r}")
                save_state(st)
            # confirm2: 仅 Lenda respell 失败格 — 复跑整格 (synth+ASR), 两次不一致 → unstable
            if (word == "Lenda" and cell.get("respell", {}).get("hit") is False
                    and "confirm" not in cell["respell"]):
                wav2 = OUT / _fname(word, "respell2", voice)
                try:
                    synth(CARRIERS[word].replace(word, respell), voice, wav2)
                    hyp2 = asr(wav2)
                    hit2 = word_hit(hyp2, word)
                    unstable = hit2 != cell["respell"]["hit"]
                    if unstable:  # 按失败计 (保守), 双 hyp 入档
                        cell["respell"]["hit"] = False
                    cell["respell"]["confirm"] = {
                        "hit": hit2, "hyp": hyp2, "unstable": unstable,
                    }
                    log(f"{'Lenda':8s} confirm {voice:10s} "
                        f"{'UNSTABLE' if unstable else '一致(失败)'} {hyp2[:40]!r}")
                except Exception as e:
                    cell["respell"]["confirm"] = {"synth_error": f"{type(e).__name__}: {e}"}
                save_state(st)
            save_state(st)


# ── Stage 2: 失败格变体搜索 (首个命中停) ────────────────────────────────


def run_variant_search(st: dict, words: list[str], voices: list[str]) -> int:
    used = 0
    vs = st["variant_search"]
    for word in words:
        wm = st["matrix"].get(word, {}).get("voices", {})
        fails = [v for v in voices
                 if wm.get(v, {}).get("respell", {}).get("hit") is False]
        if not fails:
            continue
        pool = WORDS[word]["pool"]
        wv = vs.setdefault(word, {})
        for voice in fails:
            if used >= PHASE2_MAX_CELLS:
                st["budget"]["stage2_exhausted"] = True
                log(f"stage2 预算耗尽 ({PHASE2_MAX_CELLS}), 剩余失败格跳过")
                return used
            wv.setdefault(voice, [])
            for vi, variant in enumerate(pool):
                if any(r["variant"] == variant for r in wv[voice]):
                    continue  # resume 跳过已测
                if used >= PHASE2_MAX_CELLS:
                    st["budget"]["stage2_exhausted"] = True
                    log(f"stage2 预算耗尽 ({PHASE2_MAX_CELLS})")
                    return used
                wav = OUT / _fname(word, f"v{vi}", voice)
                try:
                    synth(CARRIERS[word].replace(word, variant), voice, wav)
                    hyp = asr(wav)
                except Exception as e:
                    wv[voice].append({"variant": variant, "synth_error": f"{type(e).__name__}: {e}"})
                    save_state(st)
                    continue
                hit = word_hit(hyp, word)
                wv[voice].append({"variant": variant, "hit": hit, "hyp": hyp})
                used += 1
                save_state(st)
                mark = "✓" if hit else "✗"
                log(f"{word:8s} 变体搜索 {voice:10s} {variant:12s} {mark}")
                if hit:
                    break  # per-voice winner: 首个命中即停
    return used


# ── Stage 3: winner 补全扫描 (universal 判定) ─────────────────────────────


def run_completion(st: dict, words: list[str], voices: list[str]) -> int:
    used = 0
    comp = st["completion"]
    for word in words:
        # winners = stage2 命中变体 + 恒等 (base 命中而 respell 失败 → 原拼写即解)
        winners: dict[str, str] = {}
        for voice, runs in st["variant_search"].get(word, {}).items():
            for r in runs:
                if r.get("hit"):
                    winners[voice] = r["variant"]
                    break
        wm = st["matrix"].get(word, {}).get("voices", {})
        for voice in voices:
            if (wm.get(voice, {}).get("base", {}).get("hit") is True
                    and wm.get(voice, {}).get("respell", {}).get("hit") is False
                    and voice not in winners):
                winners[voice] = word  # 恒等变体: base 本来就命中, 无需新格
        if not winners:
            continue
        unique = sorted(set(winners.values()) - {word})  # 恒等无需补全
        wc = comp.setdefault(word, {})
        for variant in unique:
            tested = {v for v, r in winners.items() if r == variant}
            wc.setdefault(variant, {})
            for voice in voices:
                if voice in wc[variant] or voice in tested:
                    continue  # resume 跳过 / winner 音色已证
                if used >= PHASE3_MAX_CELLS:
                    st["budget"]["stage3_exhausted"] = True
                    log(f"stage3 预算耗尽 ({PHASE3_MAX_CELLS})")
                    return used
                wav = OUT / _fname(word, f"c_{re.sub(r'[^A-Za-z0-9]', '_', variant)}", voice)
                try:
                    synth(CARRIERS[word].replace(word, variant), voice, wav)
                    hyp = asr(wav)
                except Exception as e:
                    wc[variant][voice] = {"synth_error": f"{type(e).__name__}: {e}"}
                    save_state(st)
                    continue
                hit = word_hit(hyp, word)
                wc[variant][voice] = {"hit": hit, "hyp": hyp}
                used += 1
                save_state(st)
                log(f"{word:8s} 补全 {voice:10s} {variant:12s} {'✓' if hit else '✗'}")
    return used


# ── Summary: 分支自动判定 ──────────────────────────────────────────────────


def compute_summary(st: dict, words: list[str], voices: list[str]) -> None:
    s = st["summary"]
    for word in words:
        wm = st["matrix"].get(word, {}).get("voices", {})
        respell_pass, respell_fail, unstable, no_harm = [], [], [], []
        for v in voices:
            base = wm.get(v, {}).get("base", {})
            resp = wm.get(v, {}).get("respell", {})
            if resp.get("hit") is None:
                continue  # 未完成或 synth_error 格 — 不计 pass/fail
            conf = resp.get("confirm") or {}
            if conf.get("unstable"):
                unstable.append(v)
            if resp.get("hit") is True:
                respell_pass.append(v)
            else:
                respell_fail.append(v)
                if base.get("hit") is True:
                    no_harm.append(v)
        # winners: stage2 命中 + 恒等 + stage3 补全命中
        winners: dict[str, str] = {}
        for voice, runs in st["variant_search"].get(word, {}).items():
            for r in runs:
                if r.get("hit"):
                    winners[voice] = r["variant"]
                    break
        for v in no_harm:
            winners.setdefault(v, word)  # 恒等变体 (原拼写)
        for variant, cells in st["completion"].get(word, {}).items():
            for voice, r in cells.items():
                if r.get("hit") and voice in respell_fail:
                    winners.setdefault(voice, variant)
        # universal: 某非恒等变体在全部音色命中 (stage3 补全 + stage2 winner)
        universal = None
        for variant in sorted(set(winners.values()) - {word}):
            ok = all(
                (winners.get(v) == variant)
                or st["completion"].get(word, {}).get(variant, {}).get(v, {}).get("hit") is True
                for v in voices
            )
            if ok:
                universal = variant
                break
        # 分支: A 现词条全过 / B 通用变体 / C 分音色 winner 或不可修
        if len(respell_pass) == len(voices):
            branch = "A"
        elif universal:
            branch = "B"
        else:
            branch = "C"
        s[word] = {
            "respell": WORDS[word]["respell"],
            "respell_pass": respell_pass,
            "respell_fail": respell_fail,
            "unstable": unstable,
            "no_harm_violations": no_harm,
            "per_voice_winners": winners,
            "universal_variant": universal,
            "branch": branch,
        }
        log(f"summary {word:8s} 分支 {branch}: pass={len(respell_pass)}/{len(voices)} "
            f"winners={len(winners)} universal={universal!r} no_harm={no_harm}")


def print_matrix_table(st: dict, words: list[str], voices: list[str]) -> None:
    ab = {v: v.split("_")[1][:6] for v in VOICES}  # 缩写列 (adam/onyx/bella/...)
    hdr = f"{'word':10s} {'cond':7s} " + " ".join(f"{ab[v]:>6s}" for v in voices)
    log("")
    log(hdr)
    for word in words:
        wm = st["matrix"].get(word, {}).get("voices", {})
        for cond in ("base", "respell"):
            cells = []
            for v in voices:
                c = wm.get(v, {}).get(cond, {})
                hit = c.get("hit")
                cells.append("  ✓  " if hit is True else ("  ✗  " if hit is False else "  ?  "))
            log(f"{word:10s} {cond:7s} " + " ".join(cells))
        s = st["summary"].get(word, {})
        if s.get("per_voice_winners"):
            ws = " ".join(f"{ab[v]}→{r[:8]}" for v, r in list(s["per_voice_winners"].items())[:6])
            log(f"{'':10s} winner   {ws}")


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    voices_flag = next((a[9:] for a in sys.argv[1:] if a.startswith("--voices=")), None)
    words = args or list(WORDS)
    voices = voices_flag.split(",") if voices_flag else list(VOICES)
    unknown = [w for w in words if w not in WORDS]
    if unknown:
        sys.exit(f"未知词: {unknown} (可选: {list(WORDS)})")
    st = load_state()
    log(f"矩阵: {len(words)} 词 × {len(voices)} 音色; state={'resume' if st['matrix'] else 'new'}")

    run_matrix(st, words, voices)
    used2 = run_variant_search(st, words, voices)
    used3 = run_completion(st, words, voices)
    st["budget"]["stage2_used"] = st["budget"].get("stage2_used", 0) + used2
    st["budget"]["stage3_used"] = st["budget"].get("stage3_used", 0) + used3
    compute_summary(st, words, voices)
    print_matrix_table(st, words, voices)
    save_state(st)
    log(f"完成 → {JSON_PATH}")


if __name__ == "__main__":
    main()

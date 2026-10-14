"""Football Forever ch1 v5 — 多角色分声 + 情感强化(用户对 v4 的两点反馈落地):
  v4 已获认可 (粗网格冠军 am_adam 0.80 / sent 0.7 / para 2.5 / -23 LUFS), 反馈:
    1) 单声到底缺多角色 → v5 角色分声
    2) 情感语调可更强   → v5 导演层(选声/语速/动态/停顿四件套)
  本地 Kokoro 无情感标签 — 诚实边界内的全部手段:
    - 角色分声: 叙述 am_adam | 教练 onyx.65+fenrir.35 混合 | Lenda am_echo |
      Nakano/球员 am_liam | Tino 台词 am_puck | 母亲 af_nicole
    - 每句语速: 教练 0.82 / 球员喊 0.85 / 母亲 0.77 / 怯场 0.76
    - 每句动态: 教练吼 +2.5dB / Tino 自语 -3.5dB / Lenda 内心 -3dB
    - 停顿节奏: 应答交换 0.8s / 教练连句 0.45s / 引语↔旁白 0.22s / 叙述流保持 v4
  工程:
    - 引语感知分句(v4 正则会把 'Bad! Very bad!' 误切两句); 撇号不算引号
    - 引语整段连读(教练演讲一气呵成), 归属性旁白("says the coach")归叙述者
    - 每音色中位 RMS 校准到叙述者(±4dB 封顶), 情感增益叠加其上
    - 词流一致性断言: 分段重组 == 原文(保护 WER 对齐)
    - 链路同 v4: alimiter → soxr VHQ → ebur128 → 精确 -23.0 → s16
输出:
  output/football_forever_ch1/football_forever_ch1_v5_multivoice_44k1.wav
  scratch/football_test/v5/synth_summary_v5.json
用法: --check 只打印角色标注表
"""
import hashlib, json, re, subprocess, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
V5 = WORK / "v5"; V5.mkdir(exist_ok=True)
OUT = ROOT / "output" / "football_forever_ch1"
TARGET_LUFS = -23.0
CHAIN = "alimiter=limit=0.6457:attack=5:release=100:level=disabled"
SR = 24000
CHECK_ONLY = "--check" in sys.argv

MICRO_GAP = 0.22
GAPS = {"narr_sent": 0.70, "narr_para": 2.50, "turn_same": 0.60, "turn_same_coach": 0.45,
        "turn_diff": 0.80, "para_same": 0.50, "para_diff": 0.80,
        "para_d2n": 1.30, "para_n2d": 1.00}
VOICE = {"narrator": ("am_adam", 0.80), "coach": ("am_onyx+am_fenrir", 0.82),
         "lenda": ("am_echo", 0.80), "nakano": ("am_liam", 0.80),
         "players": ("am_liam", 0.85), "tino": ("am_puck", 0.78),
         "mother": ("af_nicole", 0.85), "lenda_thought": ("am_echo", 0.78)}
BASE_GAIN = {"narrator": 0.0, "coach": 1.5, "lenda": 0.5, "nakano": 0.0,
             "players": 2.5, "tino": -0.5, "mother": 0.0, "lenda_thought": -3.0}
CITATIONS = {"We", "Zangado", "angry", "TINO"}
# 人工复核覆盖: (para_idx, sent_idx) -> {"speaker":..., "gain":..., "speed":...}
LINE_OVR = {
    (14, 0): {"speaker": "coach"},   # OK. You're on.
    (14, 5): {"speaker": "coach"},   # Tino, are you ready?
    (16, 0): {"speaker": "coach"},   # Yes, you. You're the only Tino here.
    (18, 0): {"speaker": "coach"},   # OK. You're up front, with Lenda...
}

# ── 文本解析 ───────────────────────────────────────────────────
def scan_quotes(text):
    n = len(text); inq = [False] * n; state = False
    for i, c in enumerate(text):
        if c != "'":
            inq[i] = state; continue
        prev = text[i-1] if i else ""
        nxt = text[i+1] if i+1 < n else ""
        if prev.isalpha() and nxt.isalpha():
            inq[i] = state                          # 撇号: 维持原状态
        elif state:
            inq[i] = True; state = False            # 闭引号属于引语段
        elif prev == "" or prev in " \t(":
            inq[i] = True; state = True              # 开引号属于引语段
        else:
            inq[i] = False
    return inq

def split_sentences(text, inq):
    sents, buf, i, n = [], [], 0, len(text)
    while i < n:
        buf.append(text[i])
        if text[i] in ".!?" and not inq[i] and (i+1 >= n or text[i+1] in " \t"):
            j = i + 1
            while j < n and text[j] in " \t":
                j += 1
            sents.append("".join(buf)); buf = []; i = j; continue
        i += 1
    if "".join(buf).strip():
        sents.append("".join(buf))
    return [s.strip() for s in sents if s.strip()]

def segments_of(sent):
    inq = scan_quotes(sent)
    runs = []
    for i, c in enumerate(sent):
        q = inq[i]
        if runs and runs[-1][1] == q:
            runs[-1][0].append(c)
        else:
            runs.append(([c], q))
    out = []
    for chars, q in runs:
        t = "".join(chars)
        if q:
            inner = t.strip("' ").strip()
            if inner in CITATIONS and len(inner.split()) == 1:
                out.append((inner, False))        # 提名引号 → 旁白
            else:
                out.append((inner, True))
        else:
            out.append((t.strip(), False))
    merged = []
    for t, q in out:
        if t and merged and not merged[-1][1] and not q:
            merged[-1] = (merged[-1][0] + " " + t, False)
        elif t:
            merged.append((t, q))
    return [(re.sub(r"\s+([,.;:!?])", r"\1", t), q) for t, q in merged]

ATTR = [(r"\bcoach\b", "coach"), (r"\bNakano\b", "nakano"),
        (r"\bLenda\b|\bcaptain\b", "lenda"), (r"\bmother\b", "mother"),
        (r"\bplayers\b", "players"), (r"\bthinking\b", "lenda_thought"),
        (r"\bI\s+(?:ask|say|shout)\b", "tino")]

def attr_speaker(narr_text):
    for pat, sp in ATTR:
        if re.search(pat, narr_text):
            return sp
    return None

def parse_markup():
    paras = [p.strip() for p in (WORK / "chapter1_clean.txt").read_text(encoding="utf-8").split("\n\n") if p.strip()]
    units, history = [], []
    for pi, para in enumerate(paras):
        inq = scan_quotes(para)
        sents = split_sentences(para, inq)
        punits = []
        for si, sent in enumerate(sents):
            segs = segments_of(sent)
            narr = " ".join(t for t, q in segs if not q)
            seg_spk, cur_last = [], None
            for t, q in segs:
                if not q:
                    seg_spk.append(None); continue
                ovr = LINE_OVR.get((pi, si), {})
                sp = ovr.get("speaker") or attr_speaker(narr)
                if sp is None:
                    for hn in reversed(history[-6:]):
                        a = attr_speaker(hn)
                        if a:
                            sp = a; break
                seg_spk.append(sp)
                cur_last = sp or cur_last
            if narr:
                history.append(narr)
                if len(history) > 8:
                    history.pop(0)
            punits.append({"segs": segs, "seg_spk": seg_spk, "narr": narr})
        units.append(punits)
    return paras, units

def seg_policy(sp, quote_text, narr_text):
    g, spd = BASE_GAIN.get(sp, 0.0), VOICE.get(sp, ("am_adam", 0.80))[1]
    if sp == "coach":
        if "angrily" in narr_text or "Sshh" in quote_text:
            g = 2.5
        elif len(quote_text.split()) > 25:
            g = 2.0
        elif quote_text.count("!") >= 2:
            g = 2.5
    elif sp == "players":
        if "some of the players" in narr_text:
            g = 1.0
    elif sp == "tino":
        if "Who, me" in quote_text:
            g, spd = -1.0, 0.76
        elif quote_text.startswith("Er,"):
            g, spd = -1.0, 0.76
        if "quietly" in narr_text:
            g = -3.5
    elif sp == "lenda" and "let's go" in quote_text.lower():
        g = 2.0
    return g, spd

def norm_words(t):
    return re.sub(r"[^A-Za-z0-9]+", " ", t).upper().split()

def main():
    paras, units = parse_markup()
    n_sent = sum(len(u) for u in units)
    n_quote = sum(1 for pu in units for u in pu for s in u["seg_spk"] if s)
    src_words = norm_words(" ".join(paras))
    seg_words = [w for pu in units for u in pu for t, q in u["segs"] for w in norm_words(t)]
    assert seg_words == src_words, f"词流失配: {len(src_words)} vs {len(seg_words)}"
    words = len(" ".join(paras).split())

    if CHECK_ONLY:
        print(f"[v5] {len(paras)} paras / {n_sent} sents / {n_quote} quote segs / {len(src_words)} words")
        bad = [(pi, si, t[:40]) for pi, pu in enumerate(units) for si, u in enumerate(pu)
               for k, (t, q) in enumerate(u["segs"]) if q and not u["seg_spk"][k]]
        for pi, punits in enumerate(units):
            cls = "D" if punits[0]["segs"] and punits[0]["segs"][0][1] else "n"
            print(f"== P{pi} ({cls}) ==")
            for si, u in enumerate(punits):
                for k, (t, q) in enumerate(u["segs"]):
                    if q:
                        sp = u["seg_spk"][k]
                        g, spd = seg_policy(sp or "narrator", t, u["narr"])
                        print(f"  S{si} [Q {str(sp):<13}] g={g:+.1f} v={spd} | {t[:72]}")
                    else:
                        print(f"  S{si} [narr          ]            | {t[:72]}")
        print("\n未定/存疑 speaker:", bad if bad else "无")
        print("V5_CHECK_DONE")
        return

    from kokoro_onnx import Kokoro
    ko = Kokoro(str(ROOT / "models/kokoro-v1.0.onnx"), str(ROOT / "models/voices-v1.0.bin"))
    blends = {}
    def style(vk):
        if "+" in vk:
            if vk not in blends:
                a, b = vk.split("+")
                blends[vk] = (0.65 * ko.get_voice_style(a) + 0.35 * ko.get_voice_style(b)).astype(np.float32)
            return blends[vk]
        return vk

    # 展平: 与组装完全同序
    flat = []
    for pi, punits in enumerate(units):
        for si, u in enumerate(punits):
            for k, (t, q) in enumerate(u["segs"]):
                if q:
                    sp = u["seg_spk"][k] or "narrator"
                    ovr = LINE_OVR.get((pi, si), {})
                    g, spd = ovr.get("gain"), ovr.get("speed")
                    if g is None:
                        g, spd = seg_policy(sp, t, u["narr"])
                    flat.append({"vk": VOICE[sp][0], "spd": spd, "emo": g, "text": t, "sp": sp})
                else:
                    flat.append({"vk": "am_adam", "spd": 0.80, "emo": 0.0, "text": t, "sp": "narrator"})

    cache_f = V5 / "pieces_cache.npz"
    cache = dict(np.load(cache_f)) if cache_f.exists() else {}
    t0 = time.time()
    pieces = []
    for f in flat:
        key = hashlib.sha1(f"{f['vk']}|{f['spd']}|{f['text']}".encode()).hexdigest()
        if key in cache:
            pieces.append(cache[key].astype(np.float32))
        else:
            a, _ = ko.create(text=f["text"], voice=style(f["vk"]), speed=f["spd"], lang="en-gb")
            a = a.astype(np.float32); cache[key] = a; pieces.append(a)
    np.savez(cache_f, **cache)
    synth_s = time.time() - t0
    print(f"[v5] synth {len(pieces)} pieces / {synth_s:.0f}s (cache {len(cache)})")

    med = {}
    for f, p in zip(flat, pieces):
        med.setdefault(f["vk"], []).append(float(np.sqrt(np.mean(p ** 2))))
    ref = float(np.median(med["am_adam"]))
    calib = {vk: float(np.clip(20 * np.log10(ref / float(np.median(v))), -4.0, 4.0)) for vk, v in med.items()}
    print("[v5] per-voice calib dB:", {k: round(v, 2) for k, v in calib.items()})

    # 组装
    audio_parts, gap_total, speech = [], 0.0, 0.0
    def gap(sec):
        audio_parts.append(np.zeros(int(SR * sec), dtype=np.float32)); return sec
    fi = 0
    for pi, punits in enumerate(units):
        for si, u in enumerate(punits):
            if pi == 0 and si == 0:
                pass
            elif si == 0:
                prv, cur = units[pi - 1], punits
                prv_q = prv[-1]["segs"][-1][1] if prv[-1]["segs"] else False
                cur_q = cur[0]["segs"][0][1] if cur[0]["segs"] else False
                prv_spk = next((s for x in reversed(prv) for s in reversed(x["seg_spk"]) if s), None)
                cur_spk = next((s for x in cur for s in x["seg_spk"] if s), None)
                if prv_q and cur_q:
                    g = GAPS["para_same"] if prv_spk == cur_spk else GAPS["para_diff"]
                elif prv_q:
                    g = GAPS["para_d2n"]
                elif cur_q:
                    g = GAPS["para_n2d"]
                else:
                    g = GAPS["narr_para"]
                gap_total += gap(g)
            else:
                pu = punits[si - 1]
                prv_spk = next((s for s in reversed(pu["seg_spk"]) if s), None)
                cur_spk = next((s for s in u["seg_spk"] if s), None)
                if prv_spk and cur_spk:
                    if prv_spk == cur_spk:
                        g = GAPS["turn_same_coach"] if prv_spk == "coach" else GAPS["turn_same"]
                    else:
                        g = GAPS["turn_diff"]
                else:
                    g = GAPS["narr_sent"]
                gap_total += gap(g)
            for k in range(len(u["segs"])):
                f = flat[fi]; fi += 1
                a = pieces[fi - 1] * (10 ** ((calib[f["vk"]] + f["emo"]) / 20))
                audio_parts.append(a); speech += len(a) / SR
                if k < len(u["segs"]) - 1:
                    gap_total += gap(MICRO_GAP)
    assert fi == len(flat), f"flat 消费失配 {fi}/{len(flat)}"
    audio = np.concatenate(audio_parts)
    dur = len(audio) / SR
    words = words
    wpm_phon, wpm_tot = words / speech * 60, words / dur * 60
    print(f"[v5] dur {dur:.1f}s (speech {speech:.1f} + gaps {gap_total:.1f}) wpm {wpm_phon:.1f}/{wpm_tot:.1f}")

    native_f = V5 / "native_24k_float.wav"
    sf.write(str(native_f), audio, SR, subtype="FLOAT")
    lim_f = V5 / "lim_24k_float.wav"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(native_f), "-af", CHAIN,
                        "-c:a", "pcm_f32le", "-ar", str(SR), str(lim_f)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"limiter failed: {r.stderr[-300:]}")
    lim, _ = sf.read(str(lim_f))
    import soxr
    y = soxr.resample(lim.astype(np.float32), SR, 44100, quality="VHQ")
    tmp44 = V5 / "pre_gain_44k1.wav"
    sf.write(str(tmp44), y, 44100, subtype="FLOAT")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(tmp44),
                        "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    err = r.stderr[r.stderr.find("Summary:"):]
    lufs_pre = float(re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err).group(1))
    y = y * (10 ** ((TARGET_LUFS - lufs_pre) / 20))
    w44 = OUT / "football_forever_ch1_v5_multivoice_44k1.wav"
    sf.write(str(w44), y, 44100, subtype="PCM_16")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(w44),
                        "-af", "ebur128=peak=true", "-f", "null", "-"], capture_output=True, text=True)
    err = r.stderr[r.stderr.find("Summary:"):]
    lufs_post = float(re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err).group(1))
    tp_post = float(re.search(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", err).group(1))
    print(f"[v5] deliverable: {dur:.1f}s {lufs_post:.1f} LUFS TP {tp_post:.1f}")

    casting = {sp: {"voice": VOICE[sp][0], "lines": sum(1 for f in flat if f["sp"] == sp)}
               for sp in sorted({f["sp"] for f in flat})}
    summary = {"version": "v5_multivoice", "words": words, "pieces": len(pieces),
               "synth_wall_s": round(synth_s, 1), "audio_sec": round(dur, 1),
               "speech_sec": round(speech, 1), "gap_sec": round(gap_total, 1),
               "wpm_phonation": round(wpm_phon, 1), "wpm_overall": round(wpm_tot, 1),
               "per_voice_calib_db": {k: round(v, 2) for k, v in calib.items()},
               "casting": casting, "gaps": GAPS, "micro_gap": MICRO_GAP,
               "lufs": lufs_post, "tp_dbtp": tp_post, "chain": CHAIN,
               "deliverable": str(w44)}
    (V5 / "synth_summary_v5.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("V5_DONE " + json.dumps(summary))

if __name__ == "__main__":
    main()

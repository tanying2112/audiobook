"""Football Forever ch1 v6 — v5 多角色基座上的两层升级(用户对 v5 的反馈落地):
  用户反馈: "需要角色音量音调根据情感调整更充分些, 并在适当部分带音乐床的 ducking 混音版"
  (a) 逐句三轴导演: 每条对白 gain/speed/pitch 显式表(DIRECT, 32 条全覆盖),
      旁白关键词驱动(NARR_RULES); 教练怒态切换 fenrir 更重混血(hot 0.55/0.45);
      音调轴 librosa pitch_shift ±1.5 半音, soxr_vhq, 应用于缓存片段之上(不进缓存键).
  (b) 程序化音乐床 + 声码侧链 ducking: Am 小调分段和声 pad(sine+谐波, 双失谐,
      8s 和弦+2.5s 升余弦交叉) + 心跳 62BPM(Tino 段) + 人群带通噪声(出场),
      FFT 带通 65–2200Hz, Schroeder 混响 wet 0.18; 床 solo 标定 −26 LUFS,
      语音 RMS 侧链(20ms hop, thr −42dBFS)压床 −14dB, att 0.18s/rel 0.7s;
      冷开场: P0 怒吼不垫乐, 床从 P1 前 1.8s 淡入 1.5s; 尾声 +8.5s 让床浮起.
输出:
  output/football_forever_ch1/football_forever_ch1_v6_emotion_44k1.wav   (干声)
  output/football_forever_ch1/football_forever_ch1_v6_musicbed_44k1.wav  (床版)
  scratch/football_test/v6/synth_summary_v6.json
用法: --check 只打印导演标注表 + DIRECT 覆盖断言 + 床分段(不加载 Kokoro)
"""
import hashlib, json, os, re, subprocess, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
V6 = WORK / "v6"; V6.mkdir(exist_ok=True)
OUT = ROOT / "output" / "football_forever_ch1"
TARGET_LUFS = -23.0
BED_LUFS = -26.0
CHAIN = "alimiter=limit=0.6457:attack=5:release=100:level=disabled"
SR = 24000
SR44 = 44100
CHECK_ONLY = "--check" in sys.argv

# ── 停顿架构 (v5 全套 + v6 戏剧覆盖) ──────────────────────────────
MICRO_GAP = 0.22
GAPS = {"narr_sent": 0.70, "narr_para": 2.50, "turn_same": 0.60, "turn_same_coach": 0.45,
        "turn_diff": 0.80, "para_same": 0.50, "para_diff": 0.80,
        "para_d2n": 1.30, "para_n2d": 1.00}
PARA_OVR = {25: 2.2, 34: 2.0}                      # 父亲缺席→Sshh 大拍; 走出更衣室
SENT_OVR = {(14, 5): 0.9, (34, 11): 1.0}           # Tino 被点名前; 最后一句"I know..."前

# ── 选角 (v5) + v6 教练混血双态 ──────────────────────────────────
VOICE = {"narrator": ("am_adam", 0.80), "coach": ("am_onyx+am_fenrir", 0.82),
         "lenda": ("am_echo", 0.80), "nakano": ("am_liam", 0.80),
         "players": ("am_liam", 0.85), "tino": ("am_puck", 0.78),
         "mother": ("af_nicole", 0.85), "lenda_thought": ("am_echo", 0.78)}
BLEND_W = {"am_onyx+am_fenrir": {"normal": (0.65, 0.35), "hot": (0.55, 0.45)}}
CALIB_CAP = {"af_nicole": 3.0}                      # 母亲: 校准封顶 +3 (回忆声刻意退后)
CITATIONS = {"We", "Zangado", "angry", "TINO"}
LINE_OVR = {
    (14, 0): {"speaker": "coach"},   # OK. You're on.
    (14, 5): {"speaker": "coach"},   # Tino, are you ready?
    (16, 0): {"speaker": "coach"},   # Yes, you. You're the only Tino here.
    (18, 0): {"speaker": "coach"},   # OK. You're up front, with Lenda...
}

def hot_vk(base, hot):
    return base + "_hot" if hot else base  # cache key 区分, 底层同源

# ── v6 逐句导演表: (pi,si) -> (gain_dB, speed, pitch_st, hot) ──────
DIRECT = {
    (0, 0):  (4.0, 0.86, 1.0, True),    # coach: Bad! Very bad! (冷开场怒吼)
    (3, 0):  (4.5, 0.86, 1.2, True),    # coach: Bad! Very bad! (再吼, 更狠)
    (4, 0):  (3.5, 0.84, 0.8, True),    # coach: We must win this game!
    (9, 0):  (2.0, 0.82, 0.4, False),   # coach: OK,
    (9, 1):  (2.0, 0.82, 0.4, False),   # coach: I want much more from all of you...
    (11, 0): (1.5, 0.82, 0.2, False),   # coach: You and you,
    (11, 1): (1.5, 0.82, 0.2, False),   # coach: You worked well, but I'm making two changes.
    (12, 0): (1.5, 0.82, 0.2, False),   # coach: Nakano, are you ready?
    (13, 0): (0.5, 0.82, 0.3, False),   # nakano: Yes, coach,
    (14, 0): (2.0, 0.84, 0.4, False),   # coach: OK. You're on.
    (14, 5): (2.0, 0.82, 0.4, False),   # coach: Tino, are you ready?
    (15, 0): (-2.5, 0.74, -1.2, False), # tino: Who, me? (怯场最低点)
    (16, 0): (1.5, 0.82, 0.3, False),   # coach: Yes, you. You're the only Tino here.
    (17, 0): (-2.0, 0.76, -1.0, False), # tino: Er, yes, coach. I'm ready.
    (18, 0): (2.5, 0.84, 0.5, False),   # coach: OK. You're up front, with Lenda...
    (19, 0): (-1.5, 0.78, -0.8, False), # tino: Yes, coach.
    (20, 2): (-3.5, 0.76, -1.0, False), # lenda_thought: Who is this boy? (内心)
    (22, 1): (-1.0, 0.85, -0.5, False), # mother: Here, Tino, take this for luck...
    (24, 0): (1.0, 0.86, 0.6, False),   # coach: Sshh! Now listen to me, (锐利低语)
    (26, 1): (1.5, 0.82, 0.5, False),   # lenda: He's right,
    (26, 2): (2.0, 0.84, 0.8, False),   # lenda: The game isn't finished. We can do it.
    (27, 0): (3.0, 0.84, 0.8, True),    # coach: But do you want to win? (怒态)
    (28, 0): (1.0, 0.84, 0.5, False),   # players: Yes, (半心半意)
    (29, 0): (3.5, 0.86, 1.0, True),    # coach: I can't hear you, (怒)
    (29, 1): (4.0, 0.86, 1.2, True),    # coach: Do you want to win? (怒态峰值)
    (30, 0): (3.5, 0.86, 1.2, False),   # players: Yes! (第一次全队)
    (31, 0): (3.5, 0.86, 1.0, True),    # coach: And can you do it? (怒)
    (32, 0): (4.0, 0.88, 1.5, False),   # players: Yes! (最响)
    (33, 0): (3.5, 0.86, 1.2, False),   # lenda: Come on, we can do it!
    (33, 2): (4.0, 0.88, 1.5, False),   # lenda: OK, let's go! (最高点)
    (34, 10): (-4.0, 0.76, -0.8, False), # tino: Come on, Tino! (自语)
}

# ── v6 长训话逐段导演: (25,0) 教练大训话拆三段 (词流不变) ───────────
# 元组: (text, gain_dB, speed, pitch_st, hot, gap_after)
SPEECH_SPLIT = {
    (25, 0): [
        ("It isn't finished. OK, we're two-nil down. Not good. But we've got forty-five minutes. Anything can happen in football, you know that.", 1.5, 0.80, 0.3, False, 0.35),
        ("Stars is a good team; Stripes is an OK team. They've got one good player: their keeper. He's a big man and he can stop a lot, but he's only one man.", 2.5, 0.83, 0.6, False, 0.30),
        ("Let's play our game. Move the ball and work for the team. Don't stand and think. Play with your feet, and when you can, shoot! This is Brazilian football. It's easy!", 3.5, 0.86, 1.0, True, None),
    ],
}

# ── v6 旁白关键词导演: 关键词 -> (gain_dB, speed, pitch_st), 先匹配先赢 ──
NARR_RULES = [
    ("i know i can do it", (1.5, 0.82, 0.6)),        # 全篇收束句
    ("he doesn't want to come", (-2.0, 0.77, -0.8)), # 父亲缺席
    ("my mother gave", (-1.5, 0.78, -0.5)),           # 母亲回忆
    ("i love my mother", (-1.5, 0.78, -0.5)),
    ("little star", (-1.5, 0.78, -0.5)),
    ("isn't here today", (-1.5, 0.78, -0.5)),
    ("very happy and excited", (1.0, 0.82, 0.5)),    # 20号球衣
    ("for good luck", (-1.0, 0.79, -0.4)),            # 左袜幸运星
    ("butterflies", (0.5, 0.81, 0.3)),                # 出场前紧张
    ("very quiet", (-2.5, 0.77, -0.5)),               # Sshh 后全场安静
    ("big clock", (-2.5, 0.77, -0.5)),                # 只听见大钟
    ("eat and drink football", (1.5, 0.84, 0.6)),     # Tino 自我介绍燃
    ("beautiful game", (1.5, 0.84, 0.6)),
    ("i can play forever", (1.5, 0.84, 0.6)),
    ("fast game", (1.5, 0.84, 0.6)),
    ("very happy to be here", (1.5, 0.84, 0.6)),
    ("thousands and thousands", (1.0, 0.82, 0.4)),    # 球场规模
    ("noise is amazing", (1.0, 0.82, 0.4)),
    ("very, very big", (1.0, 0.82, 0.4)),
    ("nobody answers", (-1.5, 0.77, -0.6)),           # 更衣室低气压
    ("looking down", (-1.5, 0.77, -0.6)),
    ("could do nothing", (-1.5, 0.77, -0.6)),         # 替补席无力
    ("ouch", (-1.5, 0.77, -0.6)),                     # 半场落后
    ("one-nil down", (-1.5, 0.77, -0.6)),
    ("two-nil down", (-1.0, 0.79, -0.4)),
    ("losing two-nil", (-0.5, 0.79, -0.3)),
    ("feel my hands get hot", (-0.5, 0.79, 0.2)),     # 被点名的紧绷
    ("walk out of the changing room", (0.5, 0.81, 0.4)), # 出场
    ("all of the players shout", (1.0, 0.82, 0.4)),   # 全队应和
]

def narr_director(text):
    tl = text.lower()
    for key, (g, spd, pit) in NARR_RULES:
        if key in tl:
            return g, spd, pit, key
    return 0.0, 0.80, 0.0, None

# ── 文本解析 (v5 逐字复用) ──────────────────────────────────────
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
                out.append((inner, False))        # 提名引号 -> 旁白
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

def norm_words(t):
    return re.sub(r"[^A-Za-z0-9]+", " ", t).upper().split()

# ── 构建 flat（展平待合成单元，含 split/gap_after/loc）─────────────
def build_flat(paras, units):
    flat = []
    sent_count = {}  # (pi,si) -> 该句全部 flat 件数 (含 narr 件)
    for pi, punits in enumerate(units):
        for si, u in enumerate(punits):
            nsegs = len(u["segs"])
            cnt = 0
            for k, (t, q) in enumerate(u["segs"]):
                if q:
                    sp = u["seg_spk"][k] or "narrator"
                    base_vk = VOICE[sp][0]
                    key = (pi, si)
                    if key in SPEECH_SPLIT:
                        for txt, g, spd, pit, hot, ga in SPEECH_SPLIT[key]:
                            flat.append({"vk": hot_vk(base_vk, hot), "spd": spd, "emo": g,
                                         "pitch": pit, "text": txt, "sp": sp,
                                         "gap_after": ga if ga is not None else 0.0,
                                         "loc": (pi, si, k)})
                            cnt += 1
                    elif key in DIRECT:
                        g, spd, pit, hot = DIRECT[key]
                        ga = MICRO_GAP if k < nsegs - 1 else 0.0
                        flat.append({"vk": hot_vk(base_vk, hot), "spd": spd, "emo": g,
                                     "pitch": pit, "text": t, "sp": sp,
                                     "gap_after": ga, "loc": (pi, si, k)})
                        cnt += 1
                    else:
                        # DIRECT/SPLIT 未覆盖: 占位件 (check 打印, full run 报错退出)
                        flat.append({"vk": None, "spd": 0.80, "emo": 0.0, "pitch": 0.0,
                                     "text": t, "sp": sp, "gap_after": 0.0,
                                     "loc": (pi, si, k)})
                        cnt += 1
                else:
                    g, spd, pit, hit_key = narr_director(t)
                    ga = MICRO_GAP if k < nsegs - 1 else 0.0
                    flat.append({"vk": "am_adam", "spd": spd, "emo": g, "pitch": pit,
                                 "text": t, "sp": "narrator", "gap_after": ga,
                                 "loc": (pi, si, k), "hit_rule": hit_key})
                    cnt += 1
            sent_count[(pi, si)] = cnt
    return flat, sent_count

def main():
    paras, units = parse_markup()
    src_words = norm_words(" ".join(paras))
    n_sent = sum(len(u) for u in units)

    # 构建 flat + 词流断言
    flat, sent_count = build_flat(paras, units)
    # 检查 DIRECT 覆盖 & 无 None vk
    missing = []
    for f in flat:
        if f.get("vk") is None:
            pi, si, k = f["loc"]
            missing.append((pi, si))
    if missing:
        uniq = sorted(set(missing))
        print(f"[v6] ERROR: DIRECT/SPLIT 未覆盖引语句: {uniq}")
        if not CHECK_ONLY:
            sys.exit(1)
    # 词流一致性（split 后 norm 词流等于原文）
    flat_words = [w for f in flat for w in norm_words(f["text"])]
    if flat_words != src_words:
        print(f"[v6] ERROR: 词流失配: flat={len(flat_words)} src={len(src_words)}")
        # 找首个差异
        for i, (fw, sw) in enumerate(zip(flat_words, src_words)):
            if fw != sw:
                print(f"  首差异 idx={i}: flat='{fw}' vs src='{sw}'")
                break
        else:
            if len(flat_words) != len(src_words):
                print(f"  长度不同: flat={len(flat_words)} src={len(src_words)}")
        if not CHECK_ONLY:
            sys.exit(1)

    if CHECK_ONLY:
        print(f"[v6] {len(paras)} paras / {n_sent} sents / {len(flat)} pieces / {len(src_words)} words")
        # 逐段打印导演标注
        fi = 0
        for pi, punits in enumerate(units):
            for si, u in enumerate(punits):
                for j in range(sent_count[(pi, si)]):
                    f = flat[fi]; fi += 1
                    if f.get("vk") is None:
                        print(f"  P{pi}S{si} [!! MISSING DIRECT] | {f['text'][:68]}")
                    elif "hit_rule" in f:
                        rule = f["hit_rule"] or "default"
                        print(f"  P{pi}S{si} [narr          ] rule={rule} g={f['emo']:+.1f} v={f['spd']} p={f['pitch']:+.1f} | {f['text'][:68]}")
                    else:
                        hot = f["vk"].endswith("_hot")
                        src = "SPLIT" if (pi, si) in SPEECH_SPLIT else "DIRECT"
                        print(f"  P{pi}S{si} [{f['sp']:<13}] {src} g={f['emo']:+.1f} v={f['spd']} p={f['pitch']:+.1f} hot={hot} | {f['text'][:68]}")
        print(f"\nDIRECT 覆盖: {len(DIRECT)} 条 | SPEECH_SPLIT: {len(SPEECH_SPLIT)} 句")
        # 床分段概览
        print("\n床分段:")
        print("  A  P1..P8     [Am,F,Am,E]          -27.5dB")
        print("  B  P9..P19    [C,G,Am,F]           -27.0dB")
        print("  C  P20..P24   [F,G,Am,Am]          -29.0dB")
        print("  D1 P25..P26   [Am5]                -31.0dB (压场)")
        print("  D2 P27..P33   [Am,G,F,G]           -30→-25.5dB (渐强)")
        print("  E  P34..end   [C,G,Am,F]           -25.0dB + 尾声 Cadd9")
        print("  BED_IN = para_t[1][0] - 1.8s (冷开场无床)")
        print("  心跳: P14→P22 @-12rel | P27→P34 渐强 -11→-6rel")
        print("  人群: P34→尾声 @-6rel 淡入 3s")
        print("  duck: thr -42dBFS depth -14dB att 0.18s rel 0.7s | 床 solo -26 LUFS")
        print("V6_CHECK_DONE")
        return

    # ── 合成 (Kokoro) ──────────────────────────────────────────────
    from kokoro_onnx import Kokoro
    ko = Kokoro(str(ROOT / "models/kokoro-v1.0.onnx"), str(ROOT / "models/voices-v1.0.bin"))
    blends = {}
    def style(vk):
        if "+" in vk:
            if vk not in blends:
                hot = vk.endswith("_hot")
                base = vk[:-4] if hot else vk
                a, b = base.split("+")
                w = BLEND_W[base]["hot" if hot else "normal"]
                blends[vk] = (w[0] * ko.get_voice_style(a) + w[1] * ko.get_voice_style(b)).astype(np.float32)
            return blends[vk]
        return vk

    cache_f = V6 / "pieces_cache.npz"
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
    print(f"[v6] synth {len(pieces)} pieces / {synth_s:.0f}s (cache {len(cache)})")

    # ── 音调轴: ffmpeg asetrate+atempo 带式移位 (消融: 4.47 vs librosa 相位声码器 1.33) ──
    import tempfile
    _pitch_warned = False
    def apply_pitch(a, st):
        nonlocal _pitch_warned
        if abs(st) < 0.001:
            return a
        try:
            rate_f = 2 ** (st / 12.0)          # asetrate 因子
            tempo_f = 2 ** (-st / 12.0)        # atempo 补偿(时长复原)
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                in_f = tf.name
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tf:
                out_f = tf.name
            try:
                sf.write(in_f, a, SR, subtype="FLOAT")
                af = f"asetrate={SR}*{rate_f:.6f},atempo={tempo_f:.6f},aresample={SR}"
                r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", in_f, "-af", af,
                                     "-c:a", "pcm_f32le", "-ar", str(SR), out_f],
                                    capture_output=True, text=True)
                if r.returncode != 0:
                    raise RuntimeError(r.stderr[-200:])
                y, _ = sf.read(out_f)
                return y.astype(np.float32)
            finally:
                for f_ in (in_f, out_f):
                    try: os.unlink(f_)
                    except OSError: pass
        except Exception as e:
            if not _pitch_warned:
                print(f"[v6] WARN pitch_shift failed ({e}); 保留未移位音频"); _pitch_warned = True
            return a

    pitch_pieces = []
    n_pitch = 0
    for i, f in enumerate(flat):
        p = apply_pitch(pieces[i], f["pitch"])
        if p is not pieces[i]:
            n_pitch += 1
        pitch_pieces.append(p)
    print(f"[v6] pitch applied to {n_pitch} pieces")

    # ── 每音色中位 RMS 校准 (±4dB, 母亲 3dB 封顶) ──────────────────
    med = {}
    for f, p in zip(flat, pitch_pieces):
        med.setdefault(f["vk"], []).append(float(np.sqrt(np.mean(p ** 2))))
    ref = float(np.median(med["am_adam"]))
    calib = {}
    for vk, v in med.items():
        cap = CALIB_CAP.get(vk, 4.0)
        d = 20 * np.log10(ref / float(np.median(v)))
        calib[vk] = float(np.clip(d, -cap, cap))
    print("[v6] per-voice calib dB:", {k: round(v, 2) for k, v in calib.items()})

    # ── 组装 (按 sent_count 同序消费, 记录 para_t) ────────────────
    audio_parts = []
    gap_total = 0.0
    speech_sec = 0.0
    cur_n = 0
    para_t = []  # [(start_s, end_s), ...] 35 段
    fi = 0

    def _gap(sec):
        audio_parts.append(np.zeros(int(SR * sec), dtype=np.float32))
        return sec

    for pi, punits in enumerate(units):
        para_start = cur_n
        for si, u in enumerate(punits):
            # 段/句间隙
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
                g = PARA_OVR.get(pi, g)
                gap_total += _gap(g); cur_n += int(SR * g)
                para_start = cur_n               # 段语音起点 (间隙后, 供床对时)
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
                g = SENT_OVR.get((pi, si), g)
                gap_total += _gap(g); cur_n += int(SR * g)

            # 消费该句的所有 flat 件
            cnt = sent_count[(pi, si)]
            for j in range(cnt):
                f = flat[fi]; fi += 1
                a = pitch_pieces[fi - 1] * (10 ** ((calib[f["vk"]] + f["emo"]) / 20))
                audio_parts.append(a)
                speech_sec += len(a) / SR
                cur_n += len(a)
                ga = f["gap_after"]
                if ga:
                    gap_total += _gap(ga); cur_n += int(SR * ga)
        para_t.append([para_start / SR, cur_n / SR])

    assert fi == len(flat), f"flat 消费失配 {fi}/{len(flat)}"
    audio = np.concatenate(audio_parts)
    dur = len(audio) / SR
    words_total = len(" ".join(paras).split())
    wpm_phon = words_total / speech_sec * 60
    wpm_tot = words_total / dur * 60
    print(f"[v6] dur {dur:.1f}s (speech {speech_sec:.1f} + gaps {gap_total:.1f}) wpm {wpm_phon:.1f}/{wpm_tot:.1f}")

    # ── 干声链: alimiter -> soxr VHQ -> ebur128 -> 精确 -23 LUFS -> s16 ──
    native_f = V6 / "native_24k_float.wav"
    sf.write(str(native_f), audio, SR, subtype="FLOAT")
    lim_f = V6 / "lim_24k_float.wav"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(native_f), "-af", CHAIN,
                        "-c:a", "pcm_f32le", "-ar", str(SR), str(lim_f)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"limiter failed: {r.stderr[-300:]}")
    lim, _ = sf.read(str(lim_f))
    import soxr
    speech44 = soxr.resample(lim.astype(np.float32), SR, SR44, quality="VHQ")

    # 干声 ebur128 测量 -> 增益到 -23
    def measure_lufs(path):
        r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                            "-af", "ebur128=peak=true", "-f", "null", "-"],
                           capture_output=True, text=True)
        err = r.stderr[r.stderr.find("Summary:"):]
        lufs = float(re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", err).group(1))
        tp = float(re.search(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", err).group(1))
        return lufs, tp

    tmp44 = V6 / "pre_gain_44k1.wav"
    sf.write(str(tmp44), speech44, SR44, subtype="FLOAT")
    lufs_pre, tp_pre = measure_lufs(tmp44)
    gain_db = TARGET_LUFS - lufs_pre
    dry44 = speech44 * (10 ** (gain_db / 20))
    dry_wav = OUT / "football_forever_ch1_v6_emotion_44k1.wav"
    sf.write(str(dry_wav), dry44, SR44, subtype="PCM_16")
    lufs_dry, tp_dry = measure_lufs(dry_wav)
    print(f"[v6] dry deliverable: {dur:.1f}s {lufs_dry:.1f} LUFS TP {tp_dry:.1f} (gain {gain_db:+.1f}dB)")

    # ── 音乐床合成 (程序化 pad + 心跳 + 人群 + 混响) ──────────────
    speech_end = cur_n / SR
    total_s = speech_end + 8.5
    total_n = int(total_s * SR44)
    bed_in = para_t[1][0] - 1.8
    print(f"[v6] bed: {bed_in:.1f}s -> {total_s:.1f}s (speech_end={speech_end:.1f}s)")

    def midi_hz(m): return 440.0 * 2 ** ((m - 69) / 12)

    # 和弦字典
    CHORDS = {
        "Am": [45,57,60,64], "F": [41,53,57,60], "C": [48,55,60,64], "G": [43,55,59,62],
        "E": [40,52,56,59], "Am5": [45,57,64], "Cadd9": [48,55,62,64],
    }

    def synth_pad_chord(n_samples, notes, sr=SR44):
        t = np.arange(n_samples) / sr
        out = np.zeros(n_samples, dtype=np.float32)
        for m in notes:
            f = midi_hz(m)
            for sign in (+1, -1):
                fd = f * (1 + sign * 0.0012)          # 双失谐 ±0.12%
                w = 2*np.pi*fd*t
                out += np.sin(w) + 0.45*np.sin(2*w) + 0.22*np.sin(3*w)
        out /= (len(notes) * 2)
        return out.astype(np.float32)

    def bandpass_fft(x, sr, lo, hi, trans=30):
        X = np.fft.rfft(x)
        f = np.fft.rfftfreq(len(x), 1/sr)
        g = np.ones_like(f)
        g[f < lo] = 0; g[f > hi] = 0
        m1 = (f >= lo) & (f < lo+trans)
        if np.any(m1): g[m1] = 0.5*(1 - np.cos(np.pi*(f[m1]-lo)/trans))
        m2 = (f > hi-trans) & (f <= hi)
        if np.any(m2): g[m2] = 0.5*(1 + np.cos(np.pi*(f[m2]-(hi-trans))/trans))
        return np.fft.irfft(X*g, n=len(x)).astype(np.float32)

    def env_db(total_n, sr, windows):
        """windows: list of (t0, t1, db0, db1, edge_in, edge_out)"""
        t = np.arange(total_n) / sr
        lin = np.zeros(total_n, dtype=np.float32)
        for t0, t1, d0, d1, ei, eo in windows:
            m = (t >= t0) & (t <= t1)
            if not np.any(m): continue
            frac = (t[m] - t0) / max(t1 - t0, 1e-6)
            db = d0 + (d1 - d0) * frac
            # 边沿升余弦收边
            edge_m = np.ones_like(db)
            if ei > 0:
                fi = (t[m] - t0) / ei
                fi = np.clip(fi, 0, 1)
                edge_m *= 0.5 * (1 - np.cos(np.pi * fi))
            if eo > 0:
                fo = (t1 - t[m]) / eo
                fo = np.clip(fo, 0, 1)
                edge_m *= 0.5 * (1 - np.cos(np.pi * fo))
            lin[m] = 10 ** (db / 20) * edge_m
        return lin

    # ── pad timeline: 段落区间 -> 和弦序列/电平 ──
    pad_timeline = [
        # (t0, t1, [chord_names...], [dB...])
        (para_t[1][0], para_t[8][1], ["Am","F","Am","E"], [-27.5]*4),
        (para_t[9][0], para_t[19][1], ["C","G","Am","F"], [-27.0]*4),
        (para_t[20][0], para_t[24][1], ["F","G","Am","Am"], [-29.0]*4),
        (para_t[25][0], para_t[26][1], ["Am5"], [-31.0]),
        (para_t[27][0], para_t[33][1], ["Am","G","F","G"], [-30.0,-28.5,-27.0,-25.5]),
        (para_t[34][0], speech_end + 1.0, ["C","G","Am","F"], [-25.0]*4),
    ]

    pad = np.zeros(total_n, dtype=np.float32)
    for t0, t1, chords, dbs in pad_timeline:
        t0_n = int(t0 * SR44); t1_n = int(t1 * SR44)
        seg_n = t1_n - t0_n
        ch_n = seg_n / len(chords)
        for ci, (ch, db) in enumerate(zip(chords, dbs)):
            cs = t0_n + int(ci * ch_n)
            n_ch = int(ch_n + 2.5*SR44)          # 含 2.5s 淡出尾
            n_ch = min(n_ch, total_n - cs)
            if n_ch <= 0: continue
            w = synth_pad_chord(n_ch, CHORDS[ch])
            # 淡出 2.5s 升余弦
            fo = int(2.5*SR44)
            env = np.ones(n_ch, dtype=np.float32)
            if n_ch >= fo:
                env[-fo:] = 0.5*(1 + np.cos(np.linspace(0, np.pi, fo)))
            # 非首个和弦: 淡入 2.5s
            fi = int(2.5*SR44)
            if ci > 0 and n_ch >= fi:
                env[:fi] = 0.5*(1 - np.cos(np.linspace(0, np.pi, fi)))
            pad[cs:cs+n_ch] += w * env * (10 ** (db / 20))

    # LFO 0.08Hz 深度 0.12
    t_bed = np.arange(total_n) / SR44
    lfo = 1 - 0.12 * (0.5 + 0.5 * np.sin(2*np.pi*0.08*t_bed))
    pad *= lfo.astype(np.float32)

    # FFT 带通 65–2200Hz
    pad = bandpass_fft(pad, SR44, 65, 2200)

    # ── 心跳 lub-dub 62BPM ──
    def build_heartbeat(total_n, sr, bpm=62):
        beat = int(sr * 60 / bpm)
        f = 48.0
        def thump(dur, amp):
            n = int(dur*sr); t = np.arange(n)/sr
            e = np.exp(-t/0.10)
            return (amp*np.sin(2*np.pi*f*t)*e).astype(np.float32)
        lub = thump(0.32, 1.0); dub = thump(0.26, 0.6)
        out = np.zeros(total_n, dtype=np.float32)
        k = 0
        while k*beat + len(lub) + int(0.24*sr) < total_n:
            s = k*beat
            out[s:s+len(lub)] += lub
            d = s + int(0.24*sr)
            out[d:d+len(dub)] += dub
            k += 1
        return out

    hb0 = build_heartbeat(total_n, SR44)
    # 心跳窗: P14→P22 @-12rel, P27→P34 渐强 -11→-6rel
    hb_env = env_db(total_n, SR44, [
        (para_t[14][0], para_t[22][0], -12, -12, 0.4, 0.4),
        (para_t[27][0], para_t[34][0], -11, -6, 0.4, 0.4),
    ])
    hb = hb0 * hb_env

    # ── 人群带通噪声 ──
    def build_crowd(total_n, sr):
        rng = np.random.RandomState(42)
        x = rng.randn(total_n)
        b = bandpass_fft(x, sr, 350, 1400)
        hi = bandpass_fft(x, sr, 2000, 4000) * 0.3
        y = b + hi
        # 慢随机幅度调制 (0.5Hz 平滑)
        mod_n = int(total_n / (sr*2)) + 2
        mod_t = np.arange(mod_n) * 2.0
        mod_v = 0.7 + 0.3 * rng.rand(mod_n)
        mod = np.interp(t_bed, mod_t, mod_v)
        return (y * mod).astype(np.float32)

    crowd0 = build_crowd(total_n, SR44)
    crowd_env = env_db(total_n, SR44, [
        (para_t[34][0], total_s, -6, -6, 3.0, 0.0),   # 淡入 3s
    ])
    crowd = crowd0 * crowd_env

    # ── 床干声求和 -> Schroeder 混响 wet 0.18 ──
    bed_dry = pad + hb + crowd

    from scipy.signal import lfilter
    def schroeder_rev(x, sr):
        combs = [1601, 1613, 1487, 1277]     # 样本 @44.1k
        aps = [225, 556]
        y = np.zeros_like(x)
        for D in combs:
            g = 0.84
            a = np.zeros(D+1); a[0]=1; a[-1]=-g
            y += lfilter([1.0], a, x)
        y /= len(combs)
        for D in aps:
            g = 0.5
            b = np.zeros(D+1); b[0]=-g; b[-1]=1
            a = np.zeros(D+1); a[0]=1; a[-1]=-g
            y = lfilter(b, a, y)
        return y

    bed_rev = schroeder_rev(bed_dry, SR44)
    bed = 0.82 * bed_dry + 0.18 * bed_rev

    # 床整体淡入/淡出 (BED_IN 1.5s 淡入, 末 4.5s 淡出)
    fade = np.ones(total_n, dtype=np.float32)
    bi_n = int(bed_in * SR44)
    fi_n = int((bed_in + 1.5) * SR44)
    if fi_n > bi_n:
        fade[bi_n:fi_n] = 0.5*(1 - np.cos(np.linspace(0, np.pi, fi_n-bi_n)))
    fo_n = int((total_s - 4.5) * SR44)
    if fo_n < total_n:
        fade[fo_n:] = 0.5*(1 + np.cos(np.linspace(0, np.pi, total_n-fo_n)))
    bed *= fade

    # ── 床 solo 标定到 -26 LUFS ──
    bed_f = V6 / "bed_solo_44k1.wav"
    sf.write(str(bed_f), bed, SR44, subtype="FLOAT")
    bed_lufs, _ = measure_lufs(bed_f)
    bed_gain = BED_LUFS - bed_lufs
    bed *= 10 ** (bed_gain / 20)
    print(f"[v6] bed solo: {bed_lufs:.1f} LUFS -> gain {bed_gain:+.1f}dB -> {BED_LUFS:.1f} LUFS")

    # ── 声码侧链 duck: 从 speech44 计算 RMS 包络 ──
    hop = int(SR44 * 0.02)                     # 20ms hop
    n_hop = (len(speech44) + hop - 1) // hop
    rms = np.zeros(n_hop)
    for i in range(n_hop):
        s = speech44[i*hop:(i+1)*hop]
        rms[i] = np.sqrt(np.mean(s**2) + 1e-12)
    db = 20 * np.log10(rms)
    act = db > -42.0
    # 一阶环: attack 0.18s / release 0.7s
    a_c = 1 - np.exp(-0.02/0.18)
    r_c = 1 - np.exp(-0.02/0.7)
    g = np.zeros(n_hop)
    cur = 0.0
    for i in range(n_hop):
        tgt = -14.0 if act[i] else 0.0
        c = a_c if tgt < cur else r_c
        cur += c * (tgt - cur)
        g[i] = cur
    env = 10 ** (g / 20)
    # 上采样到 full length, speech 后继续 release 到 1
    duck_full = np.ones(total_n, dtype=np.float32)
    t_hop = np.arange(n_hop) * hop
    duck_full[:len(speech44)] = np.interp(np.arange(len(speech44)), t_hop, env)
    # speech 后: 继续一阶环到 1
    for i in range(len(speech44), total_n):
        if i % hop == 0:
            cur += r_c * (0.0 - cur)
        duck_full[i] = 10 ** (cur / 20)

    # ── 混音: speech44 + bed*duck -> ebur128 -> -23 LUFS -> s16 ──
    mix = np.zeros(total_n, dtype=np.float32)
    mix[:len(speech44)] += speech44
    mix += bed * duck_full
    # 安全 clip
    mix = np.clip(mix, -1.0, 1.0)

    mix_f = V6 / "mix_pre_gain_44k1.wav"
    sf.write(str(mix_f), mix, SR44, subtype="FLOAT")
    mix_lufs, _ = measure_lufs(mix_f)
    mix_gain = TARGET_LUFS - mix_lufs
    mix_out = mix * (10 ** (mix_gain / 20))
    mix_out = np.clip(mix_out, -1.0, 1.0)
    bed_wav = OUT / "football_forever_ch1_v6_musicbed_44k1.wav"
    sf.write(str(bed_wav), mix_out, SR44, subtype="PCM_16")
    lufs_bed, tp_bed = measure_lufs(bed_wav)
    print(f"[v6] bed deliverable: {total_s:.1f}s {lufs_bed:.1f} LUFS TP {tp_bed:.1f} (mix_gain {mix_gain:+.1f}dB)")

    # ── casting 统计 ──
    casting = {}
    for sp in sorted({f["sp"] for f in flat}):
        lines = sum(1 for f in flat if f["sp"] == sp)
        casting[sp] = {"voice": VOICE.get(sp, ("am_adam",))[0], "lines": lines}

    # ── summary ──
    summary = {
        "version": "v6_emotion_musicbed",
        "words": words_total,
        "pieces": len(pieces),
        "n_split": sum(len(v) for v in SPEECH_SPLIT.values()),
        "n_pitch": n_pitch,
        "pitch_range": {"min": min(f["pitch"] for f in flat), "max": max(f["pitch"] for f in flat)},
        "gain_range": {"min": min(f["emo"] for f in flat), "max": max(f["emo"] for f in flat)},
        "synth_wall_s": round(synth_s, 1),
        "audio_sec": round(dur, 1),
        "speech_sec": round(speech_sec, 1),
        "gap_sec": round(gap_total, 1),
        "wpm_phonation": round(wpm_phon, 1),
        "wpm_overall": round(wpm_tot, 1),
        "per_voice_calib_db": {k: round(v, 2) for k, v in calib.items()},
        "casting": casting,
        "gaps": GAPS, "micro_gap": MICRO_GAP,
        "para_ovr": PARA_OVR,
        "sent_ovr": {f"P{k[0]}S{k[1]}": v for k, v in SENT_OVR.items()},
        "bed": {
            "solo_lufs": round(bed_lufs, 1),
            "bed_in_s": round(bed_in, 1),
            "sections": ["A P1..P8", "B P9..P19", "C P20..P24", "D1 P25..P26", "D2 P27..P33", "E P34..end", "TAIL Cadd9"],
            "heartbeat_windows": ["P14→P22 @-12rel", "P27→P34 -11→-6rel"],
            "crowd": "P34→end @-6rel fade-in 3s",
            "duck": {"thr_dbfs": -42, "depth_db": -14, "att_s": 0.18, "rel_s": 0.7, "min_gain": round(np.min(env), 3)},
        },
        "lufs_dry": round(lufs_dry, 1), "tp_dry": round(tp_dry, 1),
        "lufs_bed": round(lufs_bed, 1), "tp_bed": round(tp_bed, 1),
        "chain": CHAIN,
        "deliverables": {"dry": str(dry_wav), "bed": str(bed_wav)},
    }
    (V6 / "synth_summary_v6.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("V6_DONE " + json.dumps(summary))

if __name__ == "__main__":
    main()

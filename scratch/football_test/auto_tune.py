"""Football Forever ch1 — 对照原声的自动调参粗网格 (设计已获同意 2026-10-09)

硬约束: 交付响度 −23.0 LUFS (精确增益; |Δ|>0.5 → 1000 罚分)
loss = 10|wpm_phon−165.3| + 5|wpm_overall−102.8| + 5|pause_budget−159|
     + 2|pause_median−0.62| + 2|pause_p90−1.20|   ← 停顿分布代理项 (ref 停顿时长
       明细未落盘; 全 KL/JSD 留给子句级停顿建模升级)
     − 50·UTMOS(chunked) + 200·WER
网格: speed {0.70,0.75,0.80} × sent_gap {0.7,0.9,1.1} × para_gap {1.5,2.0,2.5} = 27
合成: kokoro 语句片段按 speed 缓存 (npz) → 27 组装只是静音拼接, 昂贵合成只跑 3 次
链路: 与 v3 完全一致 (v4 alimiter 链 @24k float → soxr VHQ 44.1k → 精确增益 → s16)
评测: UTMOS 30s 分块 (worker_utmos_chunked, 9 文件/批) + SenseVoice WER (asr_batch_proc)
断点续跑: stage1/utmos/wer 各自 JSON 落盘, 重跑跳过已完成; v3 基准组合先跑并
  与 v3 实测自校验 (不符即 FATAL 停跑, 防管线漂移烧 2h)
4 核机器 + 用户并存任务 → 全程顺序评测 (已批准设计的"可用并行"在此环境降级为
  顺序: funasr/torch 并发原生库 segv 风险 + 内存压力)
已知口径偏差 (结果解读时说明): wpm_phonation 用合成口径 (words/Σ句长), 系统性
  比原声 VAD 口径慢读 ~4%; 网格内候选同偏差, 排序不受影响。
"""
import json, os, re, shutil, subprocess, sys, time
from pathlib import Path
import numpy as np
import soundfile as sf
import soxr

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "scratch" / "football_test"
TUNE = WORK / "auto_tune"; TUNE.mkdir(parents=True, exist_ok=True)
WAVS = TUNE / "wavs"; WAVS.mkdir(exist_ok=True)
CACHE = TUNE / "cache"; CACHE.mkdir(exist_ok=True)
HYPD = TUNE / "hyps"; HYPD.mkdir(exist_ok=True)
OUT = ROOT / "output" / "football_forever_ch1"; OUT.mkdir(parents=True, exist_ok=True)
PY = ROOT / ".venv" / "bin" / "python"
UTMOS_WORKER = WORK / "worker_utmos_chunked.py"
ASR_BATCH = WORK / "asr_batch_proc.py"
ENV = {**os.environ, "KMP_DUPLICATE_LIB_OK": "TRUE"}

SPEEDS = [0.70, 0.75, 0.80]
SENT_GAPS = [0.7, 0.9, 1.1]
PARA_GAPS = [1.5, 2.0, 2.5]
V3_COMBO = (0.75, 0.9, 2.0)
TARGET_LUFS = -23.0
CHAIN = "alimiter=limit=0.6457:attack=5:release=100:level=disabled"  # P0.1 v4 链原样
BATCH = 9

# 原声标定 (v3/synth_summary_v3.json ref_calibration + 停顿分布实测)
REF = {"wpm_phonation": 165.3, "wpm_overall": 102.8, "pause_budget_s": 159.0,
       "pause_median_s": 0.62, "pause_p90_s": 1.20, "lufs": -22.7, "tp": -3.8}
W = {"wpm_phon": 10.0, "wpm_overall": 5.0, "pause": 5.0,
     "median": 2.0, "p90": 2.0, "utmos": -50.0, "wer": 200.0}

def log(m): print(f"[tune] {m}", flush=True)

# ── 文本结构 (与 synth_en_v3 完全一致) ──────────────────────────
def split_sents(p):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()]
PARAS = [p.strip() for p in (WORK / "chapter1_clean.txt").read_text(encoding="utf-8").split("\n\n") if p.strip()]
SENTS = [split_sents(p) for p in PARAS]
WORDS = sum(len(p.split()) for p in PARAS)
N_SENT = sum(len(s) for s in SENTS)
N_PARA_GAP = len(PARAS) - 1
N_SENT_GAP = N_SENT - len(PARAS)
REF_TEXT = " ".join(p.strip() for p in PARAS)

def key(s, sg, pg): return f"s{s}_g{sg}_p{pg}"

GRID = [(s, sg, pg) for s in SPEEDS for sg in SENT_GAPS for pg in PARA_GAPS]
GRID.sort(key=lambda c: c != V3_COMBO)   # v3 基准组合排最前 (早期自校验)

# ── 状态落盘 ────────────────────────────────────────────────────
def load_state(name):
    p = TUNE / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
def save_state(name, d):
    (TUNE / name).write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

# ── 合成缓存 ────────────────────────────────────────────────────
def load_or_synth(speed):
    cpath = CACHE / f"pieces_s{speed}.npz"
    if cpath.exists():
        z = np.load(cpath)
        pieces = [z[f"p{i}"] for i in range(N_SENT)]
        assert len(pieces) == N_SENT, f"cache {cpath} has {len(pieces)} != {N_SENT}"
        log(f"PHASE synth speed={speed}: cache hit ({N_SENT} sents)")
        return pieces, int(z["sr"])
    from kokoro_onnx import Kokoro
    t0 = time.time()
    kokoro = Kokoro(str(ROOT / "models/kokoro-v1.0.onnx"), str(ROOT / "models/voices-v1.0.bin"))
    pieces, sr = [], 24000
    for pi, para in enumerate(SENTS):
        for s in para:
            a, sr = kokoro.create(text=s, voice="am_adam", speed=speed, lang="en-gb")
            pieces.append(a.astype(np.float32))
        print(f"[tune:synth] s{speed} para {pi+1}/{len(PARAS)}", flush=True)
    np.savez(cpath, sr=sr, **{f"p{i}": a for i, a in enumerate(pieces)})
    log(f"PHASE synth speed={speed} done ({N_SENT} sents, {time.time()-t0:.0f}s wall)")
    return pieces, sr

# ── 组装 + 链路 + 测量 (与 v3 管线一致) ─────────────────────────
def assemble(pieces, sr, sg, pg):
    parts, idx = [], 0
    for pi, para in enumerate(SENTS):
        for si in range(len(para)):
            parts.append(pieces[idx]); idx += 1
            if si < len(para) - 1:
                parts.append(np.zeros(int(sr * sg), dtype=np.float32))
        if pi < len(PARAS) - 1:
            parts.append(np.zeros(int(sr * pg), dtype=np.float32))
    return np.concatenate(parts)

def ebur128(path):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
                        "-af", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True, timeout=300)
    s = r.stderr[r.stderr.find("Summary:"):] if "Summary:" in r.stderr else ""
    mi = re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", s)
    mp = re.search(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", s)
    if not mi or not mp:
        raise RuntimeError(f"no ebur128 summary for {path}: {r.stderr[-200:]}")
    return float(mi.group(1)), float(mp.group(1))

def silence_stats(y, sr):
    win = int(sr * 0.1)
    rms = np.sqrt(np.convolve(y ** 2, np.ones(win) / win, mode="same"))
    sil = rms < 0.003
    durs, i = [], 0
    while i < len(sil):
        if sil[i]:
            j = i
            while j < len(sil) and sil[j]:
                j += 1
            d = (j - i) / sr
            if d > 0.3:
                durs.append(d)
            i = j
        else:
            i += 1
    return {"n_pauses": len(durs), "pause_budget_s": round(sum(durs), 1),
            "pause_median_s": round(float(np.median(durs)), 2) if durs else 0.0,
            "pause_p90_s": round(float(np.percentile(durs, 90)), 2) if durs else 0.0,
            "pause_max_s": round(max(durs), 2) if durs else 0.0}

def build_candidate(s, sg, pg, pieces, sr):
    k = key(s, sg, pg)
    audio = assemble(pieces, sr, sg, pg)
    f24 = WAVS / f"{k}_f24.wav"
    sf.write(str(f24), audio, sr, subtype="FLOAT")
    lim24 = WAVS / f"{k}_lim.wav"
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(f24), "-af", CHAIN,
                        "-c:a", "pcm_f32le", "-ar", str(sr), str(lim24)],
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"alimiter rc={r.returncode}: {r.stderr[-200:]}")
    f24.unlink()
    lim, _ = sf.read(str(lim24))
    lim24.unlink()
    y = soxr.resample(lim.astype(np.float32), sr, 44100, quality="VHQ")
    pre = WAVS / f"{k}_pre44.wav"
    sf.write(str(pre), y, 44100, subtype="FLOAT")
    lufs_pre, _ = ebur128(pre)
    pre.unlink()
    gain_db = TARGET_LUFS - lufs_pre
    y = (y * 10 ** (gain_db / 20)).astype(np.float32)
    final = WAVS / f"{k}.wav"
    sf.write(str(final), y, 44100, subtype="PCM_16")
    lufs, tp = ebur128(final)
    y16, _ = sf.read(str(final))
    speech_s = sum(len(a) for a in pieces) / sr
    m = {"key": k, "speed": s, "sent_gap_s": sg, "para_gap_s": pg,
         "audio_sec": round(len(y) / 44100, 1), "speech_sec": round(speech_s, 1),
         "gap_sec": round(N_SENT_GAP * sg + N_PARA_GAP * pg, 1),
         "gain_db": round(gain_db, 2), "lufs": round(lufs, 2), "tp_dbtp": round(tp, 2),
         "peak": round(float(np.max(np.abs(y16))), 4),
         "wpm_phonation": round(WORDS / speech_s * 60, 1),
         "wpm_overall": round(WORDS / (len(y) / 44100) * 60, 1),
         **silence_stats(y16, 44100)}
    return m, final

# ── 评测子进程 ──────────────────────────────────────────────────
def utmos_batch(paths):
    r = subprocess.run([str(PY), str(UTMOS_WORKER)] + [str(p) for p in paths],
                       capture_output=True, text=True, timeout=5400, env=ENV)
    if r.returncode != 0:
        raise RuntimeError(f"utmos rc={r.returncode}: {r.stderr[-300:]}")
    return json.loads(r.stdout.strip().splitlines()[-1])

def _parse_asr_lines(raw):
    out = {}
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                j = json.loads(line)
                out[j["path"]] = j
            except Exception:
                pass
    return out

def wer_batch(paths):
    try:
        r = subprocess.run([str(PY), str(ASR_BATCH), "iic/SenseVoiceSmall"] + [str(p) for p in paths],
                            capture_output=True, text=True, timeout=3600, env=ENV)
        return _parse_asr_lines(r.stdout)
    except subprocess.TimeoutExpired as e:
        raw = e.stdout.decode("utf-8", errors="replace") if e.stdout else ""
        return _parse_asr_lines(raw)   # 超时也能救回已完成行

def wer_from_hyp(hyp):
    def norm(t):
        t = t.replace("20", " twenty ")
        t = t.lower().replace("'", "").replace("\u2019", "").replace("-", " ")
        return [w for w in re.sub(r"[^a-z0-9 ]+", " ", t).split() if w]
    RW, HW = norm(REF_TEXT), norm(hyp)
    n, m = len(RW), len(HW)
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cur[j] = min(prev[j - 1] + (RW[i - 1] != HW[j - 1]), prev[j] + 1, cur[j - 1] + 1)
        prev = cur
    return {"wer": round(prev[m] / max(n, 1), 4), "errors": prev[m],
            "ref_words": n, "hyp_words": m}

# ── 主流程 ──────────────────────────────────────────────────────
def main():
    t_all = time.time()
    log(f"PHASE start: {len(GRID)} candidates; ref={REF}")
    log("ETA ~2h: 合成 3×~4min + 组装 27×~25s + UTMOS 3批×~23min + WER 3批×~12min (顺序)")
    pieces_by, sr = {}, 24000
    for s in SPEEDS:
        pieces_by[s], sr = load_or_synth(s)

    stage1, utmos_st, wer_st = load_state("stage1.json"), load_state("utmos.json"), load_state("wer.json")
    n_batches = (len(GRID) + BATCH - 1) // BATCH

    for bi in range(0, len(GRID), BATCH):
        batch = GRID[bi:bi + BATCH]
        bno = bi // BATCH + 1
        # stage 1: 组装 + 链路 + 测量
        for (s, sg, pg) in batch:
            k = key(s, sg, pg)
            need_eval = k not in utmos_st or k not in wer_st
            if k in stage1 and not need_eval:
                continue
            t0 = time.time()
            try:
                m, wavp = build_candidate(s, sg, pg, pieces_by[s], sr)
            except Exception as e:
                log(f"FATAL candidate build {k}: {e}")
                sys.exit(1)
            if k not in stage1:
                stage1[k] = m
                save_state("stage1.json", stage1)
            if (s, sg, pg) == V3_COMBO:
                log(f"VALIDATE v3基准复现 {k}: dur={m['audio_sec']} lufs={m['lufs']} "
                    f"pauses={m['pause_budget_s']}s/{m['n_pauses']} "
                    f"wpm_phon={m['wpm_phonation']} wpm_overall={m['wpm_overall']} "
                    f"(期望 511.5 / -23.0 / 166s/146 / ~154.7 / ~108.5)")
                ok = (abs(m["audio_sec"] - 511.5) <= 1.5 and abs(m["lufs"] + 23.0) <= 0.3
                      and abs(m["pause_budget_s"] - 166) <= 4
                      and abs(m["wpm_phonation"] - 154.7) <= 1.5
                      and abs(m["wpm_overall"] - 108.5) <= 1.5)
                if not ok:
                    log("FATAL v3 基准复现不符 — 管线漂移, 停跑排查 (断点续跑可重启)")
                    sys.exit(1)
                log("VALIDATE PASS — 组装/链路/测量与 v3 实测一致")
            print(f"[tune:stage1] {k} ok ({time.time()-t0:.0f}s) dur={m['audio_sec']} lufs={m['lufs']}", flush=True)

        # UTMOS 批
        need = [(key(*c), WAVS / f"{key(*c)}.wav") for c in batch if key(*c) not in utmos_st]
        if need:
            log(f"PHASE utmos batch {bno}/{n_batches}: {len(need)} files")
            got = None
            for attempt in (1, 2):
                try:
                    got = utmos_batch([p for _, p in need]); break
                except Exception as e:
                    log(f"ERROR utmos attempt {attempt}: {e}")
            miss = [k for k, _ in need if str(WAVS / f"{k}.wav") not in (got or {})]
            if got is None or miss:
                log(f"FATAL utmos missing {miss} — 退出 (断点续跑)")
                sys.exit(1)
            for k, _ in need:
                utmos_st[k] = got[str(WAVS / f"{k}.wav")]
            save_state("utmos.json", utmos_st)
            log("PHASE utmos batch done: " + " ".join(f"{k}={utmos_st[k]}" for k, _ in need))

        # WER 批
        need_w = [(key(*c), WAVS / f"{key(*c)}.wav") for c in batch if key(*c) not in wer_st]
        if need_w:
            log(f"PHASE wer batch {bno}/{n_batches}: {len(need_w)} files")
            got_w = {}
            for attempt in (1, 2):
                got_w = wer_batch([p for _, p in need_w])
                miss = [k for k, _ in need_w
                        if str(WAVS / f"{k}.wav") not in got_w or not got_w[str(WAVS / f"{k}.wav")].get("success")]
                if not miss:
                    break
                log(f"ERROR wer attempt {attempt} missing {miss}")
            miss = [k for k, _ in need_w
                    if str(WAVS / f"{k}.wav") not in got_w or not got_w[str(WAVS / f"{k}.wav")].get("success")]
            if miss:
                log(f"FATAL wer missing {miss} — 退出 (断点续跑)")
                sys.exit(1)
            for k, _ in need_w:
                j = got_w[str(WAVS / f"{k}.wav")]
                hyp = re.sub(r"<\|[^|]*\|>\s*", " ", j["text"]).strip()
                (HYPD / f"{k}.txt").write_text(hyp, encoding="utf-8")
                wer_st[k] = wer_from_hyp(hyp)
            save_state("wer.json", wer_st)
            log("PHASE wer batch done: " + " ".join(f"{k}={wer_st[k]['wer']:.3f}" for k, _ in need_w))

        # 清理本批 wav (交付物在收尾重造)
        for (s, sg, pg) in batch:
            p = WAVS / f"{key(s, sg, pg)}.wav"
            if p.exists():
                p.unlink()

    # ── 排名 ────────────────────────────────────────────────────
    rows = []
    for (s, sg, pg) in GRID:
        k = key(s, sg, pg)
        if k not in stage1 or k not in utmos_st or k not in wer_st:
            log(f"ERROR candidate {k} incomplete — excluded from ranking")
            continue
        m, u, w = stage1[k], utmos_st[k], wer_st[k]["wer"]
        comp = {"lufs_pen": 1000.0 if abs(m["lufs"] - TARGET_LUFS) > 0.5 else 0.0,
                "wpm_phon": W["wpm_phon"] * abs(m["wpm_phonation"] - REF["wpm_phonation"]),
                "wpm_overall": W["wpm_overall"] * abs(m["wpm_overall"] - REF["wpm_overall"]),
                "pause": W["pause"] * abs(m["pause_budget_s"] - REF["pause_budget_s"]),
                "median": W["median"] * abs(m["pause_median_s"] - REF["pause_median_s"]),
                "p90": W["p90"] * abs(m["pause_p90_s"] - REF["pause_p90_s"]),
                "utmos": W["utmos"] * u,
                "wer": W["wer"] * w}
        rows.append({**m, "utmos": u, "wer": w, "loss": round(sum(comp.values()), 2),
                     "loss_components": {kk: round(vv, 2) for kk, vv in comp.items()}})
    rows.sort(key=lambda r: r["loss"])
    log("PHASE ranking (loss 升序):")
    log(f"{'key':<18}{'loss':>8}{'utmos':>7}{'wer':>7}{'wpmP':>7}{'wpmO':>7}{'pseS':>7}{'med':>6}{'p90':>6}{'lufs':>7}{'dur':>7}")
    for r in rows:
        log(f"{r['key']:<18}{r['loss']:>8.1f}{r['utmos']:>7.2f}{r['wer']:>7.3f}{r['wpm_phonation']:>7.1f}"
            f"{r['wpm_overall']:>7.1f}{r['pause_budget_s']:>7.0f}{r['pause_median_s']:>6.2f}"
            f"{r['pause_p90_s']:>6.2f}{r['lufs']:>7.1f}{r['audio_sec']:>7.1f}")

    win = rows[0]
    v3row = next((r for r in rows if r["key"] == key(*V3_COMBO)), None)
    log(f"WINNER {win['key']} loss={win['loss']} (v3基准 {key(*V3_COMBO)} loss={v3row['loss'] if v3row else 'n/a'})")
    log(f"WINNER 详情: speed={win['speed']} sent_gap={win['sent_gap_s']} para_gap={win['para_gap_s']} "
        f"utmos={win['utmos']} wer={win['wer']} wpm_phon={win['wpm_phonation']} "
        f"wpm_overall={win['wpm_overall']} pause={win['pause_budget_s']}s lufs={win['lufs']} dur={win['audio_sec']}s")
    if win["key"] != key(*V3_COMBO):
        _, wavp = build_candidate(win["speed"], win["sent_gap_s"], win["para_gap_s"],
                                  pieces_by[win["speed"]], sr)
        dest = OUT / "football_forever_ch1_v4_tuned_44k1.wav"
        shutil.copy(str(wavp), str(dest))
        wavp.unlink()
        log(f"WINNER deliverable → {dest}")
    else:
        log("WINNER == v3 参数组合: 网格确认 v3 已是 27 点最优, 不另出交付物")

    summary = {"winner": {kk: win[kk] for kk in ("key", "speed", "sent_gap_s", "para_gap_s",
                                                  "audio_sec", "lufs", "tp_dbtp", "wpm_phonation",
                                                  "wpm_overall", "pause_budget_s", "utmos", "wer", "loss")},
               "v3_baseline_loss": v3row["loss"] if v3row else None,
               "ref_calibration": REF, "weights": W, "grid_size": len(GRID),
               "total_wall_s": round(time.time() - t_all, 1),
               "deliverable": str(OUT / "football_forever_ch1_v4_tuned_44k1.wav")
                              if win["key"] != key(*V3_COMBO) else "v3 参数即最优 (无新交付物)"}
    (TUNE / "auto_tune_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (TUNE / "auto_tune_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    log(f"AUTO_TUNE_DONE wall={summary['total_wall_s']}s winner={win['key']}")

if __name__ == "__main__":
    if "--check" in sys.argv:
        print(f"check: paras={len(PARAS)} sents={N_SENT} words={WORDS} "
              f"sent_gaps={N_SENT_GAP} para_gaps={N_PARA_GAP} grid={len(GRID)}")
        sys.exit(0)
    main()

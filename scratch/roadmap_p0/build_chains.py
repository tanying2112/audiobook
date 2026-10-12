"""对 10 段评测 wav 施加 4 条处理链，测每条链的响度/真峰，产出裁判输入。"""
import json, re, subprocess
from pathlib import Path

P0 = Path(__file__).resolve().parent
BASE = P0 / "eval_base"
VARD = P0 / "chains"
VARD.mkdir(exist_ok=True)

C1 = "alimiter=limit=0.6683:attack=5:release=100:level=disabled"   # −3.5 dBFS 峰值限幅
C2 = "volume=-3.5dB"                                                 # 标量衰减
C3_T = "loudnorm=I=-21:TP=-3.5:LRA=9"                                # 双遍 loudnorm 目标

def sh(*args):
    r = subprocess.run(list(args), capture_output=True, text=True)
    return r

def measure(path):
    """loudnorm print 测 I/TP/LRA（真峰）。"""
    r = sh("ffmpeg", "-hide_banner", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", r.stderr, re.S)
    d = json.loads(m.group(0))
    return {"i": float(d["input_i"]), "tp": float(d["input_tp"]), "lra": float(d["input_lra"])}

def astats_rms(path):
    r = sh("ffmpeg", "-hide_banner", "-i", str(path), "-af", "astats=measure_overall=RMS_level:measure_perchannel=none", "-f", "null", "-")
    m = re.findall(r"RMS level dB:\s*(-?[\d.]+|-inf)", r.stderr)
    return float(m[-1]) if m and m[-1] != "-inf" else float("nan")

wavs = sorted(BASE.glob("p*.wav"))
out = {}
for w in wavs:
    stem = w.stem
    # c0 基线即原文件
    variants = {"c0": w}
    # c1 / c2
    for tag, chain in (("c1", C1), ("c2", C2)):
        o = VARD / f"{stem}_{tag}.wav"
        assert sh("ffmpeg", "-y", "-i", str(w), "-af", chain, "-ar", "24000", "-ac", "1", str(o)).returncode == 0
        variants[tag] = o
    # c3 双遍 loudnorm
    p1 = sh("ffmpeg", "-hide_banner", "-i", str(w), "-af", C3_T + ":print_format=json", "-f", "null", "-")
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", p1.stderr, re.S)
    md = json.loads(m.group(0))
    p2af = (f"{C3_T}:measured_I={md['input_i']}:measured_LRA={md['input_lra']}"
            f":measured_TP={md['input_tp']}:measured_thresh={md['input_thresh']}"
            f":offset={md['target_offset']}:linear=true")
    o = VARD / f"{stem}_c3.wav"
    assert sh("ffmpeg", "-y", "-i", str(w), "-af", p2af, "-ar", "24000", "-ac", "1", str(o)).returncode == 0
    variants["c3"] = o
    for tag, p in variants.items():
        mm, rms = measure(p), astats_rms(p)
        out[str(p)] = {"chain": tag, "para": stem, "lufs": mm["i"], "tp_dbtp": mm["tp"], "lra": mm["lra"], "rms_db": rms}
    print(stem, "done", flush=True)

json.dump(out, open(P0 / "chain_meta.json", "w"), indent=1)
# 汇总每链均值
agg = {}
for tag in ("c0", "c1", "c2", "c3"):
    rows = [v for v in out.values() if v["chain"] == tag]
    agg[tag] = {"lufs": sum(r["lufs"] for r in rows) / len(rows),
                "tp_max": max(r["tp_dbtp"] for r in rows),
                "rms": sum(r["rms_db"] for r in rows) / len(rows)}
print(json.dumps(agg, indent=1))

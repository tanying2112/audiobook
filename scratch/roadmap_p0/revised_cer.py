"""用数字读法归一口径复算 v4 的 CER（不加载模型，直接吃已落盘的 hyp）。"""
import json, re, unicodedata
from zhconv import convert

CN_NUM = "零一二三四五六七八九"
CN_UNIT = ["", "十", "百", "千"]

def _group4(g):
    n = len(g)
    if n == 1: return CN_NUM[int(g)]
    if n == 2 and g[0] == "1": return "十" + (CN_NUM[int(g[1])] if g[1] != "0" else "")
    out, pending = "", False
    for i, ch in enumerate(g):
        d = int(ch)
        if d == 0:
            if out: pending = True
        else:
            if pending: out += "零"; pending = False
            out += CN_NUM[d] + CN_UNIT[n - 1 - i]
    return out or "零"

def _num2cn(s):
    if "." in s:
        ip, fp = s.split(".", 1)
        i = _num2cn(ip) if ip else "零"
        if i is None: return None
        return i + "点" + "".join(CN_NUM[int(c)] for c in fp if c.isdigit())
    t = s.lstrip("0") or "0"
    if t == "0": return "零"
    if len(t) > 8: return None
    if len(t) <= 4: return _group4(t)
    groups, big, u, out = [], ["", "万", "亿"], t, ""
    while u:
        groups.append(u[-4:]); u = u[:-4]
    for gi in range(len(groups) - 1, -1, -1):
        if groups[gi].strip("0"):
            out += _group4(groups[gi].lstrip("0")) + big[gi]
    return out or "零"

def norm_old(t):
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"[^一-鿿]", "", t)
    return convert(t, "zh-hans")

def norm_new(t):
    t = unicodedata.normalize("NFKC", t).lower()
    t = re.sub(r"(?<=\d),(?=\d)", "", t)
    t = re.sub(r"(\d[\d.]*?)%", lambda m: "百分之" + (_num2cn(m.group(1)) or m.group(1)), t)
    t = re.sub(r"\d[\d.]*", lambda m: _num2cn(m.group(0)) or m.group(0), t)
    t = re.sub(r"[^一-鿿]", "", t)
    return convert(t, "zh-hans")

def cer(ref, hyp, n):
    r, h = n(ref), n(hyp)
    if not r: return 0.0, 0, 0
    m = len(h)
    prev = list(range(m + 1))
    for i in range(1, len(r) + 1):
        cur = [i] + [0] * m
        for j in range(1, m + 1):
            cur[j] = min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + (r[i-1] != h[j-1]))
        prev = cur
    return prev[m] / len(r), len(r), prev[m]

ref = list(json.load(open("scratch/kokoro_iter/ref_full.json")).values())[0]
for tag, fn in (("v4.mp3", "sensevoice_23_学什么技能划算_kokoro_v4.mp3.txt"),
                ("v4.opus", "sensevoice_23_学什么技能划算_kokoro_v4.opus.txt")):
    hyp = open(f"scratch/roadmap_p0/hyp/{fn}", encoding="utf-8").read()
    o, rn, oe = cer(ref, hyp, norm_old)
    n2, _, ne = cer(ref, hyp, norm_new)
    print(f"{tag}: CER 旧口径 {o:.4f} ({oe}/{rn}) → 数字读法归一 {n2:.4f} ({ne}/{rn})  ↓{oe-ne} 字误差")

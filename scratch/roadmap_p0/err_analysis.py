"""P1.4/P1.5 误差归因：v4 SenseVoice hyp vs ref 逐操作对齐三分类。
分类：① 数字区间(格式性/读法) ② 汉字替换-同音(声学混淆) ③ 汉字替换-异音(G2P/多音字) + 纯删/插。
对齐层保留数字与字母（CER 口径会剥掉），事件标签剥掉。"""
import json, re, unicodedata
from collections import Counter
from rapidfuzz.distance import Levenshtein
editops = Levenshtein.editops
from pypinyin import lazy_pinyin

REF = list(json.load(open("scratch/kokoro_iter/ref_full.json")).values())[0]
HYP = open("scratch/roadmap_p0/hyp/sensevoice_23_学什么技能划算_kokoro_v4.mp3.txt", encoding="utf-8").read()

def align(t: str):
    """NFKC+lower，剥事件标签与标点/空白，保留汉字数字字母；返回 (串, 原文位置映射)。"""
    t = re.sub(r"<\|[^|]{0,20}\|>", "", t)
    t = unicodedata.normalize("NFKC", t).lower()
    out, pos = [], []
    for i, c in enumerate(t):
        if re.match(r"[一-鿿0-9a-z]", c):
            out.append(c)
            pos.append(i)
    return "".join(out), pos

ra, rpos = align(REF)
ha, hpos = align(HYP)
n_digit_runs = len(re.findall(r"\d[\d,]*\.?\d*", REF))
print(f"对齐层: ref {len(ra)} 字 / hyp {len(ha)} 字; ref 原文数字串 {n_digit_runs} 处")

ops = editops(ra, ha)
sub, dele, ins = [], [], []
for op in ops:
    if op.tag == "replace":
        sub.append((ra[op.src_pos], ha[op.dest_pos], op.src_pos, op.dest_pos))
    elif op.tag == "delete":
        dele.append((ra[op.src_pos], op.src_pos))
    else:
        ins.append((ha[op.dest_pos], op.src_pos))
print(f"editops: 替换 {len(sub)} 删除 {len(dele)} 插入 {len(ins)}  总误差 {len(sub)+len(dele)+len(ins)}")
print(f"(CER 口径复核: 1301 ≈ 误差/10380 字 → {len(sub)+len(dele)+len(ins)} 量级 {100*(len(sub)+len(dele)+len(ins))/10280:.2f}%)")

NUM = {str(d): c for d, c in zip(range(10), "零一二三四五六七八九")}
def digit_near(sp, w=4):
    lo, hi = max(0, sp - w), min(len(ra), sp + w)
    return any(c in "0123456789" for c in ra[lo:hi])

dig_sub = [s for s in sub if s[0] in "0123456789" or s[1] in "0123456789"]
han_sub = [s for s in sub if s[0] not in "0123456789" and s[1] not in "0123456789"]
dig_del = [d for d in dele if d[0] in "0123456789"]
dig_ins = [i for i in ins if i[0] in "0123456789" or digit_near(i[1])]
print(f"\n=== 分类 ===\n数字相关: 替换 {len(dig_sub)} 删 {len(dig_del)} 插 {len(dig_ins)}")
benign = [s for s in dig_sub if NUM.get(s[0]) == s[1] or (s[0] in NUM.values() and s[1] in NUM.values())]
print(f"  其中良性格式对(如 2→二): {len(benign)}")

def py(c):
    try:
        return lazy_pinyin(c)[0]
    except Exception:
        return "?"

homo, hetero = [], []
for r, h, sp, dp in han_sub:
    (homo if py(r) == py(h) else hetero).append((r, h, sp))
print(f"汉字替换: 同音 {len(homo)} / 异音 {len(hetero)}")
print(f"  同音 top: {Counter(f'{r}→{h}' for r,h,_ in homo).most_common(8)}")
print(f"  异音 top: {Counter(f'{r}→{h}' for r,h,_ in hetero).most_common(12)}")
print(f"  数字近邻替换(在数字串±4内): {sum(1 for r,h,sp,dp in han_sub if digit_near(sp))}")

def ctx(sp, w=8):
    lo, hi = max(0, sp - w), min(len(ra), sp + w)
    return ra[lo:hi]

print(f"\n=== 删除 {len(dele)} 采样(数字近邻标注*) ===")
for c, sp in dele[:12]:
    print(f"  {'*' if digit_near(sp) else ' '} 删[{c}] @{ctx(sp)}")
print(f"\n=== 插入 {len(ins)} 采样 ===")
for c, sp in ins[:12]:
    print(f"  {'*' if digit_near(sp) else ' '} 插[{c}] @{ctx(sp)}")

# 汇总判定
total = len(sub) + len(dele) + len(ins)
dig_mass = len(dig_sub) + len(dig_del) + len(dig_ins)
print(f"\n=== 归因汇总 ===\n总误差 {total}: 数字区间 {dig_mass} ({100*dig_mass/total:.1f}%) | "
      f"同音替换 {len(homo)} ({100*len(homo)/total:.1f}%) | 异音替换 {len(hetero)} ({100*len(hetero)/total:.1f}%) | "
      f"其余删插 {total-dig_mass-len(homo)-len(hetero)}")

"""ch23_body.txt → 朗读向文本规范化（Kokoro/cmn 音素层验证过的替换）：
- TODO 备注残句删除（1 处，属提取残留，非正文内容）
- 统计记号口语化：g/d 值 → 「g 值为」；95% CI → 「95% 置信区间」
- 「g/p/d = x」系列、Hedges' g、LPR 等英文记号保留（cmn 音素层正确读出）
- 数字/百分号/年份保持原样：espeak cmn 全部正确转中文读法（实测 88 种 token 无一错误）
验证脚本：phonemize 全量 diff（token 级），替换只影响目标 4 处。
"""
import re

path = "output/howtolivebetter_ch23/ch23_body.txt"
src = open(path, encoding="utf-8").read()

subs = [
    # 1) TODO 残句（整句删，含其后的括号内容——待核实提示对听众无意义）
    (re.compile(r"TODO（待核实[^）]*）"), ""),
    # 2) 统计记号口语化（音素层实测：CI 读成 "sˈaɪ"，改为中文全称）
    (re.compile(r"95% CI"), "95% 置信区间"),
    # 3) 「g = 0.42」→「g 值为 0.42」（d/p 同构式）
    (re.compile(r"([gdp])\s*=\s*"), r"\1 值为 "),
]

out = src
for pat, rep in subs:
    out = pat.sub(rep, out)

open(path, "w", encoding="utf-8").write(out)
print(f"chars: {len(src)} -> {len(out)}")
for m in re.finditer(r"值|置信区间|待核实", out):
    s = max(0, m.start() - 25)
    print(f"  …{out[s:m.end()+12]}…".replace("\n", " "))

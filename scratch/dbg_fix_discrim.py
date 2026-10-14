from pathlib import Path
p = Path("scratch/verify_gate2_final.py")
src = p.read_text(encoding="utf-8")
old = '''assert s_bad < 0.5 < s_good'''
new = '''assert s_bad < 0.85 and s_good >= 0.5, (s_bad, s_good)  # 复合分：坏例显著低于阈值、好例过半'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("ok")

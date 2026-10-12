from pathlib import Path
p = Path("scratch/verify_fixes23.py")
src = p.read_text(encoding="utf-8")
old = '''ok5, why5 = check_input_compatibility("annotate", {"story_line_summary": "太短", "paragraph_text": "x", "paragraph_index": 0})
assert not ok5 and "缺少阶段必需字段" in why5, why5
print("PASS annotate 缺 book_meta/character_voice_map 判不兼容:", why5)
ok += 1'''
new = '''ok5, why5 = check_input_compatibility("annotate", {"story_line_summary": "太短", "paragraph_text": "x", "paragraph_index": 0})
assert not ok5 and "输入模型转换失败" in why5, why5
print("PASS annotate 字段齐但 schema 违规（story_line_summary<100 等）判不兼容")
ok += 1'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("ok")

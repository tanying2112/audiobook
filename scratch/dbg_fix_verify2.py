from pathlib import Path
p = Path("scratch/verify_fixes23.py")
src = p.read_text(encoding="utf-8")
old = '''ok1, why1 = check_input_compatibility("quality", {"text": "一段文本"})
assert not ok1, f"quality 金标 {text}" if (text := 1) else ""
assert "缺少阶段必需字段" in why1, why1
print("PASS quality 缺字段判不兼容:", why1)
ok += 1'''
new = '''ok1, why1 = check_input_compatibility("quality", {"text": "一段文本"})
assert not ok1
assert "非 prompt 驱动" in why1, why1
print("PASS quality 金标 {text} 判不兼容（非 prompt 驱动短路）")
ok += 1'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("ok")

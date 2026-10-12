from pathlib import Path
p = Path("scratch/verify_fixes23.py")
src = p.read_text(encoding="utf-8")

old = '''ok2, why2 = check_input_compatibility("quality", {"audio_path": "a.wav", "expected_text": "你好"})
assert ok2 and why2 == "", why2
print("PASS quality 合法输入判兼容")
ok += 1'''
new = '''ok2, why2 = check_input_compatibility("quality", {"audio_path": "a.wav", "expected_text": "你好"})
assert not ok2 and "非 prompt 驱动" in why2, why2
print("PASS quality 即使字段凑齐也按非 prompt 驱动诚实短路:", why2[:50])
ok += 1'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("verify expectations updated")

from pathlib import Path
p = Path("scratch/verify_fixes23.py")
src = p.read_text(encoding="utf-8")

# edit 合法输入：paragraph_annotation 需符合 ParagraphAnnotation 契约
old = '''ok3, why3 = check_input_compatibility("edit", {"paragraph_text": "你好", "paragraph_annotation": {},
                                               "difficulty": "B", "forbid_edit": False})
assert ok3, why3
print("PASS edit 合法输入判兼容")
ok += 1'''
new = '''ok3, why3 = check_input_compatibility("edit", {
    "paragraph_text": "李明说：「你好，今天天气不错。」",
    "paragraph_annotation": {
        "paragraph_index": 0, "text": "李明说：「你好，今天天气不错。」",
        "speaker_canonical_name": "李明", "is_dialogue": True,
        "emotion": "neutral", "emotion_intensity": 0.5, "confidence": 0.9,
    },
    "difficulty": "B", "forbid_edit": False,
})
assert ok3, why3
print("PASS edit 合法输入判兼容")
ok += 1'''
assert src.count(old) == 1
src = src.replace(old, new)

# annotate 合法输入：ParagraphAnnotationInput 契约（与金标不兼容的判例不变）
old = '''ok4, why4 = check_input_compatibility("annotate", {"story_line_summary": "太短"})
assert not ok4, why4
print("PASS annotate 输入违反 schema 判不兼容:", why4[:80])
ok += 1'''
new = '''ok4, why4 = check_input_compatibility("annotate", {"story_line_summary": "太短"})
assert not ok4, why4
print("PASS annotate 输入违反 schema 判不兼容:", why4[:80])
ok += 1

ok5, why5 = check_input_compatibility("annotate", {"story_line_summary": "太短", "paragraph_text": "x", "paragraph_index": 0})
assert not ok5 and "缺少阶段必需字段" in why5, why5
print("PASS annotate 缺 book_meta/character_voice_map 判不兼容:", why5)
ok += 1'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("ok")

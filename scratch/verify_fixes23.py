"""Fix 2/3 定点验证（脱离 pytest）：canary 输入兼容检查 + 人工门严格模式。

Fix 2: check_input_compatibility 应对 quality 金标输入（缺 audio_path/
expected_text）判不兼容；对 edit 合法输入判兼容；quality 属
NON_PROMPT_DRIVEN_STAGES。
Fix 3: SELF_ITERATION_HUMAN_GATE_STRICT=true → resolve_human_default()==0.0
（fail-closed）；未设置 → 1.0（默认放行，保持既有语义）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.audiobook_studio.feedback.canary import (  # noqa: E402
    NON_PROMPT_DRIVEN_STAGES,
    check_input_compatibility,
)
from src.audiobook_studio.harness.spotcheck import (  # noqa: E402
    human_gate_strict,
    resolve_human_default,
)

ok = 0

# ── Fix 2 ──
ok1, why1 = check_input_compatibility("quality", {"text": "一段文本"})
assert not ok1
assert "非 prompt 驱动" in why1, why1
print("PASS quality 金标 {text} 判不兼容（非 prompt 驱动短路）")
ok += 1

ok2, why2 = check_input_compatibility("quality", {"audio_path": "a.wav", "expected_text": "你好"})
assert not ok2 and "非 prompt 驱动" in why2, why2
print("PASS quality 即使字段凑齐也按非 prompt 驱动诚实短路:", why2[:50])
ok += 1

ok3, why3 = check_input_compatibility("edit", {
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
ok += 1

ok4, why4 = check_input_compatibility("annotate", {"story_line_summary": "太短"})
assert not ok4, why4
print("PASS annotate 输入违反 schema 判不兼容:", why4[:80])
ok += 1

ok5, why5 = check_input_compatibility("annotate", {"story_line_summary": "太短", "paragraph_text": "x", "paragraph_index": 0})
assert not ok5 and "输入模型转换失败" in why5, why5
print("PASS annotate 字段齐但 schema 违规（story_line_summary<100 等）判不兼容")
ok += 1

assert "quality" in NON_PROMPT_DRIVEN_STAGES
print("PASS quality ∈ NON_PROMPT_DRIVEN_STAGES")
ok += 1

# ── Fix 3 ──
import os
os.environ.pop("SELF_ITERATION_HUMAN_GATE_STRICT", None)
assert resolve_human_default() == 1.0 and not human_gate_strict()
print("PASS 默认策略 default=1.0 放行（既有语义不变）")
ok += 1

os.environ["SELF_ITERATION_HUMAN_GATE_STRICT"] = "true"
assert resolve_human_default() == 0.0 and human_gate_strict()
print("PASS strict=true → default=0.0 fail-closed")
ok += 1
os.environ.pop("SELF_ITERATION_HUMAN_GATE_STRICT", None)

print(f"ALL {ok} CHECKS PASSED")

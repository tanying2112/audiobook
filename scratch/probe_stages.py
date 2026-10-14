"""探测各 stage 的 canary 真实可运行性（1 例/stage）。"""
import json, sys, traceback
sys.path.insert(0, "src")
from audiobook_studio.feedback.canary import _load_golden_examples, _run_stage_with_prompt_version, _get_required_input_fields

for stage, prompt_stage in [("annotate_paragraph","annotate"), ("analyze_structure","analyze"), ("extract","extract"), ("translate","translate")]:
    ex = _load_golden_examples(stage)[0]
    req = _get_required_input_fields(prompt_stage)
    missing = [f for f in req if f not in ex["input"]]
    print(f"\n=== {stage} (pipeline={prompt_stage}) required={req} missing={missing} ===")
    if missing:
        print("  SKIP: input shape mismatch → gates 会跳过该例")
        continue
    try:
        out = _run_stage_with_prompt_version(prompt_stage, 1, ex["input"], mock_mode=False)
        d = out.model_dump() if hasattr(out, "model_dump") else out
        print("  OK:", json.dumps(d, ensure_ascii=False, default=str)[:180])
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {str(e)[:150]}")

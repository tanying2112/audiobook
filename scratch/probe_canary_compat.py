"""Probe: which golden stages can actually run through the canary path."""
import sys, traceback
sys.path.insert(0, "src")
from audiobook_studio.feedback.canary import (
    GOLDEN_TO_PIPELINE_STAGE, _convert_input_to_model, _get_required_input_fields,
    _load_golden_examples,
)

for stage_dir in ["edit_for_tts", "annotate_paragraph", "analyze_structure", "extract", "quality_check", "quality_judge", "tts_routing"]:
    examples = _load_golden_examples(stage_dir)
    pstage = GOLDEN_TO_PIPELINE_STAGE.get(stage_dir, stage_dir)
    req = _get_required_input_fields(pstage)
    print(f"\n### {stage_dir} -> pipeline '{pstage}' (required: {req}) — {len(examples)} examples")
    for i, ex in enumerate(examples[:2]):
        if "input" not in ex:
            print(f"  ex{i}: NO 'input' key (keys={list(ex.keys())})")
            continue
        inp = ex["input"]
        missing = [f for f in req if f not in inp]
        print(f"  ex{i}: missing fields={missing}")
        try:
            m = _convert_input_to_model(pstage, dict(inp))
            print(f"  ex{i}: converted OK -> {type(m).__name__}")
        except Exception as e:
            msg = str(e).split("\n")[0][:150]
            print(f"  ex{i}: CONVERT FAILED: {msg}")

"""端到端验证：真实 LLM 跑 edit 阶段（live v1 prompt）via local_fcc_gateway。"""
import json, sys, time
sys.path.insert(0, "src")

example = json.loads(open("data/golden/val/edit/edit.jsonl", encoding="utf-8").readline())
print("INPUT text:", example["input"]["paragraph_text"][:80])
print("EXPECTED:", json.dumps(example["expected_output"], ensure_ascii=False)[:200])

from audiobook_studio.feedback.canary import _run_stage_with_prompt_version

t0 = time.time()
out = _run_stage_with_prompt_version("edit", 1, example["input"], mock_mode=False)
dt = time.time() - t0
d = out.model_dump() if hasattr(out, "model_dump") else out
print(f"\n--- REAL-LLM run in {dt:.1f}s ---")
print(json.dumps(d, ensure_ascii=False, indent=2)[:800])

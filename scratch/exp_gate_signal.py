"""实验：live v1 (裸) vs 候选 (v1+train few-shot) 在 edit 金标上的门禁信号差。
输出两者的 recursive similarity 与 text-quality 指标，验证 Gate2/Gate3 是否有真实区分度。
"""
import json, sys, time
sys.path.insert(0, "src")
from pathlib import Path
from audiobook_studio.feedback.canary import _load_golden_examples, _run_stage_with_prompt_version
from audiobook_studio.feedback.prompt_compiler import write_candidate_prompt
from audiobook_studio.feedback.similarity import _compute_output_similarity, _compute_text_quality_metrics, _aggregate_quality_score

# 1) 编译候选：base=production live v1（已拷入 scratch），加 3 条 train few-shot
cp = write_candidate_prompt("edit", k=3, prompts_root=Path("scratch/ref_prompts"))
print(f"candidate compiled: v{cp.version}, base=v{cp.base_version}, exemplars={len(cp.exemplars)}")

examples = _load_golden_examples("edit_for_tts")[:3]  # train split（门禁同款）
rows = []
for i, ex in enumerate(examples):
    exp = ex["expected_output"]
    t0 = time.time()
    base_out = _run_stage_with_prompt_version("edit", 1, ex["input"], mock_mode=False)
    cand_out = _run_stage_with_prompt_version("edit", cp.version, ex["input"], mock_mode=False, prompts_root=Path("scratch/ref_prompts"))
    b = base_out.model_dump(); c = cand_out.model_dump()
    dt = time.time() - t0
    sim_b = _compute_output_similarity(b, exp)
    sim_c = _compute_output_similarity(c, exp)
    qb = _aggregate_quality_score(_compute_text_quality_metrics(b, exp, ex["input"]), "text_edit")
    qc = _aggregate_quality_score(_compute_text_quality_metrics(c, exp, ex["input"]), "text_edit")
    rows.append((sim_b, sim_c, qb, qc))
    print(f"\n[{i}] {dt:.1f}s  base_sim={sim_b:.3f} cand_sim={sim_c:.3f}  base_q={qb:.3f} cand_q={qc:.3f}")
    print(f"    cand edited: {c['edited_text'][:60]}")
    print(f"    exp  edited: {exp['edited_text'][:60]}")

import statistics as st
print("\n=== 汇总 (3 例) ===")
mb, mc = st.mean(r[0] for r in rows), st.mean(r[1] for r in rows)
qb_m, qc_m = st.mean(r[2] for r in rows), st.mean(r[3] for r in rows)
print(f"Gate2 per-example sim: base={mb:.3f} cand={mc:.3f} (bar 0.85)")
print(f"Gate3 quality agg:     base={qb_m:.3f} cand={qc_m:.3f} ratio={qc_m/max(qb_m,0.01):.3f} (bar 1.02)")

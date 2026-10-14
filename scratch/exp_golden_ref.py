"""实验 B：reference-golden 可行性。
1) ref = candidate(v1+exemplars) 输出 → 假想为新金标
2) cand2 = 同一候选重跑（稳定性）→ sim(cand2, ref) 应 ≥0.85（Gate2 可过）
3) base = live v1 裸 prompt → sim(base, ref) 应明显更低（Gate3 有区分度）
"""
import json, sys, time
sys.path.insert(0, "src")
from pathlib import Path
from audiobook_studio.feedback.canary import _load_golden_examples, _run_stage_with_prompt_version
from audiobook_studio.feedback.similarity import _compute_output_similarity, _compute_text_quality_metrics, _aggregate_quality_score

CAND_V = 2  # exp_gate_signal 编译出的 v2（v1+3 exemplars），仍在 scratch/ref_prompts
examples = _load_golden_examples("edit_for_tts")[:3]

sims_cand, sims_base, qs_cand, qs_base = [], [], [], []
for i, ex in enumerate(examples):
    inp = ex["input"]
    ref = _run_stage_with_prompt_version("edit", CAND_V, inp, mock_mode=False, prompts_root=Path("scratch/ref_prompts")).model_dump()
    cand2 = _run_stage_with_prompt_version("edit", CAND_V, inp, mock_mode=False, prompts_root=Path("scratch/ref_prompts")).model_dump()
    base = _run_stage_with_prompt_version("edit", 1, inp, mock_mode=False).model_dump()

    s_cand = _compute_output_similarity(cand2, ref)
    s_base = _compute_output_similarity(base, ref)
    q_cand = _aggregate_quality_score(_compute_text_quality_metrics(cand2, ref, inp), "text_edit")
    q_base = _aggregate_quality_score(_compute_text_quality_metrics(base, ref, inp), "text_edit")
    sims_cand.append(s_cand); sims_base.append(s_base); qs_cand.append(q_cand); qs_base.append(q_base)
    print(f"[{i}] rerun_sim={s_cand:.3f}  base_sim={s_base:.3f}   q_cand={q_cand:.3f} q_base={q_base:.3f}")

import statistics as st
mc, mb = st.mean(sims_cand), st.mean(sims_base)
qc, qb = st.mean(qs_cand), st.mean(qs_base)
print(f"\n=== reference-golden 模拟 ===")
print(f"Gate2: candidate vs ref  = {mc:.3f} (bar: 每例≥0.85, 通过率≥0.95)")
print(f"Gate3: cand_q={qc:.3f} base_q={qb:.3f} ratio={qc/max(qb,0.01):.3f} (bar 1.02)")
print(f"per-example rerun sims: {[f'{s:.2f}' for s in sims_cand]}")

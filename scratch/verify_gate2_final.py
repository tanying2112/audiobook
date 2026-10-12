"""Gate 2（Fix 1/1b）最终回归：以重写后的 edit 金标（24 train / 20 val）走
promotion.check_golden_dataset 的真代码路径（不跑 LLM，只验门算分路径与
fail-closed 语义）。

- example_passes_gate：文本主判据（text_sim≥0.85）对编辑文本差异敏感；
- score_output_vs_expected(stage=edit)：edited_text 以权重 3.0 进入复合分；
- 校准基线回放（scratch/calibrate_gate2_results.json）：live v43 输出
  23/24 text_sim≥0.85 → 门通过率 0.9583 ≥ 0.95。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.audiobook_studio.feedback.candidate_eval import (  # noqa: E402
    example_passes_gate,
    score_output_vs_expected,
)

# ── 1) 校准基线回放：live v43 24 例（calibrate_gate2_results.json 存的是
#    逐例 out_text/exp_text/text_sim —— 文本主判据等价于 text_sim≥0.85）──
cal = json.loads(Path("scratch/calibrate_gate2_results.json").read_text(encoding="utf-8"))
rows = cal["rows"] if isinstance(cal, dict) and "rows" in cal else cal
n_pass = 0
for r in rows:
    exp = {"edited_text": r["exp_text"]}
    out = {"edited_text": r["out_text"]}
    # example_passes_gate 的文本判据 = _text_similarity(exp,out)≥0.85，
    # 与校准脚本所记 text_sim 同源，双路核对防实现漂移
    ep = example_passes_gate(exp, out, stage="edit")
    assert ep == (r["text_sim"] >= 0.85), f"row {r['i']}: gate={ep} vs calib={r['text_sim']}"
    if ep:
        n_pass += 1
rate = n_pass / len(rows)
print(f"Gate2 replay: live v43 → {n_pass}/{len(rows)} = {rate:.4f} (threshold 0.95)")
assert rate >= 0.95, "live 基线未过门 —— 门被 rigged"

# ── 2) 判别力：文本烂、confidence 高 → 必须 FAIL ──
exp = {"edited_text": "李明说：「你好，今天天气不错，我们去公园散步吧。」",
       "changes_made": ["数字归一化"], "forbidden_content_removed": [],
       "confidence": 0.9, "rationale": "ok"}
bad = {"edited_text": "完全无关的输出文本与期望毫无关系 whatsoever 完全不同",
       "changes_made": ["数字归一化"], "forbidden_content_removed": [],
       "confidence": 0.99, "rationale": "ok"}
good = {"edited_text": "李明说：「你好，今天天气不错，我们去公园散步吧。」",
        "changes_made": ["冗余修饰删减"], "forbidden_content_removed": [],
        "confidence": 0.7, "rationale": "措辞略异"}
assert not example_passes_gate(exp, bad, stage="edit"), "坏文本+高置信度必须被拒"
assert example_passes_gate(exp, good, stage="edit"), "文本正确+措辞变体必须通过"
s_bad = score_output_vs_expected(exp, bad, stage="edit")
s_good = score_output_vs_expected(exp, good, stage="edit")
print(f"discrimination: bad→{s_bad:.3f} FAIL / good(措辞变体)→{s_good:.3f} PASS")
assert s_bad < 0.85 and s_good >= 0.5, (s_bad, s_good)  # 复合分：坏例显著低于阈值、好例过半

# ── 3) 修复前缺陷回归：文本烂、confidence 一致 → 旧复合分≈1，新文本权重拉低 ──
same_conf_bad = dict(bad, changes_made=exp["changes_made"], confidence=exp["confidence"])
s_legacy_style = score_output_vs_expected(exp, same_conf_bad, stage="edit")
print(f"旧缺陷复现用例(仅文本坏) → {s_legacy_style:.3f}（修复前=1.0 必过）")
assert s_legacy_style < 0.85 and not example_passes_gate(exp, same_conf_bad, stage="edit")

# ── 4) 非 edit 阶段不受文本主判据影响（回归 judge 行为） ──
j_exp = {"overall_score": 0.9, "needs_regeneration": False, "issues": ["wrong_speed"]}
j_out = {"overall_score": 0.92, "needs_regeneration": False, "issues": ["wrong_speed"]}
assert example_passes_gate(j_exp, j_out, stage="judge")
j_out2 = {"overall_score": 0.2, "needs_regeneration": True, "issues": ["wrong_speaker"]}
assert not example_passes_gate(j_exp, j_out2, stage="judge")
print("judge stage behavior unchanged")

print("GATE2_FINAL_OK")

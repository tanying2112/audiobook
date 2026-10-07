"""校准：live v43 跑新金标 24 例，看加权相似度分布——验证 Gate2 公平且有区分度。"""
import json, sys, time
sys.path.insert(0, "src")

from audiobook_studio.feedback.canary import _run_stage_with_prompt_version, _load_golden_examples
from audiobook_studio.feedback.candidate_eval import score_output_vs_expected, _text_similarity

examples = _load_golden_examples("edit_for_tts")  # -> data/golden/train/edit/edit.jsonl (24)
print(f"loaded {len(examples)} examples", flush=True)

rows = []
for i, ex in enumerate(examples):
    inp, exp = ex["input"], ex["expected_output"]
    t0 = time.time()
    try:
        out = _run_stage_with_prompt_version("edit", 43, inp)
        out = out.model_dump() if hasattr(out, "model_dump") else out
    except Exception as e:
        print(f"[{i}] RUN ERROR: {str(e)[:120]}", flush=True)
        rows.append({"i": i, "diff": inp.get("difficulty"), "error": str(e)[:80]})
        continue
    sim = score_output_vs_expected(exp, out, stage="edit_for_tts")
    tsim = _text_similarity(exp["edited_text"], out.get("edited_text", ""))
    rows.append({"i": i, "diff": inp.get("difficulty"), "forbid": inp.get("forbid_edit"),
                 "score": round(sim, 3), "text_sim": round(tsim, 3),
                 "out_conf": out.get("confidence"), "pass": sim >= 0.85,
                 "out_text": out.get("edited_text", "")[:60],
                 "exp_text": exp["edited_text"][:60], "secs": round(time.time()-t0, 1)})
    print(f"[{i}] {inp.get('difficulty')}{'(锁)' if inp.get('forbid_edit') else ''} "
          f"score={sim:.3f} text={tsim:.3f} pass={sim>=0.85} ({rows[-1]['secs']}s)", flush=True)
    print(f"    out: {rows[-1]['out_text']}", flush=True)
    print(f"    exp: {rows[-1]['exp_text']}", flush=True)

ok = [r for r in rows if "score" in r]
if ok:
    pr = sum(r["pass"] for r in ok) / len(ok)
    print(f"\n=== 通过率 {pr:.3f} ({sum(r['pass'] for r in ok)}/{len(ok)}) ===")
    for d in "ABCD":
        sub = [r for r in ok if r["diff"] == d]
        if sub:
            print(f"  {d}: {sum(r['pass'] for r in sub)}/{len(sub)}")
Path = __import__("pathlib").Path
Path("scratch/calibrate_gate2_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))

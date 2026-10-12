from pathlib import Path
p = Path("scratch/verify_gate2_final.py")
src = p.read_text(encoding="utf-8")
old = '''# ── 1) 校准基线回放：live v43 24 例 ──
cal = json.loads(Path("scratch/calibrate_gate2_results.json").read_text(encoding="utf-8"))
rows = cal["rows"] if "rows" in cal else cal
n_pass = 0
for r in rows:
    exp = r.get("expected") or {}
    out = r.get("live_output") or r.get("output") or {}
    if example_passes_gate(exp, out, stage="edit"):
        n_pass += 1
rate = n_pass / len(rows)
print(f"Gate2 replay: live v43 → {n_pass}/{len(rows)} = {rate:.4f} (threshold 0.95)")
assert rate >= 0.95, "live 基线未过门 —— 门被 rigged"'''
new = '''# ── 1) 校准基线回放：live v43 24 例（calibrate_gate2_results.json 存的是
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
assert rate >= 0.95, "live 基线未过门 —— 门被 rigged"'''
assert src.count(old) == 1
src = src.replace(old, new)
p.write_text(src, encoding="utf-8")
print("ok")

#!/usr/bin/env python
"""差距 A/B/G 修复端到端验证: 新标注 vs 归档旧基线 (35/35 neutral) 的分布对照."""
import json, collections
from pathlib import Path

BASE = Path(__file__).parent
new = json.load(open(BASE / "run_a_annotations.json"))
old = json.load(open(BASE / "archive_pre_fix/run_a_annotations.json"))

for tag, data in (("旧(修复前)", old), ("新(修复后)", new)):
    recs = [r for r in data["records"] if r.get("ok")]
    em = collections.Counter(r["annotation"]["emotion"] for r in recs)
    sp = collections.Counter(r["annotation"]["speaker_canonical_name"] for r in recs)
    n_ovr = sum(len((r.get("director") or {}).get("sentence_overrides", [])) for r in recs)
    n_vid = sum(1 for r in recs for o in (r.get("director") or {}).get("sentence_overrides", [])
                if o.get("voice_id"))
    vids = collections.Counter(o["voice_id"] for r in recs for o in (r.get("director") or {})
                              .get("sentence_overrides", []) if o.get("voice_id"))
    speeds = [o.get("speed") for r in recs for o in (r.get("director") or {})
              .get("sentence_overrides", []) if o.get("speed")]
    print(f"[{tag}] ok={len(recs)}/{len(data['records'])}")
    print(f"  emotion: {dict(em)}")
    print(f"  speaker: {dict(sp)}")
    print(f"  导演句级覆盖 {n_ovr}, voice_id 非空 {n_vid}: {dict(vids)}")
    if speeds:
        print(f"  speed 范围: {min(speeds)} ~ {max(speeds)} (中位 {sorted(speeds)[len(speeds)//2]})")
    print()

# 差距 A 判定: 情感不再全 neutral
new_recs = [r for r in new["records"] if r.get("ok")]
non_neutral = [r for r in new_recs if r["annotation"]["emotion"] != "neutral"]
multi_spk = len({r["annotation"]["speaker_canonical_name"] for r in new_recs}) > 1
print(f"判定: 非中性段 {len(non_neutral)}/{len(new_recs)}; 说话人多值={multi_spk}")
print("PASS" if non_neutral and multi_spk else "FAIL — 差距 A/B 修复未见端到端生效")

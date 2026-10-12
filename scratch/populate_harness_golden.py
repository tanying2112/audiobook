"""把生产金标 (data/golden/{split}/{stage}/{stage}.jsonl) 移植到 harness 平铺金标
(data/golden/harness/{split}/{stage}.jsonl)，供 harness 迭代闭环的 train 选取与
test 留出集评估使用。幂等：sample_hash 去重，重复运行不重复写入。
"""
import sys
sys.path.insert(0, "src")

import json
from pathlib import Path

from audiobook_studio.harness.storage import get_storage

STAGES = ["extract", "analyze", "annotate", "edit", "judge", "quality", "translate"]
storage = get_storage()

total = 0
for split in ["train", "test"]:
    for stage in STAGES:
        src = Path("data/golden") / split / stage / f"{stage}.jsonl"
        if not src.exists():
            print(f"SKIP {split}/{stage}: source missing")
            continue
        added = 0
        with src.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                record = {
                    "stage": stage,
                    "input": rec.get("input", {}),
                    "output": rec.get("expected_output", rec.get("output", {})),
                    "source": f"production_golden_port:{split}",
                }
                if storage.append_golden_sample(split, stage, record):
                    added += 1
        total += added
        print(f"OK {split}/{stage}: +{added}")

print(f"\nTOTAL added: {total}")
print("Stats:", storage.get_golden_stats())

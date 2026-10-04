"""M0 冷启动：当 data/golden 的 val/test 稀疏时，从 train 确定性切分补充。

设计原则：
* 只读 train，写 val/test，绝不污染 train。
* 确定性：按样本内容 hash 选样，同输入同结果，可复现。
* 幂等：目标文件已存在且非空则跳过，可重复运行。
* 不触网、不调用 LLM，纯本地文件操作。
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

GOLDEN_ROOT = Path("data/golden")
STAGES = ["extract", "analyze", "annotate", "edit", "translate", "judge", "quality", "quality_judge"]


def _hash(s: str) -> int:
    return int.from_bytes(hashlib.sha256(s.encode("utf-8")).digest()[:8], "big")


def _split_train(train_dir: Path, ratio: float) -> list[str]:
    samples: list[str] = []
    if not train_dir.exists():
        return samples
    for f in sorted(train_dir.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                samples.append(line)
    if not samples:
        return samples
    # 确定性选样：hash 落在 [0, ratio) 区间的入选
    chosen = [ln for ln in samples if (_hash(ln) % 1000) / 1000.0 < ratio]
    # 保证至少 1 条，便于门禁有样本可评
    if not chosen:
        chosen = [samples[0]]
    return chosen


def seed(split: str, ratio: float = 0.15, root: Path = GOLDEN_ROOT, dry_run: bool = False) -> int:
    train_dir = root / "train"
    target_dir = root / split
    added = 0
    for stage in STAGES:
        tdir = train_dir / stage
        gdir = target_dir / stage
        gfile = gdir / f"{stage}.jsonl"
        if gfile.exists() and gfile.stat().st_size > 0:
            continue  # 已存在则不动（幂等）
        chosen = _split_train(tdir, ratio)
        if not chosen:
            continue
        if not dry_run:
            gdir.mkdir(parents=True, exist_ok=True)
            gfile.write_text("\n".join(chosen) + "\n", encoding="utf-8")
        added += len(chosen)
        print(f"{split}/{stage}: +{len(chosen)} (from {len(list(tdir.glob('*.jsonl')))} train files)")
    return added


def main() -> None:
    ap = argparse.ArgumentParser(description="冷启动金标切分 (M0)")
    ap.add_argument("--split", default="val")
    ap.add_argument("--ratio", type=float, default=0.15)
    ap.add_argument("--root", default=str(GOLDEN_ROOT))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    n = seed(args.split, args.ratio, Path(args.root), args.dry_run)
    print(f"seeded {n} samples into {args.split}")


if __name__ == "__main__":
    main()

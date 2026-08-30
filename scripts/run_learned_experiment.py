"""CLI：运行 DSPy/GEPA 学习型候选生成的离线实验，并落盘证据。

用法：
    python scripts/run_learned_experiment.py                 # 默认 stages，离线 MockLM
    MOCK_LLM=true python scripts/run_learned_experiment.py  # 显式离线
    python scripts/run_learned_experiment.py --stage judge  # 单 stage
    python scripts/run_learned_experiment.py --out /tmp/exp.jsonl

证据写入 data/harness/learned_experiment.jsonl（默认），可用
``load_experiment_records()`` 读取。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="运行 DSPy/GEPA 学习型候选生成的离线实验")
    parser.add_argument("--stage", action="append", help="指定 stage（可多次）；默认见 DEFAULT_STAGES")
    parser.add_argument("--few-shot", default="tests/golden/bootstrap_examples.json")
    parser.add_argument("--out", default=None, help="证据落盘路径")
    parser.add_argument("--k", type=int, default=1)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_arg_parser().parse_args(argv)

    # 确保能 import 包（脚本从仓库根运行）
    repo_root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(repo_root / "src"))

    from audiobook_studio.harness.learned_experiment import (
        DEFAULT_STAGES,
        load_experiment_records,
        run_learned_experiment,
    )

    stages = args.stage or DEFAULT_STAGES
    print(
        f"[learned_experiment] eval_mode={'mock' if __import__('os').getenv('MOCK_LLM','false').lower() in ('1','true','yes') else 'real'} stages={stages}"
    )

    records = run_learned_experiment(
        stages=stages,
        few_shot_path=args.few_shot,
        out_path=args.out,
        k=args.k,
    )

    print("\n=== 实验结果 ===")
    for r in records:
        print(
            f"  {r['stage']:<20} optimized_len={r.get('optimized_prompt_len')}"
            f"  iters={r.get('iterations_completed')}  pareto={r.get('pareto_frontier_size')}"
            f"  rb_v={r.get('rulebased_candidate_version')} ln_v={r.get('learned_candidate_version')}"
        )
    print(f"\n已落盘 {len(records)} 条记录。")
    if args.out:
        print(f"证据文件: {args.out}")
    else:
        print("证据文件: data/harness/learned_experiment.jsonl")
        # 回读验证可加载
        loaded = load_experiment_records()
        print(f"load_experiment_records() -> {len(loaded)} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

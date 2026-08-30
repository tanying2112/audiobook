"""端到端 dry-run 验证脚本（运维 CLI 包装）：真实跑一轮 ``run_iteration_cycle``，
验证候选是否真被编译 / 评判 / 门禁裁决。作为「自主迭代的有声书 harness 系统」运营件验收。

核心逻辑在 ``audiobook_studio.harness.smoke_test``，本脚本仅做参数解析 / 报告打印 /
退出码，便于独立运行与接入定时冒烟。详见 ``smoke_test.run_smoke_test`` 的 docstring。

用法：
    python scripts/harness_self_iteration_dryrun.py                # 默认 stage=analyze
    python scripts/harness_self_iteration_dryrun.py --stage edit
    python scripts/harness_self_iteration_dryrun.py --use-learned  # 学习型候选生成
    python scripts/harness_self_iteration_dryrun.py --out /tmp/dryrun.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from audiobook_studio.harness.smoke_test import run_smoke_test  # noqa: E402


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="端到端 dry-run 验证：真实跑一轮 run_iteration_cycle（编译→评判→门禁）"
    )
    parser.add_argument("--stage", default="analyze", help="golden stage 名（默认 analyze）")
    parser.add_argument("--k", type=int, default=3, help="M3 few-shot 示例数")
    parser.add_argument("--cases", type=int, default=3, help="注入的合成 test 样本数")
    parser.add_argument("--use-learned", action="store_true", help="启用 DSPy/GEPA 学习型候选生成")
    parser.add_argument("--no-mock", action="store_true", help="关闭 mock（触真实 LLM，谨慎）")
    parser.add_argument("--out", default=None, help="JSON 验收报告落盘路径")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    report = run_smoke_test(
        stage=args.stage,
        k=args.k,
        cases=args.cases,
        use_learned=args.use_learned,
        mock=not args.no_mock,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已落盘: {args.out}")

    if not report.get("all_passed"):
        print("\n[FAIL] 验收未通过：")
        for control in report.get("controls", []):
            for failure in control.get("acceptance_failures", []):
                print(f"  - {failure}")
        if report.get("error"):
            print(f"  - 异常: {report['error']}")
        return 1
    print("\n[PASS] 端到端 dry-run 验收通过：候选被真实编译/评判/门禁裁决。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

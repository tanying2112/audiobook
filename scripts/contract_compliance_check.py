#!/usr/bin/env python3
"""
Contract Compliance Check Script for CI Quality Gate.

Validates that LLM output schema compliance rate meets ≥99% threshold.
Run in CI as part of quality gate to block merges when compliance drops.

Usage:
    python scripts/contract_compliance_check.py --threshold 0.99 --stage all --report reports/compliance_report_latest.json
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


def load_compliance_report(report_path: str) -> dict:
    """Load compliance report from JSON file."""
    path = Path(report_path)
    if not path.exists():
        # Try to find latest report in default location
        default_dir = Path("./reports/compliance")
        if default_dir.exists():
            reports = list(default_dir.glob("compliance_report_*.json"))
            if reports:
                path = max(reports, key=lambda p: p.stat().st_mtime)
                print(f"📄 Using latest report: {path}")
            else:
                return {"error": f"No compliance report found at {report_path} or in default location"}
        else:
            return {"error": f"No compliance report found at {report_path}"}

    with open(path) as f:
        return json.load(f)


def check_compliance_from_report(report: dict, threshold: float = 0.99, stage: str = "all") -> dict:
    """Check compliance from loaded report data.

    Args:
        report: Loaded compliance report dict
        threshold: Minimum compliance rate required (0.0-1.0)
        stage: Stage to check ("all" or specific stage name)

    Returns:
        Dict with check results
    """
    if "error" in report:
        return {"passed": False, "error": report["error"]}

    if stage == "all":
        overall_rate = report.get("overall_compliance_rate", 0.0)
        passed = overall_rate >= threshold

        stage_results = {}
        for stage_name, stage_data in report.get("stage_summaries", {}).items():
            rate = stage_data.get("compliance_rate", 0.0)
            stage_passed = rate >= threshold
            stage_results[stage_name] = {
                "pass": stage_passed,
                "compliance_rate": rate,
                "total_calls": stage_data.get("total_calls", 0),
                "compliant_calls": stage_data.get("compliant_calls", 0),
            }

        return {
            "passed": passed,
            "overall_compliance_rate": overall_rate,
            "stage_results": stage_results,
        }
    else:
        stage_data = report.get("stage_summaries", {}).get(stage)
        if not stage_data:
            return {
                "passed": False,
                "overall_compliance_rate": 0.0,
                "stage": stage,
                "error": f"No data for stage: {stage}",
            }

        rate = stage_data.get("compliance_rate", 0.0)
        passed = rate >= threshold

        return {
            "passed": passed,
            "overall_compliance_rate": rate,
            "stage": stage,
            "stage_results": {
                stage: {
                    "pass": passed,
                    "compliance_rate": rate,
                    "total_calls": stage_data.get("total_calls", 0),
                    "compliant_calls": stage_data.get("compliant_calls", 0),
                }
            },
        }


def print_compliance_report(result: dict):
    """Print formatted compliance report."""
    print("\n" + "=" * 70)
    print("CONTRACT COMPLIANCE CHECK")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Threshold: {result.get('threshold', 0.99):.1%}")
    print(f"Overall Compliance Rate: {result.get('overall_compliance_rate', 0):.2%}")
    print(f"Overall Status: {'✅ PASS' if result.get('passed') else '❌ FAIL'}")
    print("-" * 70)

    if "error" in result:
        print(f"  ⚠️  {result['error']}")
    elif "stage_results" in result:
        for stage, data in result["stage_results"].items():
            if isinstance(data, dict) and "pass" in data:
                status = "✅" if data.get("pass") else "❌"
                print(
                    f"  {status} {stage:20s} | {data.get('compliance_rate', 0):.2%} | {data.get('compliant_calls', 0)}/{data.get('total_calls', 0)} calls"
                )

    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Contract Compliance Check for CI")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.99,
        help="Minimum compliance rate (default: 0.99)",
    )
    parser.add_argument("--stage", default="all", help="Stage to check (default: all)")
    parser.add_argument("--report", help="Path to compliance report JSON (default: auto-detect latest)")
    parser.add_argument("--output", help="Output JSON report path")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit with error code on failure")

    args = parser.parse_args()

    if args.threshold < 0 or args.threshold > 1:
        print(f"❌ Error: threshold must be between 0 and 1, got {args.threshold}")
        sys.exit(1)

    print(f"🔍 Running contract compliance check (threshold: {args.threshold:.1%})...")

    # Load report
    report_path = args.report or "./reports/compliance/compliance_report_latest.json"
    report = load_compliance_report(report_path)

    result = check_compliance_from_report(report, threshold=args.threshold, stage=args.stage)
    result["threshold"] = args.threshold

    print_compliance_report(result)

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
        print(f"📝 Report saved to: {args.output}")

    if args.fail_on_error and not result.get("passed", False):
        print(f"\n❌ Compliance check FAILED: {result.get('overall_compliance_rate', 0):.2%} < {args.threshold:.1%}")
        sys.exit(1)

    if result.get("passed"):
        print(f"\n✅ Compliance check PASSED: {result.get('overall_compliance_rate', 0):.2%} ≥ {args.threshold:.1%}")
    else:
        print(f"\n⚠️  Compliance check did not meet threshold (no hard fail)")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Audiobook Studio — Promotion Gate & Canary Release CLI
=======================================================

Thin CLI wrapper that delegates to src/audiobook_studio/feedback/release.py

This script provides the CLI interface for:
- Promotion Gate evaluation (4 hard criteria)
- Canary Release management (start, record, complete, status)
- Version Store & Rollback (promote, rollback, status, history)
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audiobook_studio.feedback.release import (
    CanaryConfig,
    CanaryMetrics,
    CanaryRelease,
    PromotionGate,
    PromotionGateResult,
    PromotionMetrics,
    VersionStore,
)

logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audiobook Studio Promotion Gate & Canary Release Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Evaluate promotion gate with metrics
  python scripts/promote.py evaluate --stage edit_for_tts --format 0.995 --golden 0.96 --quality 1.03 --human 0.85

  # Start canary release
  python scripts/promote.py canary-start --stage edit_for_tts --version v2 --baseline 0.85

  # Record canary metrics
  python scripts/promote.py canary-record --stage edit_for_tts --version v2 --samples 150 --quality 0.87 --baseline 0.85 --errors 0.02

  # Complete canary (promote to 100%)
  python scripts/promote.py canary-complete --stage edit_for_tts --version v2

  # Rollback to previous version
  python scripts/promote.py rollback --stage edit_for_tts

  # Rollback to specific version
  python scripts/promote.py rollback --stage edit_for_tts --target 1

  # Show version status
  python scripts/promote.py status

  # Show rollback history
  python scripts/promote.py history --stage edit_for_tts
""",
    )
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # evaluate command
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate promotion gate")
    eval_parser.add_argument("--stage", type=str, required=True, help="Pipeline stage name")
    eval_parser.add_argument("--format", type=float, required=True, help="Format compliance rate (0-1)")
    eval_parser.add_argument("--golden", type=float, required=True, help="Golden dataset pass rate (0-1)")
    eval_parser.add_argument("--quality", type=float, required=True, help="Quality score ratio (e.g., 1.03)")
    eval_parser.add_argument("--human", type=float, required=True, help="Human preference score (0-1)")
    eval_parser.add_argument("--threshold-format", type=float, default=0.99)
    eval_parser.add_argument("--threshold-golden", type=float, default=0.95)
    eval_parser.add_argument("--threshold-quality", type=float, default=1.02)
    eval_parser.add_argument("--threshold-human", type=float, default=0.80)

    # canary start command
    canary_start = subparsers.add_parser("canary-start", help="Start canary release")
    canary_start.add_argument("--stage", type=str, required=True)
    canary_start.add_argument("--version", type=str, required=True)
    canary_start.add_argument("--baseline", type=float, required=True, help="Baseline quality score")
    canary_start.add_argument("--traffic", type=float, default=0.1, help="Traffic percentage (0-1)")
    canary_start.add_argument("--min-samples", type=int, default=100)
    canary_start.add_argument("--rollback-threshold", type=float, default=0.95)

    # canary record command
    canary_record = subparsers.add_parser("canary-record", help="Record canary metrics")
    canary_record.add_argument("--stage", type=str, required=True)
    canary_record.add_argument("--version", type=str, required=True)
    canary_record.add_argument("--samples", type=int, required=True)
    canary_record.add_argument("--quality", type=float, required=True, help="Current average quality")
    canary_record.add_argument("--baseline", type=float, required=True, help="Baseline quality")
    canary_record.add_argument("--errors", type=float, default=0.0, help="Error rate (0-1)")

    # canary complete command
    canary_complete = subparsers.add_parser("canary-complete", help="Complete canary, promote to 100%")
    canary_complete.add_argument("--stage", type=str, required=True)
    canary_complete.add_argument("--version", type=str, required=True)

    # canary status command
    canary_status = subparsers.add_parser("canary-status", help="Show canary status")
    canary_status.add_argument("--stage", type=str, required=True)
    canary_status.add_argument("--version", type=str, required=True)

    # canary list command
    subparsers.add_parser("canary-list", help="List all active canaries")

    # rollback command
    rollback_parser = subparsers.add_parser("rollback", help="Rollback to previous version")
    rollback_parser.add_argument("--stage", type=str, required=True)
    rollback_parser.add_argument("--target", type=int, help="Target version (default: previous)")

    # status command
    subparsers.add_parser("status", help="Show current versions")

    # history command
    history_parser = subparsers.add_parser("history", help="Show rollback history")
    history_parser.add_argument("--stage", type=str, help="Filter by stage")
    history_parser.add_argument("--limit", type=int, default=20)

    # demo command (original functionality)
    subparsers.add_parser("demo", help="Run demo/test cases")

    return parser.parse_args()


def cmd_evaluate(args):
    gate = PromotionGate(
        format_compliance_threshold=args.threshold_format,
        golden_dataset_threshold=args.threshold_golden,
        quality_score_threshold=args.threshold_quality,
        human_preference_threshold=args.threshold_human,
    )
    result = gate.evaluate(
        format_compliance_rate=args.format,
        golden_dataset_pass_rate=args.golden,
        quality_score_ratio=args.quality,
        human_preference_score=args.human,
    )
    print(
        json.dumps(
            {
                "stage": args.stage,
                "passed": result.passed,
                "failed_criteria": result.failed_criteria,
                "metrics": {
                    "format_compliance_rate": result.metrics.format_compliance_rate,
                    "golden_dataset_pass_rate": result.metrics.golden_dataset_pass_rate,
                    "quality_score_ratio": result.metrics.quality_score_ratio,
                    "human_preference_score": result.metrics.human_preference_score,
                },
                "timestamp": result.timestamp.isoformat(),
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0 if result.passed else 1


def cmd_canary_start(args):
    config = CanaryConfig(
        traffic_percentage=args.traffic,
        min_samples=args.min_samples,
        rollback_threshold=args.rollback_threshold,
    )
    canary = CanaryRelease(config)
    success = canary.start_canary(args.stage, args.version, args.baseline)
    if success:
        print(f"✅ Started canary for {args.stage}-{args.version}")
    else:
        print(f"❌ Failed to start canary")
    return 0 if success else 1


def cmd_canary_record(args):
    config = CanaryConfig()  # Use defaults for thresholds
    canary = CanaryRelease(config)
    metrics = CanaryMetrics(
        version=args.version,
        stage=args.stage,
        samples_collected=args.samples,
        avg_quality_score=args.quality,
        baseline_quality_score=args.baseline,
        quality_ratio=args.quality / args.baseline if args.baseline > 0 else 0,
        error_rate=args.errors,
        timestamp=datetime.now(timezone.utc),
    )
    canary.record_metrics(args.stage, args.version, metrics)
    print(f"Recorded metrics for {args.stage}-{args.version}: quality_ratio={metrics.quality_ratio:.4f}")

    # Check if rollback was triggered
    status = canary.get_canary_status(args.stage, args.version)
    if status and status.get("status") == "rolled_back":
        print(f"🔴 AUTO ROLLBACK TRIGGERED: {status.get('rollback_reason')}")
        return 1
    return 0


def cmd_canary_complete(args):
    config = CanaryConfig()
    canary = CanaryRelease(config)
    success = canary.complete_canary(args.stage, args.version)
    if success:
        # Also update version store
        try:
            version_num = int(args.version.lstrip("v"))
            store = VersionStore()
            store.promote_version(args.stage, version_num)
            print(f"✅ Completed canary and promoted {args.stage} to v{version_num}")
        except ValueError:
            print(f"✅ Completed canary for {args.stage}-{args.version}")
    else:
        print(f"❌ Failed to complete canary")
    return 0 if success else 1


def cmd_canary_status(args):
    config = CanaryConfig()
    canary = CanaryRelease(config)
    status = canary.get_canary_status(args.stage, args.version)
    if status:
        print(json.dumps(status, indent=2, ensure_ascii=False, default=str))
    else:
        print(f"No canary found for {args.stage}-{args.version}")
    return 0


def cmd_canary_list(args):
    config = CanaryConfig()
    canary = CanaryRelease(config)
    all_canaries = canary.get_all_canaries()
    if all_canaries:
        for canary_id, data in all_canaries.items():
            print(f"  {canary_id}: {data.get('status', 'unknown')}")
    else:
        print("No active canaries")
    return 0


def cmd_rollback(args):
    store = VersionStore()
    if args.target:
        success = store.rollback_version(args.stage, args.target)
    else:
        success = store.rollback_last(args.stage)
    return 0 if success else 1


def cmd_status(args):
    store = VersionStore()
    status = store.get_status()
    print(json.dumps(status, indent=2, ensure_ascii=False, default=str))
    return 0


def cmd_history(args):
    store = VersionStore()
    history = store.get_rollback_history(args.stage, args.limit)
    if history:
        for entry in history:
            print(
                f"  {entry['timestamp']} | {entry['stage']} | {entry['action']} | v{entry['from_version']} → v{entry['to_version']} | {'✅' if entry['success'] else '❌'}"
            )
    else:
        print("No rollback history")
    return 0


def cmd_demo(args):
    """原有的演示功能."""
    gate = PromotionGate()

    print("Promotion Gate Criteria:")
    status = gate.get_status()
    for criterion, threshold in status["thresholds"].items():
        print(f"  {criterion}: ≥ {threshold:.0%}" if "ratio" not in criterion else f"  {criterion}: ≥ {threshold:.2f}x")
    print()

    # 测试案例1: 所有指标达标
    print("Test Case 1: All metrics PASS")
    result1 = gate.evaluate(
        format_compliance_rate=0.995,
        golden_dataset_pass_rate=0.96,
        quality_score_ratio=1.03,
        human_preference_score=0.85,
    )
    print(f"Result: {'PASS' if result1.passed else 'FAIL'}")
    if not result1.passed:
        print(f"Failed criteria: {result1.failed_criteria}")
    print()

    # 测试案例2: 格式合规率不达标
    print("Test Case 2: Format compliance FAIL")
    result2 = gate.evaluate(
        format_compliance_rate=0.98,
        golden_dataset_pass_rate=0.96,
        quality_score_ratio=1.03,
        human_preference_score=0.85,
    )
    print(f"Result: {'PASS' if result2.passed else 'FAIL'}")
    if not result2.passed:
        print(f"Failed criteria: {result2.failed_criteria}")
    print()

    # 测试案例3: 多项不达标
    print("Test Case 3: Multiple criteria FAIL")
    result3 = gate.evaluate(
        format_compliance_rate=0.98,
        golden_dataset_pass_rate=0.90,
        quality_score_ratio=1.01,
        human_preference_score=0.75,
    )
    print(f"Result: {'PASS' if result3.passed else 'FAIL'}")
    if not result3.passed:
        print(f"Failed criteria: {result3.failed_criteria}")
    print()

    # 使用字典接口
    print("Test Case 4: Using dictionary interface")
    metrics_dict = {
        "format_compliance_rate": 0.992,
        "golden_dataset_pass_rate": 0.97,
        "quality_score_ratio": 1.025,
        "human_preference_score": 0.82,
    }
    result4 = gate.evaluate_from_dict(metrics_dict)
    print(f"Result: {'PASS' if result4.passed else 'FAIL'}")
    if not result4.passed:
        print(f"Failed criteria: {result4.failed_criteria}")

    print("\n=== Demo Complete ===")
    return 0


def main():
    args = parse_args()

    if not args.command:
        # 无参数时运行 demo
        return cmd_demo(args)

    commands = {
        "evaluate": cmd_evaluate,
        "canary-start": cmd_canary_start,
        "canary-record": cmd_canary_record,
        "canary-complete": cmd_canary_complete,
        "canary-status": cmd_canary_status,
        "canary-list": cmd_canary_list,
        "rollback": cmd_rollback,
        "status": cmd_status,
        "history": cmd_history,
        "demo": cmd_demo,
    }

    if args.command in commands:
        return commands[args.command](args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())

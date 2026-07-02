#!/usr/bin/env python3
"""
CLI script to run A/B tests for prompt version comparison.

Usage:
    python scripts/run_ab_test.py --stage edit_for_tts --version-a 1 --version-b 2 --samples 10
    python scripts/run_ab_test.py --stage quality_judge --version-a 1 --version-b 2 --golden-dir tests/golden/quality_judge
    python scripts/run_ab_test.py --stage annotate_paragraph --auto-from-promotion --project-id 1
"""

import argparse
import json
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audiobook_studio.feedback.ab_test import (
    ABTestReport,
    _score_output,
    blind_evaluate,
    build_ab_samples,
    run_ab_test,
)
from src.audiobook_studio.feedback.promotion_gate import _load_golden_examples as _load_golden_dataset

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run A/B test for prompt versions")
    parser.add_argument(
        "--stage",
        type=str,
        required=True,
        help="Pipeline stage name (e.g., edit_for_tts, quality_judge, annotate_paragraph)",
    )
    parser.add_argument("--version-a", type=int, help="Control version number (e.g., 1)")
    parser.add_argument("--version-b", type=int, help="Treatment version number (e.g. 2)")
    parser.add_argument(
        "--samples",
        type=int,
        default=10,
        help="Number of samples to test (default: 10)",
    )
    parser.add_argument("--golden-dir", type=str, help="Path to golden dataset directory")
    parser.add_argument(
        "--significance",
        type=float,
        default=0.05,
        help="Significance level (default: 0.05)",
    )
    parser.add_argument("--output", type=str, help="Output report JSON file path")
    parser.add_argument("--human-ratings", type=str, help="Path to human ratings JSON file")
    return parser.parse_args()


def load_human_ratings(path: str):
    """Load human ratings from JSON file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def create_synthetic_samples(stage: str, version_a: int, version_b: int, num_samples: int):
    """Create synthetic test samples for demonstration."""
    import uuid

    from src.audiobook_studio.feedback.ab_test import ABTestSample

    samples = []
    for i in range(num_samples):
        sample = ABTestSample(
            sample_id=str(uuid.uuid4()),
            stage=stage,
            input_data={"text": f"Test paragraph {i+1}"},
            # Version A: shorter, less detailed output
            output_a={
                "edited_text": f"Version A output {i+1}",
                "confidence": 0.7 if stage == "edit_for_tts" else 0.7,
            },
            # Version B: longer, more detailed output (simulating improvement)
            output_b={
                "edited_text": f"Version B improved output {i+1} with more detail and better quality",
                "confidence": 0.85 if stage == "edit_for_tts" else 0.85,
            },
            version_a=version_a,
            version_b=version_b,
        )
        samples.append(sample)
    return samples


def main():
    args = parse_args()

    version_a = args.version_a or 1
    version_b = args.version_b or (version_a + 1)

    # Load or create samples
    if args.golden_dir:
        golden_dir = Path(args.golden_dir)
        if not golden_dir.exists():
            logger.error(f"Golden dataset directory not found: {golden_dir}")
            return 1

        golden_examples = _load_golden_dataset(args.stage)
        if not golden_examples:
            logger.warning("No golden examples found, using synthetic samples")
            samples = create_synthetic_samples(args.stage, version_a, version_b, args.samples)
        else:
            # Limit samples
            if len(golden_examples) > args.samples:
                golden_examples = golden_examples[: args.samples]
            samples = build_ab_samples(args.stage, golden_examples, version_a, version_b)
    else:
        logger.info(f"No golden dataset provided, using {args.samples} synthetic samples")
        samples = create_synthetic_samples(args.stage, version_a, version_b, args.samples)

    if not samples:
        logger.error("No samples available for testing")
        return 1

    logger.info(f"Running A/B test: {args.stage} v{version_a} vs v{version_b} with {len(samples)} samples")

    # Run A/B test
    report = run_ab_test(
        stage=args.stage,
        samples=samples,
        significance_level=args.significance,
    )

    # Apply human ratings if provided
    if args.human_ratings:
        human_ratings = load_human_ratings(args.human_ratings)
        report = blind_evaluate(report, human_ratings)
        logger.info("Applied human ratings")

    # Print summary
    print("\n=== A/B Test Report ===")
    print(f"Stage: {report.stage}")
    print(f"Versions: v{report.version_a} (control) vs v{report.version_b} (treatment)")
    print(f"Samples: {report.num_samples}")
    print(f"Avg Score A: {report.avg_score_a:.4f}")
    print(f"Avg Score B: {report.avg_score_b:.4f}")
    print(f"Improvement: {report.improvement_pct:+.2f}%")
    print(f"\nWin Counts:")
    print(f"  A wins: {report.a_wins}")
    print(f"  B wins: {report.b_wins}")
    print(f"  Ties: {report.ties}")
    print(f"\nStatistical Significance:")
    print(f"  p-value: {report.p_value:.4f}")
    print(f"  CI (95%): [{report.confidence_interval[0]:.4f}, {report.confidence_interval[1]:.4f}]")
    print(f"  Significant (α={report.significance_level}): {'Yes ✅' if report.is_significant else 'No ❌'}")
    print(f"\nRecommendation: {report.recommendation}")

    # Save report if output path provided
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        report_dict = {
            "stage": report.stage,
            "version_a": report.version_a,
            "version_b": report.version_b,
            "num_samples": report.num_samples,
            "avg_score_a": report.avg_score_a,
            "avg_score_b": report.avg_score_b,
            "improvement_pct": report.improvement_pct,
            "a_wins": report.a_wins,
            "b_wins": report.b_wins,
            "ties": report.ties,
            "p_value": report.p_value,
            "confidence_interval": list(report.confidence_interval),
            "is_significant": report.is_significant,
            "significance_level": report.significance_level,
            "recommendation": report.recommendation,
            "generated_at": report.generated_at,
            "results": [
                {
                    "sample_id": r.sample_id,
                    "winner": r.winner,
                    "score_a": r.score_a,
                    "score_b": r.score_b,
                    "rationale": r.rationale,
                }
                for r in report.results
            ],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report_dict, f, indent=2, ensure_ascii=False)

        logger.info(f"Report saved to {output_path}")

    # Exit with code based on recommendation
    if "推荐升级" in report.recommendation or "recommend upgrade" in report.recommendation.lower():
        return 0
    elif "不建议升级" in report.recommendation or "do not recommend" in report.recommendation.lower():
        return 1
    else:
        return 2  # Inconclusive


if __name__ == "__main__":
    sys.exit(main())

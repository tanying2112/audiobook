#!/usr/bin/env python3
"""CLI for BootstrapFewShot DSPy optimization.

Usage:
    python scripts/bootstrap_fewshot.py annotate_paragraph
    python scripts/bootstrap_fewshot.py edit_for_tts --budget 300
    python scripts/bootstrap_fewshot.py --help
"""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.audiobook_studio.feedback.bootstrap_fewshot import (
    BootstrapFewShotOptimizer,
    load_training_examples,
    run_bootstrap_optimization,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Run BootstrapFewShot DSPy optimization for pipeline stages")
    parser.add_argument(
        "stage",
        nargs="?",
        default="annotate_paragraph",
        help="Pipeline stage to optimize (default: annotate_paragraph)",
    )
    parser.add_argument(
        "--budget",
        type=int,
        default=500,
        help="Budget limit for optimization calls (default: 500)",
    )
    parser.add_argument(
        "--patience",
        type=int,
        default=10,
        help="Early stopping patience (default: 10)",
    )
    parser.add_argument(
        "--few-shot",
        type=str,
        default=None,
        help="Path to few-shot examples JSON (default: stage-specific)",
    )
    parser.add_argument(
        "--char-weight",
        type=float,
        default=0.5,
        help="Weight for character recognition objective (default: 0.5)",
    )
    parser.add_argument(
        "--voice-weight",
        type=float,
        default=0.5,
        help="Weight for voice design objective (default: 0.5)",
    )

    args = parser.parse_args()

    # Validate weights
    if abs(args.char_weight + args.voice_weight - 1.0) > 0.001:
        logger.warning(
            "Weights should sum to 1.0, got char=%s, voice=%s",
            args.char_weight,
            args.voice_weight,
        )

    logger.info(f"Starting BootstrapFewShot optimization for stage: {args.stage}")
    logger.info(f"Budget limit: {args.budget}, Patience: {args.patience}")

    try:
        # Load training data
        initial_prompt, training_data = load_training_examples(args.stage, args.few_shot)

        if not training_data:
            logger.error(f"No training examples found for stage: {args.stage}")
            sys.exit(1)

        logger.info(f"Loaded {len(training_data)} training examples")

        # Run optimization
        optimizer = BootstrapFewShotOptimizer(
            stage=args.stage,
            budget_limit=args.budget,
            early_stop_patience=args.patience,
            char_weight=args.char_weight,
            voice_weight=args.voice_weight,
        )

        result = optimizer.optimize(initial_prompt, training_data)

        # Print results
        print("\n" + "=" * 60)
        print("OPTIMIZATION RESULTS")
        print("=" * 60)
        print(f"Stage: {args.stage}")
        print(f"Improvement ratio: {result.improvement_ratio:.2%}")
        print(f"Iterations completed: {result.iterations_completed}")
        print(f"Early stopped: {result.stopped_early}")
        print(f"Character recognition accuracy: {result.metrics.character_recognition_accuracy:.2%}")
        print(f"Voice design accuracy: {result.metrics.voice_design_accuracy:.2%}")
        print(f"Overall score: {result.metrics.overall_score:.2%}")

        if result.pareto_frontier:
            print(f"Pareto frontier scores: {len(result.pareto_frontier)} candidates")

        print("=" * 60)

    except Exception as e:
        logger.error(f"Optimization failed: {e}")
        raise


if __name__ == "__main__":
    main()

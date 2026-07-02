#!/usr/bin/env python3
"""
Feedback Processor CLI — 自动差异分析触发器.

用法:
    python scripts/feedback_processor.py --project-id 1 --analyze-now
    python scripts/feedback_processor.py --project-id 1 --auto-start --interval 300 --threshold 10
"""

import argparse
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from audiobook_studio.database import Base
from audiobook_studio.feedback.auto_processor import create_auto_processor, run_feedback_analysis_cli

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_db_session_factory():
    """Create database session factory."""
    # Use the same database as the main app
    db_path = Path(__file__).resolve().parent.parent / "audiobook_studio.db"
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def main():
    parser = argparse.ArgumentParser(description="Feedback Processor - Auto-trigger analysis of collected feedback")
    parser.add_argument("--project-id", type=int, required=True, help="Project ID to process")
    parser.add_argument(
        "--analyze-now",
        action="store_true",
        help="Run analysis immediately and exit",
    )
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Start background auto-trigger monitor",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Check interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--threshold",
        type=int,
        default=10,
        help="Minimum feedback count to trigger analysis (default: 10)",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show processor status and exit",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Max records to analyze in batch (default: 500)",
    )

    args = parser.parse_args()

    db_factory = get_db_session_factory()

    if args.status:
        # Show status
        processor = create_auto_processor(
            db_factory,
            project_id=args.project_id,
            min_feedback_count=args.threshold,
            check_interval_seconds=args.interval,
            enable_auto_trigger=args.auto_start,
        )
        status = processor.get_status()
        print("\n=== Feedback Processor Status ===")
        for key, value in status.items():
            print(f"  {key}: {value}")
        return 0

    if args.analyze_now:
        # Run analysis once
        logger.info(f"Running one-time analysis for project {args.project_id}")
        result = run_feedback_analysis_cli(db_factory, args.project_id, limit=args.limit)
        print(f"\n=== Analysis Results ===")
        print(f"Total analyzed: {result.total_analyzed}")
        print(f"Patterns found: {len(result.pattern_frequency)}")
        print(f"Top patterns: {result.top_patterns[:5]}")
        print(f"Recommendations: {len(result.recommendations)}")
        for rec in result.recommendations:
            print(f"  - {rec}")
        return 0

    if args.auto_start:
        # Start background monitor
        logger.info(f"Starting auto-trigger monitor for project {args.project_id}")
        processor = create_auto_processor(
            db_factory,
            project_id=args.project_id,
            min_feedback_count=args.threshold,
            check_interval_seconds=args.interval,
            enable_auto_trigger=True,
        )
        processor.start()
        print(f"Feedback processor started. Monitoring project {args.project_id}...")
        print(f"  Check interval: {args.interval}s")
        print(f"  Threshold: {args.threshold} feedback records")
        print("Press Ctrl+C to stop")

        try:
            import time

            while True:
                time.sleep(10)
                status = processor.get_status()
                print(
                    f"\r[{status['generated_at'] if 'generated_at' in status else 'running'}] "
                    f"Unprocessed: {status['unprocessed_feedback_count']} | "
                    f"Last analysis: {status['last_analysis_count']}",
                    end="",
                    flush=True,
                )
        except KeyboardInterrupt:
            print("\nStopping...")
            processor.stop()
            return 0

    # Default: show help
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

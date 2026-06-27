#!/usr/bin/env python3
"""
CLI script to run the self-iteration feedback loop.

This script can be used to:
1. Start the self-iteration loop in background mode
2. Trigger a manual iteration cycle
3. Check the status of the loop
4. Run a one-shot analysis and prompt upgrade
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.audiobook_studio.database import get_database_url
from src.audiobook_studio.feedback.integration import create_self_iteration_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def get_db_session_factory():
    """Create a database session factory."""
    db_url = get_database_url()
    engine = create_engine(db_url)
    return sessionmaker(bind=engine)


def main():
    parser = argparse.ArgumentParser(description="Run self-iteration feedback loop")
    parser.add_argument("--project-id", type=int, required=True, help="Project ID to monitor")
    parser.add_argument(
        "--min-feedback",
        type=int,
        default=10,
        help="Minimum feedback count to trigger analysis (default: 10)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=300,
        help="Check interval in seconds (default: 300)",
    )
    parser.add_argument(
        "--canary",
        type=float,
        default=0.1,
        help="Canary percentage for validation (default: 0.1)",
    )
    parser.add_argument(
        "--no-auto",
        action="store_true",
        help="Disable automatic triggering",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Start command
    start_parser = subparsers.add_parser("start", help="Start the self-iteration loop")
    start_parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as daemon (background)",
    )

    # Status command
    subparsers.add_parser("status", help="Get loop status")

    # Trigger command
    subparsers.add_parser("trigger", help="Manually trigger an iteration")

    # One-shot command
    subparsers.add_parser("once", help="Run one iteration and exit")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Create session factory
    session_factory = get_db_session_factory()

    # Create loop
    loop = create_self_iteration_loop(
        db_session_factory=session_factory,
        project_id=args.project_id,
        min_feedback_count=args.min_feedback,
        check_interval_seconds=args.interval,
        enable_auto_trigger=not args.no_auto,
        canary_percentage=args.canary,
    )

    if args.command == "start":
        logger.info(f"Starting self-iteration loop for project {args.project_id}")
        loop.start()

        if args.daemon:
            import time
            logger.info("Running as daemon. Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(60)
            except KeyboardInterrupt:
                logger.info("Stopping...")
                loop.stop()
        else:
            loop.stop()

    elif args.command == "status":
        status = loop.get_status()
        print(f"Project ID: {status['project_id']}")
        print(f"Running: {status['running']}")
        print(f"Iteration Count: {status['iteration_count']}")
        print(f"Auto Processor: {status['auto_processor']}")
        print(f"Upgraded Prompts: {status['upgraded_prompts']}")
        if status['last_analysis']:
            print(f"Last Analysis: {status['last_analysis']}")

    elif args.command == "trigger":
        logger.info("Triggering manual iteration...")
        result = loop.trigger_iteration_now()
        if result:
            logger.info(f"Analysis complete: {result.total_analyzed} records, {len(result.top_patterns)} patterns")
        else:
            logger.info("No analysis triggered (insufficient feedback)")

    elif args.command == "once":
        logger.info("Running one-shot iteration...")
        loop.start()
        import time
        time.sleep(2)  # Give it time to check
        result = loop.trigger_iteration_now()
        loop.stop()
        if result:
            logger.info(f"Analysis complete: {result.total_analyzed} records")
        else:
            logger.info("No analysis triggered")

    return 0


if __name__ == "__main__":
    sys.exit(main())
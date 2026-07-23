#!/usr/bin/env python3
"""Audiobook Studio CLI - Main entry point.

Modular CLI for Audiobook Studio operations.
Replaces the monolithic run_pipeline.py with clean subcommands.

Usage:
    audiobook-studio <command> [options]
    python -m audiobook_studio.cli <command> [options]

Commands:
    mock-data    Generate mock chapter text files for testing
    init-db      Initialize database schema and seed projects
    pipeline     Run or resume the audiobook processing pipeline
    export       Export audiobook to final formats (M4B, MP3, etc.)
    book         Manage book projects (list, create, show, delete)
"""

import argparse

# Add src to path for module imports
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from .book import add_book_parser
from .export import add_export_parser
from .init_db import add_init_db_parser
from .mock_data import add_mock_data_parser
from .pipeline import add_pipeline_parser


def create_parser() -> argparse.ArgumentParser:
    """Create the main CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="audiobook-studio",
        description="Audiobook Studio - AI-powered audiobook generation pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate mock test data
  audiobook-studio mock-data

  # Initialize database with seed projects
  audiobook-studio init-db

  # Run full pipeline for a book
  audiobook-studio pipeline run 红楼梦 三国演义

  # Run quick pipeline (extract, analyze, annotate only)
  audiobook-studio pipeline run 红楼梦 --quick

  # Resume from checkpoint
  audiobook-studio pipeline resume 42

  # Export with background music
  audiobook-studio export 42 --bg-music bgm.wav --bg-volume -15

  # List all projects
  audiobook-studio book list

  # Create new project from template
  audiobook-studio book create 红楼梦
        """,
    )

    parser.add_argument(
        "--version",
        action="version",
        version="%(prog)s 0.2.0",
    )

    subparsers = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    # Register all subcommands
    add_mock_data_parser(subparsers)
    add_init_db_parser(subparsers)
    add_pipeline_parser(subparsers)
    add_export_parser(subparsers)
    add_book_parser(subparsers)

    return parser


def main(argv: list[str] = None) -> int:
    """Main CLI entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    # Execute the command function
    if hasattr(args, "func"):
        return args.func(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())

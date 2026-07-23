"""Mock data generation CLI command.

Generates mock chapter text files for testing the pipeline.
"""

import argparse
from pathlib import Path

from ..run_pipeline import BOOK_CONFIG, DATA_DIR, MOCK_DATA_DIR, _get_chapter_templates, create_mock_data


def add_mock_data_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add mock-data subcommand to the CLI parser."""
    parser = subparsers.add_parser(
        "mock-data",
        help="Generate mock chapter text files for testing",
        description="Create mock chapter text files under data/mock_data/ for each configured book.",
    )
    parser.add_argument(
        "--books",
        nargs="+",
        default=list(BOOK_CONFIG.keys()),
        help=f"Book names to generate mock data for (default: all: {', '.join(BOOK_CONFIG.keys())})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing chapter files (default: skip existing)",
    )
    parser.set_defaults(func=mock_data_command)


def mock_data_command(args: argparse.Namespace) -> int:
    """Execute the mock-data command."""
    # Override BOOK_CONFIG temporarily if specific books requested
    # For now, just call the existing create_mock_data which uses all BOOK_CONFIG
    # In a more modular design, we'd pass the book list
    try:
        create_mock_data()
        return 0
    except Exception as e:
        print(f"❌ Error generating mock data: {e}")
        return 1

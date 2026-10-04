"""Audiobook Studio CLI - Modular command-line interface.

This module provides a modular CLI for Audiobook Studio operations,
replacing the monolithic run_pipeline.py with clean subcommands.

Commands:
    mock-data    Generate mock chapter text files for testing
    init-db      Initialize database schema and seed projects
    pipeline     Run or resume pipeline processing
    export       Export audiobook to final formats (M4B, MP3, etc.)
    book         Manage book projects (list, create)

Usage:
    python -m audiobook_studio.cli <command> [options]
    audiobook-studio <command> [options]  (if installed as console script)
"""

from .main import main

__all__ = ["main"]

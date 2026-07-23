"""Database initialization CLI command.

Initializes database schema and optionally seeds project records.
"""

import argparse
import asyncio

from ..database import AsyncSessionLocal, drop_async_db, init_async_db
from ..models import Project
from ..run_pipeline import BOOK_CONFIG, initialize_database


def add_init_db_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add init-db subcommand to the CLI parser."""
    parser = subparsers.add_parser(
        "init-db",
        help="Initialize database schema and seed project records",
        description="Create database tables and optionally seed Project records for configured books.",
    )
    parser.add_argument(
        "--no-seed",
        action="store_true",
        help="Skip seeding Project records (only create tables)",
    )
    parser.add_argument(
        "--drop-first",
        action="store_true",
        help="Drop all tables before creating (DESTRUCTIVE!)",
    )
    parser.set_defaults(func=init_db_command)


async def _init_db_async(args: argparse.Namespace) -> int:
    """Async implementation of init-db command."""
    try:
        if args.drop_first:
            # Drop all tables first
            print("⚠️  Dropping all tables...")
            await drop_async_db()
            print("✅ Tables dropped.")

        # Run async initialization
        await init_async_db()
        print("✅ Database schema created.")

        if not args.no_seed:
            # Run seed projects in sync context (uses sync SessionLocal)
            # We could make initialize_database async, but for now run in executor
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, initialize_database, True)
        else:
            print("ℹ️  Skipping project seed data creation.")

        return 0
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        return 1


def init_db_command(args: argparse.Namespace) -> int:
    """Execute the init-db command."""
    return asyncio.run(_init_db_async(args))

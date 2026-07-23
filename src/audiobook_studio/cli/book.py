"""Book management CLI command.

Manages book projects (list, create, show).
"""

import argparse
import asyncio
from datetime import datetime

from sqlalchemy import select

from src.audiobook_studio.database import AsyncSessionLocal
from src.audiobook_studio.models import Project
from src.audiobook_studio.run_pipeline import BOOK_CONFIG


def add_book_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add book subcommand with list/create/show subcommands."""
    parser = subparsers.add_parser(
        "book",
        help="Manage book projects",
        description="List, create, or show book project details.",
    )
    book_subparsers = parser.add_subparsers(dest="book_command", required=True)

    # book list
    list_parser = book_subparsers.add_parser(
        "list",
        help="List all book projects",
        description="Show all projects in the database.",
    )
    list_parser.add_argument(
        "--status",
        choices=["draft", "processing", "completed", "failed"],
        help="Filter by project status",
    )
    list_parser.set_defaults(func=sync_book_list_command)

    # book create
    create_parser = book_subparsers.add_parser(
        "create",
        help="Create a new book project",
        description="Create a new project from a predefined book configuration.",
    )
    create_parser.add_argument(
        "book_name",
        choices=list(BOOK_CONFIG.keys()),
        help="Book name (must be a predefined configuration)",
    )
    create_parser.add_argument(
        "--custom-title",
        type=str,
        help="Custom title (overrides config)",
    )
    create_parser.add_argument(
        "--custom-author",
        type=str,
        help="Custom author (overrides config)",
    )
    create_parser.set_defaults(func=sync_book_create_command)

    # book show
    show_parser = book_subparsers.add_parser(
        "show",
        help="Show project details",
        description="Display detailed information about a project.",
    )
    show_parser.add_argument(
        "project_id",
        type=int,
        help="Project ID to show",
    )
    show_parser.set_defaults(func=sync_book_show_command)

    # book delete
    delete_parser = book_subparsers.add_parser(
        "delete",
        help="Delete a book project",
        description="Delete a project and all associated data (irreversible!).",
    )
    delete_parser.add_argument(
        "project_id",
        type=int,
        help="Project ID to delete",
    )
    delete_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
    )
    delete_parser.set_defaults(func=sync_book_delete_command)


async def book_list_command(args: argparse.Namespace) -> int:
    """Execute the book list command."""
    async with AsyncSessionLocal() as db:
        query = select(Project)
        if args.status:
            query = query.where(Project.status == args.status)

        result = await db.execute(query.order_by(Project.created_at.desc()))
        projects = result.scalars().all()

        if not projects:
            print("No projects found.")
            return 0

        print(f"{'ID':<6} {'Title':<20} {'Author':<15} {'Status':<12} {'Progress':<10} {'Chapters':<10} {'Created'}")
        print("-" * 100)
        for p in projects:
            created = p.created_at[:10] if p.created_at else "N/A"
            print(
                f"{p.id:<6} {p.title[:19]:<20} {p.author[:14]:<15} {p.status:<12} {p.progress:<10.1f} {p.total_chapters_estimated:<10} {created}"
            )

        return 0


async def book_create_command(args: argparse.Namespace) -> int:
    """Execute the book create command."""
    config = BOOK_CONFIG[args.book_name]

    async with AsyncSessionLocal() as db:
        try:
            # Check if project already exists
            result = await db.execute(select(Project).where(Project.title == config["title"]))
            existing = result.scalar_one_or_none()
            if existing:
                print(f"⚠️  Project '{config['title']}' already exists (id={existing.id})")
                return 1

            now = datetime.now().isoformat()
            project = Project(
                title=args.custom_title or config["title"],
                author=args.custom_author or config["author"],
                genre=config["genre"],
                difficulty=config["difficulty"],
                language=config["language"],
                era=config["era"],
                status="draft",
                total_chapters_estimated=config["num_mock_chapters"],
                current_stage="pending",
                progress=0.0,
                total_cost_usd=0.0,
                created_at=now,
                updated_at=now,
            )
            db.add(project)
            await db.commit()
            await db.refresh(project)

            print(f"✅ Created project: {project.title} (id={project.id})")
            return 0
        except Exception as e:
            await db.rollback()
            print(f"❌ Failed to create project: {e}")
            return 1


async def book_show_command(args: argparse.Namespace) -> int:
    """Execute the book show command."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == args.project_id))
        project = result.scalar_one_or_none()
        if not project:
            print(f"❌ Project {args.project_id} not found")
            return 1

        print(f"Project ID:     {project.id}")
        print(f"Title:          {project.title}")
        print(f"Author:         {project.author}")
        print(f"Genre:          {project.genre}")
        print(f"Difficulty:     {project.difficulty}")
        print(f"Language:       {project.language}")
        print(f"Era:            {project.era}")
        print(f"Status:         {project.status}")
        print(f"Progress:       {project.progress:.1f}%")
        print(f"Total Cost:     ${project.total_cost_usd:.4f}")
        print(f"Est. Chapters:  {project.total_chapters_estimated}")
        print(f"Current Stage:  {project.current_stage}")
        print(f"Created:        {project.created_at}")
        print(f"Updated:        {project.updated_at}")

        # Show chapters
        from src.audiobook_studio.models import Chapter

        chapters_result = await db.execute(
            select(Chapter).where(Chapter.project_id == project.id).order_by(Chapter.index)
        )
        chapters = chapters_result.scalars().all()
        if chapters:
            print(f"\nChapters ({len(chapters)}):")
            for ch in chapters:
                print(
                    f"  Ch {ch.index}: {ch.extract_status or 'pending'} / {ch.analyze_status or 'pending'} / {ch.synthesize_status or 'pending'}"
                )

        return 0


async def book_delete_command(args: argparse.Namespace) -> int:
    """Execute the book delete command."""
    if not args.force:
        confirm = input(f"⚠️  Delete project {args.project_id} and ALL its data? This cannot be undone! (yes/no): ")
        if confirm.lower() != "yes":
            print("Cancelled.")
            return 0

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Project).where(Project.id == args.project_id))
            project = result.scalar_one_or_none()
            if not project:
                print(f"❌ Project {args.project_id} not found")
                return 1

            title = project.title
            await db.delete(project)
            await db.commit()
            print(f"✅ Deleted project: {title} (id={args.project_id})")
            return 0
        except Exception as e:
            await db.rollback()
            print(f"❌ Failed to delete project: {e}")
            return 1


# Synchronous wrappers for argparse compatibility
def sync_book_list_command(args: argparse.Namespace) -> int:
    return asyncio.run(book_list_command(args))


def sync_book_create_command(args: argparse.Namespace) -> int:
    return asyncio.run(book_create_command(args))


def sync_book_show_command(args: argparse.Namespace) -> int:
    return asyncio.run(book_show_command(args))


def sync_book_delete_command(args: argparse.Namespace) -> int:
    return asyncio.run(book_delete_command(args))

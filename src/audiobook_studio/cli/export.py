"""Export CLI command.

Exports processed audiobook to final formats (M4B, MP3, etc.) with optional BGM mixing.
"""

import argparse
import asyncio
from typing import List, Optional

from sqlalchemy import select

from src.audiobook_studio.database import AsyncSessionLocal, create_async_session
from src.audiobook_studio.export import ExportFormat, ExportJob
from src.audiobook_studio.export.audio_ducking import MixConfig
from src.audiobook_studio.export.batch_exporter import export_project
from src.audiobook_studio.models import Project


def add_export_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add export subcommand to the CLI parser."""
    parser = subparsers.add_parser(
        "export",
        help="Export audiobook to final formats",
        description="Export a completed project to M4B, MP3, or other formats with optional BGM mixing.",
    )
    parser.add_argument(
        "project_id",
        type=int,
        help="Project ID to export",
    )
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["m4b_srt"],
        choices=[f.value for f in ExportFormat],
        help=f"Export formats (default: m4b_srt). Available: {', '.join(f.value for f in ExportFormat)}",
    )
    parser.add_argument(
        "--chapter",
        type=int,
        action="append",
        dest="chapters",
        help="Export only specific chapter(s) (can be used multiple times)",
    )
    parser.add_argument(
        "--bg-music",
        type=str,
        help="Background music file path for mixing",
    )
    parser.add_argument(
        "--bg-volume",
        type=float,
        default=-20.0,
        help="Background music volume in dB (default: -20)",
    )
    parser.add_argument(
        "--cover",
        type=str,
        help="Cover image file path",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        help="Output directory (default: exports/<project_id>/)",
    )
    parser.add_argument(
        "--no-normalize",
        action="store_true",
        help="Disable audio normalization",
    )
    parser.add_argument(
        "--keep-tmp",
        action="store_true",
        help="Keep temporary intermediate audio files",
    )
    parser.set_defaults(func=sync_export_command)


async def export_command(args: argparse.Namespace) -> int:
    """Execute the export command."""
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Project).where(Project.id == args.project_id))
            project = result.scalar_one_or_none()
            if not project:
                print(f"❌ Project {args.project_id} not found")
                return 1

            if project.progress < 100:
                print(f"⚠️  Project is not complete (progress: {project.progress:.1f}%). Export may be incomplete.")

            # Parse formats
            formats = {ExportFormat(f) for f in args.formats}

            # Build mix config if BGM provided
            mix_config = None
            if args.bg_music:
                from pathlib import Path

                bgm_path = Path(args.bg_music)
                if not bgm_path.exists():
                    print(f"❌ BGM file not found: {bgm_path}")
                    return 1
                mix_config = MixConfig(bgm_volume_db=args.bg_volume)
                print(f"🎵 BGM mixing enabled: {bgm_path} at {args.bg_volume} dB")

            # Build export job
            job = ExportJob(
                project_id=project.id,
                chapter_ids=args.chapters if args.chapters else None,
                formats=formats,
                bgm_path=args.bg_music,
                include_cover=bool(args.cover),
                cover_image=args.cover,
                normalize=not args.no_normalize,
                subtitle_config=None,
                mix_config=mix_config,
                output_dir=args.output_dir,
            )

            print(f"📦 Exporting project {project.id} ({project.title})...")
            print(f"   Formats: {', '.join(f.value for f in formats)}")
            if args.chapters:
                print(f"   Chapters: {args.chapters}")

            # Run export
            result_job = await export_project(project.id, db, job)

            if result_job.progress.value == "complete":
                print(f"✅ Export complete!")
                for fmt, path in result_job.output_paths.items():
                    print(f"   {fmt}: {path}")

                if not args.keep_tmp:
                    print("🧹 Cleaning temporary files...")
                    from src.audiobook_studio.run_pipeline import cleanup_after_export

                    cleanup_after_export(project.id, keep_final=True)
                    print("✅ Cleanup done")

                return 0
            else:
                print(f"❌ Export failed: {result_job.error}")
                return 1

    except Exception as e:
        import logging

        logging.exception("Export failed: %s", e)
        print(f"❌ Export error: {e}")
        return 1


# Synchronous wrapper for argparse compatibility
def sync_export_command(args: argparse.Namespace) -> int:
    return asyncio.run(export_command(args))

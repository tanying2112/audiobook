"""Pipeline execution CLI command.

Runs or resumes the audiobook processing pipeline for specified books.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from typing import List, Optional

from sqlalchemy import select

from src.audiobook_studio.database import AsyncSessionLocal, create_async_session, init_async_db
from src.audiobook_studio.models import Chapter, Project
from src.audiobook_studio.pipeline.checkpoint import CheckpointManager
from src.audiobook_studio.pipeline.orchestrator import init_telemetry
from src.audiobook_studio.pipeline.orchestrator import run_pipeline as orchestrator_run_pipeline
from src.audiobook_studio.pipeline.orchestrator import shutdown_telemetry
from src.audiobook_studio.run_pipeline import (
    BOOK_CONFIG,
    MOCK_DATA_DIR,
    STAGES,
    _get_chapter_files,
    cleanup_after_export,
)
from src.audiobook_studio.run_pipeline import find_project_async as _find_project
from src.audiobook_studio.storage import reports_dir


def add_pipeline_parser(subparsers: argparse._SubParsersAction) -> None:
    """Add pipeline subcommand with run/resume subcommands."""
    parser = subparsers.add_parser(
        "pipeline",
        help="Run or resume the audiobook processing pipeline",
        description="Execute the full 8-stage pipeline (extract→analyze→annotate→edit→audio_postprocess→review→synthesize→quality).",
    )
    pipeline_subparsers = parser.add_subparsers(dest="pipeline_command", required=True)

    # pipeline run
    run_parser = pipeline_subparsers.add_parser(
        "run",
        help="Run pipeline for specified books",
        description="Process books through the full pipeline stages.",
    )
    run_parser.add_argument(
        "books",
        nargs="+",
        help="Book names to process (e.g., '红楼梦' '三国演义')",
    )
    run_parser.add_argument(
        "--stages",
        nargs="+",
        default=STAGES,
        choices=STAGES,
        help=f"Pipeline stages to run (default: all {len(STAGES)} stages)",
    )
    run_parser.add_argument(
        "--chapter",
        type=int,
        help="Process only a specific chapter number",
    )
    run_parser.add_argument(
        "--quick",
        action="store_true",
        help="Quick mode: only run extract, analyze, annotate",
    )
    run_parser.add_argument(
        "--bg-music",
        type=str,
        help="Background music file path for export mixing",
    )
    run_parser.add_argument(
        "--bg-volume",
        type=float,
        default=-20.0,
        help="Background music volume in dB (default: -20)",
    )
    run_parser.add_argument(
        "--keep-tmp",
        action="store_true",
        help="Keep temporary intermediate audio files after export",
    )
    run_parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Start fresh, ignoring any existing checkpoints",
    )
    run_parser.set_defaults(func=sync_pipeline_run_command)

    # pipeline resume
    resume_parser = pipeline_subparsers.add_parser(
        "resume",
        help="Resume pipeline from last checkpoint",
        description="Continue processing from the last saved checkpoint for a project.",
    )
    resume_parser.add_argument(
        "project_id",
        type=int,
        help="Project ID to resume",
    )
    resume_parser.add_argument(
        "--chapter",
        type=int,
        help="Specific chapter to resume (default: all incomplete)",
    )
    resume_parser.set_defaults(func=sync_pipeline_resume_command)


async def _get_book_chapters(db, project_id: int, chapter_filter: Optional[int] = None) -> List[Chapter]:
    """Get chapters for a project, optionally filtered by chapter number."""
    query = select(Chapter).where(Chapter.project_id == project_id)
    if chapter_filter:
        query = query.where(Chapter.index == chapter_filter)
    result = await db.execute(query.order_by(Chapter.index))
    return result.scalars().all()


async def _run_chapter_pipeline(
    db,
    project: Project,
    chapter: Chapter,
    stages: List[str],
    checkpoint_manager: CheckpointManager,
    chapter_index: int,
) -> bool:
    """Run pipeline stages for a single chapter."""
    try:
        # Chapter-level stages (extract, analyze)
        chapter_stages = [s for s in stages if s in ("extract", "analyze")]
        if chapter_stages:
            results = await orchestrator_run_pipeline(
                stages=chapter_stages,
                db=db,
                project_id=project.id,
                chapter_index=chapter.index,
                checkpoint_manager=checkpoint_manager,
                file_path=str(MOCK_DATA_DIR / project.title / f"chapter_{chapter.index:02d}.txt"),
                mime_type="text/plain",
                detect_language=True,
                title_hint=project.title,
                author_hint=project.author,
                target_difficulty=project.difficulty,
            )
            print(f"    ✅ Chapter {chapter.index} chapter-level stages done ({len(results)} stages)")

        # Refresh chapter from DB
        await db.refresh(chapter)

        # Paragraph-level stages (annotate, edit, audio_postprocess)
        para_stages_pre = [s for s in stages if s in ("annotate", "edit", "audio_postprocess")]
        if para_stages_pre:
            from ..models import Paragraph

            result = await db.execute(
                select(Paragraph)
                .where(Paragraph.project_id == project.id, Paragraph.chapter_id == chapter.id)
                .order_by(Paragraph.index)
            )
            paragraphs = result.scalars().all()

            if paragraphs:
                print(f"    📄 Processing {len(paragraphs)} paragraphs...")
                for para in paragraphs:
                    para_results = await orchestrator_run_pipeline(
                        stages=para_stages_pre,
                        db=db,
                        project_id=project.id,
                        chapter_index=chapter.index,
                        chapter_id=chapter.id,
                        paragraph_index=para.index,
                        paragraph_id=para.id,
                        checkpoint_manager=checkpoint_manager,
                    )
                    print(f"      ✅ Paragraph {para.index} done ({len(para_results)} stages)")
            else:
                print(f"    ⚠️  No paragraphs found for chapter {chapter.index}")

        # Refresh chapter
        await db.refresh(chapter)

        # Review stage (chapter-level quality gate)
        if "review" in stages:
            print(f"    🔍 Running Reviewer Agent quality gate...")
            review_results = await orchestrator_run_pipeline(
                stages=["review"],
                db=db,
                project_id=project.id,
                chapter_index=chapter.index,
                chapter_id=chapter.id,
                checkpoint_manager=checkpoint_manager,
            )
            review_judgment = review_results[0] if review_results else None

            if review_judgment and hasattr(review_judgment, "overall_passed") and not review_judgment.overall_passed:
                print(f"    ❌ Reviewer blocked: {review_judgment.blocking_issues} blocking issues")
                if os.environ.get("REVIEWER_STRICT", "false").lower() == "true":
                    raise RuntimeError(f"Reviewer Agent blocked synthesis: {review_judgment.summary}")
            else:
                print(f"    ✅ Reviewer passed")

        # Post-review paragraph stages (synthesize, quality)
        para_stages_post = [s for s in stages if s in ("synthesize", "quality")]
        if para_stages_post:
            from ..models import Paragraph

            result = await db.execute(
                select(Paragraph)
                .where(Paragraph.project_id == project.id, Paragraph.chapter_id == chapter.id)
                .order_by(Paragraph.index)
            )
            paragraphs = result.scalars().all()

            if paragraphs:
                print(f"    🎙️ Synthesizing {len(paragraphs)} paragraphs...")
                for para in paragraphs:
                    para_results = await orchestrator_run_pipeline(
                        stages=para_stages_post,
                        db=db,
                        project_id=project.id,
                        chapter_index=chapter.index,
                        chapter_id=chapter.id,
                        paragraph_index=para.index,
                        paragraph_id=para.id,
                        checkpoint_manager=checkpoint_manager,
                    )
                    print(f"      ✅ Paragraph {para.index} done ({len(para_results)} stages)")

        print(f"    ✅ Chapter {chapter.index} complete")
        return True

    except Exception as e:
        import logging

        logging.error("Chapter %d pipeline failed: %s", chapter.index, e, exc_info=True)
        print(f"    ❌ Chapter {chapter.index} failed: {e}")
        return False


async def pipeline_run_command(args: argparse.Namespace) -> int:
    """Execute the pipeline run command."""
    books = args.books
    stages = ["extract", "analyze", "annotate"] if args.quick else args.stages
    chapter_filter = [args.chapter] if args.chapter else None

    print("=" * 50)
    print("🎙️  Audiobook Studio Pipeline")
    print("=" * 50)
    print(f"  📚 Books: {', '.join(books)}")
    print(f"  🎯 Stages: {', '.join(stages)}")
    if chapter_filter:
        print(f"  📖 Chapter filter: {chapter_filter}")

    has_error = False

    async with AsyncSessionLocal() as db:
        try:
            for book_name in books:
                if book_name not in BOOK_CONFIG:
                    print(f"  ❌ Unknown book: {book_name}")
                    has_error = True
                    continue

                print(f"\n📖 Processing: 《{book_name}》...")

                # Find or create project
                project = await _find_project(db, book_name)
                if not project:
                    config = BOOK_CONFIG[book_name]

                    now = datetime.now().isoformat()
                    project = Project(
                        title=config["title"],
                        author=config["author"],
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
                    print(f"  ✅ Created project: {config['title']} (id={project.id})")

                project_id = project.id
                print(f"  🆔 Project ID: {project_id}")

                # Checkpoint manager
                checkpoint_manager = CheckpointManager(project_id=project_id)

                # Check for existing checkpoints
                if not args.no_resume:
                    has_incomplete = False
                    chapter_files = _get_chapter_files(book_name)
                    for chap_num, _ in chapter_files:
                        if checkpoint_manager.last_completed_stage(chap_num) is not None:
                            has_incomplete = True
                            break

                    if has_incomplete and sys.stdin.isatty():
                        print("⚠️  Found existing checkpoint. Resume? (Y/n): ", end="")
                        response = input().strip().lower()
                        if response and response[0] != "y":
                            print("  Starting fresh, clearing checkpoints...")
                            checkpoint_manager._data = {"project_id": project_id, "chapters": {}, "version": 2}
                            checkpoint_manager._save()
                    elif has_incomplete:
                        print("ℹ️  Non-interactive mode: auto-resuming from checkpoint...")

                # Initialize telemetry
                output_dir = reports_dir(project_id, ensure=True)
                init_telemetry(
                    project_id=str(project_id),
                    output_dir=str(output_dir),
                )

                # Get chapters to process
                chapter_files = _get_chapter_files(book_name)
                if chapter_filter:
                    chapter_files = [(num, path) for num, path in chapter_files if num in chapter_filter]

                if not chapter_files:
                    print(f"  ⚠️  No chapter files found for {book_name}")
                    continue

                print(f"  📚 {len(chapter_files)} chapters to process")

                # Process each chapter
                for i, (chap_num, chap_file) in enumerate(chapter_files, 1):
                    print(f"  ── [{i}/{len(chapter_files)}] Chapter {chap_num}: {chap_file.name} ──")

                    # Get or create chapter record
                    result = await db.execute(
                        select(Chapter).where(Chapter.project_id == project_id, Chapter.index == chap_num)
                    )
                    chapter = result.scalar_one_or_none()
                    if not chapter:
                        chapter = Chapter(project_id=project_id, index=chap_num)
                        db.add(chapter)
                        await db.commit()
                        await db.refresh(chapter)

                    success = await _run_chapter_pipeline(db, project, chapter, stages, checkpoint_manager, chap_num)
                    if not success:
                        has_error = True

                # Update project status
                project.current_stage = "completed"
                project.progress = 100.0
                project.updated_at = datetime.now().isoformat()
                await db.commit()

                # Export if BGM provided
                if args.bg_music:
                    print("🎵 Exporting with background music...")
                    try:
                        from ..export import ExportFormat, ExportJob
                        from ..export.audio_ducking import MixConfig
                        from ..export.batch_exporter import export_project

                        mix_config = MixConfig(bgm_volume_db=args.bg_volume)
                        job = ExportJob(
                            project_id=project.id,
                            chapter_ids=None,
                            formats={ExportFormat.M4B_SRT},
                            bgm_path=args.bg_music,
                            include_cover=True,
                            cover_image=None,
                            normalize=True,
                            subtitle_config=None,
                            mix_config=mix_config,
                            output_dir=None,
                        )

                        export_db = create_async_session()
                        try:
                            result_job = await export_project(project.id, export_db, job)
                            if result_job.progress.value == "complete":
                                print(f"✅ Export complete: {result_job.output_paths}")
                                if not args.keep_tmp:
                                    print("🧹 Cleaning temp files...")
                                    cleanup_after_export(project.id, keep_final=True)
                                    print("✅ Cleanup done")
                            else:
                                print(f"❌ Export failed: {result_job.error}")
                                has_error = True
                        finally:
                            await export_db.close()
                    except Exception as e:
                        print(f"⚠️  Export failed: {e}")
                        has_error = True

                print(f"✅ 《{book_name}》processing complete")

        except Exception as e:
            import logging

            logging.error("Book %s failed: %s", book_name, e, exc_info=True)
            print(f"❌ 《{book_name}》 failed: {e}")
            has_error = True
            if "checkpoint_manager" in locals():
                checkpoint_manager._flush()
        finally:
            shutdown_telemetry()

    print("=" * 50)
    if has_error:
        print("⚠️  Completed with errors")
        return 1
    else:
        print("🎉 All books processed successfully")
        return 0


async def pipeline_resume_command(args: argparse.Namespace) -> int:
    """Execute the pipeline resume command."""
    project_id = args.project_id
    chapter_filter = [args.chapter] if args.chapter else None

    print(f"🔄 Resuming pipeline for project {project_id}")

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(select(Project).where(Project.id == project_id))
            project = result.scalar_one_or_none()
            if not project:
                print(f"❌ Project {project_id} not found")
                return 1

            checkpoint_manager = CheckpointManager(project_id=project_id)
            output_dir = reports_dir(project_id, ensure=True)
            init_telemetry(project_id=str(project_id), output_dir=str(output_dir))

            # Get chapters with incomplete checkpoints
            chapters = await _get_book_chapters(db, project_id, args.chapter)
            if not chapters:
                print("✅ No chapters to resume")
                return 0

            print(f"📚 Resuming {len(chapters)} chapter(s)")

            stages = STAGES  # Full pipeline by default

            for chapter in chapters:
                print(f"  ── Chapter {chapter.index} ──")
                success = await _run_chapter_pipeline(db, project, chapter, stages, checkpoint_manager, chapter.index)
                if not success:
                    print(f"  ❌ Chapter {chapter.index} failed, continuing...")

            project.current_stage = "completed"
            project.progress = 100.0
            project.updated_at = datetime.now().isoformat()
            await db.commit()

            print("✅ Resume complete")
            return 0

        except Exception as e:
            import logging

            logging.error("Resume failed: %s", e, exc_info=True)
            print(f"❌ Resume failed: {e}")
            return 1
        finally:
            shutdown_telemetry()


# Synchronous wrappers for argparse compatibility
def sync_pipeline_run_command(args: argparse.Namespace) -> int:
    return asyncio.run(pipeline_run_command(args))


def sync_pipeline_resume_command(args: argparse.Namespace) -> int:
    return asyncio.run(pipeline_resume_command(args))

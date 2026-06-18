#!/usr/bin/env python3
"""Version manager CLI for Audiobook Studio pipeline runs.

Records and manages ProcessingRun snapshots, enabling version tracking,
rollback, and diff across pipeline executions.

Usage::

    # Save a run after pipeline completion
    python scripts/version_manager.py save --project 1 --tag v1.0 --msg "Initial run"

    # List all runs for a project
    python scripts/version_manager.py list --project 1

    # Show details of a specific run
    python scripts/version_manager.py show --run 3

    # Roll back a project to a previous run's config
    python scripts/version_manager.py rollback --project 1 --run 3

    # Diff two runs
    python scripts/version_manager.py diff --run 3 --other 5
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# Ensure project root is on sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy.orm import Session

from src.audiobook_studio.database import SessionLocal
from src.audiobook_studio.models import ProcessingRun

# ── Terminal colours (macOS / modern terminals) ──────────────────────────────
_GREEN = "\033[92m"
_YELLOW = "\033[93m"
_RED = "\033[91m"
_CYAN = "\033[96m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def _ok(msg: str) -> None:
    print(f"{_GREEN}✓{_RESET} {msg}")


def _warn(msg: str) -> None:
    print(f"{_YELLOW}⚠{_RESET} {msg}")


def _err(msg: str) -> None:
    print(f"{_RED}✗{_RESET} {msg}", file=sys.stderr)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_db() -> Session:
    """Create a new DB session."""
    return SessionLocal()


def _find_run(db: Session, project_id: int, run_id: Optional[int] = None,
              tag: Optional[str] = None) -> Optional[ProcessingRun]:
    """Locate a processing run by id, tag, or latest for project."""
    if run_id:
        return db.query(ProcessingRun).filter(ProcessingRun.id == run_id).first()
    if tag:
        return (
            db.query(ProcessingRun)
            .filter(
                ProcessingRun.project_id == project_id,
                ProcessingRun.version_tag == tag,
            )
            .first()
        )
    # Latest for project
    return (
        db.query(ProcessingRun)
        .filter(
            ProcessingRun.project_id == project_id,
            ProcessingRun.status == "completed",
        )
        .order_by(ProcessingRun.started_at.desc())
        .first()
    )


def _collect_stages_config(db: Session, project_id: int) -> Dict[str, Any]:
    """Gather current project processing state into a snapshot dict."""
    from src.audiobook_studio.models import Chapter, Paragraph

    chapters = (
        db.query(Chapter)
        .filter(Chapter.project_id == project_id)
        .order_by(Chapter.index)
        .all()
    )
    stages_set: set = set()
    total_paragraphs = 0
    processed_paragraphs = 0

    for ch in chapters:
        # Collect completed stages from chapter status fields
        for stage_field, stage_name in [
            ("extract_status", "extract"),
            ("analyze_status", "analyze"),
            ("annotate_status", "annotate"),
            ("edit_status", "edit"),
            ("synthesize_status", "synthesize"),
            ("quality_status", "quality"),
        ]:
            val = getattr(ch, stage_field, "pending")
            if val == "completed":
                stages_set.add(stage_name)

        # Count paragraphs
        paras = (
            db.query(Paragraph)
            .filter(
                Paragraph.project_id == project_id,
                Paragraph.chapter_id == ch.id,
            )
            .count()
        )
        total_paragraphs += paras
        processed_paragraphs += (
            db.query(Paragraph)
            .filter(
                Paragraph.project_id == project_id,
                Paragraph.chapter_id == ch.id,
                Paragraph.status != "pending",
            )
            .count()
        )

    return {
        "stages_completed": sorted(stages_set),
        "total_paragraphs": total_paragraphs,
        "processed_paragraphs": processed_paragraphs,
        "chapter_count": len(chapters),
    }


# ── Commands ──────────────────────────────────────────────────────────────────


def cmd_save(args: argparse.Namespace) -> None:
    """Save a new processing run snapshot."""
    db = _get_db()
    try:
        # Collect current state
        state = _collect_stages_config(db, args.project)
        config_snapshot = state.get("config_json", "{}")

        run = ProcessingRun(
            project_id=args.project,
            config_json=config_snapshot if isinstance(config_snapshot, str) else json.dumps(config_snapshot),
            prompt_versions=args.prompt_versions or {},
            stages_completed=state["stages_completed"],
            status="completed",
            version_tag=args.tag,
            commit_message=args.msg,
            golden_score=args.score,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )

        # Link to parent if specified
        if args.parent:
            parent = db.query(ProcessingRun).filter(
                ProcessingRun.id == args.parent,
                ProcessingRun.project_id == args.project,
            ).first()
            if parent:
                run.parent_run_id = parent.id
            else:
                _warn(f"Parent run {args.parent} not found, saving without parent")

        elif args.parent_tag:
            parent = (
                db.query(ProcessingRun)
                .filter(
                    ProcessingRun.project_id == args.project,
                    ProcessingRun.version_tag == args.parent_tag,
                )
                .first()
            )
            if parent:
                run.parent_run_id = parent.id
            else:
                _warn(f"Parent tag '{args.parent_tag}' not found, saving without parent")

        db.add(run)
        db.commit()
        db.refresh(run)
        _ok(f"Run #{run.id} saved for project {args.project}")
        if args.tag:
            print(f"   Tag: {args.tag}")
        print(f"   Stages: {', '.join(state['stages_completed']) or '(none)'}")
        print(f"   Chapters: {state['chapter_count']}, "
              f"Paragraphs: {state['processed_paragraphs']}/{state['total_paragraphs']}")
    finally:
        db.close()


def cmd_list(args: argparse.Namespace) -> None:
    """List all processing runs for a project."""
    db = _get_db()
    try:
        runs = (
            db.query(ProcessingRun)
            .filter(ProcessingRun.project_id == args.project)
            .order_by(ProcessingRun.started_at.desc())
            .all()
        )
        if not runs:
            print(f"No processing runs found for project {args.project}")
            return

        print(f"\n{_BOLD}Processing runs for project {args.project}:{_RESET}")
        print(f"{'ID':<5} {'Tag':<14} {'Status':<12} {'Score':<8} "
              f"{'Stages':<30} {'Date':<22}")
        print("-" * 90)
        for r in runs:
            tag = r.version_tag or "-"
            score = f"{r.golden_score:.3f}" if r.golden_score is not None else "-"
            stages = ", ".join(r.stages_completed or [])[:28]
            date = r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "-"
            print(f"{r.id:<5} {tag:<14} {r.status:<12} {score:<8} "
                  f"{stages:<30} {date:<22}")
        print()
    finally:
        db.close()


def cmd_show(args: argparse.Namespace) -> None:
    """Show detailed information for a processing run."""
    db = _get_db()
    try:
        run = _find_run(db, args.project, run_id=args.run, tag=args.tag)
        if not run:
            _err(f"Run not found (project={args.project}, id={args.run}, tag={args.tag})")
            sys.exit(1)

        print(f"\n{_BOLD}Processing Run #{run.id}{_RESET}")
        print(f"  Project ID:     {run.project_id}")
        print(f"  Status:         {run.status}")
        print(f"  Version Tag:    {run.version_tag or '-'}")
        print(f"  Golden Score:   {run.golden_score:.3f}" if run.golden_score is not None else "  Golden Score:   -")
        print(f"  Commit Message: {run.commit_message or '-'}")
        print(f"  Started:        {run.started_at}")
        print(f"  Completed:      {run.completed_at or '-'}")
        print(f"  Parent Run:     {run.parent_run_id or '-'}")

        print(f"\n  {_BOLD}Stages completed:{_RESET}")
        for s in (run.stages_completed or []):
            print(f"    ✓ {s}")

        print(f"\n  {_BOLD}Prompt versions:{_RESET}")
        pv = run.prompt_versions or {}
        if pv:
            for stage, ver in pv.items():
                print(f"    {stage}: {ver}")
        else:
            print("    (none)")

        # Print config summary (first 500 chars)
        config = run.config_json
        if config and config != "{}":
            print(f"\n  {_BOLD}Config (truncated):{_RESET}")
            config_str = config if isinstance(config, str) else json.dumps(config, indent=2)
            if len(config_str) > 500:
                config_str = config_str[:500] + "\n    ..."
            for line in config_str.split("\n"):
                print(f"    {line}")

        print()
    finally:
        db.close()


def cmd_rollback(args: argparse.Namespace) -> None:
    """Roll back a project's processing state to a previous run.

    In the MVP this records the rollback intent; full state restoration
    (e.g. reverting chapter/paragraph status fields) should be called
    with --apply in production.
    """
    db = _get_db()
    try:
        target = _find_run(db, args.project, run_id=args.run, tag=args.tag)
        if not target:
            _err(f"Target run not found (project={args.project}, id={args.run}, tag={args.tag})")
            sys.exit(1)

        # Get the current (latest) run for comparison
        latest = (
            db.query(ProcessingRun)
            .filter(
                ProcessingRun.project_id == args.project,
                ProcessingRun.status == "completed",
            )
            .order_by(ProcessingRun.started_at.desc())
            .first()
        )

        print(f"\n{_BOLD}Rollback Plan{_RESET}")
        print(f"  Project:  {args.project}")
        print(f"  Target:   Run #{target.id} ({target.version_tag or '-'}) "
              f"from {target.started_at}")
        if latest:
            print(f"  Current:  Run #{latest.id} ({latest.version_tag or '-'}) "
                  f"from {latest.started_at}")
        print()

        if args.apply:
            # MVP: record rollback as a new run pointing to target as parent
            rollback_run = ProcessingRun(
                project_id=args.project,
                parent_run_id=target.id,
                config_json=target.config_json,
                prompt_versions=target.prompt_versions or {},
                stages_completed=list(target.stages_completed or []),
                status="rollback",
                version_tag=f"rollback_to_{target.version_tag or target.id}",
                commit_message=f"Rollback to run #{target.id} ({target.version_tag or '-'})",
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
            )
            db.add(rollback_run)
            db.commit()
            db.refresh(rollback_run)

            # TODO: Full state restoration in production
            # This would reset Chapter/Paragraph status fields and reprocess
            _ok(f"Rollback recorded as Run #{rollback_run.id}")
            _warn("Chapter/paragraph status fields NOT reverted (--apply-full for full restoration)")
            print()
            print("To reset status fields and reprocess from the target state:")
            print(f"  python scripts/version_manager.py restore-state --project {args.project} --run {target.id}")
        else:
            print("  Use --apply to record this rollback (dry-run mode)")
            print()

    finally:
        db.close()


def cmd_diff(args: argparse.Namespace) -> None:
    """Show differences between two processing runs."""
    db = _get_db()
    try:
        run_a = db.query(ProcessingRun).filter(ProcessingRun.id == args.run).first()
        run_b = db.query(ProcessingRun).filter(ProcessingRun.id == args.other).first()

        if not run_a or not run_b:
            _err("One or both runs not found")
            sys.exit(1)

        print(f"\n{_BOLD}Diff: Run #{run_a.id} → Run #{run_b.id}{_RESET}\n")

        # Status
        if run_a.status != run_b.status:
            print(f"  {'Status:':<20} {run_a.status} → {run_b.status}")

        # Score
        if run_a.golden_score != run_b.golden_score:
            print(f"  {'Golden Score:':<20} {run_a.golden_score} → {run_b.golden_score}")

        # Stages
        stages_a = set(run_a.stages_completed or [])
        stages_b = set(run_b.stages_completed or [])
        added = stages_b - stages_a
        removed = stages_a - stages_b
        if added:
            print(f"  {'Stages added:':<20} {', '.join(sorted(added))}")
        if removed:
            print(f"  {'Stages removed:':<20} {', '.join(sorted(removed))}")

        # Config (just show keys)
        config_a = set()
        config_b = set()
        try:
            ca = json.loads(run_a.config_json) if isinstance(run_a.config_json, str) else run_a.config_json
            cb = json.loads(run_b.config_json) if isinstance(run_b.config_json, str) else run_b.config_json
            config_a = set(ca.keys()) if isinstance(ca, dict) else set()
            config_b = set(cb.keys()) if isinstance(cb, dict) else set()
        except (json.JSONDecodeError, TypeError):
            pass
        config_added = config_b - config_a
        config_removed = config_a - config_b
        if config_added:
            print(f"  {'Config keys added:':<20} {', '.join(sorted(config_added))}")
        if config_removed:
            print(f"  {'Config keys removed:':<20} {', '.join(sorted(config_removed))}")

        if not added and not removed and run_a.status == run_b.status and run_a.golden_score == run_b.golden_score:
            print("  (no significant differences)")

        print()
    finally:
        db.close()


def cmd_restore_state(args: argparse.Namespace) -> None:
    """Restore chapter/paragraph status to match a target run.

    This is a destructive operation! It reverts the processing status
    fields of Chapters and Paragraphs so that only stages recorded
    in the target run show as completed.
    """
    db = _get_db()
    try:
        target = _find_run(db, args.project, run_id=args.run)
        if not target:
            _err(f"Target run not found (project={args.project}, id={args.run})")
            sys.exit(1)

        if not args.force:
            print(f"\n{_RED}{_BOLD}WARNING: This will modify chapter/paragraph status fields{_RESET}")
            print(f"  Project: {args.project}")
            print(f"  Target:  Run #{target.id} ({target.version_tag or '-'})")
            print(f"  Stages to preserve: {', '.join(target.stages_completed or [])}")
            ans = input("\nContinue? [y/N]: ").strip().lower()
            if ans != "y":
                print("Aborted.")
                return

        from src.audiobook_studio.models import Chapter, Paragraph

        stages = set(target.stages_completed or [])

        # Map stage names to chapter status fields
        stage_field_map = {
            "extract": "extract_status",
            "analyze": "analyze_status",
            "annotate": "annotate_status",
            "edit": "edit_status",
            "synthesize": "synthesize_status",
            "quality": "quality_status",
        }

        chapters_updated = 0
        paragraphs_updated = 0

        chapters = (
            db.query(Chapter)
            .filter(Chapter.project_id == args.project)
            .all()
        )
        for ch in chapters:
            changed = False
            for stage_name, field in stage_field_map.items():
                current = getattr(ch, field, "pending")
                if stage_name in stages:
                    if current != "completed":
                        setattr(ch, field, "completed")
                        changed = True
                else:
                    if current != "pending":
                        setattr(ch, field, "pending")
                        changed = True
            if changed:
                chapters_updated += 1

            # Paragraph status: reset to "pending" for stages not in target
            paras = (
                db.query(Paragraph)
                .filter(
                    Paragraph.project_id == args.project,
                    Paragraph.chapter_id == ch.id,
                )
                .all()
            )
            for p in paras:
                if p.status not in ("pending",) and p.status not in stages:
                    # Map old paragraph status to stage names
                    status_map = {
                        "extracted": "extract",
                        "analyzed": "analyze",
                        "annotated": "annotate",
                        "edited": "edit",
                        "synthesized": "synthesize",
                        "quality_checked": "quality",
                    }
                    mapped = status_map.get(p.status)
                    if mapped and mapped not in stages:
                        p.status = "pending"
                        paragraphs_updated += 1

        db.commit()
        _ok(f"State restored: {chapters_updated} chapters, {paragraphs_updated} paragraphs updated")
        print(f"  Active stages: {', '.join(stages)}")
    finally:
        db.close()


# ── CLI entry point ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Version manager for Audiobook Studio pipeline runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/version_manager.py save --project 1 --tag v1.0 --msg "Initial run"
  python scripts/version_manager.py list --project 1
  python scripts/version_manager.py show --run 3
  python scripts/version_manager.py rollback --project 1 --run 3 --apply
  python scripts/version_manager.py diff --run 3 --other 5
        """,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # save
    p_save = sub.add_parser("save", help="Save a new processing run snapshot")
    p_save.add_argument("--project", "-p", type=int, required=True, help="Project ID")
    p_save.add_argument("--tag", "-t", type=str, help="Version tag (e.g. v1.0)")
    p_save.add_argument("--msg", "-m", type=str, help="Commit message")
    p_save.add_argument("--score", type=float, help="Golden quality score")
    p_save.add_argument("--parent", type=int, help="Parent run ID")
    p_save.add_argument("--parent-tag", type=str, help="Parent version tag")
    p_save.add_argument("--prompt-versions", type=json.loads, default=None,
                        help='JSON dict of prompt versions, e.g. \'{"extract":"v2"}\'')

    # list
    p_list = sub.add_parser("list", help="List runs for a project")
    p_list.add_argument("--project", "-p", type=int, required=True, help="Project ID")

    # show
    p_show = sub.add_parser("show", help="Show run details")
    p_show.add_argument("--project", "-p", type=int, default=0, help="Project ID (optional)")
    p_show.add_argument("--run", "-r", type=int, help="Run ID")
    p_show.add_argument("--tag", "-t", type=str, help="Version tag")

    # rollback
    p_roll = sub.add_parser("rollback", help="Roll back to a previous run")
    p_roll.add_argument("--project", "-p", type=int, required=True, help="Project ID")
    p_roll.add_argument("--run", "-r", type=int, help="Target run ID")
    p_roll.add_argument("--tag", "-t", type=str, help="Target version tag")
    p_roll.add_argument("--apply", action="store_true", help="Record the rollback")

    # diff
    p_diff = sub.add_parser("diff", help="Diff two runs")
    p_diff.add_argument("--run", "-r", type=int, required=True, help="First run ID")
    p_diff.add_argument("--other", "-o", type=int, required=True, help="Second run ID")

    # restore-state (hidden destructive command)
    p_restore = sub.add_parser("restore-state", help="Restore chapter/paragraph status to target run (DESTRUCTIVE)")
    p_restore.add_argument("--project", "-p", type=int, required=True, help="Project ID")
    p_restore.add_argument("--run", "-r", type=int, help="Target run ID")
    p_restore.add_argument("--tag", "-t", type=str, help="Target version tag")
    p_restore.add_argument("--force", "-f", action="store_true", help="Skip confirmation")

    args = parser.parse_args()

    commands = {
        "save": cmd_save,
        "list": cmd_list,
        "show": cmd_show,
        "rollback": cmd_rollback,
        "diff": cmd_diff,
        "restore-state": cmd_restore_state,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Version manager CLI for Audiobook Studio pipeline runs.

Thin CLI wrapper that delegates to src/audiobook_studio/version_manager.py

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
from src.audiobook_studio.version_manager import (
    diff_runs,
    get_run,
    list_runs,
    restore_state,
    rollback_to_run,
    save_run,
)

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


def cmd_save(args: argparse.Namespace) -> None:
    """Save a new processing run snapshot."""
    try:
        run = save_run(
            project_id=args.project,
            tag=args.tag,
            message=args.msg,
            score=args.score,
            parent_run_id=args.parent,
            parent_tag=args.parent_tag,
            prompt_versions=args.prompt_versions,
        )
        _ok(f"Run #{run.id} saved for project {args.project}")
        if args.tag:
            print(f"   Tag: {args.tag}")
        print(f"   Stages: {', '.join(run.stages_completed or []) or '(none)'}")
    except Exception as e:
        _err(f"Failed to save run: {e}")
        sys.exit(1)


def cmd_list(args: argparse.Namespace) -> None:
    """List all processing runs for a project."""
    runs = list_runs(args.project)
    if not runs:
        print(f"No processing runs found for project {args.project}")
        return

    print(f"\n{_BOLD}Processing runs for project {args.project}:{_RESET}")
    print(
        f"{'ID':<5} {'Tag':<14} {'Status':<12} {'Score':<8} "
        f"{'Stages':<30} {'Date':<22}"
    )
    print("-" * 90)
    for r in runs:
        tag = r.version_tag or "-"
        score = f"{r.golden_score:.3f}" if r.golden_score is not None else "-"
        stages = ", ".join(r.stages_completed or [])[:28]
        date = r.started_at.strftime("%Y-%m-%d %H:%M") if r.started_at else "-"
        print(
            f"{r.id:<5} {tag:<14} {r.status:<12} {score:<8} " f"{stages:<30} {date:<22}"
        )
    print()


def cmd_show(args: argparse.Namespace) -> None:
    """Show detailed information for a processing run."""
    run = get_run(args.project, run_id=args.run, tag=args.tag)
    if not run:
        _err(f"Run not found (project={args.project}, id={args.run}, tag={args.tag})")
        sys.exit(1)

    print(f"\n{_BOLD}Processing Run #{run.id}{_RESET}")
    print(f"  Project ID:     {run.project_id}")
    print(f"  Status:         {run.status}")
    print(f"  Version Tag:    {run.version_tag or '-'}")
    print(
        f"  Golden Score:   {run.golden_score:.3f}"
        if run.golden_score is not None
        else "  Golden Score:   -"
    )
    print(f"  Commit Message: {run.commit_message or '-'}")
    print(f"  Started:        {run.started_at}")
    print(f"  Completed:      {run.completed_at or '-'}")
    print(f"  Parent Run:     {run.parent_run_id or '-'}")

    print(f"\n  {_BOLD}Stages completed:{_RESET}")
    for s in run.stages_completed or []:
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


def cmd_rollback(args: argparse.Namespace) -> None:
    """Roll back a project's processing state to a previous run.

    In the MVP this records the rollback intent; full state restoration
    (e.g. reverting chapter/paragraph status fields) should be called
    with --apply in production.
    """
    rollback_run = rollback_to_run(
        project_id=args.project,
        run_id=args.run,
        tag=args.tag,
        apply=args.apply,
    )

    if not rollback_run and args.apply:
        _err("Rollback failed")
        sys.exit(1)
    elif not args.apply:
        print("  Use --apply to record this rollback (dry-run mode)")
        print()


def cmd_diff(args: argparse.Namespace) -> None:
    """Show differences between two processing runs."""
    diff = diff_runs(args.run, args.other)

    if "error" in diff:
        _err(diff["error"])
        sys.exit(1)

    print(f"\n{_BOLD}Diff: Run #{args.run} → Run #{args.other}{_RESET}\n")

    if not diff.get("differences"):
        print("  (no significant differences)")
        return

    for key, value in diff["differences"].items():
        if isinstance(value, dict) and "from" in value and "to" in value:
            print(f"  {key:<20} {value['from']} → {value['to']}")
        elif isinstance(value, list):
            print(f"  {key:<20} {', '.join(map(str, value))}")
        else:
            print(f"  {key:<20} {value}")

    print()


def cmd_restore_state(args: argparse.Namespace) -> None:
    """Restore chapter/paragraph status to match a target run.

    This is a destructive operation! It reverts the processing status
    fields of Chapters and Paragraphs so that only stages recorded
    in the target run show as completed.
    """
    if not args.force:
        print(
            f"\n{_RED}{_BOLD}WARNING: This will modify chapter/paragraph status fields{_RESET}"
        )
        print(f"  Project: {args.project}")
        target = get_run(args.project, run_id=args.run)
        if target:
            print(f"  Target:  Run #{target.id} ({target.version_tag or '-'})")
            print(f"  Stages to preserve: {', '.join(target.stages_completed or [])}")
        ans = input("\nContinue? [y/N]: ").strip().lower()
        if ans != "y":
            print("Aborted.")
            return

    result = restore_state(args.project, args.run)
    _ok(
        f"State restored: {result['chapters_updated']} chapters, {result['paragraphs_updated']} paragraphs updated"
    )
    print(f"  Active stages: {', '.join(result.get('stages', []))}")


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
    p_save.add_argument(
        "--prompt-versions",
        type=json.loads,
        default=None,
        help='JSON dict of prompt versions, e.g. \'{"extract":"v2"}\'',
    )

    # list
    p_list = sub.add_parser("list", help="List runs for a project")
    p_list.add_argument("--project", "-p", type=int, required=True, help="Project ID")

    # show
    p_show = sub.add_parser("show", help="Show run details")
    p_show.add_argument(
        "--project", "-p", type=int, default=0, help="Project ID (optional)"
    )
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
    p_restore = sub.add_parser(
        "restore-state",
        help="Restore chapter/paragraph status to target run (DESTRUCTIVE)",
    )
    p_restore.add_argument(
        "--project", "-p", type=int, required=True, help="Project ID"
    )
    p_restore.add_argument("--run", "-r", type=int, help="Target run ID")
    p_restore.add_argument("--tag", "-t", type=str, help="Target version tag")
    p_restore.add_argument(
        "--force", "-f", action="store_true", help="Skip confirmation"
    )

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

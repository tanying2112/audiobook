"""
Audiobook Studio — Version Manager Module
=========================================

Extracted from scripts/version_manager.py for reuse across the codebase.

Manages ProcessingRun snapshots for version tracking, rollback, and diff
across pipeline executions.
"""

import json
import logging
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

logger = logging.getLogger(__name__)


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


# ── Public API ────────────────────────────────────────────────────────────────


def save_run(
    project_id: int,
    tag: Optional[str] = None,
    message: Optional[str] = None,
    score: Optional[float] = None,
    parent_run_id: Optional[int] = None,
    parent_tag: Optional[str] = None,
    prompt_versions: Optional[Dict[str, Any]] = None,
) -> ProcessingRun:
    """Save a new processing run snapshot.

    Args:
        project_id: Project ID
        tag: Version tag (e.g. v1.0)
        message: Commit message
        score: Golden quality score
        parent_run_id: Parent run ID
        parent_tag: Parent version tag
        prompt_versions: JSON dict of prompt versions

    Returns:
        The created ProcessingRun object
    """
    db = _get_db()
    try:
        # Collect current state
        state = _collect_stages_config(db, project_id)
        config_snapshot = state.get("config_json", "{}")

        run = ProcessingRun(
            project_id=project_id,
            config_json=config_snapshot if isinstance(config_snapshot, str) else json.dumps(config_snapshot),
            prompt_versions=prompt_versions or {},
            stages_completed=state["stages_completed"],
            status="completed",
            version_tag=tag,
            commit_message=message,
            golden_score=score,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )

        # Link to parent if specified
        if parent_run_id:
            parent = db.query(ProcessingRun).filter(
                ProcessingRun.id == parent_run_id,
                ProcessingRun.project_id == project_id,
            ).first()
            if parent:
                run.parent_run_id = parent.id
            else:
                logger.warning(f"Parent run {parent_run_id} not found, saving without parent")

        elif parent_tag:
            parent = (
                db.query(ProcessingRun)
                .filter(
                    ProcessingRun.project_id == project_id,
                    ProcessingRun.version_tag == parent_tag,
                )
                .first()
            )
            if parent:
                run.parent_run_id = parent.id
            else:
                logger.warning(f"Parent tag '{parent_tag}' not found, saving without parent")

        db.add(run)
        db.commit()
        db.refresh(run)
        logger.info(f"Run #{run.id} saved for project {project_id}")
        if tag:
            logger.info(f"   Tag: {tag}")
        logger.info(f"   Stages: {', '.join(state['stages_completed']) or '(none)'}")
        logger.info(f"   Chapters: {state['chapter_count']}, "
                    f"Paragraphs: {state['processed_paragraphs']}/{state['total_paragraphs']}")
        return run
    finally:
        db.close()


def list_runs(project_id: int) -> List[ProcessingRun]:
    """List all processing runs for a project."""
    db = _get_db()
    try:
        runs = (
            db.query(ProcessingRun)
            .filter(ProcessingRun.project_id == project_id)
            .order_by(ProcessingRun.started_at.desc())
            .all()
        )
        return runs
    finally:
        db.close()


def get_run(project_id: int, run_id: Optional[int] = None,
            tag: Optional[str] = None) -> Optional[ProcessingRun]:
    """Get a processing run by ID or tag."""
    db = _get_db()
    try:
        return _find_run(db, project_id, run_id=run_id, tag=tag)
    finally:
        db.close()


def rollback_to_run(
    project_id: int,
    run_id: Optional[int] = None,
    tag: Optional[str] = None,
    apply: bool = False,
) -> Optional[ProcessingRun]:
    """Roll back a project's processing state to a previous run.

    Args:
        project_id: Project ID
        run_id: Target run ID
        tag: Target version tag
        apply: If True, record the rollback as a new run

    Returns:
        The rollback run if applied, None otherwise
    """
    db = _get_db()
    try:
        target = _find_run(db, project_id, run_id=run_id, tag=tag)
        if not target:
            logger.error(f"Target run not found (project={project_id}, id={run_id}, tag={tag})")
            return None

        # Get the current (latest) run for comparison
        latest = (
            db.query(ProcessingRun)
            .filter(
                ProcessingRun.project_id == project_id,
                ProcessingRun.status == "completed",
            )
            .order_by(ProcessingRun.started_at.desc())
            .first()
        )

        logger.info(f"Rollback Plan for project {project_id}")
        logger.info(f"  Target:   Run #{target.id} ({target.version_tag or '-'}) "
                    f"from {target.started_at}")
        if latest:
            logger.info(f"  Current:  Run #{latest.id} ({latest.version_tag or '-'}) "
                        f"from {latest.started_at}")

        if apply:
            # MVP: record rollback as a new run pointing to target as parent
            rollback_run = ProcessingRun(
                project_id=project_id,
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

            logger.info(f"Rollback recorded as Run #{rollback_run.id}")
            logger.warning("Chapter/paragraph status fields NOT reverted (use restore_state for full restoration)")
            return rollback_run
        return None
    finally:
        db.close()


def diff_runs(run_a_id: int, run_b_id: int) -> Dict[str, Any]:
    """Show differences between two processing runs.

    Returns:
        Dict with differences
    """
    db = _get_db()
    try:
        run_a = db.query(ProcessingRun).filter(ProcessingRun.id == run_a_id).first()
        run_b = db.query(ProcessingRun).filter(ProcessingRun.id == run_b_id).first()

        if not run_a or not run_b:
            logger.error("One or both runs not found")
            return {"error": "Run not found"}

        diff = {
            "run_a": {"id": run_a.id, "tag": run_a.version_tag, "status": run_a.status},
            "run_b": {"id": run_b.id, "tag": run_b.version_tag, "status": run_b.status},
            "differences": {}
        }

        # Status
        if run_a.status != run_b.status:
            diff["differences"]["status"] = {"from": run_a.status, "to": run_b.status}

        # Score
        if run_a.golden_score != run_b.golden_score:
            diff["differences"]["golden_score"] = {"from": run_a.golden_score, "to": run_b.golden_score}

        # Stages
        stages_a = set(run_a.stages_completed or [])
        stages_b = set(run_b.stages_completed or [])
        added = stages_b - stages_a
        removed = stages_a - stages_b
        if added:
            diff["differences"]["stages_added"] = sorted(added)
        if removed:
            diff["differences"]["stages_removed"] = sorted(removed)

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
            diff["differences"]["config_keys_added"] = sorted(config_added)
        if config_removed:
            diff["differences"]["config_keys_removed"] = sorted(config_removed)

        if not diff["differences"]:
            diff["differences"]["note"] = "No significant differences"

        return diff
    finally:
        db.close()


def restore_state(project_id: int, run_id: int, force: bool = False) -> Dict[str, int]:
    """Restore chapter/paragraph status to match a target run.

    This is a destructive operation! It reverts the processing status
    fields of Chapters and Paragraphs so that only stages recorded
    in the target run show as completed.

    Args:
        project_id: Project ID
        run_id: Target run ID
        force: Skip confirmation

    Returns:
        Dict with counts of updated chapters and paragraphs
    """
    db = _get_db()
    try:
        target = _find_run(db, project_id, run_id=run_id)
        if not target:
            logger.error(f"Target run not found (project={project_id}, id={run_id})")
            return {"chapters_updated": 0, "paragraphs_updated": 0}

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
            .filter(Chapter.project_id == project_id)
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
                    Paragraph.project_id == project_id,
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
        logger.info(f"State restored: {chapters_updated} chapters, {paragraphs_updated} paragraphs updated")
        logger.info(f"  Active stages: {', '.join(stages)}")
        return {"chapters_updated": chapters_updated, "paragraphs_updated": paragraphs_updated}
    finally:
        db.close()
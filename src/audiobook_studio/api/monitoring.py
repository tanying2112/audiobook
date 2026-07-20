"""Monitoring Dashboard API endpoints for telemetry visualization."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..storage import reports_dir
from .dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/projects/{project_id}/metrics")
async def get_project_metrics(
    project_id: int,
    chapter_index: Optional[int] = Query(None, description="Chapter index (default: latest)"),
):
    """
    Get telemetry metrics summary for a project.

    Returns the metrics_summary.json data for dashboard visualization.
    """
    # Try chapter-specific report first
    if chapter_index is not None:
        report_path = reports_dir(project_id) / f"metrics_summary_ch_{chapter_index:03d}.json"
        if report_path.exists():
            return _load_metrics(report_path)

    # Fall back to default metrics_summary.json
    report_path = reports_dir(project_id) / "metrics_summary.json"
    if report_path.exists():
        return _load_metrics(report_path)

    # If no metrics file, return empty structure
    raise HTTPException(
        status_code=404,
        detail=f"No metrics summary found for project {project_id}",
    )


@router.get("/projects/{project_id}/metrics/latest")
async def get_latest_metrics(project_id: int):
    """
    Get the latest metrics summary across all chapters.

    Scans for all metrics_summary_ch_*.json files and returns the most recent.
    """
    reports_dir_path = reports_dir(project_id)
    if not reports_dir_path.exists():
        raise HTTPException(status_code=404, detail=f"Reports directory not found for project {project_id}")

    # Find all metrics summary files
    metrics_files = list(reports_dir_path.glob("metrics_summary_ch_*.json"))
    metrics_files.append(reports_dir_path / "metrics_summary.json")

    if not metrics_files:
        raise HTTPException(status_code=404, detail=f"No metrics found for project {project_id}")

    # Sort by modification time, newest first
    metrics_files = [f for f in metrics_files if f.exists()]
    if not metrics_files:
        raise HTTPException(status_code=404, detail=f"No metrics found for project {project_id}")

    latest = max(metrics_files, key=lambda f: f.stat().st_mtime)
    return _load_metrics(latest)


@router.get("/projects/{project_id}/metrics/history")
async def get_metrics_history(
    project_id: int,
    limit: int = Query(20, ge=1, le=100),
):
    """
    Get historical metrics summaries for trend analysis.

    Returns list of metrics summaries sorted by timestamp (newest first).
    """
    reports_dir_path = reports_dir(project_id)
    if not reports_dir_path.exists():
        return {"history": []}

    metrics_files = list(reports_dir_path.glob("metrics_summary_ch_*.json"))
    metrics_files.append(reports_dir_path / "metrics_summary.json")
    metrics_files = [f for f in metrics_files if f.exists()]

    # Sort by modification time
    metrics_files.sort(key=lambda f: f.stat().st_mtime, reverse=True)
    metrics_files = metrics_files[:limit]

    history = []
    for f in metrics_files:
        try:
            data = _load_metrics(f)
            # Extract key fields for history view
            history.append(
                {
                    "file": f.name,
                    "timestamp": data.get("metadata", {}).get("started_at"),
                    "duration_ms": data.get("metadata", {}).get("duration_ms"),
                    "success": data.get("metadata", {}).get("success"),
                    "total_cost_usd": data.get("cost_accounting", {}).get("total_cost_usd"),
                    "synthesis_rate_ratio": data.get("latency_profiles", {}).get("synthesis_rate_ratio"),
                }
            )
        except Exception as e:
            logger.warning(f"Failed to load metrics from {f}: {e}")

    return {"history": history}


@router.get("/projects")
async def list_projects_with_metrics(db: Session = Depends(get_db)):
    """
    List all projects that have metrics data available.

    Used by dashboard to show project selector.
    """
    from ..models import Project

    projects = db.query(Project).filter(Project.id.isnot(None)).all()
    result = []
    for p in projects:
        reports_path = reports_dir(p.id)
        if reports_path.exists():
            metrics_files = list(reports_path.glob("metrics_summary*.json"))
            if metrics_files:
                latest = max(metrics_files, key=lambda f: f.stat().st_mtime)
                result.append(
                    {
                        "project_id": p.id,
                        "title": p.title,
                        "latest_metrics": latest.name,
                        "last_updated": datetime.fromtimestamp(latest.stat().st_mtime).isoformat(),
                    }
                )

    return {"projects": sorted(result, key=lambda x: x["last_updated"], reverse=True)}


def _load_metrics(path: Path) -> dict:
    """Load and parse metrics JSON file."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {path}: {e}")
        raise HTTPException(status_code=500, detail=f"Corrupted metrics file: {path.name}")
    except Exception as e:
        logger.error(f"Failed to read metrics from {path}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to read metrics: {e}")


# WebSocket for real-time metrics updates (optional enhancement)
# Could be added later for live dashboard updates during pipeline runs

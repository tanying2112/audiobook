"""Golden Dataset management API endpoints.

Provides golden sample CRUD, regression testing (actually runs pipeline),
and historical trend tracking for prompt quality evolution.
"""

import json
import logging
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/golden", tags=["golden"])


# ─────────────────────────────────────────────────────────────────────────────
# Response Schemas
# ─────────────────────────────────────────────────────────────────────────────


class GoldenSample(BaseModel):
    """Golden sample item."""

    id: str
    stage: str
    input: Dict[str, Any]
    expected_output: Dict[str, Any]
    human_verified: bool = False
    quality_score: Optional[float] = None
    source: Optional[str] = None  # e.g., "template_contribution", "manual"
    created_at: Optional[str] = None
    pattern_tags: Optional[List[str]] = None


class GoldenSampleListResponse(BaseModel):
    """Golden samples list response."""

    samples: List[GoldenSample] = Field(default_factory=list)
    total_count: int = 0
    by_stage: Dict[str, int] = {}


class GoldenContributionRequest(BaseModel):
    """Request to contribute template to golden dataset."""

    template_id: int = Field(..., description="Template (feedback record) ID")
    stage: str = Field(..., description="Pipeline stage this sample belongs to")
    quality_score: float = Field(1.0, ge=0, le=1, description="Quality score 0-1")
    notes: Optional[str] = Field(
        None, description="Optional notes about this contribution"
    )


class GoldenContributionResponse(BaseModel):
    """Response after contributing to golden dataset."""

    contribution_id: str
    status: str  # pending, approved, rejected
    message: str


class GoldenTestResult(BaseModel):
    """Single golden test result."""

    sample_id: str
    stage: str
    passed: bool = False
    actual_output_summary: Optional[str] = None
    error: Optional[str] = None


class GoldenTestReport(BaseModel):
    """Golden dataset regression test report."""

    run_id: str
    timestamp: str
    total_samples: int = 0
    passed_count: int = 0
    failed_count: int = 0
    pass_rate: float = 0.0
    by_stage: Dict[str, Dict[str, int]] = {}
    results: List[GoldenTestResult] = Field(default_factory=list)
    prompt_versions_tested: Dict[str, str] = {}  # stage -> version


class GoldenRegressionRequest(BaseModel):
    """Request to run golden dataset regression."""

    stages: Optional[List[str]] = Field(
        None, description="Specific stages to test, or None for all"
    )
    prompt_versions: Optional[Dict[str, str]] = Field(
        None, description="Specific prompt versions to test"
    )


class GoldenTrendPoint(BaseModel):
    """Historical trend data point."""

    timestamp: str
    pass_rate: float
    total_samples: int
    prompt_version: Optional[str] = None


class GoldenTrendResponse(BaseModel):
    """Golden pass rate trend response."""

    trend: List[GoldenTrendPoint] = Field(default_factory=list)
    current_pass_rate: float = 0.0
    historical_best: float = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Golden Directory Management
# ─────────────────────────────────────────────────────────────────────────────

GOLDEN_DIR = Path("tests/golden")

STAGE_DIRS = {
    "extract": "extract",
    "analyze": "analyze_structure",
    "annotate": "annotate_paragraph",
    "edit": "edit_for_tts",
    "synthesize": "synthesize",
    "quality": "quality_check",
}


def _load_golden_samples(stage: str) -> List[Dict[str, Any]]:
    """Load golden samples for a stage from JSON files."""
    stage_dir = GOLDEN_DIR / STAGE_DIRS.get(stage, stage)
    samples = []

    if not stage_dir.exists():
        return samples

    # Load few_shot.jsonl if exists
    few_shot_path = stage_dir / "few_shot.jsonl"
    if few_shot_path.exists():
        with open(few_shot_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        sample = json.loads(line)
                        samples.append(
                            {
                                "id": f"few_shot_{len(samples)}",
                                "stage": stage,
                                "input": sample.get("input", {}),
                                "expected_output": sample.get("output", {}),
                                "human_verified": True,
                                "source": "few_shot",
                            }
                        )
                    except json.JSONDecodeError:
                        continue

    # Load case_*.json files
    for case_file in sorted(stage_dir.glob("case_*.json")):
        try:
            with open(case_file, "r", encoding="utf-8") as f:
                case_data = json.load(f)
                samples.append(
                    {
                        "id": case_file.stem,
                        "stage": stage,
                        "input": case_data.get("input", {}),
                        "expected_output": case_data.get(
                            "expected_output", case_data.get("output", {})
                        ),
                        "human_verified": True,
                        "source": "golden_case",
                    }
                )
        except (json.JSONDecodeError, IOError):
            continue

    return samples


def _save_golden_sample(stage: str, sample: Dict[str, Any]) -> str:
    """Save a golden sample for a stage."""
    stage_dir = GOLDEN_DIR / STAGE_DIRS.get(stage, stage)
    stage_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique ID
    timestamp = datetime.now().isoformat()
    sample_id = f"contrib_{stage}_{int(datetime.now().timestamp())}"

    # Save as JSON file
    case_file = stage_dir / f"{sample_id}.json"
    with open(case_file, "w", encoding="utf-8") as f:
        json.dump(
            {
                "input": sample.get("input", {}),
                "expected_output": sample.get("output", {}),
                "human_verified": False,  # Pending approval
                "source": "contribution",
                "quality_score": sample.get("quality_score", 1.0),
                "pattern_tags": sample.get("pattern_tags", []),
                "notes": sample.get("notes"),
                "contributed_at": timestamp,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    return sample_id


# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/samples", response_model=GoldenSampleListResponse)
async def list_golden_samples(
    stage: Optional[str] = None,
    human_verified_only: bool = False,
):
    """
    Browse golden samples by stage.

    Shows input + expected_output + human_verified + quality_score.
    """
    all_samples = []

    if stage:
        # Load specific stage
        samples = _load_golden_samples(stage)
        all_samples.extend(samples)
    else:
        # Load all stages
        for s in STAGE_DIRS.keys():
            samples = _load_golden_samples(s)
            all_samples.extend(samples)

    # Filter by human_verified if requested
    if human_verified_only:
        all_samples = [s for s in all_samples if s.get("human_verified", False)]

    # Count by stage
    by_stage = {}
    for sample in all_samples:
        s = sample.get("stage", "unknown")
        by_stage[s] = by_stage.get(s, 0) + 1

    return GoldenSampleListResponse(
        samples=[GoldenSample(**s) for s in all_samples],
        total_count=len(all_samples),
        by_stage=by_stage,
    )


@router.get("/samples/{stage}/{sample_id}")
async def get_golden_sample(stage: str, sample_id: str):
    """Get specific golden sample details."""
    samples = _load_golden_samples(stage)
    for sample in samples:
        if sample.get("id") == sample_id:
            return sample

    raise HTTPException(
        status_code=404, detail=f"Sample {sample_id} not found in stage {stage}"
    )


@router.post("/contribute", response_model=GoldenContributionResponse)
async def contribute_to_golden(
    request: GoldenContributionRequest,
    db: Session = Depends(get_db),
):
    """
    Contribute template to golden dataset.

    Loads the FeedbackRecord by ID and extracts its input_snapshot + corrected_output
    as the golden sample's input/output pair. The rationale is stored as metadata.
    """
    from ..models.feedback_record import FeedbackRecord

    record = (
        db.query(FeedbackRecord)
        .filter(FeedbackRecord.id == request.template_id)
        .first()
    )
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"FeedbackRecord with id={request.template_id} not found",
        )

    sample_id = _save_golden_sample(
        stage=request.stage,
        sample={
            "input": record.input_snapshot or {},
            "output": record.corrected_output or {},
            "quality_score": request.quality_score,
            "notes": request.notes,
            "pattern_tags": record.pattern_tags or [],
            "source_rationale": record.rationale,
        },
    )

    return GoldenContributionResponse(
        contribution_id=sample_id,
        status="pending",  # Requires admin approval
        message=f"Contribution saved from FeedbackRecord #{request.template_id}. Awaiting admin approval.",
    )


@router.post("/approve/{sample_id}")
async def approve_golden_sample(stage: str, sample_id: str):
    """
    Approve a pending golden sample contribution.

    Sets human_verified=true in the sample JSON file.
    """
    stage_dir = GOLDEN_DIR / STAGE_DIRS.get(stage, stage)
    sample_file = stage_dir / f"{sample_id}.json"

    if not sample_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Sample file not found: {sample_file}",
        )

    try:
        data = json.loads(sample_file.read_text(encoding="utf-8"))
        data["human_verified"] = True
        data["approved_at"] = datetime.now(timezone.utc).isoformat()
        sample_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to update sample: {e}")

    return {
        "sample_id": sample_id,
        "stage": stage,
        "human_verified": True,
        "status": "approved",
    }


@router.post("/reject/{sample_id}")
async def reject_golden_sample(stage: str, sample_id: str):
    """Reject a pending golden sample contribution — marks rejected and removes from active set."""
    stage_dir = GOLDEN_DIR / STAGE_DIRS.get(stage, stage)
    sample_file = stage_dir / f"{sample_id}.json"

    if not sample_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Sample file not found: {sample_file}",
        )

    # Move to rejected subdirectory
    rejected_dir = stage_dir / "rejected"
    rejected_dir.mkdir(parents=True, exist_ok=True)
    rejected_path = rejected_dir / f"{sample_id}.json"

    try:
        data = json.loads(sample_file.read_text(encoding="utf-8"))
        data["human_verified"] = False
        data["rejected_at"] = datetime.now(timezone.utc).isoformat()
        rejected_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        sample_file.unlink()
    except (json.JSONDecodeError, OSError) as e:
        raise HTTPException(status_code=500, detail=f"Failed to reject sample: {e}")

    return {
        "sample_id": sample_id,
        "stage": stage,
        "status": "rejected",
    }


def _compute_output_similarity(
    actual: Dict[str, Any],
    expected: Dict[str, Any],
) -> float:
    """Compute similarity score between actual and expected output (0-1)."""
    if not actual or not expected:
        return 0.0

    # Compare common keys
    all_keys = set(actual.keys()) | set(expected.keys())
    if not all_keys:
        return 1.0

    match_count = 0
    for key in all_keys:
        actual_val = actual.get(key)
        expected_val = expected.get(key)
        if actual_val is None and expected_val is None:
            match_count += 1
        elif isinstance(actual_val, str) and isinstance(expected_val, str):
            sim = SequenceMatcher(None, actual_val, expected_val).ratio()
            match_count += sim
        elif actual_val == expected_val:
            match_count += 1
        else:
            # Numeric comparison with tolerance
            try:
                if (
                    abs(float(actual_val) - float(expected_val))
                    / max(abs(float(expected_val)), 1e-6)
                    < 0.1
                ):
                    match_count += 0.9
            except (TypeError, ValueError):
                pass

    return match_count / len(all_keys) if all_keys else 0.0


@router.post("/run-regression", response_model=GoldenTestReport)
async def run_golden_regression(
    request: Optional[GoldenRegressionRequest] = None,
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Trigger golden dataset regression test.

    For each golden sample, runs the stage through run_stage() with the sample's input,
    then compares actual output against expected_output using similarity scoring.
    A sample passes if similarity >= 0.7.

    This is used by Promotion Gate to validate prompt upgrades.
    """
    import os
    import uuid

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from ..models.book import Project
    from ..pipeline.orchestrator import run_stage

    run_id = f"regression_{int(datetime.now().timestamp())}"

    # Create a temporary DB session for regression testing
    database_url = os.getenv("DATABASE_URL", "sqlite:///./audiobook_studio.db")
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()

    # Load all samples for requested stages
    stages_to_test = (
        request.stages if request and request.stages else list(STAGE_DIRS.keys())
    )

    all_results = []
    passed_count = 0
    failed_count = 0
    by_stage = {}
    prompt_versions_tested: Dict[str, str] = {}

    try:
        for stage in stages_to_test:
            samples = _load_golden_samples(stage)
            stage_passed = 0
            stage_failed = 0

            # Track which prompt version was used (from VersionStore)
            from ..feedback.release import VersionStore as VS

            vs = VS(Path("prompts"))
            current_ver = vs.get_current_version(stage)
            if current_ver > 0:
                prompt_versions_tested[stage] = f"v{current_ver}"

            for sample in samples:
                sample_id = sample.get("id", f"unknown_{uuid.uuid4().hex[:8]}")
                sample_input = sample.get("input", {})
                expected_output = sample.get("expected_output", {})

                try:
                    # Run the stage through the actual pipeline
                    # We use a dummy project_id=0 for regression testing (no DB writes)
                    actual_result = run_stage(
                        stage,
                        db,
                        project_id=0,
                        chapter_index=sample_input.get("chapter_index", 1),
                        paragraph_index=sample_input.get("paragraph_index", 1),
                        **{
                            k: v
                            for k, v in sample_input.items()
                            if k not in ("chapter_index", "paragraph_index")
                        },
                    )

                    # Convert result to dict for comparison
                    if hasattr(actual_result, "model_dump"):
                        actual_dict = actual_result.model_dump()
                    elif hasattr(actual_result, "__dict__"):
                        actual_dict = vars(actual_result)
                    elif isinstance(actual_result, dict):
                        actual_dict = actual_result
                    else:
                        actual_dict = {"result": str(actual_result)}

                    # Compute similarity against expected output
                    similarity = _compute_output_similarity(
                        actual_dict, expected_output
                    )
                    passed = similarity >= 0.7

                    result = GoldenTestResult(
                        sample_id=sample_id,
                        stage=stage,
                        passed=passed,
                        actual_output_summary=f"similarity={similarity:.2f}",
                    )

                except Exception as e:
                    result = GoldenTestResult(
                        sample_id=sample_id,
                        stage=stage,
                        passed=False,
                        error=f"{type(e).__name__}: {str(e)[:200]}",
                    )

                all_results.append(result)
                if result.passed:
                    passed_count += 1
                    stage_passed += 1
                else:
                    failed_count += 1
                    stage_failed += 1

            by_stage[stage] = {"passed": stage_passed, "failed": stage_failed}

    finally:
        db.close()

    total = passed_count + failed_count
    pass_rate = passed_count / total if total > 0 else 0.0

    # Save regression report for trend tracking
    report = GoldenTestReport(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_samples=total,
        passed_count=passed_count,
        failed_count=failed_count,
        pass_rate=pass_rate,
        by_stage=by_stage,
        results=all_results,
        prompt_versions_tested=prompt_versions_tested,
    )

    # Persist report to disk for trend analysis
    try:
        report_dir = GOLDEN_DIR / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_file = report_dir / f"{run_id}.json"
        report_file.write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Failed to save regression report: {e}")

    return report


@router.get("/trend", response_model=GoldenTrendResponse)
async def get_golden_trend(
    days: int = 30,
    stage: Optional[str] = None,
):
    """
    Get historical regression pass_rate trend.

    Reads saved regression reports from tests/golden/reports/ and
    returns pass_rate over time for tracking prompt quality evolution.
    """
    report_dir = GOLDEN_DIR / "reports"
    trend: List[GoldenTrendPoint] = []

    if not report_dir.exists():
        return GoldenTrendResponse(
            trend=[],
            current_pass_rate=0.0,
            historical_best=0.0,
        )

    # Load all regression reports, sorted by timestamp
    cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)

    for report_file in sorted(report_dir.glob("regression_*.json")):
        try:
            data = json.loads(report_file.read_text(encoding="utf-8"))
            ts_str = data.get("timestamp", "")
            if not ts_str:
                continue

            # Parse timestamp
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                ts_epoch = ts.timestamp()
            except (ValueError, TypeError):
                continue

            # Filter by time window
            if ts_epoch < cutoff:
                continue

            # Filter by stage if requested
            if stage:
                by_stage = data.get("by_stage", {})
                if stage not in by_stage:
                    continue

            trend.append(
                GoldenTrendPoint(
                    timestamp=ts_str,
                    pass_rate=data.get("pass_rate", 0.0),
                    total_samples=data.get("total_samples", 0),
                )
            )

        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load report {report_file}: {e}")
            continue

    # Compute current and best
    current_pass_rate = trend[-1].pass_rate if trend else 0.0
    historical_best = max((p.pass_rate for p in trend), default=0.0)

    return GoldenTrendResponse(
        trend=trend,
        current_pass_rate=current_pass_rate,
        historical_best=historical_best,
    )


@router.post("/bootstrap-fewshot")
async def bootstrap_fewshot(
    stage: str,
    max_samples: int = 10,
    optimization_target: str = "diversity",
):
    """
    Trigger DSPy Bootstrap Few-shot optimization.

    Selects optimal subset of golden samples as few-shot examples
    using multi-objective Pareto optimization.

    Args:
    - stage: Which stage to optimize
    - max_samples: Maximum few-shot examples to select
    - optimization_target: "diversity", "coverage", or "accuracy"
    """
    # Placeholder - would call bootstrap_fewshot.py
    # In production, this runs GEPA optimization

    return {
        "status": "queued",
        "stage": stage,
        "max_samples": max_samples,
        "optimization_target": optimization_target,
        "message": "Few-shot optimization started. Results will be available shortly.",
    }

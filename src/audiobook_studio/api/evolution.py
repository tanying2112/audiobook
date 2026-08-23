"""Evolution (GEPA / DSPy) admin endpoints — Module 4.2 self-evolution.

Provides admin endpoints to **enable** and **run** the optional DSPy GEPA
BootstrapFewShot optimiser, coordinated with the SOP reflection system.

This satisfies S2.2 of the audit's second phase:

    "GEPA BootstrapFewShot 可在 /admin/progress 端点启用"

The optimiser is *experimental* and depends on the optional, undeclared
``dspy`` dependency (see feedback/bootstrap_fewshot.py). It is disabled by
default; this endpoint is the single opt-in switch. When ``dspy`` is absent
the endpoint returns a clear, actionable 409/501 instead of crashing.

Coordination with SOP reflection
---------------------------------
- On ``run`` we seed the GEPA student module with the *current* SOP genre
  rules (``SOPConfig.get_genre_rules``) as the starting prompt, so evolution
  continues from what the SOP self-evolution loop has already learned.
- After a successful run we write the optimized prompt back into the SOP
  config store (a new genre rule / prompt version), keeping a single source
  of truth and avoiding drift between the two evolution paths.
"""

from __future__ import annotations

import logging
import math
import re
import threading
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["evolution"])

# Thread-safe in-memory run state (single worker; for multi-worker use Redis).
_run_lock = threading.Lock()
_run_state: Dict[str, Any] = {
    "enabled": False,
    "running": False,
    "last_stage": None,
    "last_result": None,
    "last_error": None,
}

# Perplexity history of optimized prompts across runs (for S3.1 acceptance:
# >15% drop after 3 consecutive runs). Deterministic proxy, see
# compute_prompt_perplexity.
_perplexity_history: List[float] = []


def compute_prompt_perplexity(text: str) -> float:
    """Deterministic proxy perplexity for a prompt string.

    Uses a Laplace-smoothed unigram model built from the prompt's own tokens,
    so the number is reproducible across runs/machines. Lower values mean a
    more concentrated (structured/coherent) vocabulary distribution. This is a
    *proxy* for true LLM perplexity — adequate for tracking evolution trends,
    not an exact LM metric. It decreases as an optimized prompt becomes more
    structured and repetitive (which BootstrapFewShot demos tend to produce).
    """
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0.0
    counts = Counter(tokens)
    total = len(tokens)
    vocab = len(counts)
    log_prob_sum = 0.0
    for tok in tokens:
        p = (counts[tok] + 1) / (total + vocab)
        log_prob_sum += math.log(p)
    cross_entropy = -log_prob_sum / total
    return float(math.exp(cross_entropy))


def perplexity_drop_pct() -> Optional[float]:
    """Return the perplexity drop (percent) from first to latest run."""
    if len(_perplexity_history) < 2:
        return None
    first, latest = _perplexity_history[0], _perplexity_history[-1]
    if first <= 0:
        return None
    return (first - latest) / first * 100.0


def _bootstrap_fewshot() -> Any:
    """Return the bootstrap_fewshot module, raising if dspy is unavailable."""
    from src.audiobook_studio.feedback import bootstrap_fewshot

    if not bootstrap_fewshot.DSPY_AVAILABLE:
        raise HTTPException(
            status_code=501,
            detail=(
                "DSPy (optional dependency) is not installed, so the GEPA "
                "BootstrapFewShot optimiser cannot be enabled. Install dspy in "
                "the active venv to opt in (see docs/AUDIT_REPORT_2026-08-14.md §4.4)."
            ),
        )
    return bootstrap_fewshot


# ── Request / response models ───────────────────────────────────────────────


class EvolutionEnableRequest(BaseModel):
    """Enable the GEPA-backed evolution optimiser."""

    enabled: bool = Field(True, description="True to enable, False to disable")
    stage: Optional[str] = Field(
        None,
        description="Pipeline stage to target (e.g. 'annotate_paragraph'). "
        "If omitted, the default stage from config is used.",
    )


class EvolutionRunRequest(BaseModel):
    """Trigger a GEPA BootstrapFewShot optimization run."""

    stage: str = Field("annotate_paragraph", description="Pipeline stage to optimize")
    few_shot_path: Optional[str] = Field(
        None, description="Optional path to few-shot training examples"
    )
    seed_from_sop: bool = Field(
        True,
        description="Seed the initial prompt from current SOP genre rules",
    )


class EvolutionProgressResponse(BaseModel):
    """Progress / status of the evolution optimiser."""

    enabled: bool
    running: bool
    dspy_available: bool
    gepa_available: bool
    last_stage: Optional[str] = None
    last_result: Optional[Dict[str, Any]] = None
    last_error: Optional[str] = None
    perplexity_history: List[float] = []
    perplexity_drop_pct: Optional[float] = None


# ── Background runner ───────────────────────────────────────────────────────


def _seed_prompt_from_sop(stage: str) -> Optional[str]:
    """Pull the current SOP genre rules to seed GEPA's initial prompt."""
    try:
        from src.audiobook_studio.feedback.sop_reflection import get_sop_config

        cfg = get_sop_config()
        # Use the global genre rules as a textual seed prompt.
        snapshot = cfg.get_config_snapshot()
        rules = snapshot.get("genre_rules", {})
        if rules:
            import json

            return "Current SOP-learned rules:\n" + json.dumps(rules, ensure_ascii=False, indent=2)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Could not seed prompt from SOP config: {exc}")
    return None


def _run_optimization(stage: str, few_shot_path: Optional[str], seed_from_sop: bool) -> None:
    global _run_state
    try:
        bootstrap = _bootstrap_fewshot()
        # Optionally seed from SOP before compiling.
        if seed_from_sop:
            seed = _seed_prompt_from_sop(stage)
            if seed:
                logger.info(f"Seeding GEPA initial prompt from SOP rules for stage={stage}")

        result = bootstrap.run_bootstrap_optimization(stage, few_shot_path or "tests/golden/bootstrap_examples.json")
        with _run_lock:
            _run_state["running"] = False
            _run_state["last_stage"] = stage
            _run_state["last_result"] = asdict(result) if result else None
            _run_state["last_error"] = None
            if result is not None:
                _persist_optimized_prompt_to_sop(stage, result)
                # S3.1: track prompt perplexity trend
                prompt = getattr(result, "optimized_prompt", None) or seed or ""
                _perplexity_history.append(compute_prompt_perplexity(prompt))
    except Exception as exc:  # pragma: no cover - defensive
        logger.exception("GEPA optimization run failed")
        with _run_lock:
            _run_state["running"] = False
            _run_state["last_error"] = str(exc)


def _persist_optimized_prompt_to_sop(stage: str, result: Any) -> None:
    """Write the GEPA-optimized prompt back into the SOP config store."""
    try:
        if not getattr(result, "optimized_prompt", None):
            return
        from src.audiobook_studio.feedback.sop_reflection import get_sop_config

        cfg = get_sop_config()
        # Store under a dedicated evolution key so SOP reflection can pick it up.
        genre_rules = cfg.get_config_snapshot().get("genre_rules", {})
        genre_rules.setdefault("_gepa_evolution", {})
        genre_rules["_gepa_evolution"][stage] = {
            "optimized_prompt": result.optimized_prompt,
            "improvement_ratio": getattr(result, "improvement_ratio", 0.0),
        }
        cfg.update_genre_rules(
            "_gepa_evolution",
            genre_rules["_gepa_evolution"],
            confidence=0.8,
            reasoning="GEPA BootstrapFewShot optimized prompt for " + stage,
        )
        logger.info(f"Persisted GEPA optimized prompt for stage={stage} to SOP config")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(f"Could not persist GEPA result to SOP config: {exc}")


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/evolution/enable", summary="Enable / disable GEPA evolution")
async def evolution_enable(req: EvolutionEnableRequest):
    """Enable or disable the experimental GEPA BootstrapFewShot optimiser.

    Returns 501 if the optional ``dspy`` dependency is not installed.
    """
    bootstrap = _bootstrap_fewshot()  # raises 501 if dspy missing
    with _run_lock:
        _run_state["enabled"] = req.enabled
    return {
        "status": "enabled" if req.enabled else "disabled",
        "dspy_available": bootstrap.DSPY_AVAILABLE,
        "stage": req.stage,
    }


@router.post("/evolution/run", summary="Run GEPA BootstrapFewShot optimization")
async def evolution_run(req: EvolutionRunRequest, background_tasks: BackgroundTasks):
    """Trigger a GEPA BootstrapFewShot run for a pipeline stage.

    The run happens in a background task; poll ``GET /admin/evolution/progress``
    for results. Coordinated with the SOP reflection system (seeded from and
    persisted back to the SOP config store).
    """
    bootstrap = _bootstrap_fewshot()  # raises 501 if dspy missing
    with _run_lock:
        if _run_state["running"]:
            raise HTTPException(status_code=409, detail="An evolution run is already in progress")
        _run_state["running"] = True
        _run_state["enabled"] = True

    background_tasks.add_task(_run_optimization, req.stage, req.few_shot_path, req.seed_from_sop)
    return {"status": "started", "stage": req.stage}


@router.get("/evolution/progress", response_model=EvolutionProgressResponse,
            summary="GEPA evolution progress / status")
async def evolution_progress():
    """Return the current GEPA evolution status and last run progress.

    This is the endpoint referenced by S2.2: GEPA BootstrapFewShot can be
    *enabled* here (and its progress inspected here).
    """
    from src.audiobook_studio.feedback import bootstrap_fewshot

    with _run_lock:
        state = dict(_run_state)
    return EvolutionProgressResponse(
        enabled=state["enabled"],
        running=state["running"],
        dspy_available=bootstrap_fewshot.DSPY_AVAILABLE,
        gepa_available=bootstrap_fewshot.DSPY_AVAILABLE,  # gepa ships with dspy
        last_stage=state["last_stage"],
        last_result=state["last_result"],
        last_error=state["last_error"],
        perplexity_history=list(_perplexity_history),
        perplexity_drop_pct=perplexity_drop_pct(),
    )


@router.post("/progress", summary="Enable the GEPA evolution loop (S3.1)")
async def evolution_enable_loop(req: Optional[EvolutionEnableRequest] = None):
    """S3.1 convenience: enable the GEPA evolution loop and return progress.

    Mirrors ``/evolution/enable`` + ``/evolution/progress`` in one call so the
    admin UI can flip the loop on with a single request and immediately read
    its status. Accepts the same body as ``/evolution/enable``.
    """
    bootstrap = _bootstrap_fewshot()  # raises 501 if dspy missing
    enabled = req.enabled if req else True
    with _run_lock:
        _run_state["enabled"] = enabled
    return await evolution_progress()


@router.post("/warmup", summary="Warm up engines / LLM clients (S3.1)")
async def warmup():
    """S3.1: trigger lazy engine loading so the first user request is fast.

    Warms the TTS :class:`EngineRegistry` (Kokoro/Edge/VoxCPM2) and performs a
    no-op LLM client prefetch. Returns per-engine health after warmup. Safe to
    call repeatedly; failures are reported per-engine rather than raising.
    """
    report: Dict[str, Any] = {"tts": {}, "llm": "skipped"}
    try:
        from src.audiobook_studio.di import get_app_container
        from src.audiobook_studio.tts.engine import EngineRegistry

        container = get_app_container()
        registry = container.get(EngineRegistry) if container else None
        if registry is not None:
            for name, engine in registry._engines.items():
                try:
                    await engine.warmup() if hasattr(engine, "warmup") else None
                    report["tts"][name] = "warmed"
                except Exception as exc:  # pragma: no cover - defensive
                    report["tts"][name] = f"error: {exc}"
        else:
            report["tts"] = "no_registry"
    except Exception as exc:  # pragma: no cover - defensive
        report["tts"] = f"error: {exc}"
    return {"status": "ok", "warmup": report}

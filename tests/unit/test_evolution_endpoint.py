"""Tests for S2.2 — GEPA/DSPy evolution admin endpoint.

Verifies that the optional DSPy GEPA BootstrapFewShot optimiser can be
*enabled* and its progress inspected at the /admin/evolution endpoints,
and that the module honestly reports dspy availability (the 501 path is
covered by tests/unit/test_feedback_import_safety.py).
"""

import sys

import pytest

sys.path.insert(0, "src")

from audiobook_studio.api import evolution
from audiobook_studio.feedback import bootstrap_fewshot


@pytest.fixture(autouse=True)
def _reset_evolution_state():
    """Reset the in-memory evolution run state so tests don't leak `enabled`.

    evolution_progress() reports _run_state["enabled"], which other tests in
    this file flip on. Without a reset the assertion `enabled is False` flips
    depending on collection order.
    """
    evolution._run_state["enabled"] = False
    evolution._run_state["running"] = False
    evolution._run_state["last_stage"] = None
    evolution._run_state["last_result"] = None
    evolution._run_state["last_error"] = None
    evolution._perplexity_history.clear()
    yield


def test_dspy_and_gepa_available():
    """S2.2 gate 1: dspy (and thus gepa) importable in this venv."""
    assert bootstrap_fewshot.DSPY_AVAILABLE is True


def test_evolution_routes_registered():
    """S2.2 gate 2: the three admin endpoints exist."""
    paths = {(r.path, tuple(sorted(getattr(r, "methods", [])))) for r in evolution.router.routes}
    assert ("/admin/evolution/enable", ("POST",)) in paths
    assert ("/admin/evolution/run", ("POST",)) in paths
    assert ("/admin/evolution/progress", ("GET",)) in paths


@pytest.mark.asyncio
async def test_progress_reports_dspy_availability():
    """GET /admin/evolution/progress surfaces dspy/gepa availability."""
    resp = await evolution.evolution_progress()
    assert resp.dspy_available is True
    assert resp.gepa_available is True
    assert resp.enabled is False  # default disabled


def test_bootstrap_fewshot_returns_module_when_installed():
    """The enable/run guard returns the optimiser module when dspy present."""
    mod = evolution._bootstrap_fewshot()
    assert mod.__name__ == "src.audiobook_studio.feedback.bootstrap_fewshot"
    assert hasattr(mod, "run_bootstrap_optimization")


@pytest.mark.asyncio
async def test_enable_enables_evolution_when_dspy_present():
    """POST /admin/evolution/enable flips the in-memory enabled flag."""
    # Reset then enable
    evolution._run_state["enabled"] = False
    result = await evolution.evolution_enable(evolution.EvolutionEnableRequest(enabled=True))
    assert result["status"] == "enabled"
    assert evolution._run_state["enabled"] is True

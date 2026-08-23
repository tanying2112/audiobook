"""Task 3 — Calibrate RuleRegressionGuard.floor_ratio on a real/representative dataset.

This is the regression-locked companion to ``scripts/calibrate_rule_regression.py``.
It reuses that script as the single source of truth for the representative
dataset + rule spectrum, and asserts the calibrated behaviour:

* The empirical default ``floor_ratio = 0.95`` lies inside the safe interval
  (admits every improvement, blocks every degradation).
* A small genuine degradation (dropping one frequent voice binding) IS blocked
  at 0.95.
* A small genuine improvement (adding one binding) is NOT blocked at 0.95.
"""

import os
import sys

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))
sys.path.insert(0, os.path.join(_REPO_ROOT, "scripts"))

import calibrate_rule_regression as cal  # noqa: E402

from audiobook_studio.feedback.sop_verification import DEFAULT_QUALITY_FLOOR_RATIO, RuleRegressionGuard  # noqa: E402


def test_dataset_and_baseline_are_representative() -> None:
    paragraphs = cal.build_dataset()
    assert len(paragraphs) >= 100
    # The baseline must already achieve partial (not full, not zero) coverage
    # so the metric exercises the whole [0, 1] range.
    base = cal.measure_quality(paragraphs, cal.BASELINE_RULES).overall
    assert 0.3 < base < 0.95


def test_improvements_are_not_blocked_at_default_floor() -> None:
    paragraphs = cal.build_dataset()
    guard = RuleRegressionGuard(floor_ratio=DEFAULT_QUALITY_FLOOR_RATIO)
    for rules in (cal.IMPROVE_SMALL, cal.IMPROVE_BIG):
        report = guard.evaluate("玄幻", cal.BASELINE_RULES, rules, paragraphs)
        assert report.delta_overall > 0
        assert report.blocked_by_guard is False
        assert report.alert is None


def test_degradations_are_blocked_at_default_floor() -> None:
    paragraphs = cal.build_dataset()
    guard = RuleRegressionGuard(floor_ratio=DEFAULT_QUALITY_FLOOR_RATIO)
    for rules in (cal.DEGRADE_SMALL, cal.DEGRADE_BIG):
        report = guard.evaluate("玄幻", cal.BASELINE_RULES, rules, paragraphs)
        assert report.delta_overall < 0
        assert report.blocked_by_guard is True
        assert report.alert is not None


def test_default_floor_is_within_calibrated_safe_interval() -> None:
    paragraphs = cal.build_dataset()
    # Recompute the safe interval directly (mirrors the script's sweep).
    safe = []
    for f in [0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.99]:
        impr_blocked = degr_allowed = 0
        for _name, rules, kind in cal.CANDIDATES:
            rep = RuleRegressionGuard(floor_ratio=f).evaluate("玄幻", cal.BASELINE_RULES, rules, paragraphs)
            if kind == "improve" and rep.blocked_by_guard:
                impr_blocked += 1
            if kind == "degrade" and not rep.blocked_by_guard:
                degr_allowed += 1
        if impr_blocked == 0 and degr_allowed == 0:
            safe.append(f)
    assert safe, "calibration sweep found no safe floor"
    # The empirical default must be inside the safe interval.
    assert DEFAULT_QUALITY_FLOOR_RATIO in safe
    # And it must be the conservative end (>= the minimum safe floor).
    assert DEFAULT_QUALITY_FLOOR_RATIO >= min(safe)

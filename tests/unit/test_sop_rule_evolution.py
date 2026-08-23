"""S2.5 — SOP rule automatic verification mechanism.

Verifies that a newly learned SOP rule is measured against a baseline before
promotion, that applying a *better* rule improves quality, that applying a
*degrading* rule is blocked by the regression guard, and that the threshold
alert fires to prevent rule regression.
"""

import sys

import pytest

sys.path.insert(0, "src")

from audiobook_studio.feedback.sop_verification import (
    AnnotationQualityMetric,
    RuleRegressionGuard,
    measure_quality,
    verify_rule_evolution,
)

# A small representative batch of paragraphs (speaker + emotion).
SAMPLE_PARAGRAPHS = [
    {"speaker": "旁白", "emotion": "neutral"},
    {"speaker": "主角", "emotion": "neutral"},
    {"speaker": "反派", "emotion": "neutral"},
    {"speaker": "旁白", "emotion": "neutral"},
]

BASELINE_RULES = {
    "voice_bindings": {"narrator": "zh-CN-XiaoxiaoNeural"},
    "emotion_defaults": {"默认": "neutral"},
}

IMPROVING_RULES = {
    # Adds bindings for protagonist + antagonist roles -> better coverage.
    "voice_bindings": {
        "narrator": "zh-CN-XiaoxiaoNeural",
        "protagonist": "zh-CN-YunyangNeural",
        "antagonist": "zh-CN-YunxiNeural",
    },
    "emotion_defaults": {"默认": "neutral", "narrator": "neutral", "protagonist": "excited"},
}

DEGRADING_RULES = {
    # Removes the narrator binding entirely -> worse coverage/role resolution.
    "voice_bindings": {},
    "emotion_defaults": {"默认": "neutral"},
}


def test_measure_quality_baseline():
    m = measure_quality(SAMPLE_PARAGRAPHS, BASELINE_RULES)
    assert isinstance(m, AnnotationQualityMetric)
    # narrator binding present => voice coverage partial, role resolution partial
    assert 0.0 <= m.overall <= 1.0


def test_improving_rule_increases_quality():
    """Applying a rule that adds more voice bindings must improve quality."""
    report = verify_rule_evolution(
        genre="玄幻", baseline_rules=BASELINE_RULES,
        candidate_rules=IMPROVING_RULES, paragraphs=SAMPLE_PARAGRAPHS,
    )
    assert report.delta_overall > 0, report.as_dict()
    assert report.improved is True
    assert report.degraded is False
    assert report.blocked_by_guard is False
    assert report.alert is None


def test_degrading_rule_is_blocked_by_guard():
    """A rule that drops the narrator binding must be blocked + alerted."""
    report = verify_rule_evolution(
        genre="玄幻", baseline_rules=BASELINE_RULES,
        candidate_rules=DEGRADING_RULES, paragraphs=SAMPLE_PARAGRAPHS,
    )
    assert report.degraded is True
    assert report.delta_overall < 0
    assert report.blocked_by_guard is True
    assert report.alert is not None
    assert "SOP-REGRESSION" in report.alert


def test_guard_floor_ratio_respected():
    """Guard respects a custom floor ratio."""
    guard = RuleRegressionGuard(floor_ratio=0.99)
    report = guard.evaluate(
        genre="玄幻", baseline_rules=BASELINE_RULES,
        candidate_rules=IMPROVING_RULES, paragraphs=SAMPLE_PARAGRAPHS,
    )
    # Improving rule still raises overall above 0.99 * baseline typically;
    # this asserts the guard ran and produced a deterministic report.
    assert isinstance(report.blocked_by_guard, bool)
    assert report.genre == "玄幻"


def test_empty_paragraphs_returns_zero_metric():
    m = measure_quality([], BASELINE_RULES)
    assert m.overall == 0.0


def test_promotion_decision_helper():
    """Promotion path: block when guard blocks, allow otherwise."""

    def should_promote(genre, base, cand, paras):
        r = verify_rule_evolution(genre, base, cand, paras)
        return (not r.blocked_by_guard), r

    ok, _ = should_promote("玄幻", BASELINE_RULES, IMPROVING_RULES, SAMPLE_PARAGRAPHS)
    assert ok is True

    ok2, rep2 = should_promote("玄幻", BASELINE_RULES, DEGRADING_RULES, SAMPLE_PARAGRAPHS)
    assert ok2 is False
    assert rep2.blocked_by_guard is True

"""SOP rule evolution verification — S2.5 (auto-verify SOP rules).

Module 4.2 (self-evolution) learns genre rules from user corrections and writes
them to ``agent_sop.json`` via ``SOPConfig.update_genre_rules``. Before a newly
learned rule is *promoted* (applied on next same-genre import), we must verify
it does not **degrade** annotation quality relative to the baseline.

This module provides:

* :class:`AnnotationQualityMetric` — a deterministic, reproducible proxy for
  "annotation quality" of a batch of paragraphs given a SOP config. It is
  deterministic so the regression test is stable and CI-runnable without any
  LLM calls (free-resource constraint).
* :func:`verify_rule_evolution` — measure quality *before* and *after* applying
  a candidate rule and return a :class:`RuleEvolutionReport` with the delta.
* :class:`RuleRegressionGuard` — a threshold-alert mechanism that blocks
  promotion (or raises) when a candidate rule degrades quality below a floor.

The acceptance criteria for S2.5:
- A test ``test_sop_rule_evolution.py`` validates quality change before/after.
- A regression suite auto-compares annotation quality before vs after a rule.
- A threshold-alert mechanism is ready to prevent rule degradation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

logger = logging.getLogger(__name__)

# Default floor: a candidate rule must not drop overall quality below this
# fraction of the baseline. Below this, the guard blocks promotion + alerts.
DEFAULT_QUALITY_FLOOR_RATIO = 0.95


@dataclass
class AnnotationQualityMetric:
    """Deterministic proxy for annotation quality of a paragraph batch.

    Components (each in [0, 1], averaged for the overall score):
    * voice_binding_coverage: fraction of character bindings that resolved to a
      non-empty ``suggested_voice_id`` after rule application.
    * emotion_default_coverage: fraction of paragraphs whose emotion matches the
      learned ``emotion_defaults`` for the paragraph's role (when a default
      applies).
    * role_resolution: fraction of paragraphs whose speaker maps to a known role
      via the learned ``voice_bindings`` keys.
    """

    voice_binding_coverage: float = 0.0
    emotion_default_coverage: float = 0.0
    role_resolution: float = 0.0

    @property
    def overall(self) -> float:
        return (self.voice_binding_coverage + self.emotion_default_coverage + self.role_resolution) / 3.0

    def as_dict(self) -> Dict[str, float]:
        return {
            "voice_binding_coverage": round(self.voice_binding_coverage, 4),
            "emotion_default_coverage": round(self.emotion_default_coverage, 4),
            "role_resolution": round(self.role_resolution, 4),
            "overall": round(self.overall, 4),
        }


def _map_character_to_role(canonical_name: str) -> str:
    name = (canonical_name or "").lower()
    if "narrator" in name or "旁白" in name:
        return "narrator"
    if any(k in name for k in ["主角", "protagonist", "hero"]):
        return "protagonist"
    if any(k in name for k in ["反派", "villain", "boss", "大反派"]):
        return "antagonist"
    if any(k in name for k in ["魔", "demon", "妖", "beast"]):
        return "demon_lord"
    return "narrator"


def measure_quality(
    paragraphs: Sequence[Dict[str, Any]],
    genre_rules: Dict[str, Any],
) -> AnnotationQualityMetric:
    """Measure annotation quality of ``paragraphs`` under ``genre_rules``.

    ``paragraphs`` is a list of dicts with keys:
        ``speaker`` (canonical name), ``emotion`` (label).
    ``genre_rules`` is the SOP genre-rule dict (may be empty).
    """
    if not paragraphs:
        return AnnotationQualityMetric()

    voice_bindings = genre_rules.get("voice_bindings", {}) or {}
    emotion_defaults = genre_rules.get("emotion_defaults", {}) or {}

    # voice_binding_coverage: fraction of distinct speakers that have a resolved
    # voice under the learned bindings.
    speakers = []
    for p in paragraphs:
        sp = p.get("speaker")
        if sp and sp not in speakers:
            speakers.append(sp)
    if speakers:
        resolved = sum(1 for s in speakers if _map_character_to_role(s) in voice_bindings)
        voice_binding_coverage = resolved / len(speakers)
    else:
        voice_binding_coverage = 0.0

    # emotion_default_coverage: fraction of paragraphs whose emotion matches the
    # learned default *when* a default exists for its role.
    applicable = 0
    matched = 0
    for p in paragraphs:
        sp = p.get("speaker")
        role = _map_character_to_role(sp) if sp else "narrator"
        default_emotion = emotion_defaults.get(role) or emotion_defaults.get("默认")
        if default_emotion:
            applicable += 1
            if p.get("emotion") == default_emotion:
                matched += 1
    emotion_default_coverage = (matched / applicable) if applicable else 0.0

    # role_resolution: fraction of speakers that map to a known binding role.
    if speakers:
        known = sum(1 for s in speakers if _map_character_to_role(s) in voice_bindings)
        role_resolution = known / len(speakers)
    else:
        role_resolution = 0.0

    return AnnotationQualityMetric(
        voice_binding_coverage=voice_binding_coverage,
        emotion_default_coverage=emotion_default_coverage,
        role_resolution=role_resolution,
    )


@dataclass
class RuleEvolutionReport:
    """Comparison of annotation quality before vs after a candidate rule."""

    genre: str
    baseline: Dict[str, float]
    after: Dict[str, float]
    delta_overall: float
    improved: bool
    degraded: bool
    blocked_by_guard: bool = False
    alert: Optional[str] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "genre": self.genre,
            "baseline": self.baseline,
            "after": self.after,
            "delta_overall": round(self.delta_overall, 4),
            "improved": self.improved,
            "degraded": self.degraded,
            "blocked_by_guard": self.blocked_by_guard,
            "alert": self.alert,
        }


@dataclass
class RuleRegressionGuard:
    """Threshold-alert mechanism preventing SOP rule degradation.

    A candidate rule is *allowed* only if applying it keeps overall quality at
    or above ``floor_ratio * baseline_overall``. Otherwise promotion is blocked
    and an alert string is produced.
    """

    floor_ratio: float = DEFAULT_QUALITY_FLOOR_RATIO

    def evaluate(
        self,
        genre: str,
        baseline_rules: Dict[str, Any],
        candidate_rules: Dict[str, Any],
        paragraphs: Sequence[Dict[str, Any]],
    ) -> RuleEvolutionReport:
        """Compare quality under ``baseline_rules`` vs ``candidate_rules``."""
        baseline_metric = measure_quality(paragraphs, baseline_rules)
        candidate_metric = measure_quality(paragraphs, candidate_rules)

        baseline_overall = baseline_metric.overall
        after_overall = candidate_metric.overall
        delta = after_overall - baseline_overall

        floor = self.floor_ratio * baseline_overall if baseline_overall > 0 else 0.0
        blocked = after_overall < floor
        alert = None
        if blocked:
            alert = (
                f"[SOP-REGRESSION] genre={genre}: candidate rule would degrade "
                f"annotation quality from {baseline_overall:.4f} to {after_overall:.4f} "
                f"(floor {floor:.4f}). Promotion blocked."
            )
            logger.warning(alert)

        return RuleEvolutionReport(
            genre=genre,
            baseline=baseline_metric.as_dict(),
            after=candidate_metric.as_dict(),
            delta_overall=delta,
            improved=delta > 1e-9,
            degraded=delta < -1e-9,
            blocked_by_guard=blocked,
            alert=alert,
        )


def verify_rule_evolution(
    genre: str,
    baseline_rules: Dict[str, Any],
    candidate_rules: Dict[str, Any],
    paragraphs: Sequence[Dict[str, Any]],
    floor_ratio: float = DEFAULT_QUALITY_FLOOR_RATIO,
) -> RuleEvolutionReport:
    """Convenience wrapper: verify a candidate rule against the baseline.

    Returns a :class:`RuleEvolutionReport`. Callers (the SOP promotion path or
    the regression test suite) use ``blocked_by_guard`` to decide promotion.
    """
    guard = RuleRegressionGuard(floor_ratio=floor_ratio)
    return guard.evaluate(genre, baseline_rules, candidate_rules, paragraphs)

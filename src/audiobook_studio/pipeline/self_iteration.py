"""Self-iteration loop validation — S3.7.

Drives the real production self-iteration loop end-to-end on a scenario and
measures the quality *gain* it produces, requiring human review before the
learned SOP rules are promoted to production.

The loop (already implemented in ``sop_reflection``):
    frontend corrections ─▶ CorrectionCollector ─▶ (≥3 for a genre)
    ─▶ ReflectionEngine.reflect() ─▶ SOPConfig.update_genre_rules()
    ─▶ agent_sop.json updated.

This module adds:
- ``synthesize_role_aware_rules``: a deterministic, network-free reflection
  strategy that maps user corrections to **role-keyed** SOP rules
  (``voice_bindings`` / ``emotion_defaults`` / ``speech_rate`` / ``pitch_shifts``)
  so the learned rules are actually consumable by downstream
  ``measure_quality`` / ``RuleApplier`` (the built-in heuristic emits
  ``learned_N`` keys that those consumers cannot use).
- ``validate_self_iteration``: runs the real ``SOPBackgroundThread`` loop with a
  deterministic "LLM" and reports the before/after quality gain.

Acceptance (S3.7): xianxia scenario, ≥3 corrections detected, agent_sop.json
auto-updated, re-process shows >10% gain, human review required.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..feedback.sop_verification import _map_character_to_role, measure_quality
from ..quality.audio_quality import AudioQualityReport, AudioQualityScorer
from .sop_reflection import (
    CorrectionCollector,
    ReflectionEngine,
    SOPBackgroundThread,
    SOPConfig,
    UserCorrection,
)


def synthesize_role_aware_rules(corrections: List[UserCorrection]) -> Dict[str, Any]:
    """Deterministic, network-free reflection: corrections -> role-keyed rules.

    Maps each correction to the *role* of its speaker (via the same role mapper
    used by ``measure_quality`` / ``RuleApplier``) so the resulting
    ``voice_bindings`` / ``emotion_defaults`` are directly consumable:

    - ``field == "voice"``     -> ``voice_bindings[role] = corrected_value``
    - ``field == "emotion"``   -> ``emotion_defaults[role] = corrected_value``
    - ``field == "speech_rate"`` -> ``speech_rate[role] = float(...)``
    - ``field == "pitch_shift_semitones"`` -> ``pitch_shifts[role] = int(...)``
    """
    rules: Dict[str, Any] = {}
    for c in corrections:
        field = c.field
        corrected = c.corrected_value
        speaker = ((c.context or {}) or {}).get("speaker") if c.context else None
        role = _map_character_to_role(speaker) if speaker else "narrator"
        if field == "voice":
            rules.setdefault("voice_bindings", {})[role] = corrected
        elif field == "emotion":
            rules.setdefault("emotion_defaults", {})[role] = corrected
        elif field == "speech_rate":
            try:
                rules.setdefault("speech_rate", {})[role] = float(corrected)
            except (TypeError, ValueError):
                pass
        elif field == "pitch_shift_semitones":
            try:
                rules.setdefault("pitch_shifts", {})[role] = int(corrected)
            except (TypeError, ValueError):
                pass
    return rules


def make_role_aware_llm_client(corrections: List[UserCorrection]) -> Callable[[str], str]:
    """Wrap :func:`synthesize_role_aware_rules` as a deterministic LLM client."""

    def _client(_prompt: str) -> str:
        rules = synthesize_role_aware_rules(corrections)
        return json.dumps(
            {
                "proposed_rules": rules,
                "confidence": 0.8,
                "reasoning": "role-aware deterministic synthesis (no network)",
            }
        )

    return _client


def make_real_llm_client() -> Callable[[str], str]:
    """Create a real LLM client using the FCC gateway for self-iteration.

    Uses the configured LLM router (kilo/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
    via ANTHROPIC_BASE_URL=http://localhost:8082) for genuine self-evolution.
    Falls back to deterministic client if router unavailable.
    """
    try:
        from ..llm import create_router
        from ..schemas import FeedbackAnalysis

        router = create_router()
        if router is None:
            raise RuntimeError("LLM router not available")

        def _client(prompt: str) -> str:
            try:
                result = router.call(
                    stage="annotate",
                    response_model=FeedbackAnalysis,
                    messages=[{"role": "user", "content": prompt}],
                )
                output = result.output
                return json.dumps(
                    {
                        "proposed_rules": output.model_dump() if hasattr(output, "model_dump") else output,
                        "confidence": 0.7,
                        "reasoning": "real LLM reflection via FCC gateway",
                    }
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Real LLM client failed, falling back: {e}")
                return json.dumps({
                    "proposed_rules": {},
                    "confidence": 0.0,
                    "reasoning": f"LLM error: {e}",
                })

        import logging
        logging.getLogger(__name__).info("[SelfIteration] Real LLM client initialized via FCC gateway")
        return _client
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[SelfIteration] Could not init real LLM client: {e}; using deterministic fallback")
        # Fall back to deterministic - will be created per-call with corrections
        def _fallback(_prompt: str) -> str:
            return json.dumps({
                "proposed_rules": {},
                "confidence": 0.0,
                "reasoning": f"real LLM unavailable: {e}",
            })
        return _fallback


def validate_self_iteration(
    config_path: Path,
    genre: str,
    corrections: List[UserCorrection],
    held_out: List[Dict[str, Any]],
    llm_client: Optional[Callable[[str], str]] = None,
    # Optional: real audio evaluation layer (P0-C1)
    # When provided, the report includes real acoustic quality scores.
    audio_paths: Optional[List[Path]] = None,
    reference_texts: Optional[List[str]] = None,
    reference_speaker_audio: Optional[Path] = None,
    hardware_profile: Optional[str] = None,
    mock_mode: bool = False,
) -> Dict[str, Any]:
    """Run the real self-iteration loop on a scenario and report the gain.

    Parameters
    ----------
    config_path : where to read/write ``agent_sop.json`` (use a temp path in tests).
    genre : genre label for the scenario (e.g. ``"仙侠"``).
    corrections : ≥3 :class:`UserCorrection` for the genre.
    held_out : list of ``{"speaker", "emotion"}`` paragraphs used to measure heuristic gain.
    llm_client : optional LLM callable; defaults to the deterministic role-aware one.
    audio_paths : optional list of synthesized audio files to score with real metrics.
    reference_texts : parallel list of expected texts for WER calculation.
    reference_speaker_audio : voice anchor for speaker similarity.
    hardware_profile : hardware tier for metric selection.
    mock_mode : when True, return deterministic mock scores (CI-hermetic).
    """
    sop = SOPConfig(config_path)
    collector = CorrectionCollector()
    for c in corrections:
        collector.add_correction(c)

    # Use real LLM client when SELF_ITERATION_MOCK=false, otherwise deterministic
    use_real = os.getenv("SELF_ITERATION_MOCK", "true").lower() in ("false", "0", "no")
    if use_real and llm_client is None:
        client = make_real_llm_client()
    else:
        client = llm_client or make_role_aware_llm_client(corrections)
    engine = ReflectionEngine(sop, llm_client=client)
    thread = SOPBackgroundThread(sop, collector, engine, check_interval=0.01)

    baseline_rules = sop.get_genre_rules(genre)
    baseline_overall = measure_quality(held_out, baseline_rules).overall

    # Optional: real audio quality baseline
    audio_baseline: Optional[AudioQualityReport] = None
    audio_after: Optional[AudioQualityReport] = None
    if audio_paths:
        scorer = AudioQualityScorer(
            hardware_profile=hardware_profile,
            mock_mode=mock_mode,
        )
        # Pair audio_paths with reference_texts if provided
        samples = []
        for i, ap in enumerate(audio_paths):
            rt = reference_texts[i] if reference_texts and i < len(reference_texts) else ""
            samples.append({"audio_path": ap, "reference_text": rt})
        audio_baseline = scorer.score_batch(samples, reference_speaker_audio=reference_speaker_audio)

    # Drive the REAL production loop (≥3 corrections -> reflect -> update).
    thread._check_and_reflect()

    after_rules = sop.get_genre_rules(genre)
    after_overall = measure_quality(held_out, after_rules).overall

    # Optional: real audio quality after rule update
    if audio_paths:
        scorer = AudioQualityScorer(
            hardware_profile=hardware_profile,
            mock_mode=mock_mode,
        )
        samples = []
        for i, ap in enumerate(audio_paths):
            rt = reference_texts[i] if reference_texts and i < len(reference_texts) else ""
            samples.append({"audio_path": ap, "reference_text": rt})
        audio_after = scorer.score_batch(samples, reference_speaker_audio=reference_speaker_audio)

    gain_pct = ((after_overall - baseline_overall) / baseline_overall * 100.0) if baseline_overall > 0 else (after_overall * 100.0)

    result: Dict[str, Any] = {
        "genre": genre,
        "corrections_fed": len(corrections),
        "sop_updated": after_rules != baseline_rules,
        "baseline_overall": round(baseline_overall, 4),
        "after_overall": round(after_overall, 4),
        "gain_pct": round(gain_pct, 2),
        "requires_human_review": True,
        "config_path": str(config_path),
    }

    if audio_baseline:
        result["audio_baseline"] = audio_baseline.to_dict()
    if audio_after:
        result["audio_after"] = audio_after.to_dict()
        if audio_baseline and audio_after.scored_count and audio_baseline.scored_count:
            audio_gain_pct = ((audio_after.mean_overall - audio_baseline.mean_overall) / audio_baseline.mean_overall * 100.0) if audio_baseline.mean_overall > 0 else 0.0
            result["audio_gain_pct"] = round(audio_gain_pct, 2)

    return result

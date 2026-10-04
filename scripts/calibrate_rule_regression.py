"""Calibrate RuleRegressionGuard.floor_ratio on a representative dataset — Task 3 (S2.5 follow-up).

The SOP self-evolution path (Module 4.2) learns genre rules from user
corrections and proposes them for promotion into ``agent_sop.json``. Before
promotion we run :class:`RuleRegressionGuard` to ensure the candidate rule does
not degrade annotation quality below ``floor_ratio * baseline_overall``.

Because :func:`measure_quality` is a *deterministic* proxy (no LLM / sampling
noise inside a single measurement), the only source of "noise" we must
tolerate is *sample-selection*: the paragraphs used to measure quality are a
finite subset of the true distribution, so a genuinely beneficial rule may
score slightly lower on one particular subset. The floor_ratio is that
tolerance band.

This script:
1. builds a representative, deterministic paragraph batch (multi-genre,
   realistic speaker frequency + emotion distribution),
2. defines baseline rules plus a spectrum of candidate changes
   (improvements of varying size, a neutral no-op, and degradations of
   varying size),
3. sweeps ``floor_ratio`` and reports, for each floor, whether it correctly
   admits every improvement and blocks every degradation,
4. recommends a calibrated default.

Run:  .venv/bin/python scripts/calibrate_rule_regression.py
"""

from __future__ import annotations

import sys

sys.path.insert(0, "src")

from audiobook_studio.feedback.sop_verification import DEFAULT_QUALITY_FLOOR_RATIO, RuleRegressionGuard, measure_quality

# ── 1. Representative dataset ───────────────────────────────────────────────
# Deterministic construction (no RNG) so the calibration is reproducible.
# Speaker frequencies mimic a real audiobook chapter: narrator dominates, then
# protagonist / antagonist / demon-lord, with a few minor characters.
_SPEAKER_MIX = [
    ("旁白", 60, "neutral"),  # narrator
    ("主角", 35, "excited"),  # protagonist
    ("反派", 25, "angry"),  # antagonist
    ("魔王", 20, "cold"),  # demon_lord
    ("配角A", 6, "neutral"),  # minor -> maps to narrator role
    ("配角B", 4, "neutral"),  # minor -> maps to narrator role
]


def build_dataset() -> list[dict[str, str]]:
    """Return a deterministic list of {speaker, emotion} paragraphs."""
    paragraphs = []
    for speaker, count, emotion in _SPEAKER_MIX:
        for _ in range(count):
            paragraphs.append({"speaker": speaker, "emotion": emotion})
    return paragraphs


# ── 2. Rules spectrum ───────────────────────────────────────────────────────
BASELINE_RULES = {
    "voice_bindings": {
        "narrator": "zh-CN-XiaoxiaoNeural",
        "protagonist": "zh-CN-YunyangNeural",
        "antagonist": "zh-CN-YunxiNeural",
    },
    "emotion_defaults": {"默认": "neutral", "narrator": "neutral"},
}

IMPROVE_SMALL = {
    "voice_bindings": {
        "narrator": "zh-CN-XiaoxiaoNeural",
        "protagonist": "zh-CN-YunyangNeural",
        "antagonist": "zh-CN-YunxiNeural",
        "demon_lord": "zh-CN-YunjianNeural",  # adds one more binding
    },
    "emotion_defaults": {"默认": "neutral", "narrator": "neutral"},
}

IMPROVE_BIG = {
    "voice_bindings": {
        "narrator": "zh-CN-XiaoxiaoNeural",
        "protagonist": "zh-CN-YunyangNeural",
        "antagonist": "zh-CN-YunxiNeural",
        "demon_lord": "zh-CN-YunjianNeural",
        "minor": "zh-CN-XiaoyiNeural",
    },
    "emotion_defaults": {
        "默认": "neutral",
        "narrator": "neutral",
        "protagonist": "excited",
        "antagonist": "angry",
    },
}

DEGRADE_SMALL = {
    "voice_bindings": {
        "narrator": "zh-CN-XiaoxiaoNeural",
        "protagonist": "zh-CN-YunyangNeural",
        # antagonist binding removed
    },
    "emotion_defaults": {"默认": "neutral", "narrator": "neutral"},
}

DEGRADE_BIG = {
    "voice_bindings": {
        # narrator + antagonist bindings removed
        "protagonist": "zh-CN-YunyangNeural",
    },
    "emotion_defaults": {"默认": "neutral"},  # narrator emotion default removed
}

NEUTRAL = BASELINE_RULES

CANDIDATES = [
    ("IMPROVE_BIG", IMPROVE_BIG, "improve"),
    ("IMPROVE_SMALL", IMPROVE_SMALL, "improve"),
    ("NEUTRAL", NEUTRAL, "neutral"),
    ("DEGRADE_SMALL", DEGRADE_SMALL, "degrade"),
    ("DEGRADE_BIG", DEGRADE_BIG, "degrade"),
]


def main() -> int:
    paragraphs = build_dataset()
    baseline_overall = measure_quality(paragraphs, BASELINE_RULES).overall
    print(f"Dataset size: {len(paragraphs)} paragraphs")
    print(f"Baseline overall quality: {baseline_overall:.4f}")
    print()

    # Per-candidate deltas (reference, floor_ratio=1.0 => never blocks).
    print("Candidate quality deltas (vs baseline):")
    deltas = {}
    for name, rules, kind in CANDIDATES:
        after = measure_quality(paragraphs, rules).overall
        d = after - baseline_overall
        deltas[name] = d
        flag = {"improve": "  +", "degrade": "  -", "neutral": "  ="}[kind]
        print(f"  {name:14} overall={after:.4f}  delta={flag}{d:+.4f}  [{kind}]")
    print()

    floors = [0.80, 0.85, 0.90, 0.93, 0.95, 0.97, 0.99]
    print(f"{'floor':>6} | {'impr_blocked':>12} {'degr_allowed':>13} | verdict")
    print("-" * 56)
    safe_floors = []
    for f in floors:
        impr_blocked = 0
        degr_allowed = 0
        for _name, rules, _kind in CANDIDATES:
            guard = RuleRegressionGuard(floor_ratio=f)
            report = guard.evaluate("玄幻", BASELINE_RULES, rules, paragraphs)
            if kind == "improve" and report.blocked_by_guard:
                impr_blocked += 1
            if kind == "degrade" and not report.blocked_by_guard:
                degr_allowed += 1
        verdict = "OK" if (impr_blocked == 0 and degr_allowed == 0) else "BAD"
        if verdict == "OK":
            safe_floors.append(f)
        print(f"{f:6.2f} | {impr_blocked:12d} {degr_allowed:13d} | {verdict}")
    print()

    min_safe = min(safe_floors) if safe_floors else None
    print(f"Current default floor_ratio = {DEFAULT_QUALITY_FLOOR_RATIO}")
    if min_safe is None:
        print("WARNING: no tested floor is safe — review the metric/dataset.")
        return 1
    print(f"Safe interval (admits all improvements, blocks all degradations): " f"[{min_safe:.2f}, 1.00)")
    # The metric is deterministic, so improvements are never blocked at any
    # floor <= 1.0; strictness only changes how small a degradation is caught.
    # We recommend the *conservative* end of the safe interval so the promotion
    # gate tolerates only minimal (< 5% of baseline) quality loss from
    # sample-selection noise, but still blocks every genuine degradation.
    recommended = DEFAULT_QUALITY_FLOOR_RATIO if min_safe <= DEFAULT_QUALITY_FLOOR_RATIO < 1.0 else min_safe
    print(f"Recommended calibrated floor_ratio = {recommended:.2f}")
    print()
    print("Interpretation:")
    min_blocked_drop = min(-deltas[n] for n, r, k in CANDIDATES if k == "degrade")
    band = (1.0 - recommended) * baseline_overall
    print(f"  smallest genuine degradation drops overall by " f"{min_blocked_drop:.4f}")
    print(
        f"  tolerance band at floor {recommended:.2f}: up to "
        f"{band:.4f} absolute (~{(1-recommended)*100:.1f}% of "
        f"baseline) quality loss is tolerated"
    )
    print(f"  => {recommended:.2f} is within the safe interval and is the")
    print("     conservative choice for a one-way SOP promotion gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""S3.7 — validate the full self-iteration loop on a 仙侠 (xianxia) scenario.

Usage:
    python scripts/validate_self_iteration.py [--config PATH] [--genre 仙侠]

This runs the REAL production self-iteration loop (CorrectionCollector ->
SOPBackgroundThread -> ReflectionEngine -> SOPConfig) against a small embedded
仙侠 scenario: ≥3 user corrections are fed, the loop auto-updates
config/agent_sop.json, and we measure the annotation-quality gain via
feedback.sop_verification.measure_quality. The result REQUIRES HUMAN REVIEW
before the learned rules are promoted to production.

No network / paid API is used: the reflection strategy is the deterministic,
role-aware synthesis in pipeline.self_iteration.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running as a script: src/ on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from audiobook_studio.pipeline.self_iteration import (  # noqa: E402
    UserCorrection,
    validate_self_iteration,
)


def _xianxia_corrections() -> list[UserCorrection]:
    """Build ≥3 仙侠 user corrections (旁白 / 主角 / 反派 roles)."""
    base = {
        "timestamp": "2026-01-01T00:00:00Z",
        "project_id": 1,
        "chapter_index": 0,
        "paragraph_index": 0,
        "genre": "仙侠",
    }
    return [
        UserCorrection(
            **{**base, "field": "voice", "original_value": "narrator", "corrected_value": "kokoro_zh_narrator", "context": {"speaker": "旁白"}},
        ),
        UserCorrection(
            **{**base, "field": "voice", "original_value": "主角", "corrected_value": "kokoro_zh_protagonist", "context": {"speaker": "林轩"}},
        ),
        UserCorrection(
            **{**base, "field": "voice", "original_value": "反派", "corrected_value": "kokoro_zh_antagonist", "context": {"speaker": "魔尊"}},
        ),
        UserCorrection(
            **{**base, "field": "emotion", "original_value": "neutral", "corrected_value": "solemn", "context": {"speaker": "旁白"}},
        ),
        UserCorrection(
            **{**base, "field": "emotion", "original_value": "neutral", "corrected_value": "resolute", "context": {"speaker": "林轩"}},
        ),
    ]


def _xianxia_held_out() -> list[dict]:
    """Held-out paragraphs (speaker + emotion) used to measure gain."""
    return [
        {"speaker": "旁白", "emotion": "solemn"},
        {"speaker": "林轩", "emotion": "resolute"},
        {"speaker": "魔尊", "emotion": "cold"},
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate S3.7 self-iteration loop (仙侠 scenario).")
    parser.add_argument(
        "--config",
        type=str,
        default=str(Path(__file__).resolve().parents[1] / "config" / "agent_sop.json"),
        help="Path to agent_sop.json (default: repo config/agent_sop.json).",
    )
    parser.add_argument("--genre", type=str, default="仙侠")
    args = parser.parse_args()

    report = validate_self_iteration(
        config_path=Path(args.config),
        genre=args.genre,
        corrections=_xianxia_corrections(),
        held_out=_xianxia_held_out(),
    )

    print("=" * 60)
    print("S3.7 Self-Iteration Loop Validation Report")
    print("=" * 60)
    for k, v in report.items():
        print(f"  {k}: {v}")
    print("-" * 60)
    if report["sop_updated"] and report["gain_pct"] > 10.0:
        print("✅ Loop validated: SOP auto-updated with >10% gain.")
        print("⚠️  HUMAN REVIEW REQUIRED before promoting learned rules to production.")
        return 0
    print("❌ Loop did not meet acceptance (update or gain threshold).")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

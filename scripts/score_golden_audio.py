#!/usr/bin/env python3
"""Score the golden dataset with real audio quality metrics — P0-C1 evidence.

Usage:
    python scripts/score_golden_audio.py [--mock] [--output storage/golden_audio_scores.json]

Runs DNSMOS, UTMOS, ASR WER, and Speaker Similarity on each golden WAV.
Real mode downloads models on first run (cached to ~/.cache/audiobook_studio/models/).
Mock mode returns deterministic values for CI.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# Ensure src on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from audiobook_studio.quality.audio_quality import AudioQualityScorer, load_quality_thresholds_default

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GOLDEN_DIR = Path("tests/golden/v04_multilingual")
OUTPUT_DEFAULT = Path("storage/golden_audio_scores.json")


def load_golden_cases() -> list[dict]:
    """Load the golden dataset test cases."""
    cases_file = GOLDEN_DIR / "test_cases.json"
    if not cases_file.exists():
        raise FileNotFoundError(f"Golden test cases not found: {cases_file}")
    import json as _json

    with open(cases_file, "r", encoding="utf-8") as f:
        data = _json.load(f)
    return data.get("test_cases", [])


def build_samples() -> list[dict]:
    """Build sample dicts for the scorer from golden test cases."""
    cases = load_golden_cases()
    samples = []
    for c in cases:
        ref_audio = c.get("reference_audio")
        if not ref_audio:
            continue
        path = Path(ref_audio)
        if not path.exists():
            logger.warning(f"Missing golden WAV: {path}")
            continue
        sample = {
            "audio_path": str(path),
            "reference_text": c.get("target_text", ""),
        }
        samples.append(sample)
    return samples


def main() -> int:
    parser = argparse.ArgumentParser(description="Score golden audio with real metrics (P0-C1)")
    parser.add_argument("--mock", action="store_true", help="Use deterministic mock scores (CI)")
    parser.add_argument("--output", type=Path, default=OUTPUT_DEFAULT, help="Output JSON path")
    parser.add_argument("--hw-profile", default="cloud_hybrid", help="Hardware profile for metric selection")
    args = parser.parse_args()

    samples = build_samples()
    if not samples:
        logger.error("No valid golden samples found")
        return 1

    logger.info(f"Scoring {len(samples)} golden WAVs (mock={args.mock})")

    scorer = AudioQualityScorer(
        thresholds=load_quality_thresholds_default(),
        hardware_profile=args.hw_profile,
        mock_mode=args.mock,
    )

    report = scorer.score_batch(samples)

    # Print summary
    logger.info(f"Scored {report.scored_count}/{len(samples)} samples")
    if report.scored_count:
        logger.info(f"Mean overall: {report.mean_overall:.3f}")
        logger.info(f"  UTMOS: {report.mean_utmos:.2f}" if report.mean_utmos else "  UTMOS: N/A")
        logger.info(f"  DNSMOS: {report.mean_dnsmos:.2f}" if report.mean_dnsmos else "  DNSMOS: N/A")
        logger.info(f"  WER: {report.mean_wer:.2%}" if report.mean_wer else "  WER: N/A")
        logger.info(f"  SpeakerSim: {report.mean_speaker_sim:.3f}" if report.mean_speaker_sim else "  SpeakerSim: N/A")

    # Write output
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2)
    logger.info(f"Wrote report to {args.output}")

    # Print per-sample for verification
    for s in report.samples:
        if s.success:
            logger.info(f"  {Path(s.audio_path).name}: overall={s.overall:.3f} utmos={s.utmos} dnsmos={s.dnsmos} wer={s.wer} sim={s.speaker_sim}")
        else:
            logger.warning(f"  {Path(s.audio_path).name}: FAILED - {s.error}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
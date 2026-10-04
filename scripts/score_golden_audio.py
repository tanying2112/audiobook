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
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# Ensure src on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from audiobook_studio.quality.audio_quality import AudioQualityScorer, load_quality_thresholds_default

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

GOLDEN_DIR = Path("tests/golden/v04_multilingual")
OUTPUT_DEFAULT = Path("storage/golden_audio_scores.json")


def load_golden_cases() -> list[dict[str, Any]]:
    """Load the golden dataset test cases."""
    cases_file = GOLDEN_DIR / "test_cases.json"
    if not cases_file.exists():
        raise FileNotFoundError(f"Golden test cases not found: {cases_file}")
    import json as _json

    with open(cases_file, "r", encoding="utf-8") as f:
        data = _json.load(f)
    cases: list[dict[str, Any]] = data.get("test_cases", [])
    return cases


_SPEAKER_KEY_RE = re.compile(r"^ref_(?P<lang>[a-z]+)_(?P<gender>[a-z]+)")


def _speaker_key(path: Path) -> str:
    """Derive a same-speaker grouping key from a reference filename.

    e.g. ref_zh_female_001 -> 'zh_female', ref_en_male_001 -> 'en_male'.
    Files sharing a key are treated as recordings of the same speaker, so we
    can compute an *intra-speaker* similarity (voice consistency) even though the
    golden set ships reference audio only (no clone outputs).
    """
    m = _SPEAKER_KEY_RE.match(path.stem)
    return m.group(0) if m else path.stem


def build_samples() -> list[dict[str, Any]]:
    """Build sample dicts for the scorer from golden test cases.

    Reference audio only is available (no generated clones), so:
    * speaker similarity = intra-speaker consistency vs a *different* recording
      of the same speaker (a real, computable ECAPA-TDNN cosine).
    * WER is computed only when the reference audio language matches the target
      text language (mono-lingual cases). Cross-lingual cases compare a Chinese
      reference utterance against a foreign target sentence, which is not a valid
      clone-intelligibility measurement, so WER is honestly skipped (None).
    """
    cases = load_golden_cases()
    # Group valid reference files by speaker for intra-speaker anchoring.
    by_speaker: Dict[str, List[Path]] = {}
    valid_cases: list[dict[str, Any]] = []
    for c in cases:
        ref_audio = c.get("reference_audio")
        if not ref_audio:
            continue
        path = Path(ref_audio)
        if not path.exists():
            logger.warning(f"Missing golden WAV: {path}")
            continue
        valid_cases.append(c)
        by_speaker.setdefault(_speaker_key(path), []).append(path)

    samples = []
    for c in valid_cases:
        path = Path(c["reference_audio"])
        ref_lang = c.get("reference_language") or c.get("language")
        tgt_lang = c.get("target_language") or c.get("language")
        target_text = c.get("target_text", "") or c.get("text", "")

        # WER is only meaningful when the reference utterance is in the same
        # language as the target text; otherwise skip honestly (None).
        if ref_lang and tgt_lang and ref_lang != tgt_lang:
            reference_text = ""
        else:
            reference_text = target_text

        # Intra-speaker anchor: a different recording of the same speaker.
        anchor = None
        siblings = [p for p in by_speaker.get(_speaker_key(path), []) if p != path]
        if siblings:
            anchor = siblings[0]

        sample = {
            "audio_path": str(path),
            "reference_text": reference_text,
            "reference_speaker_audio": str(anchor) if anchor else None,
            "language": ref_lang or tgt_lang,
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

    thresholds = load_quality_thresholds_default()
    # Use the multilingual-aware ASR backend: SenseVoice for non-Chinese audio,
    # Paraformer-ZH for Chinese. (Cross-lingual reference/target pairs still skip
    # WER because the reference utterance is in a different language.)
    thresholds.setdefault("quality_check", {})["asr_model"] = "auto"

    scorer = AudioQualityScorer(
        thresholds=thresholds,
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

    # Write output (with methodology notes so the numbers are interpretable).
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out = report.to_dict()
    out["methodology"] = {
        "speaker_similarity": "intra-speaker ECAPA-TDNN cosine vs a different recording of the same speaker (golden ships reference audio only; no clone outputs)",
        "wer": "WER = ASR(reference_audio) vs target_text; computed for mono-lingual cases, honestly skipped (None) for cross-lingual reference/target language mismatch",
        "dnsmos": "Microsoft P.835 ONNX (sig/bak/ovr); UTMOS via UTokyo-SaruLab ONNX",
    }
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    logger.info(f"Wrote report to {args.output}")

    # Print per-sample for verification
    for s in report.samples:
        if s.success:
            logger.info(
                f"  {Path(s.audio_path).name}: overall={s.overall:.3f} utmos={s.utmos} dnsmos={s.dnsmos} wer={s.wer} sim={s.speaker_sim}"
            )
        else:
            logger.warning(f"  {Path(s.audio_path).name}: FAILED - {s.error}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

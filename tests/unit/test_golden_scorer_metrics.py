"""Unit tests for the golden-benchmark metric fixes (P0-C1).

These are hermetic: they exercise the code paths that were buggy
(``sensevoice_small`` alias, 16 kHz resampling, empty-hypothesis honesty,
multilingual auto backend selection, DNSMOS sig/bak/ovr surfacing, and the
golden-sample builder's intra-speaker anchor / cross-lingual WER skip) without
downloading any ASR/TTS models.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

import pytest

from audiobook_studio.quality.audio_quality import AudioQualityScorer
from audiobook_studio.quality.metrics import ASRBackend, ASRResult, FunASRBackend

# ── FunASR alias correctness ──────────────────────────────────────────────────


def test_sensevoice_small_alias_resolves_to_camelcase_model():
    """The previous alias ``iic/sensevoice_small`` 404'd on ModelScope.

    The correct id is ``iic/SenseVoiceSmall`` (registered key SenseVoiceSmall).
    """
    backend = FunASRBackend(model_name="sensevoice_small")
    assert backend.model_name == "iic/SenseVoiceSmall"
    assert backend.original_model_name == "sensevoice_small"


def test_paraformer_zh_alias_unchanged():
    backend = FunASRBackend(model_name="paraformer-zh")
    assert backend.model_name == "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"


def test_sensevoice_large_alias_unchanged():
    backend = FunASRBackend(model_name="sensevoice_large")
    assert backend.model_name == "iic/sensevoice_large"


# ── Empty-hypothesis honesty ──────────────────────────────────────────────────


class _EmptyASRBackend(ASRBackend):
    """Fake backend that "succeeds" but returns an empty transcript."""

    def transcribe(self, audio_path: Path) -> ASRResult:
        return ASRResult(
            text="",
            words=[],
            language="unknown",
            confidence=0.0,
            duration_ms=0,
            success=True,
        )

    def get_name(self) -> str:
        return "empty"


def test_asr_wer_empty_hypothesis_is_honest_failure():
    """An empty hypothesis must NOT be reported as wer=1.0 success=True.

    Previously ``compute`` returned ``wer=1.0, success=True`` for an empty
    hypothesis, which the scorer counted as a real measurement. Now it fails
    honestly so WER is recorded as unavailable (None).
    """
    from audiobook_studio.quality.metrics import ASRWerMetric

    metric = ASRWerMetric(backend="funasr", model_name="paraformer-zh")
    metric._backend = _EmptyASRBackend()
    result = metric.compute(Path("/tmp/does_not_matter.wav"), "some reference text")
    assert result.success is False
    assert result.error is not None
    # The scorer maps success=False -> wer=None (not a fabricated 1.0 measurement).


# ── Multilingual auto backend selection ───────────────────────────────────────


def test_asr_wer_auto_selects_multilingual_for_non_zh():
    from audiobook_studio.quality.metrics import ASRWerMetric

    metric = ASRWerMetric(model_name="auto", mock_mode=True)
    zh_backend = metric._resolve_backend("zh")
    en_backend = metric._resolve_backend("en")
    assert zh_backend.model_name == "iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
    assert en_backend.model_name == "iic/SenseVoiceSmall"
    # Same (cached) backend instance returned for the same language.
    assert metric._resolve_backend("ja") is en_backend


def test_asr_wer_explicit_model_not_overridden_by_auto():
    from audiobook_studio.quality.metrics import ASRWerMetric

    metric = ASRWerMetric(backend="funasr", model_name="paraformer-zh")
    assert metric._backend is not None
    assert metric._resolve_backend("en") is metric._backend


# ── DNSMOS sig/bak/ovr surfacing ──────────────────────────────────────────────


def test_scorer_mock_sample_includes_dnsmos_breakdown():
    scorer = AudioQualityScorer(mock_mode=True)
    # An existing path keeps mock_mode on the deterministic mock branch.
    sample = scorer.score(Path("tests/golden/v04_multilingual/ref_zh_female_001.wav"))
    assert sample.dnsmos == 4.2
    assert sample.dnsmos_sig == 4.2
    assert sample.dnsmos_bak == 4.2
    assert sample.dnsmos_ovr == 4.2
    d = sample.to_dict()
    assert {"dnsmos_sig", "dnsmos_bak", "dnsmos_ovr"} <= d.keys()


def test_scorer_score_batch_forwards_language_and_anchor():
    scorer = AudioQualityScorer(mock_mode=True)
    samples: List[Dict[str, Any]] = [
        {
            "audio_path": "tests/golden/v04_multilingual/ref_zh_female_001.wav",
            "reference_text": "ref",
            "reference_speaker_audio": "tests/golden/v04_multilingual/ref_zh_female_3s.wav",
            "language": "zh",
        }
    ]
    report = scorer.score_batch(samples)
    assert report.scored_count == 1
    assert report.samples[0].speaker_sim == 0.90


# ── Golden sample builder: intra-speaker anchor + cross-lingual WER skip ──────


def test_build_samples_skips_crosslingual_wer_and_anchors_intraspeaker():
    """Import the script module and exercise build_samples against the committed
    golden dataset (reference WAVs exist; no model download needed)."""
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "score_golden_audio",
        str(Path(__file__).resolve().parents[2] / "scripts" / "score_golden_audio.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    samples = mod.build_samples()
    # 10 cases carry a reference_audio (7 cross-lingual + 3 mono-lingual zh).
    assert len(samples) == 10

    # Cross-lingual cases: WER reference_text must be empty (honestly skipped).
    # The same file appears for multiple cases; at least one must be cross-lingual.
    cross_empty = any(
        s["reference_text"] == "" and Path(s["audio_path"]).name == "ref_zh_female_001.wav" for s in samples
    )
    assert cross_empty, "cross-lingual reference/target pair should skip WER (empty reference_text)"

    # Mono-lingual zh case keeps its target_text for WER.
    mono = [s for s in samples if Path(s["audio_path"]).name == "ref_zh_female_3s.wav"]
    assert mono, "zero_shot_3s_ref_001 should produce a sample"
    assert mono[0]["reference_text"] != "", "mono-lingual zh case should keep target_text for WER"

    # Intra-speaker anchor: ref_zh_female_001 should anchor against a sibling
    # same-speaker file (ref_zh_female_3s), not itself.
    anchored = [
        s for s in samples if Path(s["audio_path"]).name == "ref_zh_female_001.wav" and s.get("reference_speaker_audio")
    ]
    assert anchored, "ref_zh_female_001 should get an intra-speaker anchor"
    assert Path(anchored[0]["reference_speaker_audio"]).name != "ref_zh_female_001.wav"

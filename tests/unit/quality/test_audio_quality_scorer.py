"""Tests for AudioQualityScorer — P0-C1 real audio quality scoring layer.

Covers:
- Mock-mode deterministic scoring (CI-hermetic, no model downloads)
- Fusion math (fuse_audio_scores)
- Honest insufficient-data handling (no fabricated values)
- Batch aggregation / report
- validate_self_iteration wiring with real audio (mock-mode scorer)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.audiobook_studio.quality.audio_quality import (
    AudioQualitySample,
    AudioQualityScorer,
    AudioQualityReport,
    fuse_audio_scores,
)
from src.audiobook_studio.pipeline.self_iteration import UserCorrection, validate_self_iteration

GOLDEN_DIR = Path(__file__).parent.parent.parent / "golden" / "v04_multilingual"
REF_WAV = GOLDEN_DIR / "ref_zh_female_001.wav"


def test_fuse_audio_scores_full():
    # utmos=4.0->0.75, dnsmos=4.2->0.80, wer=0.02->0.80, sim=0.9
    overall = fuse_audio_scores(4.0, 4.2, 0.02, 0.90)
    assert 0.0 <= overall <= 1.0
    # Weighted: (0.35*0.75 + 0.25*0.80 + 0.20*0.80 + 0.20*0.90)/1.0
    expected = (0.35 * 0.75 + 0.25 * 0.80 + 0.20 * 0.80 + 0.20 * 0.90)
    assert overall == pytest.approx(expected, abs=1e-6)


def test_fuse_audio_scores_partial():
    # Only one metric available -> its normalized value
    assert fuse_audio_scores(None, 4.2, None, None) == pytest.approx(0.80, abs=1e-6)


def test_fuse_audio_scores_none():
    assert fuse_audio_scores(None, None, None, None) == 0.0


def test_scorer_mock_deterministic(tmp_path: Path):
    scorer = AudioQualityScorer(mock_mode=True)
    sample = scorer.score(REF_WAV)
    assert sample.success is True
    assert sample.utmos == 4.0
    assert sample.dnsmos == 4.2
    assert sample.available_metrics == 4
    assert sample.overall > 0.5

    # Deterministic: scoring again gives identical values
    sample2 = scorer.score(REF_WAV)
    assert sample2.to_dict() == sample.to_dict()


def test_scorer_missing_file():
    scorer = AudioQualityScorer(mock_mode=True)
    sample = scorer.score(Path("/nonexistent/audio.wav"))
    assert sample.success is False
    assert "not found" in (sample.error or "")


def test_scorer_real_suite_reuses_suite():
    """Mock-mode path should not require a real suite."""
    scorer = AudioQualityScorer(mock_mode=True)
    assert scorer._suite is None  # no real suite needed in mock mode


def test_score_batch_report(tmp_path: Path):
    scorer = AudioQualityScorer(mock_mode=True)
    samples = [
        {"audio_path": str(REF_WAV), "reference_text": "测试"},
        {"audio_path": str(REF_WAV), "reference_text": "test"},
    ]
    report = scorer.score_batch(samples)
    assert isinstance(report, AudioQualityReport)
    assert len(report.samples) == 2
    assert report.scored_count == 2
    assert report.mean_overall > 0.5


def test_validate_self_iteration_with_audio(tmp_path: Path):
    """The self-iteration loop accepts real audio and reports audio quality."""
    config = tmp_path / "agent_sop.json"
    corrections = [
        UserCorrection(
            timestamp="2026-01-01T00:00:00Z",
            project_id=1,
            chapter_index=0,
            paragraph_index=0,
            field="voice",
            original_value="x",
            corrected_value="kokoro_zh_narrator",
            genre="仙侠",
            context={"speaker": "旁白"},
        ),
        UserCorrection(
            timestamp="2026-01-01T00:00:00Z",
            project_id=1,
            chapter_index=0,
            paragraph_index=0,
            field="voice",
            original_value="x",
            corrected_value="kokoro_zh_protagonist",
            genre="仙侠",
            context={"speaker": "林轩"},
        ),
        UserCorrection(
            timestamp="2026-01-01T00:00:00Z",
            project_id=1,
            chapter_index=0,
            paragraph_index=0,
            field="voice",
            original_value="x",
            corrected_value="kokoro_zh_antagonist",
            genre="仙侠",
            context={"speaker": "魔尊"},
        ),
    ]
    held_out = [{"speaker": "旁白", "emotion": "solemn"}, {"speaker": "林轩", "emotion": "resolute"}]

    report = validate_self_iteration(
        config_path=config,
        genre="仙侠",
        corrections=corrections,
        held_out=held_out,
        audio_paths=[REF_WAV],
        reference_texts=["测试"],
        mock_mode=True,  # CI-hermetic
    )
    assert report["sop_updated"] is True
    assert report["gain_pct"] > 10.0
    assert "audio_baseline" in report
    assert report["audio_baseline"]["scored_count"] >= 1
    assert report["audio_baseline"]["mean_overall"] > 0.0
    assert "audio_after" in report


def test_validate_self_iteration_backward_compat(tmp_path: Path):
    """Without audio_paths, the report has no audio keys (backward compatible)."""
    config = tmp_path / "agent_sop.json"
    corrections = [
        UserCorrection(
            timestamp="2026-01-01T00:00:00Z", project_id=1, chapter_index=0, paragraph_index=0,
            field="voice", original_value="x", corrected_value="kokoro_zh_narrator",
            genre="仙侠", context={"speaker": "旁白"},
        ),
        UserCorrection(
            timestamp="2026-01-01T00:00:00Z", project_id=1, chapter_index=0, paragraph_index=0,
            field="voice", original_value="x", corrected_value="kokoro_zh_protagonist",
            genre="仙侠", context={"speaker": "林轩"},
        ),
        UserCorrection(
            timestamp="2026-01-01T00:00:00Z", project_id=1, chapter_index=0, paragraph_index=0,
            field="voice", original_value="x", corrected_value="kokoro_zh_antagonist",
            genre="仙侠", context={"speaker": "魔尊"},
        ),
    ]
    report = validate_self_iteration(
        config_path=config,
        genre="仙侠",
        corrections=corrections,
        held_out=[{"speaker": "旁白", "emotion": "solemn"}],
    )
    assert "audio_baseline" not in report
    assert "audio_after" not in report
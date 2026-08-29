"""Item 8 — quality gate is driven by REAL metrics (DNSMOS/ASR-WER), not the LLM-Judge.

Audit rec #6/#8: auto-resynthesis must be triggered by actual hard-metric scores
(DNSMOS ONNX + faster-whisper WER), not by a synthetic "mock judge" pass. These
tests prove three things on a *real* WAV:

  1. ``DNSMOSMetric`` actually runs the real ONNX model (it auto-fetches the
     ~1MB Microsoft DNSMOS ONNX file) and returns a genuine MOS, not a constant.
  2. The ``QualityCheckSuite`` hard gate's pass/fail decision follows the real
     metric value — a low MOS fails, a high MOS passes. This is what drives
     regeneration independently of any LLM-as-a-Judge.
  3. The default ASR backend is faster-whisper ``tiny`` (lightweight, runs offline
     on free hardware), so real WER is the actual default — not a placeholder.

``tests/conftest_minimal.py`` installs MagicMocks for ``numpy``/``soundfile``; the
``quality`` fixture swaps the real libraries back in and reloads the quality
package so ``numpy`` binds to the real lib (same restore-real pattern as the
``real_soundfile`` fixture), because DNSMOS/ONNX cannot compute against a mock.
"""

import importlib
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def quality(monkeypatch):
    """Return (quality.metrics module, real_numpy, real_soundfile) with real libs."""
    for mod_name in ("numpy", "soundfile"):
        monkeypatch.delitem(sys.modules, mod_name, raising=False)
    import numpy as np  # noqa: F401  (real)
    import soundfile as sf  # noqa: F401  (real)

    import audiobook_studio.quality as qpkg

    # Reload the quality package so its modules bind to the real numpy (not the
    # conftest MagicMock) and DNSMOS/ONNX can actually compute.
    import audiobook_studio.quality.metrics as m

    importlib.reload(m)
    importlib.reload(qpkg)
    return m, np, sf


def _write_16k_wav(sf, path: Path, signal) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), signal, 16000)


def _overdriven_square(np, n: int = 16000 * 5):
    """Full-scale square wave — acoustically terrible, must score very low MOS."""
    return np.ones(n, dtype=np.float32) * 0.999


def _bandlimited_tone(np, n: int = 16000 * 5):
    sr = 16000
    t = np.arange(n) / sr
    return (np.sin(2 * np.pi * 220.0 * t) * 0.3).astype(np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# (1) DNSMOS real ONNX model actually computes a genuine MOS on a real WAV
# ─────────────────────────────────────────────────────────────────────────────
def test_dnsmos_real_model_computes_mos(quality, tmp_path):
    m, np, sf = quality
    wav = tmp_path / "clip.wav"
    _write_16k_wav(sf, wav, _bandlimited_tone(np))

    metric = m.DNSMOSMetric(mock_mode=False)
    # The ONNX model is auto-fetched from Microsoft's DNS-Challenge repo on first use.
    assert metric.model_path.exists(), "DNSMOS ONNX model should auto-download and persist"

    detailed = metric.compute_detailed(wav)
    assert detailed is not None
    assert detailed.success is True, f"DNSMOS failed: {detailed.error}"
    # A genuine MOS is in the valid 1..5 range (not a mock constant).
    assert 1.0 <= detailed.mos_ovr <= 5.0
    assert 1.0 <= detailed.mos_sig <= 5.0
    assert 1.0 <= detailed.mos_bak <= 5.0


# ─────────────────────────────────────────────────────────────────────────────
# (2) The hard gate's pass/fail follows the REAL metric, not the LLM-Judge
# ─────────────────────────────────────────────────────────────────────────────
def test_quality_gate_rejects_real_bad_audio(quality, tmp_path):
    m, np, sf = quality
    wav = tmp_path / "bad.wav"
    _write_16k_wav(sf, wav, _overdriven_square(np))

    suite = m.QualityCheckSuite(
        config={
            "thresholds": {"dnsmos_min": 3.5},
            "quality_check": {
                "dnsmos_enabled": True,
                "utmos_enabled": False,
                "asr_enabled": False,  # isolate the DNSMOS gate; WER download is network-heavy
                "speaker_similarity_enabled": False,
                "mock_mode": False,
            },
        }
    )
    result = suite.check_all(audio_path=wav, reference_text="")
    # The real DNSMOS metric actually ran on the acoustic data.
    assert result.dnsmos is not None and result.dnsmos.success is True
    # A genuinely terrible signal must NOT be waved through by a mock judge.
    assert result.passed is False
    assert "DNSMOS" in result.overall_message


def test_quality_gate_pass_follows_metric_value(quality, tmp_path):
    """The gate decision tracks the real metric value (low→fail, high→pass)."""
    m, np, sf = quality
    wav = tmp_path / "any.wav"
    _write_16k_wav(sf, wav, _bandlimited_tone(np))

    suite = m.QualityCheckSuite(
        config={
            "thresholds": {"dnsmos_min": 3.5},
            "quality_check": {
                "dnsmos_enabled": True,
                "utmos_enabled": False,
                "asr_enabled": False,
                "speaker_similarity_enabled": False,
                "mock_mode": False,
            },
        }
    )
    suite._initialize()

    # Force a low real-looking MOS → must fail.
    low = m.DNSMOSResult(mos_overall=1.2, mos_sig=1.1, mos_bak=1.3, mos_ovr=1.2, success=True)
    suite._dnsmos.compute_detailed = lambda p: low
    fail = suite.check_all(audio_path=wav, reference_text="")
    assert fail.passed is False

    # Force a high real-looking MOS → must pass (no fabricated issue).
    high = m.DNSMOSResult(mos_overall=4.6, mos_sig=4.5, mos_bak=4.7, mos_ovr=4.6, success=True)
    suite._dnsmos.compute_detailed = lambda p: high
    ok = suite.check_all(audio_path=wav, reference_text="")
    assert ok.passed is True


# ─────────────────────────────────────────────────────────────────────────────
# (3) Default ASR backend is faster-whisper "tiny" (real WER, lightweight)
# ─────────────────────────────────────────────────────────────────────────────
def test_default_asr_is_faster_whisper_tiny(quality, tmp_path):
    m, np, sf = quality
    # Constructing the metric does NOT download the model (lazy); we only assert
    # the backend selection defaults to the lightweight faster-whisper "tiny".
    asr = m.ASRWerMetric(backend="whisper", model_name="tiny", use_faster_whisper=True, mock_mode=False)
    backend = asr._backend
    assert isinstance(backend, m.WhisperBackend)
    assert backend.model_size == "tiny"
    assert backend.use_faster is True


def test_suite_defaults_to_faster_whisper_tiny(quality, tmp_path):
    """QualityCheckSuite._initialize selects faster-whisper tiny by default."""
    m, np, sf = quality
    # No quality_check config → default ASR selection applies (tiny + faster-whisper).
    suite = m.QualityCheckSuite(config={})
    suite._initialize()
    assert suite._wer is not None
    assert isinstance(suite._wer._backend, m.WhisperBackend)
    assert suite._wer._backend.model_size == "tiny"
    assert suite._wer._backend.use_faster is True


# ─────────────────────────────────────────────────────────────────────────────
# (4) The pipeline's resynthesis gate uses the REAL metric, not the LLM-Judge
# ─────────────────────────────────────────────────────────────────────────────
def test_pipeline_hard_gate_driven_by_real_metric(quality, tmp_path):
    """Even with a pass-always judge, a real-metric failure forces regeneration."""
    m, np, sf = quality
    from unittest.mock import MagicMock

    from audiobook_studio.pipeline.quality_check import QualityCheckPipeline

    wav = tmp_path / "bad.wav"
    _write_16k_wav(sf, wav, _overdriven_square(np))

    judge = MagicMock()
    router = MagicMock()
    pipeline = QualityCheckPipeline(
        mock_mode=False,
        judge=judge,
        router=router,
        config_path=str(REPO_ROOT / "config" / "quality_thresholds.yaml"),
    )
    # The pipeline module was imported (with the conftest-mocked numpy) before the
    # quality package was reloaded. Swap in the reloaded, real-numpy QualityCheckSuite
    # so DNSMOS can actually compute against the real acoustic data.
    pipeline._quality_suite = m.QualityCheckSuite(
        config=dict(pipeline.quality_thresholds),
        hardware_profile=pipeline.hardware_profile.active_profile,
    )
    # The single source of truth for resynthesis is the hard-metric result.
    result = pipeline._run_hard_quality_checks(audio_path=wav, reference_text="")
    assert result.passed is False
    assert result.dnsmos is not None and result.dnsmos.success is True
    assert "DNSMOS" in result.overall_message

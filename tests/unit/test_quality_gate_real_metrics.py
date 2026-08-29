"""Item 6: auto-resynthesis must be driven by REAL metrics, not only LLM-Judge.

The quality gate fuses real acoustic metrics (DNSMOS ONNX + faster-whisper WER)
into both the judge prompt and the ``needs_regeneration`` decision. These tests
prove the wiring feeds real DNSMOS/WER scores into the gate and that a failing
real metric (not the LLM judge) can trigger re-synthesis.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline
from src.audiobook_studio.quality.metrics import DNSMOSResult, QualityCheckResult, WERResult
from src.audiobook_studio.schemas import ParagraphAnnotation, QualityJudgment
from src.audiobook_studio.schemas.tts_routing import TtsRoutingDecision as TtsRoutingDecisionSchema


# Some other unit tests in the suite leak MagicMocks into sys.modules (e.g. for
# funasr / numba / numpy). When a later test imports those modules for real, the
# leaked Mock breaks their package __init__ (e.g. ``Mock.__version__``).
# Neutralize any leaked mocks so this file imports the genuine (or absent)
# modules — real modules are never MagicMock instances, so this is safe.
@pytest.fixture(autouse=True)
def _neutralize_leaked_module_mocks():
    for name in [k for k, v in list(sys.modules.items()) if isinstance(v, MagicMock)]:
        del sys.modules[name]
    yield


def _annotation():
    return ParagraphAnnotation(
        paragraph_index=0,
        speaker_canonical_name="旁白",
        is_dialogue=False,
        emotion="neutral",
        emotion_intensity=0.5,
        speech_rate=1.0,
        pitch_shift_semitones=0,
        pause_before_ms=300,
        pause_after_ms=500,
        confidence=0.9,
        difficulty="B",
        needs_sfx=False,
        sfx_tags=[],
    )


def _routing():
    return TtsRoutingDecisionSchema(
        segment_id="book_001_ch1_p0",
        engine_choice="kokoro",
        voice_id="kokoro_narrator",
        prosody_overrides=None,
        fallback_engine="edge",
        reasoning="test",
        estimated_cost_usd=0.001,
        estimated_duration_ms=5000,
    )


def _pipeline_with_hard_result(dnsmos_ovr: float, wer: float, passed: bool):
    """Build a non-mock pipeline whose suite returns the given real metrics."""
    mock_judge = MagicMock()
    mock_judge.judge_quality.return_value = QualityJudgment(
        segment_id="book_001_ch1_p0",
        speaker_clarity=0.9,
        emotion_match=0.85,
        prosody_naturalness=0.9,
        text_audio_alignment=0.95,
        overall_score=0.9,
        issues=[],
        fix_suggestions=[],
        needs_regeneration=False,
    )
    pipeline = QualityCheckPipeline(judge=mock_judge, mock_mode=False)
    # Pretend the lightweight deps (onnxruntime + faster-whisper) are installed.
    pipeline._available_features = {
        "ffmpeg": True,
        "dnsmos": True,
        "asr": True,
        "speaker_sim": False,
    }
    hard = QualityCheckResult(
        passed=passed,
        dnsmos=DNSMOSResult(
            mos_overall=dnsmos_ovr,
            mos_sig=dnsmos_ovr,
            mos_bak=dnsmos_ovr,
            mos_ovr=dnsmos_ovr,
            success=True,
        ),
        wer=WERResult(
            wer=wer,
            cer=wer,
            insertions=0,
            deletions=0,
            substitutions=0,
            reference_words=10,
            hypothesis_words=10,
            success=True,
        ),
        overall_message="hard metrics computed",
    )
    pipeline._quality_suite.check_all = MagicMock(return_value=hard)
    return pipeline, mock_judge


def _fake_wav():
    d = tempfile.mkdtemp()
    p = Path(d) / "seg.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 1000)
    return p


def test_real_metrics_fed_to_judge_not_only_llm():
    pipeline, judge = _pipeline_with_hard_result(dnsmos_ovr=4.2, wer=0.02, passed=True)
    inputs = [(str(_fake_wav()), _annotation(), _routing(), "测试文本")]

    results = pipeline.run(inputs)

    assert len(results) == 1
    judge.judge_quality.assert_called_once()
    kwargs = judge.judge_quality.call_args.kwargs
    real_metrics = kwargs["real_audio_metrics"]
    # Real DNSMOS + WER scores are surfaced to the judge (not only the LLM text).
    assert real_metrics is not None
    assert real_metrics["dnsmos"] == pytest.approx(4.2)
    assert real_metrics["wer"] == pytest.approx(0.02)
    assert real_metrics["available_metrics"] >= 2
    # The fused overall score is computed from the real metrics.
    assert "overall" in real_metrics


def test_failing_real_metric_triggers_regeneration():
    """A below-threshold DNSMOS must trigger re-synthesis on its own (real gate)."""
    pipeline, judge = _pipeline_with_hard_result(dnsmos_ovr=2.0, wer=0.30, passed=False)
    inputs = [(str(_fake_wav()), _annotation(), _routing(), "测试文本")]

    results = pipeline.run(inputs)

    assert len(results) == 1
    # The real metric failure (not the LLM judge) drives the regeneration flag.
    assert results[0].needs_regeneration is True
    # And the real failure reason is recorded in the judgment issues.
    assert any("Hard quality check failed" in str(i) for i in results[0].issues)
    # The judge still received the real metric values.
    real_metrics = judge.judge_quality.call_args.kwargs["real_audio_metrics"]
    assert real_metrics["dnsmos"] == pytest.approx(2.0)


def test_suite_defaults_to_lightweight_whisper_tiny():
    """The gate's default ASR backend must be the lightweight faster-whisper tiny."""
    import sys
    from unittest.mock import MagicMock

    saved = sys.modules.get("faster_whisper")
    sys.modules["faster_whisper"] = MagicMock()
    try:
        from src.audiobook_studio.quality import metrics as M

        suite = M.QualityCheckSuite({"quality_check": {}})
        suite._initialize()
        # With the lightweight dep present, the suite selects whisper/tiny by default.
        assert suite._wer is not None
        assert suite._wer._backend.model_size == "tiny"
        assert suite._wer._backend.use_faster is True
    finally:
        if saved is None:
            sys.modules.pop("faster_whisper", None)
        else:
            sys.modules["faster_whisper"] = saved

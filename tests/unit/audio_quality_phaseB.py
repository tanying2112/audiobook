"""Phase B structural tests for audio_quality.py (mocking audio/ffmpeg/quality boundaries)."""

import asyncio
import json
import subprocess
import sys
import types
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import src.audiobook_studio.audio_quality as aq
from src.audiobook_studio.audio_quality import (
    QualityReport,
    SegmentQualityResult,
)


# ---------------------------------------------------------------------------
# Fake quality package (injected into sys.modules so _run_hard_metrics_async
# can run its main path without onnxruntime/whisper/torch).
# ---------------------------------------------------------------------------


class _Metric:
    def __init__(self, success=True, mos_ovr=None, wer=None, similarity=None,
                 error=None, is_same_speaker=True, threshold=0.8):
        self.success = success
        self.mos_ovr = mos_ovr
        self.wer = wer
        self.similarity = similarity
        self.error = error
        self.is_same_speaker = is_same_speaker
        self.threshold = threshold


class _QCResult:
    def __init__(self, dnsmos=None, wer=None, speaker_sim=None,
                 passed=True, overall_message=""):
        self.dnsmos = dnsmos
        self.wer = wer
        self.speaker_sim = speaker_sim
        self.passed = passed
        self.overall_message = overall_message


class _Suite:
    def check_all(self, **kwargs):
        return _fake_quality_mod._current

    def register_speaker(self, *a, **k):
        return True


@pytest.fixture
def fake_quality(monkeypatch):
    global _fake_quality_mod
    mod = types.ModuleType("src.audiobook_studio.quality")
    mod._current = _QCResult()
    mod.QualityCheckResult = _QCResult
    mod.QualityCheckSuite = _Suite
    mod.Metric = _Metric
    _fake_quality_mod = mod
    monkeypatch.setitem(sys.modules, "src.audiobook_studio.quality", mod)
    return mod


@pytest.fixture
def fake_voice_anchor(monkeypatch):
    mod = types.ModuleType("src.audiobook_studio.pipeline.voice_anchor")

    def _raise(*a, **k):
        raise RuntimeError("voice_anchor unavailable in test")

    mod.get_voice_anchor_manager = _raise
    monkeypatch.setitem(sys.modules, "src.audiobook_studio.pipeline.voice_anchor", mod)
    return mod


def _patch_ffmpeg(monkeypatch, **kwargs):
    for name, val in kwargs.items():
        monkeypatch.setattr(
            f"src.audiobook_studio.audio_quality.{name}",
            AsyncMock(return_value=val),
        )


# ---------------------------------------------------------------------------
# Dataclasses + serialization
# ---------------------------------------------------------------------------


def test_segment_result_defaults():
    r = SegmentQualityResult(segment_id="s1", file_path="/a.wav", duration_ms=100)
    assert r.silence_regions == []
    assert r.issues == []
    assert r.passed is True
    assert r.mos is None


def test_segment_result_to_dict():
    r = SegmentQualityResult(segment_id="s1", file_path="/a.wav", duration_ms=100)
    d = r.to_dict()
    assert d["segment_id"] == "s1"
    assert d["duration_ms"] == 100
    assert d["issues"] == []


def test_quality_report_defaults_and_to_dict():
    r = SegmentQualityResult(segment_id="s1", file_path="/a.wav", duration_ms=100)
    rep = QualityReport(
        project_id="p",
        chapter_index=1,
        total_segments=1,
        passed_segments=1,
        failed_segments=0,
        segment_results=[r],
        overall_passed=True,
        generated_at="now",
    )
    assert rep.chapter_voice_cosine_means == {}
    assert rep.drift_alerts == []
    d = rep.to_dict()
    assert d["project_id"] == "p"
    assert d["segment_results"][0]["segment_id"] == "s1"
    assert d["breach_reason"] is None


def test_quality_report_to_json_roundtrip():
    r = SegmentQualityResult(segment_id="s1", file_path="/a.wav", duration_ms=100)
    rep = QualityReport(
        project_id="p", chapter_index=0, total_segments=1, passed_segments=1,
        failed_segments=0, segment_results=[r], overall_passed=True, generated_at="now",
    )
    s = rep.to_json()
    loaded = json.loads(s)
    assert loaded["project_id"] == "p"
    assert loaded["segment_results"][0]["segment_id"] == "s1"


def test_thresholds_are_floats():
    assert isinstance(aq.SILENCE_THRESHOLD_DB, float)
    assert isinstance(aq.MAX_SILENCE_RATIO, float)
    assert isinstance(aq.CLIPPING_THRESHOLD_DB, float)


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------


def test_save_and_load_quality_report(tmp_path):
    r = SegmentQualityResult(segment_id="s1", file_path="/a.wav", duration_ms=100)
    rep = QualityReport(
        project_id="p", chapter_index=2, total_segments=1, passed_segments=1,
        failed_segments=0, segment_results=[r], overall_passed=True, generated_at="now",
    )
    out = tmp_path / "report.json"
    aq.save_quality_report(rep, out)
    assert out.exists()
    loaded = aq.load_quality_report(out)
    assert loaded is not None
    assert loaded.project_id == "p"
    assert loaded.chapter_index == 2
    assert loaded.segment_results[0].segment_id == "s1"


def test_load_missing_file_returns_none(tmp_path):
    assert aq.load_quality_report(tmp_path / "nope.json") is None


def test_load_invalid_json_returns_none(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert aq.load_quality_report(bad) is None


# ---------------------------------------------------------------------------
# _check_silence_async (mocked ffmpeg boundary)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_silence_zero_duration():
    _patch = None
    import unittest.mock as um

    aq.get_duration = AsyncMock(return_value=0)
    res = await aq._check_silence_async(Path("/x.wav"))
    assert res["silence_detected"] is True
    assert res["silence_ratio"] == 1.0


@pytest.mark.asyncio
async def test_silence_normal():
    aq.get_duration = AsyncMock(return_value=1000.0)
    aq.detect_silence = AsyncMock(return_value=[(0, 400), (500, 600)])
    res = await aq._check_silence_async(Path("/x.wav"))
    # 400 + 100 = 500ms / 1000ms = 0.5
    assert abs(res["silence_ratio"] - 0.5) < 1e-9
    assert res["silence_detected"] is True


@pytest.mark.asyncio
async def test_silence_exception_path():
    aq.get_duration = AsyncMock(side_effect=RuntimeError("boom"))
    res = await aq._check_silence_async(Path("/x.wav"))
    assert res["silence_detected"] is True
    assert res["silence_ratio"] == 1.0


# ---------------------------------------------------------------------------
# _check_corruption_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_corruption_valid():
    aq.get_audio_info = AsyncMock(
        return_value={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]}
    )
    aq.read_pcm_samples = AsyncMock(return_value=None)
    res = await aq._check_corruption_async(Path("/x.wav"))
    assert res["corruption_detected"] is False
    assert res["decode_valid"] is True


@pytest.mark.asyncio
async def test_corruption_no_format():
    aq.get_audio_info = AsyncMock(return_value={})
    res = await aq._check_corruption_async(Path("/x.wav"))
    assert res["corruption_detected"] is True
    assert "No format" in res["corruption_error"]


@pytest.mark.asyncio
async def test_corruption_no_duration():
    aq.get_audio_info = AsyncMock(
        return_value={"format": {"duration": None}, "streams": [{"codec_type": "audio"}]}
    )
    res = await aq._check_corruption_async(Path("/x.wav"))
    assert res["corruption_detected"] is True
    assert "No duration" in res["corruption_error"]


@pytest.mark.asyncio
async def test_corruption_duration_out_of_range():
    aq.get_audio_info = AsyncMock(
        return_value={"format": {"duration": "0.01"}, "streams": [{"codec_type": "audio"}]}
    )
    res = await aq._check_corruption_async(Path("/x.wav"))
    assert res["corruption_detected"] is True


@pytest.mark.asyncio
async def test_corruption_no_audio_stream():
    aq.get_audio_info = AsyncMock(
        return_value={"format": {"duration": "1.0"}, "streams": [{"codec_type": "video"}]}
    )
    res = await aq._check_corruption_async(Path("/x.wav"))
    assert res["corruption_detected"] is True
    assert "No audio stream" in res["corruption_error"]


@pytest.mark.asyncio
async def test_corruption_pcm_decode_fails():
    aq.get_audio_info = AsyncMock(
        return_value={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]}
    )
    aq.read_pcm_samples = AsyncMock(side_effect=RuntimeError("decode failed"))
    res = await aq._check_corruption_async(Path("/x.wav"))
    assert res["corruption_detected"] is True
    assert "PCM decode failed" in res["corruption_error"]


@pytest.mark.asyncio
async def test_corruption_called_process_error():
    aq.get_audio_info = AsyncMock(side_effect=subprocess.CalledProcessError(1, "ffprobe"))
    res = await aq._check_corruption_async(Path("/x.wav"))
    assert res["corruption_detected"] is True
    assert "ffprobe failed" in res["corruption_error"]


@pytest.mark.asyncio
async def test_corruption_generic_exception():
    aq.get_audio_info = AsyncMock(side_effect=ValueError("weird"))
    res = await aq._check_corruption_async(Path("/x.wav"))
    assert res["corruption_detected"] is True
    assert "Validation error" in res["corruption_error"]


# ---------------------------------------------------------------------------
# _check_clipping_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clipping_detected():
    aq.get_rms_peak = AsyncMock(return_value=(-10.0, 0.2))
    res = await aq._check_clipping_async(Path("/x.wav"))
    assert res["clipping_detected"] is True  # 0.2 dB > -0.5 dB
    assert res["peak_db"] == 0.2


@pytest.mark.asyncio
async def test_clipping_not_detected():
    aq.get_rms_peak = AsyncMock(return_value=(-20.0, -10.0))
    res = await aq._check_clipping_async(Path("/x.wav"))
    assert res["clipping_detected"] is False


@pytest.mark.asyncio
async def test_clipping_exception_path():
    aq.get_rms_peak = AsyncMock(side_effect=RuntimeError("boom"))
    res = await aq._check_clipping_async(Path("/x.wav"))
    assert res["clipping_detected"] is True
    assert res["peak_db"] == 0.0


# ---------------------------------------------------------------------------
# _run_hard_metrics_async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hard_metrics_quality_unavailable():
    # Ensure the real quality package is not importable for this branch.
    try:
        import src.audiobook_studio.quality  # noqa

        pytest.skip("quality package present; unavailable branch not exercised")
    except ModuleNotFoundError:
        pass
    res = await aq._run_hard_metrics_async(Path("/x.wav"))
    assert res["mos"] is None
    assert res["status"].startswith("skipped:quality-package-unavailable")


@pytest.mark.asyncio
async def test_hard_metrics_all_ran(fake_quality):
    fake_quality._current = _QCResult(
        dnsmos=_Metric(success=True, mos_ovr=4.1),
        wer=_Metric(success=True, wer=0.02),
        speaker_sim=_Metric(success=True, similarity=0.95),
    )
    res = await aq._run_hard_metrics_async(Path("/x.wav"), reference_text="hi")
    assert res["mos"] == 4.1
    assert res["wer"] == 0.02
    assert res["voice_cosine"] == 0.95
    assert res["status"] == "all-ran"


@pytest.mark.asyncio
async def test_hard_metrics_partial_skipped(fake_quality):
    fake_quality._current = _QCResult(
        dnsmos=None, wer=None, speaker_sim=None,
    )
    res = await aq._run_hard_metrics_async(Path("/x.wav"))
    assert res["status"].startswith("skipped:")
    assert "wer(no-reference)" in res["status"]


@pytest.mark.asyncio
async def test_hard_metrics_failed_metrics_recorded(fake_quality):
    fake_quality._current = _QCResult(
        dnsmos=_Metric(success=False, error="model missing"),
        wer=_Metric(success=True, wer=0.1),
        speaker_sim=_Metric(success=True, similarity=0.9),
        passed=False,
        overall_message="mos below threshold",
    )
    res = await aq._run_hard_metrics_async(Path("/x.wav"), reference_text="hi")
    assert "硬质检门禁" in res["issues"][0]


@pytest.mark.asyncio
async def test_hard_metrics_suite_error(fake_quality):
    class _BoomSuite(_Suite):
        def check_all(self, **kwargs):
            raise RuntimeError("model crash")

    fake_quality.QualityCheckSuite = _BoomSuite
    res = await aq._run_hard_metrics_async(Path("/x.wav"))
    assert res["mos"] is None
    assert "skipped:suite-error" in res["status"]


# ---------------------------------------------------------------------------
# _check_segment_async (speaker=None to skip voice_anchor resolution)
# ---------------------------------------------------------------------------


async def _segment_passing_mocks():
    aq.get_duration = AsyncMock(return_value=1000.0)
    aq.detect_silence = AsyncMock(return_value=[])
    aq.get_audio_info = AsyncMock(
        return_value={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]}
    )
    aq.read_pcm_samples = AsyncMock(return_value=None)
    aq.get_rms_peak = AsyncMock(return_value=(-20.0, -10.0))


@pytest.mark.asyncio
async def test_check_segment_passing(fake_quality, fake_voice_anchor):
    await _segment_passing_mocks()
    fake_quality._current = _QCResult(
        dnsmos=_Metric(success=True, mos_ovr=4.0),
        wer=_Metric(success=True, wer=0.01),
        speaker_sim=_Metric(success=True, similarity=0.9),
    )
    res = await aq._check_segment_async(Path("/x.wav"), "seg1")
    assert res.passed is True
    assert res.issues == []
    assert res.mos == 4.0


@pytest.mark.asyncio
async def test_check_segment_silence_fails(fake_quality):
    await _segment_passing_mocks()
    aq.detect_silence = AsyncMock(return_value=[(0, 900)])
    fake_quality._current = _QCResult(speaker_sim=_Metric(success=True, similarity=0.9))
    res = await aq._check_segment_async(Path("/x.wav"), "seg1")
    assert res.passed is False
    assert any("silence" in i.lower() for i in res.issues)


@pytest.mark.asyncio
async def test_check_segment_corruption_fails(fake_quality):
    await _segment_passing_mocks()
    aq.get_audio_info = AsyncMock(return_value={})
    res = await aq._check_segment_async(Path("/x.wav"), "seg1")
    assert res.passed is False
    assert res.corruption_detected is True


@pytest.mark.asyncio
async def test_check_segment_clipping_fails(fake_quality):
    await _segment_passing_mocks()
    aq.get_rms_peak = AsyncMock(return_value=(-1.0, 1.0))
    res = await aq._check_segment_async(Path("/x.wav"), "seg1")
    assert res.passed is False
    assert res.clipping_detected is True


@pytest.mark.asyncio
async def test_check_segment_with_speaker_map(fake_quality, fake_voice_anchor, tmp_path):
    await _segment_passing_mocks()
    fake_quality._current = _QCResult(
        dnsmos=_Metric(success=True, mos_ovr=4.0),
        wer=_Metric(success=True, wer=0.01),
        speaker_sim=_Metric(success=True, similarity=0.9),
    )
    seg = tmp_path / "seg.wav"
    seg.write_text("x")
    res = await aq._check_segment_async(
        seg, "seg1", reference_text="hi", speaker="Narrator", chapter_index=3, book_id="b"
    )
    assert res.passed is True
    assert res.voice_cosine == 0.9


# ---------------------------------------------------------------------------
# check_all_segments / sync wrapper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_all_segments_missing_file(monkeypatch, fake_voice_anchor):
    # stub all ffmpeg helpers so existing-file path is inert if hit
    _patch_ffmpeg(
        monkeypatch,
        get_duration=1000.0,
        detect_silence=[],
        get_audio_info={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]},
        read_pcm_samples=None,
        get_rms_peak=(-20.0, -10.0),
    )
    missing = Path("/does/not/exist.wav")
    report = await aq.check_all_segments(
        [missing], ["s1"], "proj", 1,
    )
    assert report.total_segments == 1
    assert report.failed_segments == 1
    assert report.overall_passed is False
    assert report.segment_results[0].needs_manual_review is True


@pytest.mark.asyncio
async def test_check_all_segments_passing(monkeypatch, fake_quality, fake_voice_anchor, tmp_path):
    _patch_ffmpeg(
        monkeypatch,
        get_duration=1000.0,
        detect_silence=[],
        get_audio_info={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]},
        read_pcm_samples=None,
        get_rms_peak=(-20.0, -10.0),
    )
    fake_quality._current = _QCResult(
        dnsmos=_Metric(success=True, mos_ovr=4.0),
        wer=_Metric(success=True, wer=0.01),
        speaker_sim=_Metric(success=True, similarity=0.9),
    )
    f = tmp_path / "ok.wav"
    f.write_text("x")
    report = await aq.check_all_segments([f], ["s1"], "proj", 1, speaker_map={"s1": "Narrator"})
    assert report.overall_passed is True
    assert report.passed_segments == 1
    # voice_cosine aggregation across chapter
    assert report.voice_cosine_mean == 0.9
    assert report.chapter_voice_cosine_means == {"Narrator": 0.9}


@pytest.mark.asyncio
async def test_check_all_segments_retry_then_manual_review(
    monkeypatch, fake_quality, fake_voice_anchor, tmp_path
):
    _patch_ffmpeg(
        monkeypatch,
        get_duration=1000.0,
        detect_silence=[(0, 900)],  # silence -> fail
        get_audio_info={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]},
        read_pcm_samples=None,
        get_rms_peak=(-20.0, -10.0),
    )
    fake_quality._current = _QCResult(speaker_sim=_Metric(success=True, similarity=0.9))

    first = tmp_path / "a.wav"
    second = tmp_path / "b.wav"
    first.write_text("x")
    second.write_text("x")

    calls = {"n": 0}

    def retry_cb(segment_id, attempt):
        calls["n"] += 1
        return str(second)

    report = await aq.check_all_segments(
        [first], ["s1"], "proj", 1, max_retries=1, retry_callback=retry_cb
    )
    assert calls["n"] == 1
    seg = report.segment_results[0]
    assert seg.passed is False
    assert seg.needs_manual_review is True
    assert any("人工复核" in i for i in seg.issues)


def test_sync_check_all_segments_missing(monkeypatch, fake_voice_anchor, tmp_path):
    _patch_ffmpeg(
        monkeypatch,
        get_duration=1000.0,
        detect_silence=[],
        get_audio_info={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]},
        read_pcm_samples=None,
        get_rms_peak=(-20.0, -10.0),
    )
    missing = Path("/nope.wav")
    report = aq.sync_check_all_segments([missing], ["s1"], "proj", 1)
    assert report.overall_passed is False
    assert report.failed_segments == 1


# ---------------------------------------------------------------------------
# Sync wrappers (check_silence / check_corruption / check_clipping /
# check_segment / get_duration_sync) — no heavy metrics involved.
# ---------------------------------------------------------------------------


def test_sync_wrappers(monkeypatch):
    _patch_ffmpeg(
        monkeypatch,
        get_duration=1000.0,
        detect_silence=[(0, 900)],
        get_audio_info={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]},
        read_pcm_samples=None,
        get_rms_peak=(-1.0, 1.0),
    )
    assert aq.check_silence(Path("/x.wav"))["silence_detected"] is True
    assert aq.check_corruption(Path("/x.wav"))["corruption_detected"] is False
    assert aq.check_clipping(Path("/x.wav"))["clipping_detected"] is True


def test_check_segment_sync_wrapper(monkeypatch, fake_quality, fake_voice_anchor):
    _patch_ffmpeg(
        monkeypatch,
        get_duration=1000.0,
        detect_silence=[],
        get_audio_info={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]},
        read_pcm_samples=None,
        get_rms_peak=(-20.0, -10.0),
    )
    fake_quality._current = _QCResult(speaker_sim=_Metric(success=True, similarity=0.9))
    seg = aq.check_segment(Path("/x.wav"), "seg1")
    assert seg.segment_id == "seg1"
    assert seg.passed is True


def test_get_duration_sync(monkeypatch):
    monkeypatch.setattr("src.audiobook_studio.audio_quality.get_duration", AsyncMock(return_value=1234))
    assert aq.get_duration_sync(Path("/x.wav")) == 1234


# ---------------------------------------------------------------------------
# voice_anchor-enabled reference resolution + drift gate
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_voice_anchor_enabled(monkeypatch, tmp_path):
    mod = types.ModuleType("src.audiobook_studio.pipeline.voice_anchor")
    ref = tmp_path / "ref.wav"
    ref.write_text("x")

    class _Cfg:
        enabled = True

    class _VA:
        config = _Cfg()

        def get_reference_audio(self, speaker, chapter_index=0):
            return str(ref)

        def register_speaker(self, *a, **k):
            return True

        def _record_drift_alert(self, **k):
            self.recorded = k

        def get_drift_alerts(self, chapter_index):
            return []

    mgr = _VA()

    def _get_mgr(*a, **k):
        return mgr

    mod.get_voice_anchor_manager = _get_mgr
    monkeypatch.setitem(sys.modules, "src.audiobook_studio.pipeline.voice_anchor", mod)
    return mod


@pytest.mark.asyncio
async def test_check_segment_voice_anchor_enabled(
    fake_quality, fake_voice_anchor_enabled, monkeypatch
):
    await _segment_passing_mocks()
    fake_quality._current = _QCResult(
        dnsmos=_Metric(success=True, mos_ovr=4.0),
        wer=_Metric(success=True, wer=0.01),
        speaker_sim=_Metric(success=True, similarity=0.5, is_same_speaker=False, threshold=0.8),
    )
    res = await aq._check_segment_async(
        Path("/x.wav"), "seg1", reference_text="hi", speaker="Narrator",
        chapter_index=2, book_id="b",
    )
    # drift gate: not same speaker -> drift alert recorded
    assert res.voice_cosine == 0.5


@pytest.mark.asyncio
async def test_check_all_segments_drift_aggregation(
    monkeypatch, fake_quality, fake_voice_anchor_enabled, tmp_path
):
    _patch_ffmpeg(
        monkeypatch,
        get_duration=1000.0,
        detect_silence=[],
        get_audio_info={"format": {"duration": "1.0"}, "streams": [{"codec_type": "audio"}]},
        read_pcm_samples=None,
        get_rms_peak=(-20.0, -10.0),
    )
    fake_quality._current = _QCResult(
        dnsmos=_Metric(success=True, mos_ovr=4.0),
        wer=_Metric(success=True, wer=0.01),
        speaker_sim=_Metric(success=True, similarity=0.9),
    )
    f = tmp_path / "ok.wav"
    f.write_text("x")
    report = await aq.check_all_segments([f], ["s1"], "proj", 1, speaker_map={"s1": "Narrator"})
    assert report.overall_passed is True
    assert report.drift_alerts == []


@pytest.mark.asyncio
async def test_check_segment_duration_exception(fake_quality):
    await _segment_passing_mocks()
    aq.get_duration = AsyncMock(side_effect=RuntimeError("no duration"))
    fake_quality._current = _QCResult(speaker_sim=_Metric(success=True, similarity=0.9))
    res = await aq._check_segment_async(Path("/x.wav"), "seg1")
    assert res.duration_ms == 0

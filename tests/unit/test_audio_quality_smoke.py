from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

import src.audiobook_studio.audio_quality as AQ
import src.audiobook_studio.quality.audio_metrics as AM


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    import urllib.request

    def _raise(*a, **k):
        raise OSError("network disabled in tests")

    monkeypatch.setattr(urllib.request, "urlopen", _raise)
    try:
        import requests

        monkeypatch.setattr(requests, "get", lambda *a, **k: _raise())
        monkeypatch.setattr(requests, "download", lambda *a, **k: _raise())
    except Exception:
        pass


def _make_wav(path: Path, sr=16000, dur=0.5, amp=0.3):
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    data = (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    sf.write(str(path), data, sr)


@pytest.fixture
def wav(tmp_path):
    p = tmp_path / "clip.wav"
    _make_wav(p)
    return p


def test_audio_quality_checks(wav):
    s = AQ.check_silence(wav)
    assert "silence_detected" in s and "silence_ratio" in s
    c = AQ.check_corruption(wav)
    assert "corruption_detected" in c
    cl = AQ.check_clipping(wav)
    assert "clipping_detected" in cl


def test_check_segment(wav):
    r = AQ.check_segment(wav, "seg1")
    assert r.segment_id == "seg1"
    assert r.file_path == str(wav)


def test_sync_check_all_segments(tmp_path, wav):
    a = tmp_path / "a.wav"
    b = tmp_path / "b.wav"
    a.write_bytes(wav.read_bytes())
    b.write_bytes(wav.read_bytes())
    report = AQ.sync_check_all_segments([a, b], ["a", "b"], "1", 0)
    assert len(report.segment_results) == 2
    out = tmp_path / "report.json"
    AQ.save_quality_report(report, out)
    loaded = AQ.load_quality_report(out)
    assert loaded is not None and len(loaded.segment_results) == 2


def test_get_duration_sync(wav, monkeypatch):
    # get_duration_sync must propagate the RuntimeError raised by the underlying
    # ffmpeg probe when the subprocess fails (e.g. ffmpeg missing or returning a
    # non-zero exit code). We mock the probe so the test is deterministic and does
    # not depend on whether ffmpeg happens to be installed in the environment.
    async def _boom(path):
        raise RuntimeError("ffmpeg PCM extraction failed (simulated)")

    monkeypatch.setattr(AQ, "get_duration", _boom)
    with pytest.raises(RuntimeError):
        AQ.get_duration_sync(wav)


def test_audio_metrics_levenshtein():
    assert AM._levenshtein_distance(["a", "b", "c"], ["a", "c"]) == 1
    assert AM._levenshtein_distance([], []) == 0


def test_get_available_metrics():
    avail = AM.get_available_metrics()
    assert isinstance(avail, dict)


def test_check_audio_quality(wav, monkeypatch):
    # Unit tests must not load the real faster-whisper model: on some hosts
    # ctranslate2 aborts the whole process (native crash, not an exception).
    # The WER path itself is covered by integration/e2e suites.
    monkeypatch.setattr(AM, "_whisper_available", False)
    rep = AM.check_audio_quality(str(wav), "参考文本")
    assert rep is not None


def test_predict_mos_missing_model(tmp_path):
    p = tmp_path / "x.wav"
    _make_wav(p)
    res = AM.predict_mos(str(p))
    assert res is None or isinstance(res, float)

"""Regression test: /tts/voices/clone must PERSIST the reference sample.

Audit rec #9 (Track B / Pro Studio): real zero-shot cloning is only usable if the
uploaded 15s reference sample survives the request and lives on a path the
self-hosted GPU backend can read via ``reference_audio_path``. A prior bug deleted
the temp upload buffer in ``finally``, leaving a dangling ``reference_audio_path``
and making real cloning impossible end-to-end. This test pins the persistence.
"""

import importlib
import sys
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.audiobook_studio.api.tts_voices import router as tts_router
from src.audiobook_studio.exceptions import register_error_handlers

app = FastAPI()
app.include_router(tts_router)
# Same AudiobookError -> HTTP mapping as the real app, so the consent gate is
# observed as a 422 response instead of a bare exception.
register_error_handlers(app)


@pytest.fixture()
def real_soundfile(monkeypatch):
    """Swap the genuine ``soundfile`` back into ``sys.modules``.

    ``tests/conftest_minimal.py`` installs a MagicMock for ``soundfile`` whose
    ``write`` emits ``b"\\x00" * len(data)`` (no RIFF header). This endpoint runs
    real duration/SNR validation via ``sf.read``, so it needs the real library.
    ``monkeypatch.delitem`` restores the mock during teardown.
    """
    monkeypatch.delitem(sys.modules, "soundfile", raising=False)
    return importlib.import_module("soundfile")


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def _make_15s_wav(sf, path: Path) -> None:
    """Write a 15s 24kHz WAV with silent leading/trailing edges (high SNR)."""
    sr = 24000
    n = sr * 15
    t = np.arange(n) / sr
    sig = np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    # Silent first/last 100 samples -> the endpoint's SNR estimate hits its
    # 50 dB fallback (noise_floor == 0), comfortably above the 20 dB minimum.
    sig[:100] = 0.0
    sig[-100:] = 0.0
    sf.write(str(path), sig, sr)


@pytest.fixture()
def _isolate(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)
    monkeypatch.delenv("COSYVOICE_ENDPOINT", raising=False)
    monkeypatch.delenv("CLONE_BACKEND_DISABLED", raising=False)
    monkeypatch.setenv("AUDIO_OUTPUT_DIR", str(tmp_path))
    yield tmp_path


def test_clone_persists_reference_sample_and_does_not_delete(client, real_soundfile, _isolate, tmp_path):
    wav = tmp_path / "sample.wav"
    _make_15s_wav(real_soundfile, wav)

    # Pass raw bytes (not an already-consumed file object) so the upload has content.
    resp = client.post(
        "/tts/voices/clone",
        files={"file": ("sample.wav", wav.read_bytes(), "audio/wav")},
        data={
            "speaker_id": "narrator01",
            "language": "zh-CN",
            "text_content": "参考文本",
            "consent": "true",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["success"] is True
    assert body["mode"] == "preset"  # no GPU backend configured in this test
    assert body["clone_available"] is False

    # The reference sample MUST survive the request on the shared output volume.
    persisted = Path(tmp_path) / "cloned_voices" / "narrator01.wav"
    assert persisted.exists(), "reference sample was deleted — real cloning cannot run"
    assert persisted.stat().st_size == wav.stat().st_size


def test_clone_rejects_without_consent(client, real_soundfile, _isolate, tmp_path):
    wav = tmp_path / "sample.wav"
    _make_15s_wav(real_soundfile, wav)

    resp = client.post(
        "/tts/voices/clone",
        files={"file": ("sample.wav", wav.read_bytes(), "audio/wav")},
        data={"speaker_id": "narrator01", "consent": "false"},
    )

    # P2.11: honest refusal (422), never a fake "cloned" success.
    assert resp.status_code == 422, resp.text
    assert resp.json()["error"]["error_code"] == "VALIDATION_ERROR"
    # No sample persisted when consent is missing.
    assert not (Path(tmp_path) / "cloned_voices").exists()

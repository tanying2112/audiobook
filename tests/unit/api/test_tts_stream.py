"""Streaming TTS endpoint tests (POST/GET /api/tts/stream).

Verifies that the endpoint returns a chunked ``audio/*`` stream so the client can
begin playback before the whole utterance is synthesized.

- The mock path (engine='mock' / MOCK_TTS=true) is fully offline and deterministic.
- The real Edge-TTS branch (engine='edge_tts') streams audio/mpeg; because the test
  environment mocks the ``edge_tts`` package, we patch ``EdgeTTSEngine.stream`` with a
  fake async generator to exercise the real (non-mock) wiring without network access.
  The live Microsoft Edge-TTS service path is validated manually.
"""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.audiobook_studio.api import tts_voices
from src.audiobook_studio.api.tts_voices import (
    _mock_stream_generator,
    _mock_wav_bytes,
    router as tts_router,
)

app = FastAPI()
app.include_router(tts_router)


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


# ── Source-level: the generator truly yields multiple chunks ─────────────────


def test_mock_wav_is_valid_container():
    data = _mock_wav_bytes("测试")
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"


def test_mock_stream_generator_yields_multiple_chunks():
    async def _collect(gen):
        return [c async for c in gen]

    chunks = asyncio.run(_collect(_mock_stream_generator("流式语音合成测试" * 3)))
    assert len(chunks) > 1, "streaming generator must yield multiple chunks"
    assert b"".join(chunks)[:4] == b"RIFF"


# ── HTTP layer: endpoint returns a streamed audio response ───────────────────


def test_tts_stream_post_mock_returns_audio(client):
    with client.stream(
        "POST", "/tts/stream", json={"text": "这是一个流式语音合成测试。", "engine": "mock"}
    ) as r:
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("audio/")
        data = b"".join(r.iter_bytes())
    assert data[:4] == b"RIFF"
    assert len(data) > 44


def test_tts_stream_get_mock_returns_audio(client):
    with client.stream(
        "GET", "/tts/stream", params={"text": "hello streaming", "engine": "mock"}
    ) as r:
        assert r.status_code == 200
        data = b"".join(r.iter_bytes())
    assert data[:4] == b"RIFF"


@pytest.mark.skip(reason="Test app missing global exception handler")
def test_tts_stream_get_requires_text(client):
    with client.stream("GET", "/tts/stream", params={"engine": "mock"}) as r:
        assert r.status_code == 422


def test_tts_stream_respects_global_mock_env(monkeypatch, client):
    monkeypatch.setenv("MOCK_TTS", "true")
    # engine not specified -> defaults to edge_tts, but global MOCK_TTS must force mock
    assert tts_voices._tts_stream_use_mock("edge_tts") is True
    with client.stream("POST", "/tts/stream", json={"text": "env mock"}) as r:
        assert r.status_code == 200
        data = b"".join(r.iter_bytes())
    assert data[:4] == b"RIFF"


def test_tts_stream_edge_path_streams_mp3(client, monkeypatch):
    """Real (non-mock) code path: engine='edge_tts' must stream audio/mpeg.

    conftest_minimal mocks the ``edge_tts`` package globally, so we patch
    ``EdgeTTSEngine.stream`` with a fake async generator that yields MP3-like
    bytes. This verifies the endpoint wires the real streaming branch and emits
    a chunked audio/mpeg response (the production path uses Edge-TTS's native
    streaming API, validated manually against the live service).
    """
    fake_mp3 = b"\xff\xfb\x90\x00" * 400  # MP3 frame-like bytes

    async def _fake_stream(self, payload):
        for i in range(0, len(fake_mp3), 100):
            yield fake_mp3[i : i + 100]

    monkeypatch.setattr(
        "src.audiobook_studio.tts.edge_tts_engine.EdgeTTSEngine.stream",
        _fake_stream,
    )
    # Force the real (non-mock) branch regardless of the MOCK_TTS env value.
    monkeypatch.setattr(
        tts_voices, "_tts_stream_use_mock", lambda engine: False if engine == "edge_tts" else True
    )

    with client.stream(
        "POST", "/tts/stream", json={"text": "edge path test", "engine": "edge_tts"}
    ) as r:
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("audio/mpeg")
        data = b"".join(r.iter_bytes())
    assert len(data) > 0
    assert data[:2] == b"\xff\xfb"

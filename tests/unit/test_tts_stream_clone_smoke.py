import asyncio
from unittest import mock

import pytest

from audiobook_studio.tts.streaming import (
    CosyVoiceStreamEngine,
    MeloTTSStreamEngine,
    SeedTTSStreamEngine,
    StreamingTTSConfig,
    create_streaming_tts_engine,
)
from audiobook_studio.tts.zero_shot_clone import (
    CosyVoiceCloneEngine,
    OpenVoiceV2Engine,
    XTTSv2Engine,
    ZeroShotCloneConfig,
    create_zero_shot_clone_engine,
)


@pytest.mark.asyncio
async def test_streaming_mock(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "true")
    cfg = StreamingTTSConfig(engine="cosyvoice_stream", host="localhost", port=9999)
    eng = create_streaming_tts_engine(cfg)
    assert isinstance(eng.synthesize("你好世界"), (bytes, bytearray))
    assert list(eng.synthesize_stream("你好世界"))
    async for _ in eng.synthesize_stream_async("你好世界"):
        pass
    for cls in (CosyVoiceStreamEngine, SeedTTSStreamEngine, MeloTTSStreamEngine):
        e = cls(cfg)
        assert e.synthesize("hi")
        assert list(e.synthesize_stream("hi"))
        async for _ in e.synthesize_stream_async("hi"):
            pass


@pytest.mark.asyncio
async def test_zero_shot_clone_mock(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "true")
    cfg = ZeroShotCloneConfig(engine="xtts_v2", host="localhost", port=5010)
    eng = create_zero_shot_clone_engine(cfg)
    assert eng.clone("要合成的文本", reference_audio=b"PROMPT", voice_id="v1") is not None
    assert await eng.clone_async("文本", reference_audio=b"PROMPT") is not None
    assert list(eng.clone_stream("文本", reference_audio=b"PROMPT"))
    for cls in (XTTSv2Engine, OpenVoiceV2Engine, CosyVoiceCloneEngine):
        e = cls(cfg)
        assert e.clone("t", reference_audio=b"P") is not None


@pytest.mark.asyncio
async def test_edge_tts_engine_importable():
    from audiobook_studio.tts import edge_tts_engine as ETE

    assert hasattr(ETE, "EdgeTTSEngine")
    assert hasattr(ETE, "create_edge_tts_engine")

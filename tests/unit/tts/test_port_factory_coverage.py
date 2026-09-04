"""Phase 3 isolated coverage tests for ``tts/port_factory.py``.

These tests drive the offline-testable business logic of the TTS engine
factory without requiring real TTS backends (Kokoro/Coqui/Edge/etc.).
Heavy backend constructors are monkeypatched so the dispatch/branching
logic inside ``create_engine`` and friends is fully exercised.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.audiobook_studio.tts import TTSVoiceAnchor
from src.audiobook_studio.tts import port_factory as pf
from src.audiobook_studio.tts.port import (
    TTSStatus,
    TTSTaskPayload,
    TTSTaskResult,
)
from src.audiobook_studio.tts.port_factory import (
    StreamingTTSConfig,
    ZeroShotCloneConfig,
)

# ── _get_lock ──────────────────────────────────────────────────────────────


def test_get_lock_returns_real_lock():
    lock = pf._get_lock()
    assert lock is not None
    assert isinstance(lock, type(threading.Lock()))
    # It must be usable as a context manager
    with lock:
        pass


# ── StreamingTTSConfig / ZeroShotCloneConfig properties ────────────────────


def test_streaming_config_properties(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "false")
    cfg = StreamingTTSConfig(engine="cosyvoice_stream", host="h", port=5000)
    assert cfg.base_url == "http://h:5000"
    assert cfg.mock_mode is False
    assert cfg.chunk_samples == int(24000 * 100 / 1000)


def test_streaming_config_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "true")
    cfg = StreamingTTSConfig(engine="seed_tts_stream")
    assert cfg.mock_mode is True


def test_zero_shot_config_properties(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "false")
    cfg = ZeroShotCloneConfig(engine="xtts_v2", host="h", port=5010)
    assert cfg.base_url == "http://h:5010"
    assert cfg.mock_mode is False


def test_zero_shot_config_mock_mode(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "true")
    cfg = ZeroShotCloneConfig(engine="openvoice_v2")
    assert cfg.mock_mode is True


# ── create_engine dispatch branches ────────────────────────────────────────


def test_create_engine_fake():
    eng = pf.create_engine("fake")
    assert isinstance(eng, pf.FakeRemoteTTSPort)


def test_create_engine_mock():
    eng = pf.create_engine("mock")
    assert isinstance(eng, pf.MockRemoteTTSPort)


def test_create_engine_voxcpm2_real():
    eng = pf.create_engine("voxcpm2")
    # Real backend constructor — just assert it returns a port-like object
    assert eng is not None


def test_create_engine_auto_mock_llm(monkeypatch):
    monkeypatch.setenv("MOCK_LLM", "true")
    monkeypatch.setenv("MOCK_TTS", "false")
    eng = pf.create_engine("auto")
    assert isinstance(eng, pf.FakeRemoteTTSPort)


def test_create_engine_auto_test_mode(monkeypatch):
    monkeypatch.setenv("TEST_MODE", "true")
    monkeypatch.setenv("MOCK_TTS", "false")
    eng = pf.create_engine("auto")
    assert isinstance(eng, pf.FakeRemoteTTSPort)


def test_create_engine_auto_voxcpm2_endpoint(monkeypatch):
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://localhost:9100")
    monkeypatch.setenv("MOCK_TTS", "false")
    eng = pf.create_engine("auto")
    assert eng is not None


def test_create_engine_auto_default_kokoro(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "false")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "true")
    sentinel = object()
    monkeypatch.setattr(pf, "create_kokoro_port", lambda **kw: sentinel)
    monkeypatch.setattr(pf, "create_edge_tts_port", lambda **kw: object())
    assert pf.create_engine("auto") is sentinel


def test_create_engine_auto_default_edge(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "false")
    monkeypatch.delenv("MOCK_LLM", raising=False)
    monkeypatch.delenv("TEST_MODE", raising=False)
    monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "false")
    sentinel = object()
    monkeypatch.setattr(pf, "create_kokoro_port", lambda **kw: object())
    monkeypatch.setattr(pf, "create_edge_tts_port", lambda **kw: sentinel)
    assert pf.create_engine("auto") is sentinel


def test_create_engine_kokoro(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "false")
    sentinel = object()
    monkeypatch.setattr(pf, "create_kokoro_port", lambda **kw: sentinel)
    assert pf.create_engine("kokoro") is sentinel


def test_create_engine_edge(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "false")
    sentinel = object()
    monkeypatch.setattr(pf, "create_edge_tts_port", lambda **kw: sentinel)
    assert pf.create_engine("edge") is sentinel


def test_create_engine_streaming_branches(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "false")
    captured = {}

    def fake_streaming(**kw):
        captured.update(kw)
        return "STREAM"

    monkeypatch.setattr(pf, "create_streaming_tts_engine", fake_streaming)
    for etype in ("cosyvoice_stream", "seed_tts_stream", "melotts_stream"):
        captured.clear()
        assert pf.create_engine(etype) == "STREAM"
        assert captured["engine"] == etype


def test_create_engine_clone_branches(monkeypatch):
    monkeypatch.setenv("MOCK_TTS", "false")
    captured = {}

    def fake_clone(**kw):
        captured.update(kw)
        return "CLONE"

    monkeypatch.setattr(pf, "create_zero_shot_clone_engine", fake_clone)
    for etype in ("xtts_v2", "openvoice_v2", "cosyvoice_clone"):
        captured.clear()
        assert pf.create_engine(etype) == "CLONE"
        assert captured["engine"] == etype


def test_create_engine_unknown_raises():
    with pytest.raises(ValueError):
        pf.create_engine("definitely_not_a_real_engine")


# ── _build_config_from_env ─────────────────────────────────────────────────


def test_build_config_default_kokoro_only(monkeypatch):
    for k in (
        "EDGE_TTS_ENABLED",
        "VOXCPM2_ENDPOINT",
        "KOKORO_MODEL_PATH",
        "COSYVOICE_STREAM_ENDPOINT",
        "SEED_TTS_STREAM_ENDPOINT",
        "MELOTTS_STREAM_ENDPOINT",
        "XTTS_V2_ENDPOINT",
        "OPENVOICE_V2_ENDPOINT",
        "COSYVOICE_CLONE_ENDPOINT",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "true")
    cfg = pf._build_config_from_env()
    assert "kokoro" in cfg
    assert "edge" not in cfg  # edge only added if enabled or config empty


def test_build_config_edge_enabled(monkeypatch):
    monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)
    monkeypatch.delenv("KOKORO_MODEL_PATH", raising=False)
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "true")
    monkeypatch.setenv("EDGE_TTS_ENABLED", "true")
    cfg = pf._build_config_from_env()
    assert "edge" in cfg
    assert cfg["edge"]["voice"] == "zh-CN-XiaoxiaoNeural"


def test_build_config_kokoro_model_path(monkeypatch):
    monkeypatch.delenv("VOXCPM2_ENDPOINT", raising=False)
    monkeypatch.delenv("EDGE_TTS_ENABLED", raising=False)
    monkeypatch.setenv("ENABLE_LOCAL_TTS", "true")
    monkeypatch.setenv("KOKORO_MODEL_PATH", "/models/kokoro")
    cfg = pf._build_config_from_env()
    assert cfg["kokoro"]["model_path"] == "/models/kokoro"


def test_build_config_voxcpm2(monkeypatch):
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://vox:1234")
    monkeypatch.setenv("VOXCPM2_TIMEOUT_SEC", "42")
    cfg = pf._build_config_from_env()
    assert cfg["voxcpm2"]["endpoint"] == "http://vox:1234"
    assert cfg["voxcpm2"]["timeout_sec"] == 42


def test_build_config_streaming_endpoints(monkeypatch):
    monkeypatch.setenv("COSYVOICE_STREAM_ENDPOINT", "http://cosy:5000")
    monkeypatch.setenv("SEED_TTS_STREAM_ENDPOINT", "http://seed:5001")
    monkeypatch.setenv("MELOTTS_STREAM_ENDPOINT", "http://melo:5002")
    cfg = pf._build_config_from_env()
    assert cfg["cosyvoice_stream"] == {"host": "cosy", "port": 5000, "sample_rate": 24000}
    assert cfg["seed_tts_stream"] == {"host": "seed", "port": 5001, "sample_rate": 24000}
    assert cfg["melotts_stream"] == {"host": "melo", "port": 5002, "sample_rate": 24000}


def test_build_config_clone_endpoints(monkeypatch):
    monkeypatch.setenv("XTTS_V2_ENDPOINT", "http://xtts:5010")
    monkeypatch.setenv("OPENVOICE_V2_ENDPOINT", "http://ov:5011")
    monkeypatch.setenv("COSYVOICE_CLONE_ENDPOINT", "http://csc:5012")
    cfg = pf._build_config_from_env()
    assert cfg["xtts_v2"] == {"host": "xtts", "port": 5010, "sample_rate": 24000}
    assert cfg["openvoice_v2"] == {"host": "ov", "port": 5011, "sample_rate": 24000}
    assert cfg["cosyvoice_clone"] == {"host": "csc", "port": 5012, "sample_rate": 24000}


# ── create_configured_registry ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_configured_registry(monkeypatch):
    captured = {}

    class FakeRegistry:
        def __init__(self):
            self.config = None

        async def initialize(self):
            captured["init"] = True

    monkeypatch.setattr(pf, "EngineRegistry", FakeRegistry)
    monkeypatch.setattr(pf, "_build_config_from_env", lambda: {"kokoro": {}})
    reg = await pf.create_configured_registry()
    assert reg.config == {"kokoro": {}}
    assert captured["init"] is True


@pytest.mark.asyncio
async def test_create_configured_registry_explicit_config(monkeypatch):
    initialized = {}

    class FakeRegistry:
        def __init__(self):
            self.config = None

        async def initialize(self):
            initialized["ok"] = True

    monkeypatch.setattr(pf, "EngineRegistry", FakeRegistry)
    reg = await pf.create_configured_registry({"edge": {"voice": "x"}})
    assert reg.config == {"edge": {"voice": "x"}}
    assert initialized["ok"] is True


# ── get_default_engine ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_default_engine_passed_registry(monkeypatch):
    fake_engine = object()
    reg = MagicMock()
    reg.get_default.return_value = fake_engine
    assert await pf.get_default_engine(reg) is fake_engine


@pytest.mark.asyncio
async def test_get_default_engine_passed_registry_none_default(monkeypatch):
    fake_engine = object()
    reg = MagicMock()
    reg.get_default.side_effect = [None, fake_engine]
    reg.initialize = AsyncMock()
    monkeypatch.setattr(pf, "_build_config_from_env", lambda: {"edge": {}})
    assert await pf.get_default_engine(reg) is fake_engine


# ── get_port (EnginePortAdapter) ──────────────────────────────────────────


class _FakeResult:
    def __init__(self, status, audio_path=None, duration_ms=100, error_message=None):
        self.status = status
        self.audio_path = audio_path
        self.duration_ms = duration_ms
        self.error_message = error_message


class _FakeEngine:
    def __init__(self, result):
        self.output_dir = "/tmp"
        self.result = result
        self.health_called = False
        self.closed = False

    async def synthesize(self, payload, output_path):
        return self.result

    async def health_check(self):
        self.health_called = True
        return {"ok": True}

    async def close(self):
        self.closed = True


async def _drain(adapter, task_id):
    """Let the background _run_synthesis task finish, then return final status."""
    for _ in range(200):
        await asyncio.sleep(0)
        st = await adapter.get_status(task_id)
        if st.status != TTSStatus.RUNNING:
            return st
    return await adapter.get_status(task_id)


@pytest.mark.asyncio
async def test_get_port_done_path(tmp_path, monkeypatch):
    audio = tmp_path / "out.wav"
    audio.write_bytes(b"RIFF")
    engine = _FakeEngine(_FakeResult(TTSStatus.DONE, audio_path=str(audio), duration_ms=123))
    monkeypatch.setattr(pf, "get_default_engine", AsyncMock(return_value=engine))

    adapter = await pf.get_port()
    ok = await adapter.submit("t1", TTSTaskPayload(text="hi", voice_anchor=TTSVoiceAnchor(voice_id="t1")))
    assert ok is True
    # duplicate submit rejected
    assert await adapter.submit("t1", TTSTaskPayload(text="hi", voice_anchor=TTSVoiceAnchor(voice_id="t1"))) is False

    status = await _drain(adapter, "t1")
    assert status.status == TTSStatus.DONE

    result = await adapter.get_result("t1")
    assert isinstance(result, TTSTaskResult)
    assert result.duration_ms == 123

    assert await adapter.cancel("t1") is False  # already DONE
    await adapter.health_check()
    assert engine.health_called is True
    await adapter.close()
    assert engine.closed is True


@pytest.mark.asyncio
async def test_get_port_failed_status(tmp_path, monkeypatch):
    engine = _FakeEngine(_FakeResult(TTSStatus.FAILED, error_message="boom"))
    monkeypatch.setattr(pf, "get_default_engine", AsyncMock(return_value=engine))
    adapter = await pf.get_port()
    await adapter.submit("f1", TTSTaskPayload(text="x", voice_anchor=TTSVoiceAnchor(voice_id="f1")))
    status = await _drain(adapter, "f1")
    assert status.status == TTSStatus.FAILED
    assert status.error_message == "boom"


@pytest.mark.asyncio
async def test_get_port_missing_audio(tmp_path, monkeypatch):
    engine = _FakeEngine(_FakeResult(TTSStatus.DONE, audio_path="/nonexistent/path.wav"))
    monkeypatch.setattr(pf, "get_default_engine", AsyncMock(return_value=engine))
    adapter = await pf.get_port()
    await adapter.submit("m1", TTSTaskPayload(text="x", voice_anchor=TTSVoiceAnchor(voice_id="m1")))
    status = await _drain(adapter, "m1")
    assert status.status == TTSStatus.FAILED
    assert "not found" in status.error_message


@pytest.mark.asyncio
async def test_get_port_status_not_found(monkeypatch):
    engine = _FakeEngine(_FakeResult(TTSStatus.DONE, audio_path="/x.wav"))
    monkeypatch.setattr(pf, "get_default_engine", AsyncMock(return_value=engine))
    adapter = await pf.get_port()
    status = await adapter.get_status("nope")
    assert status.status == TTSStatus.PENDING


@pytest.mark.asyncio
async def test_get_port_result_not_ready(monkeypatch):
    engine = _FakeEngine(_FakeResult(TTSStatus.DONE, audio_path="/x.wav"))
    monkeypatch.setattr(pf, "get_default_engine", AsyncMock(return_value=engine))
    adapter = await pf.get_port()
    with pytest.raises(KeyError):
        await adapter.get_result("nope")


@pytest.mark.asyncio
async def test_get_port_cancel_running(tmp_path, monkeypatch):
    audio = tmp_path / "o.wav"
    audio.write_bytes(b"RIFF")
    engine = _FakeEngine(_FakeResult(TTSStatus.DONE, audio_path=str(audio)))
    monkeypatch.setattr(pf, "get_default_engine", AsyncMock(return_value=engine))
    adapter = await pf.get_port()
    await adapter.submit("c1", TTSTaskPayload(text="x", voice_anchor=TTSVoiceAnchor(voice_id="c1")))
    # immediately try cancel before synthesis finishes
    await adapter.cancel("c1")
    # Allow the background task to run and settle
    for _ in range(20):
        await asyncio.sleep(0)
    status = await adapter.get_status("c1")
    assert status.status in (TTSStatus.DONE, TTSStatus.FAILED)


@pytest.mark.asyncio
async def test_engine_context_provided(monkeypatch):
    reg = MagicMock()
    reg.close_all = AsyncMock()
    async with pf.engine_context(reg) as got:
        assert got is reg
    reg.close_all.assert_awaited_once()


@pytest.mark.asyncio
async def test_engine_context_default(monkeypatch):
    fake_reg = MagicMock()
    fake_reg.close_all = AsyncMock()

    async def fake_create():
        return fake_reg

    monkeypatch.setattr(pf, "create_configured_registry", fake_create)

    async with pf.engine_context() as got:
        assert got is fake_reg
    fake_reg.close_all.assert_awaited_once()

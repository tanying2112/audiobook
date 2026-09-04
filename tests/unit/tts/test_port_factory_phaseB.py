"""Phase B structural tests for tts/port_factory.py."""

import threading

import pytest

from src.audiobook_studio.tts import port_factory as pf
from src.audiobook_studio.tts.fake_port import FakeRemoteTTSPort, MockRemoteTTSPort

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


def test_streaming_config_base_url():
    c = pf.StreamingTTSConfig(engine="cosyvoice_stream", host="h", port=9000)
    assert c.base_url == "http://h:9000"


def test_streaming_config_mock_mode(monkeypatch):
    monkeypatch.delenv("MOCK_TTS", raising=False)
    c = pf.StreamingTTSConfig(engine="x")
    assert c.mock_mode is False
    monkeypatch.setenv("MOCK_TTS", "true")
    assert c.mock_mode is True


def test_streaming_config_chunk_samples():
    c = pf.StreamingTTSConfig(engine="x", sample_rate=24000, chunk_size_ms=100)
    assert c.chunk_samples == 2400
    c2 = pf.StreamingTTSConfig(engine="x", sample_rate=16000, chunk_size_ms=50)
    assert c2.chunk_samples == 800


def test_zero_shot_clone_config_base_url():
    c = pf.ZeroShotCloneConfig(engine="xtts_v2", host="h", port=9000)
    assert c.base_url == "http://h:9000"


def test_zero_shot_clone_mock_mode(monkeypatch):
    monkeypatch.delenv("MOCK_TTS", raising=False)
    c = pf.ZeroShotCloneConfig(engine="x")
    assert c.mock_mode is False
    monkeypatch.setenv("MOCK_TTS", "true")
    assert c.mock_mode is True


# ---------------------------------------------------------------------------
# _get_lock
# ---------------------------------------------------------------------------


def test_get_lock_returns_usable_lock():
    lock = pf._get_lock()
    assert isinstance(lock, type(threading.Lock()))
    assert lock.acquire(timeout=0.1)
    lock.release()


# ---------------------------------------------------------------------------
# create_engine
# ---------------------------------------------------------------------------


def test_create_engine_fake_no_kwargs():
    engine = pf.create_engine("fake")
    assert isinstance(engine, FakeRemoteTTSPort)


def test_create_engine_fake_passes_kwargs():
    engine = pf.create_engine("fake", synthesis_delay=0.0, failure_rate=0.0)
    assert isinstance(engine, FakeRemoteTTSPort)


def test_create_engine_fake_invalid_kwargs_raises():
    with pytest.raises(ValueError):
        pf.create_engine("fake", failure_rate=2.0)
    with pytest.raises(ValueError):
        pf.create_engine("fake", synthesis_delay=-1.0)


def test_create_engine_mock():
    engine = pf.create_engine("mock")
    assert isinstance(engine, MockRemoteTTSPort)


def test_create_engine_auto_mock_llm(monkeypatch):
    for v in ("MOCK_LLM", "TEST_MODE", "VOXCPM2_ENDPOINT"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("MOCK_LLM", "true")
    engine = pf.create_engine("auto")
    assert isinstance(engine, FakeRemoteTTSPort)


def test_create_engine_auto_test_mode(monkeypatch):
    for v in ("MOCK_LLM", "TEST_MODE", "VOXCPM2_ENDPOINT"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("TEST_MODE", "true")
    engine = pf.create_engine("auto")
    assert isinstance(engine, FakeRemoteTTSPort)


def test_create_engine_unknown_raises():
    with pytest.raises(ValueError):
        pf.create_engine("not-a-real-engine")


# ---------------------------------------------------------------------------
# _build_config_from_env
# ---------------------------------------------------------------------------


@pytest.fixture
def clean_env(monkeypatch):
    for v in (
        "ENABLE_LOCAL_TTS",
        "EDGE_TTS_ENABLED",
        "EDGE_TTS_VOICE",
        "AUDIO_OUTPUT_DIR",
        "KOKORO_MODEL_PATH",
        "VOXCPM2_ENDPOINT",
        "VOXCPM2_REMOTE_URL",
        "COSYVOICE_STREAM_ENDPOINT",
        "SEED_TTS_STREAM_ENDPOINT",
        "MELOTTS_STREAM_ENDPOINT",
        "XTTS_V2_ENDPOINT",
        "OPENVOICE_V2_ENDPOINT",
        "COSYVOICE_CLONE_ENDPOINT",
    ):
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def test_build_config_default_local_kokoro(clean_env):
    config = pf._build_config_from_env()
    assert "kokoro" in config
    assert config["kokoro"]["output_dir"] == "./output"
    assert config["kokoro"]["max_concurrent"] == 2
    assert "edge" not in config


def test_build_config_local_disabled_adds_edge(clean_env):
    clean_env.setenv("ENABLE_LOCAL_TTS", "false")
    config = pf._build_config_from_env()
    assert "kokoro" not in config
    assert "edge" in config


def test_build_config_kokoro_model_path(clean_env):
    clean_env.setenv("KOKORO_MODEL_PATH", "/models/kokoro.onnx")
    config = pf._build_config_from_env()
    assert config["kokoro"]["model_path"] == "/models/kokoro.onnx"


def test_build_config_edge_enabled(clean_env):
    clean_env.setenv("EDGE_TTS_ENABLED", "true")
    clean_env.setenv("EDGE_TTS_VOICE", "zh-CN-YunxiNeural")
    config = pf._build_config_from_env()
    assert config["edge"]["voice"] == "zh-CN-YunxiNeural"
    assert config["edge"]["max_concurrent"] == 4


def test_build_config_voxcpm2_endpoint(clean_env):
    clean_env.setenv("VOXCPM2_ENDPOINT", "http://vox:7000")
    config = pf._build_config_from_env()
    assert config["voxcpm2"]["endpoint"] == "http://vox:7000"
    assert config["voxcpm2"]["timeout_sec"] == 60


def test_build_config_voxcpm2_remote_url(clean_env):
    clean_env.setenv("VOXCPM2_REMOTE_URL", "https://vox.modal.dev")
    config = pf._build_config_from_env()
    assert config["voxcpm2"]["endpoint"] == "https://vox.modal.dev"


def test_build_config_streaming_endpoint(clean_env):
    clean_env.setenv("COSYVOICE_STREAM_ENDPOINT", "http://cosy:5500")
    config = pf._build_config_from_env()
    assert config["cosyvoice_stream"]["host"] == "cosy"
    assert config["cosyvoice_stream"]["port"] == 5500
    assert config["cosyvoice_stream"]["sample_rate"] == 24000


def test_build_config_clone_endpoint(clean_env):
    clean_env.setenv("XTTS_V2_ENDPOINT", "http://xtts:5510")
    config = pf._build_config_from_env()
    assert config["xtts_v2"]["host"] == "xtts"
    assert config["xtts_v2"]["port"] == 5510


def test_build_config_env_overrides_defaults(clean_env):
    clean_env.setenv("AUDIO_OUTPUT_DIR", "/tmp/audio")
    clean_env.setenv("KOKORO_MAX_CONCURRENT", "8")
    config = pf._build_config_from_env()
    assert config["kokoro"]["output_dir"] == "/tmp/audio"
    assert config["kokoro"]["max_concurrent"] == 8

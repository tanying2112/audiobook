"""Phase B structural tests for tts/engine.py (EngineRegistry + dataclasses)."""

import asyncio

import pytest

from src.audiobook_studio.tts import engine as eng_mod
from src.audiobook_studio.tts.engine import (
    LicenseMetadata,
    SynthesisResult,
    TTSProsody,
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSVoiceAnchor,
    VoiceInfo,
)


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


def test_license_metadata_defaults():
    m = LicenseMetadata()
    assert m.commercial_use is None
    assert m.license_name is None
    assert m.note == ""
    assert m.verified_at is None


def test_voice_info_defaults():
    v = VoiceInfo(voice_id="v1", name="n", language="zh", gender="f")
    assert v.gender == "f"
    assert v.sample_rate == 24000
    assert v.supports_prosody is True
    assert v.license_metadata is None


def test_synthesis_result_defaults():
    r = SynthesisResult(
        audio_path="/a.wav",
        duration_ms=100,
        engine="kokoro",
        voice_id="v1",
        text_hash="h",
    )
    assert r.sample_rate == 24000
    assert r.channels == 1
    assert r.metadata is None


def test_engine_voice_anchor_valid_and_invalid():
    a = TTSVoiceAnchor(voice_id="v1")
    assert a.voice_id == "v1"
    with pytest.raises(ValueError):
        TTSVoiceAnchor(voice_id="")


def test_engine_prosody_seed():
    p = TTSProsody(rate=1.3, seed=7)
    assert p.rate == 1.3
    assert p.seed == 7


def test_engine_task_payload_valid_and_invalid():
    anchor = TTSVoiceAnchor(voice_id="v1")
    payload = TTSTaskPayload(text="hi", voice_anchor=anchor)
    assert payload.text == "hi"
    with pytest.raises(ValueError):
        TTSTaskPayload(text=" ", voice_anchor=anchor)
    with pytest.raises(TypeError):
        TTSTaskPayload(text="hi", voice_anchor="bad")


def test_engine_task_result_and_status():
    r = TTSTaskResult(task_id="t", status="DONE", audio_path="/a.wav", engine="kokoro")
    assert r.engine == "kokoro"
    assert r.status == "DONE"
    s = TTSTaskStatus(task_id="t", status="RUNNING", progress=0.3)
    assert s.progress == 0.3


# ---------------------------------------------------------------------------
# EngineRegistry
# ---------------------------------------------------------------------------


class FakeEngine:
    def __init__(self, name="fake", loaded=True):
        self.engine_name = name
        self._loaded = loaded
        self.closed = False
        self.init_called = False

    async def initialize(self):
        self.init_called = True
        self._loaded = True

    async def close(self):
        self.closed = True

    async def health_check(self):
        return {"healthy": True}


@pytest.fixture
def registry():
    return eng_mod.EngineRegistry()


def test_register_and_get(registry):
    e = FakeEngine("alpha")
    _run(registry.register(e))
    assert registry.get("alpha") is e
    assert registry.get_default() is e
    assert registry.list_engines() == ["alpha"]


def test_register_explicit_name_and_default(registry):
    e = FakeEngine("beta")
    _run(registry.register(e, name="custom", set_as_default=True))
    assert registry.get("custom") is e
    assert registry.get_default() is e


def test_register_second_not_default(registry):
    a = FakeEngine("a")
    b = FakeEngine("b")
    _run(registry.register(a))
    _run(registry.register(b))
    assert registry.get_default() is a
    assert set(registry.list_engines()) == {"a", "b"}


def test_register_active_profile_blocked(monkeypatch, registry):
    monkeypatch.setattr(
        "src.audiobook_studio.tts.license_guard.load_license_registry",
        lambda *a, **k: {
            "blocked": type(
                "X",
                (),
                {
                    "commercial_use": False,
                    "license_name": None,
                    "note": "",
                    "verified_at": None,
                },
            )()
        },
    )
    e = FakeEngine("blocked")
    _run(registry.register(e, active_profile="pro_studio"))
    assert registry.get("blocked") is None


def test_register_active_profile_free_allows(monkeypatch, registry):
    monkeypatch.setattr(
        "src.audiobook_studio.tts.license_guard.load_license_registry",
        lambda *a, **k: {
            "blocked": type(
                "X",
                (),
                {
                    "commercial_use": False,
                    "license_name": None,
                    "note": "",
                    "verified_at": None,
                },
            )()
        },
    )
    e = FakeEngine("blocked")
    _run(registry.register(e, active_profile="potato"))
    assert registry.get("blocked") is e


def test_register_active_profile_unverified_allows(monkeypatch, registry):
    monkeypatch.setattr(
        "src.audiobook_studio.tts.license_guard.load_license_registry",
        lambda *a, **k: {},
    )
    e = FakeEngine("unknown_engine")
    _run(registry.register(e, active_profile="pro_studio"))
    assert registry.get("unknown_engine") is e


def test_is_ready_and_ready_status(registry):
    e = FakeEngine("a", loaded=False)
    _run(registry.register(e))
    assert registry.is_ready is False
    assert registry.ready_status == {"a": False}
    e._loaded = True
    assert registry.is_ready is True
    assert registry.ready_status == {"a": True}


def test_warmup_loads_and_skips(registry):
    not_loaded = FakeEngine("nl", loaded=False)
    loaded = FakeEngine("ld", loaded=True)
    _run(registry.register(not_loaded))
    _run(registry.register(loaded))
    results = _run(registry.warmup())
    assert results["nl"] is True
    assert not_loaded.init_called is True
    assert results["ld"] is True
    assert loaded.init_called is False


def test_close_all(registry):
    e = FakeEngine("a")
    _run(registry.register(e))
    _run(registry.close_all())
    assert e.closed is True


def test_close_all_handles_exception(registry):
    class BoomEngine(FakeEngine):
        async def close(self):
            raise RuntimeError("boom")

    e = BoomEngine("boom")
    _run(registry.register(e))
    _run(registry.close_all())  # should not raise


def test_async_context_manager():
    reg = eng_mod.EngineRegistry()

    async def _go():
        async with reg as entered:
            assert entered is reg

    _run(_go())
    # close_all on empty registry is a no-op


def test_initialize_unknown_engine_warns(registry, caplog):
    import logging

    registry.config = {"not_real": {"x": 1}}
    with caplog.at_level(logging.WARNING):
        _run(registry.initialize())
    assert "not_real" not in registry.list_engines()
    assert any("Unknown engine type" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# license_guard.register_guard
# ---------------------------------------------------------------------------


def test_register_guard_unverified_allows(monkeypatch):
    from src.audiobook_studio.tts.license_guard import register_guard

    monkeypatch.setattr(
        "src.audiobook_studio.tts.license_guard.load_license_registry",
        lambda *a, **k: {},
    )
    assert register_guard("unknown", "pro_studio") is True
    assert register_guard("unknown", "potato") is True


def test_register_guard_false_commercial_blocked(monkeypatch):
    from src.audiobook_studio.tts.license_guard import register_guard

    meta = type(
        "X",
        (),
        {"commercial_use": False, "license_name": None, "note": "", "verified_at": None},
    )()

    monkeypatch.setattr(
        "src.audiobook_studio.tts.license_guard.load_license_registry",
        lambda *a, **k: {"eng": meta},
    )
    assert register_guard("eng", "pro_studio") is False
    assert register_guard("eng", "potato") is True


def test_register_guard_true_allows(monkeypatch):
    from src.audiobook_studio.tts.license_guard import register_guard

    meta = type(
        "X",
        (),
        {"commercial_use": True, "license_name": None, "note": "", "verified_at": None},
    )()

    monkeypatch.setattr(
        "src.audiobook_studio.tts.license_guard.load_license_registry",
        lambda *a, **k: {"eng": meta},
    )
    assert register_guard("eng", "pro_studio") is True


# ---------------------------------------------------------------------------
# probe_tts_engines
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code):
        self.status_code = status_code


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url):
        return _FakeResp(200)


@pytest.fixture
def clean_tts_env(monkeypatch):
    for v in (
        "KOKORO_MODEL_PATH",
        "VOXCPM2_ENDPOINT",
        "EDGE_TTS_HOST",
        "ENABLE_LOCAL_TTS",
    ):
        monkeypatch.delenv(v, raising=False)
    return monkeypatch


def test_probe_defaults_not_configured(clean_tts_env, monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    result = _run(eng_mod.probe_tts_engines(timeout=0.1))
    engines = result["engines"]
    assert engines["kokoro"] is False
    assert engines["voxcpm2"] is False
    assert engines["piper"] is False
    assert engines["edge"] is True
    assert result["details"]["piper"]["detail"]["reason"] == "not_implemented"


def test_probe_kokoro_model_present(clean_tts_env, monkeypatch, tmp_path):
    model = tmp_path / "kokoro.onnx"
    model.write_text("x")
    monkeypatch.setenv("KOKORO_MODEL_PATH", str(model))
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    result = _run(eng_mod.probe_tts_engines(timeout=0.1))
    assert result["engines"]["kokoro"] is True


def test_probe_voxcpm2_endpoint(clean_tts_env, monkeypatch):
    monkeypatch.setenv("VOXCPM2_ENDPOINT", "http://vox:7000")
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    result = _run(eng_mod.probe_tts_engines(timeout=0.1))
    assert result["engines"]["voxcpm2"] is True


def test_probe_overlay_registry_health(clean_tts_env, monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    reg = eng_mod.EngineRegistry()
    e = FakeEngine("custom")
    _run(reg.register(e))
    result = _run(eng_mod.probe_tts_engines(timeout=0.1, registry=reg))
    assert result["details"]["custom"]["healthy"] is True


def test_probe_overlay_health_timeout(clean_tts_env, monkeypatch):
    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)

    class SlowEngine(FakeEngine):
        async def health_check(self):
            raise asyncio.TimeoutError()

    reg = eng_mod.EngineRegistry()
    e = SlowEngine("slow")
    _run(reg.register(e))
    result = _run(eng_mod.probe_tts_engines(timeout=0.01, registry=reg))
    assert result["details"]["slow"]["healthy"] is False

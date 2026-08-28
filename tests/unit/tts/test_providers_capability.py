"""P0 capability-aware provider model — pure logic tests (mock mode, no GPU)."""

import importlib

import pytest

from audiobook_studio.tts import providers_config as pc


def test_gpu_backends_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ENABLE_GPU_BACKENDS", raising=False)
    assert pc.gpu_backends_enabled() is False


def test_gpu_backends_enabled_via_env(monkeypatch):
    monkeypatch.setenv("ENABLE_GPU_BACKENDS", "true")
    assert pc.gpu_backends_enabled() is True
    monkeypatch.setenv("ENABLE_GPU_BACKENDS", "1")
    assert pc.gpu_backends_enabled() is True


def test_capability_matrix_parsed():
    matrix = pc.capability_matrix()
    assert matrix["piper"].min_compute == "cpu"
    assert matrix["piper"].cloning is False
    assert "zh" in matrix["piper"].languages
    assert matrix["kokoro"].min_compute == "cpu"


def test_license_matrix_honest():
    lic = pc.license_matrix()
    # Piper/Kokoro verified commercial; Edge left unverified (None) per P2.11.
    assert lic["piper"].commercial_use is True
    assert lic["kokoro"].commercial_use is True
    assert lic["edge_tts"].commercial_use is None


def test_priority_map_preserved():
    assert pc.provider_priority_map() == {"piper": 0, "kokoro": 1, "edge_tts": 2}


def test_select_default_no_gpu(monkeypatch):
    monkeypatch.delenv("ENABLE_GPU_BACKENDS", raising=False)
    engine, mode = pc.select_engine(language="zh-CN")
    assert engine == "piper"
    assert mode == "standard"


def test_select_need_clone_degrades_to_preset_no_gpu(monkeypatch):
    monkeypatch.delenv("ENABLE_GPU_BACKENDS", raising=False)
    engine, mode = pc.select_engine(language="zh-CN", need_clone=True)
    # No GPU clone backend exists -> graceful "preset" degradation, never a gpu engine.
    assert mode == "preset"
    assert pc.capability_matrix()[engine].min_compute == "cpu"


def test_select_need_clone_with_gpu_env_still_preset(monkeypatch):
    # Even with GPU enabled, the config has no cloning-capable engine yet -> preset.
    monkeypatch.setenv("ENABLE_GPU_BACKENDS", "true")
    engine, mode = pc.select_engine(language="zh-CN", need_clone=True)
    assert mode == "preset"
    assert pc.capability_matrix()[engine].min_compute == "cpu"


def test_select_need_emotion_falls_back_to_cpu(monkeypatch):
    monkeypatch.delenv("ENABLE_GPU_BACKENDS", raising=False)
    engine, mode = pc.select_engine(language="zh-CN", need_emotion=True)
    assert mode == "standard"
    assert pc.capability_matrix()[engine].min_compute == "cpu"


def test_engine_module_skips_gpu_when_disabled(monkeypatch):
    """engine._should_skip_engine must skip GPU-only engines when GPU is off."""
    from audiobook_studio.tts import engine as eng_mod

    monkeypatch.delenv("ENABLE_GPU_BACKENDS", raising=False)
    # Simulate a gpu clone engine present in the capability matrix (config has none today).
    base = dict(pc.capability_matrix())
    base["f5"] = pc.EngineCapability(cloning=True, min_compute="gpu")
    monkeypatch.setattr(pc, "capability_matrix", lambda *a, **k: base)

    # GPU disabled -> f5 (gpu) is skipped, kokoro (cpu) is not.
    assert eng_mod._should_skip_engine("f5", False) is True
    assert eng_mod._should_skip_engine("kokoro", False) is False

    # GPU enabled -> gpu engine is no longer skipped.
    monkeypatch.setenv("ENABLE_GPU_BACKENDS", "true")
    assert eng_mod._gpu_backends_enabled() is True
    assert eng_mod._should_skip_engine("f5", True) is False

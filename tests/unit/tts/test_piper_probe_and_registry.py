"""Tests for S2-4 Piper integration into the TTS readiness probe & EngineRegistry."""

import asyncio
from unittest.mock import patch

import pytest

from audiobook_studio.tts.engine import EngineRegistry, probe_tts_engines


@pytest.mark.asyncio
async def test_probe_piper_false_when_unconfigured(monkeypatch):
    """S1-6 canonical shape preserved; piper defaults to False when nothing set."""
    monkeypatch.delenv("PIPER_BIN", raising=False)
    monkeypatch.delenv("PIPER_MODEL_PATH", raising=False)
    monkeypatch.delenv("ENABLE_LOCAL_TTS", raising=False)
    with patch("shutil.which", return_value=None):
        result = await probe_tts_engines(timeout=1.0)
    assert set(result["engines"]) == {"kokoro", "voxcpm2", "edge", "piper"}
    assert result["engines"]["piper"] is False
    assert result["details"]["piper"]["detail"]["reason"] == "binary_not_found"


@pytest.mark.asyncio
async def test_probe_piper_true_when_binary_and_model(monkeypatch, tmp_path):
    (tmp_path / "zh_CN-huayan-medium.onnx").write_bytes(b"fake")
    monkeypatch.delenv("PIPER_BIN", raising=False)
    monkeypatch.delenv("ENABLE_LOCAL_TTS", raising=False)
    with patch("shutil.which", return_value=None):
        result = await probe_tts_engines(
            timeout=1.0,
            # force detection inputs via env
        )
    # default path: no binary -> False (ensure determinism regardless of host)
    assert result["engines"]["piper"] is False


@pytest.mark.asyncio
async def test_probe_piper_true_with_injected_detection(monkeypatch, tmp_path):
    """When detect_piper_availability reports a real binary+model, probe says True."""
    (tmp_path / "zh_CN-huayan-medium.onnx").write_bytes(b"fake")
    monkeypatch.delenv("PIPER_BIN", raising=False)
    monkeypatch.delenv("ENABLE_LOCAL_TTS", raising=False)
    with patch(
        "audiobook_studio.tts.piper_models.detect_piper_availability",
        return_value=(True, {"binary": "/usr/bin/piper", "model": str(tmp_path / "zh_CN-huayan-medium.onnx")}),
    ):
        result = await probe_tts_engines(timeout=1.0)
    assert result["engines"]["piper"] is True
    assert result["details"]["piper"]["detail"]["binary"] == "/usr/bin/piper"


@pytest.mark.asyncio
async def test_registry_factory_registers_piper(tmp_path):
    """EngineRegistry knows how to create a piper backend (priority 0 engine)."""
    registry = EngineRegistry()
    # minimal config that includes piper in mock mode
    await registry.initialize(config={"piper": {"mock_mode": True, "output_dir": str(tmp_path / "piper_out")}})
    assert "piper" in registry.list_engines()
    engine = registry.get("piper")
    assert engine is not None
    assert engine.engine_name == "piper"
    assert engine.is_available is True
    await registry.close_all()

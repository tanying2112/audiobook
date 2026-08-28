"""S2-4: tts_voices.py probe must surface Piper (priority 0) as available."""

from unittest.mock import AsyncMock, patch

import pytest

from src.audiobook_studio.api import tts_voices as tv
from src.audiobook_studio.tts.providers_config import provider_priority_map


@pytest.mark.asyncio
async def test_piper_engine_present_with_priority_zero():
    """/voices includes Piper with the configured priority (0)."""
    result = await tv.list_tts_voices()
    assert "piper" in result.engines
    piper_engine = result.engines["piper"]
    # Priority sourced from config/tts_providers.yaml (piper=0).
    assert piper_engine.priority == provider_priority_map().get("piper", 0)
    assert piper_engine.priority == 0
    piper_ids = {v.id for v in piper_engine.voices}
    assert "zh_CN-huayan-medium" in piper_ids


@pytest.mark.asyncio
async def test_piper_available_reflected_in_voices(monkeypatch):
    """When detection finds a real binary+model, piper.available is True."""
    monkeypatch.delenv("ENABLE_LOCAL_TTS", raising=False)
    with patch(
        "src.audiobook_studio.api.tts_voices.detect_piper_availability",
        return_value=(True, {"binary": "/usr/bin/piper", "model": "m.onnx"}),
    ):
        result = await tv.list_tts_voices()
        assert result.engines["piper"].available is True


@pytest.mark.asyncio
async def test_piper_unavailable_honest_when_no_binary(monkeypatch):
    """When no binary/model, piper.available stays False (no false happiness)."""
    monkeypatch.delenv("ENABLE_LOCAL_TTS", raising=False)
    with patch(
        "src.audiobook_studio.api.tts_voices.detect_piper_availability",
        return_value=(False, {"reason": "binary_not_found"}),
    ):
        result = await tv.list_tts_voices()
        assert result.engines["piper"].available is False


@pytest.mark.asyncio
async def test_status_includes_piper_fields(monkeypatch):
    """/status returns piper_available / piper_model_loaded (defaults to False)."""
    monkeypatch.delenv("ENABLE_LOCAL_TTS", raising=False)
    with patch(
        "src.audiobook_studio.api.tts_voices.detect_piper_availability",
        return_value=(False, {"reason": "binary_not_found"}),
    ), patch(
        "edge_tts.list_voices", new=AsyncMock(side_effect=Exception("offline"))
    ):
        status = await tv.get_tts_status()
        assert hasattr(status, "piper_available")
        assert status.piper_available is False
        assert status.piper_model_loaded is False


@pytest.mark.asyncio
async def test_status_piper_available_sets_recommended(monkeypatch):
    """When Piper is available, it becomes the recommended engine."""
    monkeypatch.delenv("ENABLE_LOCAL_TTS", raising=False)
    with patch(
        "src.audiobook_studio.api.tts_voices.detect_piper_availability",
        return_value=(True, {"binary": "/usr/bin/piper", "model": "m.onnx"}),
    ), patch(
        "edge_tts.list_voices", new=AsyncMock(side_effect=Exception("offline"))
    ):
        status = await tv.get_tts_status()
        assert status.piper_available is True
        assert status.recommended_engine == "piper"
        assert status.recommended_voice == "zh_CN-huayan-medium"

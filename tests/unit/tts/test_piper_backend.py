"""Tests for S2-4 PiperBackend (TTSEngine implementation)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from audiobook_studio.tts.engine import (
    TTSTaskPayload,
    TTSVoiceAnchor,
)
from audiobook_studio.tts.piper_backend import PiperBackend, create_piper_backend
from audiobook_studio.tts.piper_models import detect_piper_availability


@pytest.fixture
def mock_payload():
    return TTSTaskPayload(
        text="这是一个测试句子。",
        voice_anchor=TTSVoiceAnchor(voice_id="zh_CN-huayan-medium"),
    )


@pytest.mark.asyncio
async def test_mock_mode_initialize_and_available(tmp_path):
    backend = PiperBackend(mock_mode=True, output_dir=str(tmp_path))
    await backend.initialize()
    assert backend.is_available is True
    assert backend.engine_name == "piper"


@pytest.mark.asyncio
async def test_mock_mode_synthesize_writes_file(tmp_path, mock_payload):
    backend = PiperBackend(mock_mode=True, output_dir=str(tmp_path))
    await backend.initialize()
    out = tmp_path / "out.wav"
    result = await backend.synthesize(mock_payload, out)
    assert result.status == "DONE"
    assert Path(result.audio_path).exists()
    assert result.engine == "piper"
    assert result.voice_id == "zh_CN-huayan-medium"
    assert result.duration_ms > 0


@pytest.mark.asyncio
async def test_get_voices_returns_catalogue(tmp_path):
    backend = PiperBackend(mock_mode=True, output_dir=str(tmp_path))
    await backend.initialize()
    voices = backend.get_voices()
    ids = {v.voice_id for v in voices}
    assert "zh_CN-huayan-medium" in ids
    assert all(v.engine == "piper" for v in voices)


@pytest.mark.asyncio
async def test_estimate_duration_chinese():
    backend = PiperBackend(mock_mode=True)
    # ~10 Chinese chars -> ~2s
    dur = backend.estimate_duration("一二三四五六七八九十", "zh_CN-huayan-medium")
    assert 1500 <= dur <= 3000


@pytest.mark.asyncio
async def test_factory_creates_initialized_backend(tmp_path):
    backend = await create_piper_backend(mock_mode=True, output_dir=str(tmp_path))
    assert backend.is_available is True
    assert isinstance(backend, PiperBackend)


@pytest.mark.asyncio
async def test_real_initialize_raises_without_binary(tmp_path):
    with patch("shutil.which", return_value=None), patch.dict("os.environ", {}, clear=True):
        backend = PiperBackend(mock_mode=False, output_dir=str(tmp_path), auto_download=False)
        with pytest.raises(RuntimeError):
            await backend.initialize()


@pytest.mark.asyncio
async def test_real_initialize_downloads_model(tmp_path):
    """When binary present + auto_download, missing model triggers download."""
    model_dir = tmp_path / "models" / "piper"
    with patch("shutil.which", return_value="/usr/bin/piper"), patch.dict("os.environ", {}, clear=True), patch(
        "audiobook_studio.tts.piper_backend.ensure_piper_models", return_value=True
    ) as mock_dl, patch(
        "audiobook_studio.tts.piper_backend.get_piper_model_path"
    ) as mock_path:
        mock_path.return_value = (model_dir / "zh_CN-huayan-medium.onnx", model_dir / "zh_CN-huayan-medium.onnx.json")
        backend = PiperBackend(
            mock_mode=False, output_dir=str(tmp_path), auto_download=True, model_dir=str(model_dir)
        )
        await backend.initialize()
        mock_dl.assert_called_once()
        assert backend.is_available is True


@pytest.mark.asyncio
async def test_health_check_reports_real_detection(tmp_path):
    backend = PiperBackend(mock_mode=True, output_dir=str(tmp_path))
    await backend.initialize()
    health = await backend.health_check()
    assert health["engine"] == "piper"
    assert health["healthy"] is True


@pytest.mark.asyncio
async def test_stream_yields_bytes_mock(tmp_path, mock_payload):
    backend = PiperBackend(mock_mode=True, output_dir=str(tmp_path))
    await backend.initialize()
    chunks = [c async for c in backend.stream(mock_payload)]
    assert chunks  # at least one chunk
    assert all(isinstance(c, bytes) for c in chunks)


def test_static_detect_wrapper():
    # detect() is a thin wrapper; ensure it returns (bool, dict)
    available, detail = PiperBackend.detect()
    assert isinstance(available, bool)
    assert isinstance(detail, dict)

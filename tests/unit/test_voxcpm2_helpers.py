"""Targeted tests for VoxCPM2Backend mock-mode branches."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from src.audiobook_studio.tts.voxcpm2_backend import (
    QUANTIZATION_MODES,
    VOXCPM2_VOICES,
    VoxCPM2Backend,
    create_voxcpmp2_backend,
)


def setUpModule():
    """Re-import the real voxcpm2_backend if an earlier test mocked it.

    Some suites (e.g. pipeline/test_synthesize_nonmock.py) temporarily mock
    ``audiobook_studio.tts`` in sys.modules during import. If the mock is
    present when this module is imported, the top-level symbols above may be
    bound to MagicMock classes rather than the real ``VoxCPM2Backend``.
    """
    import importlib
    import sys

    sys.modules.pop("src.audiobook_studio.tts.voxcpm2_backend", None)
    sys.modules.pop("src.audiobook_studio.tts", None)
    real = importlib.import_module("src.audiobook_studio.tts.voxcpm2_backend")
    global QUANTIZATION_MODES, VOXCPM2_VOICES, VoxCPM2Backend, create_voxcpmp2_backend
    QUANTIZATION_MODES = real.QUANTIZATION_MODES
    VOXCPM2_VOICES = real.VOXCPM2_VOICES
    VoxCPM2Backend = real.VoxCPM2Backend
    create_voxcpmp2_backend = real.create_voxcpmp2_backend


class TestVoxCPM2BackendInit:
    def test_engine_name(self):
        b = VoxCPM2Backend()
        assert b.engine_name == "voxcpmp2"

    def test_supports_streaming(self):
        b = VoxCPM2Backend()
        assert b.supports_streaming is True

    def test_supports_batch(self):
        b = VoxCPM2Backend()
        assert b.supports_batch is True

    def test_init_with_defaults(self):
        b = VoxCPM2Backend()
        assert b.dtype == "float16"
        assert b.batch_size == 4
        assert b.sample_rate == 48000
        assert b.kv_cache_reuse is True
        assert b.compile_model is True
        assert b.mock_mode is True

    def test_init_with_custom_params(self):
        b = VoxCPM2Backend(
            model_path="/tmp/m",
            device="cpu",
            dtype="int8",
            sample_rate=44100,
            batch_size=8,
            kv_cache_reuse=False,
            compile_model=False,
        )
        assert b.dtype == "int8"
        assert b.batch_size == 8
        assert b.sample_rate == 44100
        assert b.device == "cpu"
        assert b.kv_cache_reuse is False
        assert b.compile_model is False


class TestVoxCPM2Init:
    @pytest.mark.asyncio
    async def test_initialize_mock_mode(self):
        b = VoxCPM2Backend()
        await b.initialize()
        assert b._initialized is True

    def test_init_voice_embeddings_copy(self):
        b1 = VoxCPM2Backend()
        b2 = VoxCPM2Backend()
        # Mutating b1's voice embeddings should not affect b2
        b1._voice_embeddings["custom"] = {"name": "c", "language": "x"}
        assert "custom" not in b2._voice_embeddings


class TestVoxCPM2VoiceEmbedding:
    def test_get_voice_embedding_known_voice(self):
        b = VoxCPM2Backend()
        result = b._get_voice_embedding("zh_female_1")
        assert result is not None
        assert result["name"] == "zh_female_1"

    def test_get_voice_embedding_unknown_falls_back(self):
        b = VoxCPM2Backend()
        result = b._get_voice_embedding("totally_unknown_voice_id")
        assert result is not None
        assert result["name"] == "zh_female_1"  # default fallback

    def test_get_voice_embedding_with_reference_audio(self, tmp_path: Path):
        b = VoxCPM2Backend()
        ref_path = tmp_path / "ref.wav"
        ref_path.write_bytes(b"\x00" * 100)
        embedding = b._get_voice_embedding("zh_female_1", reference_audio=str(ref_path))
        assert embedding is not None
        # Second call should hit the cache and return same data
        embedding2 = b._get_voice_embedding("zh_female_1", reference_audio=str(ref_path))
        assert embedding is embedding2

    def test_get_voice_embedding_reference_nonexistent(self, tmp_path: Path):
        b = VoxCPM2Backend()
        # Reference audio path that doesn't exist: falls back to voice_id lookup
        embedding = b._get_voice_embedding("zh_male_1", reference_audio="/no/such/path/file.wav")
        assert embedding is not None
        assert embedding["name"] == "zh_male_1"


class TestVoxCPM2Synthesize:
    @pytest.mark.asyncio
    async def test_synthesize_mock_mode(self, tmp_path: Path):
        b = VoxCPM2Backend()
        out = tmp_path / "out.wav"
        result = await b.synthesize(
            text="你好 hello",
            voice_id="zh_female_1",
            output_path=out,
        )
        assert result.duration_ms == 1000
        assert result.engine == "voxcpmp2"
        assert result.sample_rate == 48000
        assert out.exists()

    @pytest.mark.asyncio
    async def test_synthesize_returns_text_hash(self, tmp_path: Path):
        b = VoxCPM2Backend()
        out = tmp_path / "out.wav"
        result = await b.synthesize(
            text="unique_test_string",
            voice_id="zh_female_1",
            output_path=out,
        )
        assert result.text_hash is not None
        assert len(result.text_hash) == 12


class TestVoxCPM2Voices:
    def test_get_voices_returns_all(self):
        b = VoxCPM2Backend()
        voices = b.get_voices()
        assert len(voices) == len(VOXCPM2_VOICES)
        for v in voices:
            assert v.engine == "voxcpmp2"
            assert v.supports_reference_audio is True

    def test_quantization_modes_have_required_keys(self):
        for _mode, info in QUANTIZATION_MODES.items():
            assert "dtype" in info
            assert "vram_gb" in info
            assert "min_vram_gb" in info


class TestVoxCPM2EstimateDuration:
    def test_estimate_duration_chinese(self):
        b = VoxCPM2Backend()
        d = b.estimate_duration("你好世界", "zh_female_1")
        # 5 chars/sec → 4 chars → ~0.8 sec → ~800ms; min is 500
        assert d >= 500

    def test_estimate_duration_english(self):
        b = VoxCPM2Backend()
        d = b.estimate_duration("Hello World", "en_female_1")
        assert d >= 500

    def test_estimate_duration_with_prosody_rate(self):
        b = VoxCPM2Backend()
        kwargs = {"prosody": {"rate": 2.0}}
        d_fast = b.estimate_duration("你好世界", "zh_female_1", **kwargs)
        kwargs = {"prosody": {"rate": 0.5}}
        d_slow = b.estimate_duration("你好世界", "zh_female_1", **kwargs)
        # Faster speech = shorter duration
        assert d_fast < d_slow

    def test_estimate_duration_empty_string(self):
        b = VoxCPM2Backend()
        # Empty → still returns min 500ms
        d = b.estimate_duration("", "v")
        assert d == 500


class TestVoxCPM2Cleanup:
    @pytest.mark.asyncio
    async def test_cleanup_mock_mode(self):
        b = VoxCPM2Backend()
        await b.initialize()
        await b.cleanup()
        assert b._initialized is False
        assert b._model is None
        assert b._tokenizer is None
        assert b._reference_audio_cache == {}


class TestVoxCPM2Factory:
    @pytest.mark.asyncio
    async def test_create_factory(self):
        backend = await create_voxcpmp2_backend()
        assert isinstance(backend, VoxCPM2Backend)
        assert backend._initialized is True


class TestVoxCPM2SynthesizeEdge:
    @pytest.mark.asyncio
    async def test_synthesize_with_prosody(self, tmp_path: Path):
        b = VoxCPM2Backend()
        out = tmp_path / "out.wav"
        prosody = {"rate": 1.0, "pitch": 0, "volume": 0}
        result = await b.synthesize(
            text="hello",
            voice_id="zh_female_1",
            output_path=out,
            prosody=prosody,
        )
        assert result.audio_path == str(out)

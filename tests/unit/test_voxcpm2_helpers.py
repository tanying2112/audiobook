"""Targeted tests for VoxCPM2Backend mock-mode branches with deep assertions."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.audiobook_studio.tts.voxcpm2_backend import (
    QUANTIZATION_MODES,
    VOXCPM2_VOICES,
    VoxCPM2Backend,
    create_voxcpm2_backend,
)
from src.audiobook_studio.tts.engine import TTSProsody, TTSVoiceAnchor, TTSTaskPayload, TTSTaskResult


def setUpModule():
    os.environ["MOCK_LLM"] = "true"


class TestVoxCPM2BackendInit:
    """Tests for VoxCPM2Backend initialization."""

    def test_engine_name(self):
        """Test engine_name property."""
        backend = VoxCPM2Backend()
        assert backend.engine_name == "voxcpm2"

    def test_is_available_before_init(self):
        """Test is_available before initialization."""
        backend = VoxCPM2Backend()
        assert backend.is_available is False

    def test_is_available_after_init(self):
        """Test is_available after initialization."""
        backend = VoxCPM2Backend()
        backend.mock_mode = True
        import asyncio
        asyncio.run(backend.initialize())
        assert backend.is_available is True

    def test_init_with_defaults(self):
        """Test default initialization."""
        backend = VoxCPM2Backend()
        assert backend.mock_mode is True  # MOCK_LLM=true from setUpModule
        assert backend.dtype == "float16"
        assert backend.batch_size == 4
        assert backend.kv_cache_reuse is True
        assert backend.compile_model is True
        assert backend._model is None
        assert backend._tokenizer is None
        assert backend._voice_embeddings == VOXCPM2_VOICES
        assert backend._reference_audio_cache == {}

    def test_init_with_custom_params(self):
        """Test initialization with custom parameters."""
        backend = VoxCPM2Backend(
            model_path="/custom/model/path",
            device="cpu",
            dtype="float32",
            batch_size=8,
            kv_cache_reuse=False,
            compile_model=False,
        )
        assert backend.model_path == "/custom/model/path"
        assert backend.device == "cpu"
        assert backend.dtype == "float32"
        assert backend.batch_size == 8
        assert backend.kv_cache_reuse is False
        assert backend.compile_model is False


class TestVoxCPM2VoiceEmbedding:
    """Tests for voice embedding retrieval."""

    def test_get_voice_embedding_known_voice(self):
        """Test _get_voice_embedding with predefined voice."""
        backend = VoxCPM2Backend()
        embedding = backend._get_voice_embedding("zh_female_1")
        # In mock mode, returns random tensor; in real mode returns from VOXCPM2_VOICES
        assert embedding is not None

    def test_get_voice_embedding_unknown_falls_back(self):
        """Test _get_voice_embedding falls back to default for unknown voice."""
        backend = VoxCPM2Backend()
        embedding = backend._get_voice_embedding("nonexistent_voice")
        assert embedding is not None

    def test_get_voice_embedding_with_reference_audio(self, tmp_path):
        """Test _get_voice_embedding with reference audio."""
        backend = VoxCPM2Backend()
        backend.mock_mode = True
        # Create a fake reference audio file
        ref_audio = tmp_path / "reference.wav"
        ref_audio.write_bytes(b"fake wav data")

        with patch("pathlib.Path.exists", return_value=True):
            with patch("hashlib.md5") as mock_md5:
                mock_hash = MagicMock()
                mock_hash.hexdigest.return_value = "fakehash123"
                mock_md5.return_value = mock_hash

                with patch.object(backend, "_reference_audio_cache", {}):
                    embedding = backend._get_voice_embedding("zh_female_1", str(ref_audio))
                    assert embedding is not None

    def test_get_voice_embedding_reference_nonexistent(self):
        """Test _get_voice_embedding with nonexistent reference audio falls back."""
        backend = VoxCPM2Backend()
        backend.mock_mode = True
        with patch("pathlib.Path.exists", return_value=False):
            embedding = backend._get_voice_embedding("zh_female_1", "/nonexistent/path.wav")
            # Should fall back to predefined embedding
            assert embedding is not None


class TestVoxCPM2Synthesize:
    """Tests for synthesize method in mock mode."""

    @pytest.mark.asyncio
    async def test_synthesize_mock_mode(self):
        """Test synthesize in mock mode with TTSTaskPayload protocol."""
        b = VoxCPM2Backend()
        b.mock_mode = True
        await b.initialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out.wav"
            payload = TTSTaskPayload(
                text="hello",
                voice_anchor=TTSVoiceAnchor(voice_id="zh_female_1"),
            )
            result = await b.synthesize(payload, out)

            assert isinstance(result, TTSTaskResult)
            assert result.audio_path == str(out)
            assert result.status == "DONE"
            assert result.engine == "voxcpm2"
            assert result.text_hash is not None
            assert out.exists()
            assert out.stat().st_size > 0

    @pytest.mark.asyncio
    async def test_synthesize_returns_text_hash(self):
        """Test synthesize returns valid text_hash."""
        b = VoxCPM2Backend()
        b.mock_mode = True
        await b.initialize()

        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "out.wav"
            payload = TTSTaskPayload(
                text="test text for hashing",
                voice_anchor=TTSVoiceAnchor(voice_id="zh_female_1"),
            )
            result = await b.synthesize(payload, out)

            assert result.text_hash is not None
            assert len(result.text_hash) == 12  # SHA256 truncated to 12 chars


class TestVoxCPM2Voices:
    """Tests for get_voices method."""

    def test_get_voices_returns_all(self):
        """Test get_voices returns all predefined voices."""
        backend = VoxCPM2Backend()
        voices = backend.get_voices()
        assert len(voices) == len(VOXCPM2_VOICES)
        voice_ids = {v.voice_id for v in voices}
        assert voice_ids == set(VOXCPM2_VOICES.keys())

    def test_quantization_modes_have_required_keys(self):
        """Test QUANTIZATION_MODES dict has required keys."""
        for mode, info in QUANTIZATION_MODES.items():
            assert "dtype" in info
            assert "vram_gb" in info
            assert "min_vram_gb" in info


class TestVoxCPM2EstimateDuration:
    """Tests for estimate_duration method."""

    def test_estimate_duration_chinese(self):
        """Test duration estimation for Chinese text."""
        backend = VoxCPM2Backend()
        duration = backend.estimate_duration("你好世界", "zh_female_1")
        assert isinstance(duration, int)
        assert duration > 0
        assert duration >= 500

    def test_estimate_duration_english(self):
        """Test duration estimation for English text."""
        backend = VoxCPM2Backend()
        duration = backend.estimate_duration("Hello world", "en_female_1")
        assert isinstance(duration, int)
        assert duration > 0

    def test_estimate_duration_with_prosody_rate(self):
        """Test duration estimation respects prosody rate."""
        backend = VoxCPM2Backend()
        duration_normal = backend.estimate_duration("测试文本", "zh_female_1", prosody={"rate": 1.0})
        duration_fast = backend.estimate_duration("测试文本", "zh_female_1", prosody={"rate": 2.0})
        assert duration_fast < duration_normal

    def test_estimate_duration_empty_string(self):
        """Test duration estimation for empty string returns minimum."""
        backend = VoxCPM2Backend()
        duration = backend.estimate_duration("", "zh_female_1")
        assert duration == 500


class TestVoxCPM2Cleanup:
    """Tests for cleanup method."""

    @pytest.mark.asyncio
    async def test_cleanup_mock_mode(self):
        """Test cleanup in mock mode."""
        b = VoxCPM2Backend()
        b.mock_mode = True
        await b.initialize()
        await b.close()
        assert b._initialized is False
        assert b._model is None
        assert b._tokenizer is None
        assert b._reference_audio_cache == {}


class TestVoxCPM2Factory:
    """Tests for factory function."""

    @pytest.mark.asyncio
    async def test_create_factory(self):
        """Test create_voxcpm2_backend factory."""
        backend = await create_voxcpm2_backend(
            model_path="/fake/VoxCPM2",
            device="cpu",
            mock_mode=True,
        )
        assert isinstance(backend, VoxCPM2Backend)
        assert backend._initialized is True
        assert backend._loaded is True


class TestVoxCPM2SynthesizeEdge:
    """Edge case tests for synthesize."""

    @pytest.mark.asyncio
    async def test_synthesize_with_prosody(self, tmp_path: Path):
        """Test synthesize with prosody controls using protocol."""
        b = VoxCPM2Backend()
        b.mock_mode = True
        await b.initialize()
        out = tmp_path / "out.wav"
        prosody = TTSProsody(rate=1.0, pitch=0, volume=0)
        payload = TTSTaskPayload(
            text="hello",
            voice_anchor=TTSVoiceAnchor(voice_id="zh_female_1"),
            prosody=prosody,
        )
        result = await b.synthesize(payload, out)
        assert result.audio_path == str(out)
        assert result.status == "DONE"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
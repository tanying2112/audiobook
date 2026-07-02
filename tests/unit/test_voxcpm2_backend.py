"""Tests for voxcpm2_backend module."""

import hashlib
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from src.audiobook_studio.tts.voxcpm2_backend import (
    QUANTIZATION_MODES,
    VOXCPM2_VOICES,
    VoxCPM2Backend,
    create_voxcpmp2_backend,
)


class TestVoxCPM2BackendInit:
    """Tests for VoxCPM2Backend initialization."""

    def test_init_default(self):
        """Test default initialization."""
        import os

        os.environ["MOCK_LLM"] = "false"
        backend = VoxCPM2Backend()
        assert backend.mock_mode is False  # Default unless MOCK_LLM env var set
        assert backend.dtype == "float16"
        assert backend.batch_size == 4
        assert backend.kv_cache_reuse is True
        assert backend.compile_model is True
        assert backend._model is None
        assert backend._tokenizer is None
        assert backend._voice_embeddings == VOXCPM2_VOICES
        assert backend._reference_audio_cache == {}

    def test_init_custom(self):
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

    def test_init_mock_mode_from_env(self, monkeypatch):
        """Test initialization with MOCK_LLM environment variable."""
        monkeypatch.setenv("MOCK_LLM", "true")
        backend = VoxCPM2Backend()
        assert backend.mock_mode is True


class TestVoxCPM2BackendProperties:
    """Tests for VoxCPM2Backend properties."""

    def test_engine_name(self):
        """Test engine_name property."""
        backend = VoxCPM2Backend()
        assert backend.engine_name == "voxcpmp2"

    def test_supports_streaming(self):
        """Test supports_streaming property."""
        backend = VoxCPM2Backend()
        assert backend.supports_streaming is True

    def test_supports_batch(self):
        """Test supports_batch property."""
        backend = VoxCPM2Backend()
        assert backend.supports_batch is True


class TestVoxCPM2BackendMethods:
    """Tests for VoxCPM2Backend methods."""

    def test_get_voice_embedding_predefined(self):
        """Test _get_voice_embedding with predefined voice."""
        backend = VoxCPM2Backend()
        embedding = backend._get_voice_embedding("zh_female_1")
        # Should return the predefined embedding from VOXCPM2_VOICES
        assert isinstance(embedding, dict)  # Actually returns the dict from VOXCPM2_VOICES
        assert "name" in embedding
        assert embedding["name"] == "zh_female_1"

    def test_get_voice_embedding_with_reference(self, tmp_path, monkeypatch):
        """Test _get_voice_embedding with reference audio."""
        import os

        os.environ["MOCK_LLM"] = "true"

        # Re-import to pick up the new env var
        import importlib

        import src.audiobook_studio.tts.voxcpm2_backend as vcb

        importlib.reload(vcb)
        VoxCPM2Backend = vcb.VoxCPM2Backend

        from unittest.mock import patch

        backend = VoxCPM2Backend()
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
                    # Should return a tensor (placeholder implementation)
                    # In the actual implementation, this returns a torch tensor
                    assert embedding is not None

    def test_get_voice_embedding_fallback(self):
        """Test _get_voice_embedding fallback to default voice."""
        backend = VoxCPM2Backend()
        # Request a non-existent voice
        embedding = backend._get_voice_embedding("non_existent_voice")
        # Should fall back to zh_female_1
        assert isinstance(embedding, dict)
        assert embedding["name"] == "zh_female_1"

    @pytest.mark.asyncio
    async def test_synthesize_mock_mode(self, tmp_path):
        """Test synthesize in mock mode."""
        import os

        os.environ["MOCK_LLM"] = "true"

        try:
            backend = VoxCPM2Backend()
            output_path = tmp_path / "output.wav"

            result = await backend.synthesize(
                text="Hello world",
                voice_id="zh_female_1",
                output_path=output_path,
            )

            assert result.audio_path == str(output_path)
            assert result.engine == "voxcpmp2"
            assert result.voice_id == "zh_female_1"
            assert result.duration_ms == 1000  # Mock returns 1 second
            assert result.text_hash is not None
            assert len(result.text_hash) == 12  # First 12 chars of MD5
            assert output_path.exists()

        finally:
            # Clean up environment variable
            if "MOCK_LLM" in os.environ:
                del os.environ["MOCK_LLM"]

    def test_get_voices(self):
        """Test get_voices method."""
        backend = VoxCPM2Backend()
        voices = backend.get_voices()
        assert isinstance(voices, list)
        assert len(voices) == len(VOXCPM2_VOICES)
        # Check that all expected voices are present
        voice_names = [v.name for v in voices]
        for voice_id, info in VOXCPM2_VOICES.items():
            assert info["name"] in voice_names

    @pytest.mark.asyncio
    async def test_cleanup(self):
        """Test cleanup method."""
        backend = VoxCPM2Backend()
        # Set some state
        backend._model = "dummy_model"
        backend._tokenizer = "dummy_tokenizer"
        backend._voice_embeddings = {"test": "dummy_embedding"}
        backend._reference_audio_cache = {"key": "dummy_cache"}
        backend._initialized = True

        # Call cleanup
        await backend.cleanup()

        # Check that state is reset
        assert backend._model is None
        assert backend._tokenizer is None
        assert backend._voice_embeddings == {}
        assert backend._reference_audio_cache == {}
        assert backend._initialized is False

    @pytest.mark.asyncio
    async def test_create_voxcpmp2_backend(self):
        """Test factory function creates and initializes backend."""
        with patch("src.audiobook_studio.tts.voxcpm2_backend.VoxCPM2Backend") as mock_backend_class:
            mock_backend = MagicMock()
            mock_backend_class.return_value = mock_backend
            mock_backend.initialize = AsyncMock()

            backend = await create_voxcpmp2_backend(
                model_path="/test/model",
                device="cpu",
                dtype="float32",
            )

            # Check that the constructor was called with correct parameters
            mock_backend_class.assert_called_once_with(
                model_path="/test/model",
                device="cpu",
                dtype="float32",
            )
            # Check that initialize was called
            mock_backend.initialize.assert_called_once()
            # Check that the returned object is our mock
            assert backend == mock_backend


class TestQuantizationModes:
    """Tests for QUANTIZATION_MODES constant."""

    def test_quantization_modes_structure(self):
        """Test that QUANTIZATION_MODES has the expected structure."""
        assert isinstance(QUANTIZATION_MODES, dict)
        assert "fp32" in QUANTIZATION_MODES
        assert "fp16" in QUANTIZATION_MODES
        assert "bf16" in QUANTIZATION_MODES
        assert "int8" in QUANTIZATION_MODES

        for mode, info in QUANTIZATION_MODES.items():
            assert isinstance(info, dict)
            assert "dtype" in info
            assert "vram_gb" in info
            assert "min_vram_gb" in info
            assert isinstance(info["dtype"], str)
            assert isinstance(info["vram_gb"], float)
            assert isinstance(info["min_vram_gb"], (int, float))

    def test_voxcpm2_voices_structure(self):
        """Test that VOXCPM2_VOICES has the expected structure."""
        assert isinstance(VOXCPM2_VOICES, dict)
        assert len(VOXCPM2_VOICES) > 0

        for voice_id, info in VOXCPM2_VOICES.items():
            assert isinstance(info, dict)
            assert "name" in info
            assert "language" in info
            assert "gender" in info
            assert "description" in info
            assert isinstance(info["name"], str)
            assert isinstance(info["language"], str)
            assert isinstance(info["gender"], str)
            assert isinstance(info["description"], str)


class TestEdgeCases:
    """Tests for edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_initialize_import_error(self, monkeypatch):
        """
        ```markdown
        Test initialize when import of torch halted; None in sys.modules.
        """
        # Mock the import to raise ImportError
        with patch.dict("sys.modules", {"torch": None}):
            import os

            os.environ["MOCK_LLM"] = "false"
            backend = VoxCPM2Backend(mock_mode=False)  # Not in mock mode to trigger import
            with pytest.raises(ImportError, match="import of torch halted; None in sys.modules"):
                await backend.initialize()

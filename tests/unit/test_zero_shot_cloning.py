"""Tests for Zero-Shot Voice Cloning - XTTS-v2, OpenVoice V2, CosyVoice.

P2-4: Cross-lingual voice transfer with zero-shot cloning.
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.audiobook_studio.tts.zero_shot_clone import (
    ZeroShotCloneConfig,
    ZeroShotCloneEngine,
    ZeroShotCloneResult,
    create_zero_shot_clone_engine,
)
from src.audiobook_studio.tts.port import RemoteTTSPort


class TestZeroShotCloneConfig:
    """Test ZeroShotCloneConfig dataclass."""

    def test_default_values(self):
        config = ZeroShotCloneConfig(engine="xtts_v2")
        assert config.engine == "xtts_v2"
        assert config.host == "localhost"
        assert config.port == 5010
        assert config.sample_rate == 24000
        assert config.language == "auto"
        assert config.speed == 1.0
        assert config.timeout == 60

    def test_custom_values(self):
        config = ZeroShotCloneConfig(
            engine="openvoice_v2",
            host="127.0.0.1",
            port=5011,
            sample_rate=16000,
            language="zh",
            speed=1.2,
            timeout=120,
        )
        assert config.engine == "openvoice_v2"
        assert config.host == "127.0.0.1"
        assert config.port == 5011
        assert config.sample_rate == 16000
        assert config.language == "zh"
        assert config.speed == 1.2
        assert config.timeout == 120

    def test_cosyvoice_config(self):
        config = ZeroShotCloneConfig(
            engine="cosyvoice_clone",
            host="localhost",
            port=5012,
        )
        assert config.engine == "cosyvoice_clone"


class TestCreateZeroShotCloneEngine:
    """Test create_zero_shot_clone_engine factory function."""

    def test_create_xtts_v2(self):
        config = ZeroShotCloneConfig(engine="xtts_v2")
        engine = create_zero_shot_clone_engine(config)
        assert isinstance(engine, ZeroShotCloneEngine)
        assert engine.config.engine == "xtts_v2"

    def test_create_openvoice_v2(self):
        config = ZeroShotCloneConfig(engine="openvoice_v2")
        engine = create_zero_shot_clone_engine(config)
        assert isinstance(engine, ZeroShotCloneEngine)
        assert engine.config.engine == "openvoice_v2"

    def test_create_cosyvoice_clone(self):
        config = ZeroShotCloneConfig(engine="cosyvoice_clone")
        engine = create_zero_shot_clone_engine(config)
        assert isinstance(engine, ZeroShotCloneEngine)
        assert engine.config.engine == "cosyvoice_clone"

    def test_unknown_engine_raises(self):
        config = ZeroShotCloneConfig(engine="unknown_engine")
        with pytest.raises(ValueError, match="Unsupported zero-shot clone engine"):
            create_zero_shot_clone_engine(config)


class TestZeroShotCloneEngine:
    """Test ZeroShotCloneEngine functionality."""

    @pytest.fixture
    def xtts_config(self):
        return ZeroShotCloneConfig(
            engine="xtts_v2",
            host="localhost",
            port=5010,
        )

    @pytest.fixture
    def openvoice_config(self):
        return ZeroShotCloneConfig(
            engine="openvoice_v2",
            host="localhost",
            port=5011,
        )

    def test_init_mock_mode(self, xtts_config):
        """Test initialization in mock mode."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_zero_shot_clone_engine(xtts_config)
            assert engine.config.engine == "xtts_v2"

    def test_clone_mock_mode(self, xtts_config):
        """Test zero-shot cloning in mock mode."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_zero_shot_clone_engine(xtts_config)
            
            result = engine.clone(
                text="这是零样本克隆测试文本。",
                reference_audio=b"fake_reference_audio_data",
            )
            
            assert isinstance(result, ZeroShotCloneResult)
            assert result.audio_data is not None
            assert len(result.audio_data) > 0
            assert result.sample_rate == 24000
            assert result.latency_ms >= 0

    def test_clone_with_language(self, openvoice_config):
        """Test cloning with specific language."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_zero_shot_clone_engine(openvoice_config)
            
            result = engine.clone(
                text="This is English text for cloning.",
                reference_audio=b"fake_reference_audio_data",
                language="en",
            )
            
            assert isinstance(result, ZeroShotCloneResult)
            assert result.audio_data is not None

    def test_clone_stream_mock_mode(self, xtts_config):
        """Test streaming cloning in mock mode."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_zero_shot_clone_engine(xtts_config)
            
            chunks = list(engine.clone_stream(
                text="流式零样本克隆测试。",
                reference_audio=b"fake_reference_audio_data",
            ))
            
            assert len(chunks) > 0
            for chunk in chunks:
                assert isinstance(chunk, ZeroShotCloneResult)
                assert chunk.audio_data is not None

    def test_clone_empty_text(self, xtts_config):
        """Test cloning with empty text."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_zero_shot_clone_engine(xtts_config)
            
            result = engine.clone(
                text="",
                reference_audio=b"fake_reference_audio_data",
            )
            
            # Should handle gracefully
            assert isinstance(result, ZeroShotCloneResult)

    def test_mock_mode_via_config(self, xtts_config):
        """Test that config.mock_mode property works."""
        config = ZeroShotCloneConfig(engine="xtts_v2")
        
        if "MOCK_TTS" in os.environ:
            del os.environ["MOCK_TTS"]
        assert config.mock_mode is False
        
        os.environ["MOCK_TTS"] = "true"
        config2 = ZeroShotCloneConfig(engine="xtts_v2")
        assert config2.mock_mode is True


class TestZeroShotCloneEngineAsync:
    """Test async cloning functionality."""

    @pytest.fixture
    def xtts_config(self):
        return ZeroShotCloneConfig(
            engine="xtts_v2",
            host="localhost",
            port=5010,
        )

    @pytest.mark.asyncio
    async def test_clone_async(self, xtts_config):
        """Test async zero-shot cloning."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_zero_shot_clone_engine(xtts_config)
            
            result = await engine.clone_async(
                text="异步零样本克隆测试。",
                reference_audio=b"fake_reference_audio_data",
            )
            
            assert isinstance(result, ZeroShotCloneResult)
            assert result.audio_data is not None


class TestZeroShotClonePort:
    """Test ZeroShotCloneEngine interface compatibility."""

    def test_implements_clone_interface(self):
        """Test that ZeroShotCloneEngine has required clone methods."""
        from src.audiobook_studio.tts.zero_shot_clone import ZeroShotCloneEngine
        
        assert hasattr(ZeroShotCloneEngine, "clone")
        assert hasattr(ZeroShotCloneEngine, "clone_async")
        assert hasattr(ZeroShotCloneEngine, "clone_stream")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

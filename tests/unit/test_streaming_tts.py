"""Tests for Streaming TTS - First-byte latency < 500ms.

P2-3: Streaming TTS integration with WebSocket audio chunk streaming.
"""

import os
from unittest.mock import patch

import pytest

from src.audiobook_studio.tts.streaming import (
    StreamingTTSConfig,
    StreamingTTSEngine,
    StreamingTTSResult,
    create_streaming_tts_engine,
)


class TestStreamingTTSConfig:
    """Test StreamingTTSConfig dataclass."""

    def test_default_values(self):
        config = StreamingTTSConfig(engine="cosyvoice_stream")
        assert config.engine == "cosyvoice_stream"
        assert config.host == "localhost"
        assert config.port == 5000
        assert config.sample_rate == 24000
        assert config.chunk_size_ms == 100
        assert config.voice_id == "default"
        assert config.speed == 1.0
        assert config.timeout == 30

    def test_custom_values(self):
        config = StreamingTTSConfig(
            engine="melotts_stream",
            host="127.0.0.1",
            port=5001,
            sample_rate=16000,
            chunk_size_ms=50,
            voice_id="zh-CN-Xiaoxiao",
            speed=1.2,
            timeout=60,
        )
        assert config.engine == "melotts_stream"
        assert config.host == "127.0.0.1"
        assert config.port == 5001
        assert config.sample_rate == 16000
        assert config.chunk_size_ms == 50
        assert config.voice_id == "zh-CN-Xiaoxiao"
        assert config.speed == 1.2
        assert config.timeout == 60


class TestCreateStreamingTTSEngine:
    """Test create_streaming_tts_engine factory function."""

    def test_create_cosyvoice_stream(self):
        config = StreamingTTSConfig(engine="cosyvoice_stream")
        engine = create_streaming_tts_engine(config)
        assert isinstance(engine, StreamingTTSEngine)
        assert engine.config.engine == "cosyvoice_stream"

    def test_create_melotts_stream(self):
        config = StreamingTTSConfig(engine="melotts_stream")
        engine = create_streaming_tts_engine(config)
        assert isinstance(engine, StreamingTTSEngine)
        assert engine.config.engine == "melotts_stream"

    def test_create_seed_tts_stream(self):
        config = StreamingTTSConfig(engine="seed_tts_stream")
        engine = create_streaming_tts_engine(config)
        assert isinstance(engine, StreamingTTSEngine)
        assert engine.config.engine == "seed_tts_stream"

    def test_unknown_engine_raises(self):
        config = StreamingTTSConfig(engine="unknown_engine")
        with pytest.raises(ValueError, match="Unsupported streaming TTS engine"):
            create_streaming_tts_engine(config)


class TestStreamingTTSEngine:
    """Test StreamingTTSEngine functionality."""

    @pytest.fixture
    def cosyvoice_config(self):
        return StreamingTTSConfig(
            engine="cosyvoice_stream",
            host="localhost",
            port=5000,
        )

    @pytest.fixture
    def melotts_config(self):
        return StreamingTTSConfig(
            engine="melotts_stream",
            host="localhost",
            port=5001,
        )

    def test_init_mock_mode(self, cosyvoice_config):
        """Test initialization in mock mode."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_streaming_tts_engine(cosyvoice_config)
            assert engine.config.engine == "cosyvoice_stream"

    def test_synthesize_stream_mock_mode(self, cosyvoice_config):
        """Test streaming synthesis in mock mode."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_streaming_tts_engine(cosyvoice_config)

            chunks = list(engine.synthesize_stream("测试文本"))

            assert len(chunks) > 0
            for chunk in chunks:
                assert isinstance(chunk, StreamingTTSResult)
                assert chunk.audio_data is not None
                assert len(chunk.audio_data) > 0
                assert chunk.sample_rate == 24000
                assert chunk.is_final in (True, False)

    def test_synthesize_stream_first_chunk_latency(self, cosyvoice_config):
        """Test first chunk latency is under 500ms in mock mode."""
        import time

        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_streaming_tts_engine(cosyvoice_config)

            start = time.time()
            chunks = list(engine.synthesize_stream("测试文本"))
            first_chunk_time = time.time() - start

            # In mock mode, first chunk should be nearly instant
            assert first_chunk_time < 0.5  # 500ms
            assert len(chunks) > 0

    def test_synthesize_stream_with_voice_id(self, melotts_config):
        """Test streaming synthesis with specific voice."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_streaming_tts_engine(melotts_config)

            chunks = list(engine.synthesize_stream("测试文本", voice_id="zh-CN-Xiaoxiao"))

            assert len(chunks) > 0
            for chunk in chunks:
                assert chunk.audio_data is not None

    def test_synthesize_stream_empty_text(self, cosyvoice_config):
        """Test streaming synthesis with empty text."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_streaming_tts_engine(cosyvoice_config)

            chunks = list(engine.synthesize_stream(""))

            # Should handle gracefully
            assert isinstance(chunks, list)

    def test_mock_mode_via_config(self, cosyvoice_config):
        """Test that config.mock_mode property works."""
        config = StreamingTTSConfig(engine="cosyvoice_stream")

        if "MOCK_TTS" in os.environ:
            del os.environ["MOCK_TTS"]
        assert config.mock_mode is False

        os.environ["MOCK_TTS"] = "true"
        config2 = StreamingTTSConfig(engine="cosyvoice_stream")
        assert config2.mock_mode is True


class TestStreamingTTSEngineAsync:
    """Test async streaming functionality."""

    @pytest.fixture
    def cosyvoice_config(self):
        return StreamingTTSConfig(
            engine="cosyvoice_stream",
            host="localhost",
            port=5000,
        )

    @pytest.mark.asyncio
    async def test_synthesize_stream_async(self, cosyvoice_config):
        """Test async streaming synthesis."""
        with patch.dict(os.environ, {"MOCK_TTS": "true"}):
            engine = create_streaming_tts_engine(cosyvoice_config)

            chunks = []
            async for chunk in engine.synthesize_stream_async("测试文本"):
                chunks.append(chunk)

            assert len(chunks) > 0
            for chunk in chunks:
                assert isinstance(chunk, StreamingTTSResult)
                assert chunk.audio_data is not None


class TestStreamingTTSPort:
    """Test StreamingTTSPort interface compatibility."""

    def test_implements_remote_tts_port(self):
        """Test that StreamingTTSEngine can be used as RemoteTTSPort."""
        from src.audiobook_studio.tts.streaming import StreamingTTSEngine

        # Check it has the required methods
        assert hasattr(StreamingTTSEngine, "synthesize_stream")
        assert hasattr(StreamingTTSEngine, "synthesize_stream_async")
        assert hasattr(StreamingTTSEngine, "synthesize")  # For backward compatibility


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

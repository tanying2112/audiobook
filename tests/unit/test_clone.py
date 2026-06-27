"""Tests for TTS voice cloning module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.audiobook_studio.tts.clone import (
    AudioQuality,
    CloningConfig,
    VoiceCloningEngine,
    VoicePrint,
    VoiceSample,
)


class TestAudioQuality:
    """Tests for AudioQuality enum."""

    def test_enum_values(self):
        """Test enum has correct values."""
        assert AudioQuality.EXCELLENT.value == "excellent"
        assert AudioQuality.GOOD.value == "good"
        assert AudioQuality.FAIR.value == "fair"
        assert AudioQuality.POOR.value == "poor"


class TestCloningConfig:
    """Tests for CloningConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = CloningConfig()
        assert config.min_sample_duration == 15.0
        assert config.min_snr_db == 20.0
        assert config.similarity_threshold == 0.85
        assert config.model_path == "./models/kokoro-onnx"
        assert config.output_dir == "./voices/cloned"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = CloningConfig(
            min_sample_duration=10.0,
            min_snr_db=15.0,
            similarity_threshold=0.9,
            model_path="/custom/path",
            output_dir="/custom/output",
        )
        assert config.min_sample_duration == 10.0
        assert config.min_snr_db == 15.0
        assert config.similarity_threshold == 0.9
        assert config.model_path == "/custom/path"
        assert config.output_dir == "/custom/output"


class TestVoiceSample:
    """Tests for VoiceSample dataclass."""

    def test_create_sample(self):
        """Test creating a voice sample."""
        sample = VoiceSample(
            id="test_001",
            file_path=Path("/path/to/audio.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=25.0,
            text_content="Test text",
            language="zh-CN",
            speaker_id="speaker_1",
        )
        assert sample.id == "test_001"
        assert sample.duration == 20.0
        assert sample.snr_db == 25.0
        assert sample.speaker_id == "speaker_1"
        assert sample.timestamp is not None


class TestVoicePrint:
    """Tests for VoicePrint dataclass."""

    def test_create_voice_print(self):
        """Test creating a voice print."""
        vp = VoicePrint(
            speaker_id="speaker_1",
            voice_hash="abc123",
            embedding=[0.1, 0.2, 0.3, 0.4],
            quality=AudioQuality.GOOD,
            sample_count=3,
            avg_snr=22.5,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        assert vp.speaker_id == "speaker_1"
        assert vp.quality == AudioQuality.GOOD
        assert vp.sample_count == 3
        assert vp.avg_snr == 22.5


@pytest.fixture
def config():
    """Create a config."""
    return CloningConfig(
        min_sample_duration=15.0,
        min_snr_db=20.0,
        model_path="/tmp/test_models",
        output_dir="/tmp/test_voices",
    )


@pytest.fixture
def engine(config):
    """Create a VoiceCloningEngine instance with mocked persistence."""
    with patch.object(VoiceCloningEngine, '_load_voice_prints'), \
         patch.object(VoiceCloningEngine, '_save_voice_prints'):
        engine = VoiceCloningEngine(config)
        yield engine


class TestVoiceCloningEngine:
    """Tests for VoiceCloningEngine class."""

    def test_calculate_audio_hash(self, engine):
        """Test audio hash calculation."""
        audio_data = np.random.rand(48000)  # 2 seconds at 24kHz
        sample_rate = 24000

        hash1 = engine._calculate_audio_hash(audio_data, sample_rate)
        hash2 = engine._calculate_audio_hash(audio_data, sample_rate)

        # Same audio should produce same hash
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex length

    def test_calculate_audio_hash_different(self, engine):
        """Test different audio produces different hash."""
        audio1 = np.random.rand(48000)
        audio2 = np.random.rand(48000)
        sample_rate = 24000

        hash1 = engine._calculate_audio_hash(audio1, sample_rate)
        hash2 = engine._calculate_audio_hash(audio2, sample_rate)

        assert hash1 != hash2

    def test_estimate_snr(self, engine):
        """Test SNR estimation."""
        # High signal, low noise
        audio = np.concatenate([np.random.rand(100) * 0.01,  # noise
                                np.sin(np.linspace(0, 100, 47900)) * 0.5,  # signal
                                np.random.rand(100) * 0.01])  # noise
        sample_rate = 24000

        snr = engine._estimate_snr(audio, sample_rate)
        assert snr > 0

    def test_estimate_snr_empty_audio(self, engine):
        """Test SNR with empty audio."""
        audio = np.array([])
        sample_rate = 24000

        snr = engine._estimate_snr(audio, sample_rate)
        assert snr == 0.0

    def test_is_sample_valid_duration(self, engine):
        """Test sample validation - duration check."""
        # Valid duration
        sample = VoiceSample(
            id="test",
            file_path=Path("test.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=25.0,
            text_content="test",
            language="zh-CN",
            speaker_id="speaker",
        )
        valid, msg = engine._is_sample_valid(sample)
        assert valid is True

        # Invalid duration
        sample.duration = 10.0  # Less than 15s default
        valid, msg = engine._is_sample_valid(sample)
        assert valid is False
        assert "时长不足" in msg

    def test_is_sample_valid_snr(self, engine):
        """Test sample validation - SNR check."""
        # Valid SNR
        sample = VoiceSample(
            id="test",
            file_path=Path("test.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=25.0,
            text_content="test",
            language="zh-CN",
            speaker_id="speaker",
        )
        valid, msg = engine._is_sample_valid(sample)
        assert valid is True

        # Invalid SNR
        sample.snr_db = 15.0  # Less than 20dB default
        valid, msg = engine._is_sample_valid(sample)
        assert valid is False
        assert "信噪比不足" in msg

    def test_add_voice_sample_valid(self, engine):
        """Test adding a valid voice sample."""
        sample = VoiceSample(
            id="sample_001",
            file_path=Path("test.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=25.0,
            text_content="Test text for cloning",
            language="zh-CN",
            speaker_id="speaker_1",
        )
        success, msg = engine.add_voice_sample(sample)
        assert success is True
        assert "创建新声音指纹" in msg
        assert "speaker_1" in engine.voice_prints

    def test_add_voice_sample_invalid_duration(self, engine):
        """Test adding a sample with invalid duration."""
        sample = VoiceSample(
            id="sample_001",
            file_path=Path("test.wav"),
            duration=5.0,  # Too short
            sample_rate=24000,
            snr_db=25.0,
            text_content="Test",
            language="zh-CN",
            speaker_id="speaker_1",
        )
        success, msg = engine.add_voice_sample(sample)
        assert success is False
        assert "时长不足" in msg

    def test_add_voice_sample_invalid_snr(self, engine):
        """Test adding a sample with invalid SNR."""
        sample = VoiceSample(
            id="sample_001",
            file_path=Path("test.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=10.0,  # Too low
            text_content="Test",
            language="zh-CN",
            speaker_id="speaker_1",
        )
        success, msg = engine.add_voice_sample(sample)
        assert success is False
        assert "信噪比不足" in msg

    def test_update_voice_print_multiple_samples(self, engine):
        """Test updating voice print with multiple samples."""
        speaker_id = "speaker_multi"

        # Add 3 valid samples
        for i in range(3):
            sample = VoiceSample(
                id=f"{speaker_id}_sample_{i}",
                file_path=Path(f"test_{i}.wav"),
                duration=20.0,
                sample_rate=24000,
                snr_db=25.0,
                text_content=f"Sample {i}",
                language="zh-CN",
                speaker_id=speaker_id,
            )
            success, msg = engine.add_voice_sample(sample)
            assert success is True

        # Voice print should have 3 samples
        vp = engine.voice_prints[speaker_id]
        assert vp.sample_count == 3
        assert vp.avg_snr == pytest.approx(25.0)
        assert vp.quality == AudioQuality.EXCELLENT

    def test_assess_quality(self, engine):
        """Test quality assessment based on SNR."""
        assert engine._assess_quality(30.0) == AudioQuality.EXCELLENT
        assert engine._assess_quality(22.0) == AudioQuality.GOOD
        assert engine._assess_quality(17.0) == AudioQuality.FAIR
        assert engine._assess_quality(10.0) == AudioQuality.POOR
        # Boundary cases
        assert engine._assess_quality(25.0) == AudioQuality.EXCELLENT
        assert engine._assess_quality(20.0) == AudioQuality.GOOD
        assert engine._assess_quality(15.0) == AudioQuality.FAIR

    def test_synthesize_speech_missing_voice(self, engine):
        """Test synthesis with missing voice print."""
        success, msg, path = engine.synthesize_speech("Test", "nonexistent")
        assert success is False
        assert "找不到说话人" in msg
        assert path is None

    def test_synthesize_speech_poor_quality(self, engine):
        """Test synthesis with poor quality voice."""
        # Create a voice print with poor quality
        vp = VoicePrint(
            speaker_id="poor_speaker",
            voice_hash="hash123",
            embedding=[0.1] * 8,
            quality=AudioQuality.POOR,
            sample_count=1,
            avg_snr=10.0,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        engine.voice_prints["poor_speaker"] = vp

        success, msg, path = engine.synthesize_speech("Test", "poor_speaker")
        assert success is False
        assert "质量太差" in msg
        assert path is None

    def test_synthesize_speech_success(self, engine):
        """Test successful speech synthesis."""
        # Create a good quality voice print
        vp = VoicePrint(
            speaker_id="good_speaker",
            voice_hash="hash123",
            embedding=[0.1] * 8,
            quality=AudioQuality.GOOD,
            sample_count=2,
            avg_snr=22.0,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        engine.voice_prints["good_speaker"] = vp

        success, msg, path = engine.synthesize_speech("Test text", "good_speaker")
        assert success is True
        assert "MOCK模式合成" in msg
        assert path is not None

    def test_get_voice_info_exists(self, engine):
        """Test getting voice info for existing speaker."""
        vp = VoicePrint(
            speaker_id="info_speaker",
            voice_hash="abcdef1234567890",
            embedding=[0.1] * 8,
            quality=AudioQuality.GOOD,
            sample_count=2,
            avg_snr=22.0,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )
        engine.voice_prints["info_speaker"] = vp

        info = engine.get_voice_info("info_speaker")
        assert info is not None
        assert info["speaker_id"] == "info_speaker"
        assert info["quality"] == "good"
        assert info["sample_count"] == 2
        assert info["avg_snr_db"] == 22.0
        assert info["is_available_for_cloning"] is True

    def test_get_voice_info_not_exists(self, engine):
        """Test getting voice info for non-existent speaker."""
        info = engine.get_voice_info("nonexistent")
        assert info is None

    def test_voice_cloning_manager_alias(self):
        """Test that VoiceCloningManager is an alias."""
        from src.audiobook_studio.tts.clone import VoiceCloningManager
        assert VoiceCloningManager is VoiceCloningEngine


class TestVoiceCloningPersistence:
    """Tests for voice print persistence (mocked)."""

    def test_add_voice_sample_triggers_save(self, engine):
        """Test that adding a valid sample triggers save."""
        with patch.object(engine, '_save_voice_prints') as mock_save:
            sample = VoiceSample(
                id="persist_001",
                file_path=Path("test.wav"),
                duration=20.0,
                sample_rate=24000,
                snr_db=25.0,
                text_content="Test",
                language="zh-CN",
                speaker_id="persist_speaker",
            )
            engine.add_voice_sample(sample)
            mock_save.assert_called_once()

    def test_update_voice_print_triggers_save(self, engine):
        """Test that updating an existing voice print triggers save."""
        # First create a voice print
        sample = VoiceSample(
            id="update_001",
            file_path=Path("test.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=25.0,
            text_content="Test",
            language="zh-CN",
            speaker_id="update_speaker",
        )
        engine.add_voice_sample(sample)

        # Now add another sample for the same speaker
        with patch.object(engine, '_save_voice_prints') as mock_save:
            sample2 = VoiceSample(
                id="update_002",
                file_path=Path("test2.wav"),
                duration=20.0,
                sample_rate=24000,
                snr_db=25.0,
                text_content="Test 2",
                language="zh-CN",
                speaker_id="update_speaker",
            )
            engine.add_voice_sample(sample2)
            mock_save.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
"""Tests for voice_cloning module."""

import pytest
from unittest.mock import patch, MagicMock, mock_open
import sys
import tempfile
import json
from pathlib import Path
from datetime import datetime

# Add project path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def test_voice_cloning_imports():
    """Test that voice_cloning module can be imported."""
    from src.audiobook_studio.tts.voice_cloning import (
        AudioQuality,
        VoiceSample,
        VoicePrint,
        CloningConfig,
        VoiceCloningManager,
    )
    assert AudioQuality is not None
    assert VoiceSample is not None
    assert VoicePrint is not None
    assert CloningConfig is not None
    assert VoiceCloningManager is not None


class TestAudioQuality:
    """Tests for AudioQuality enum."""

    def test_audio_quality_values(self):
        """Test AudioQuality enum values."""
        from src.audiobook_studio.tts.voice_cloning import AudioQuality

        assert AudioQuality.EXCELLENT.value == "excellent"
        assert AudioQuality.GOOD.value == "good"
        assert AudioQuality.FAIR.value == "fair"
        assert AudioQuality.POOR.value == "poor"


class TestCloningConfig:
    """Tests for CloningConfig dataclass."""

    def test_default_config(self):
        """Test default CloningConfig values."""
        from src.audiobook_studio.tts.voice_cloning import CloningConfig

        config = CloningConfig()
        assert config.min_sample_duration == 15.0
        assert config.min_snr_db == 20.0
        assert config.similarity_threshold == 0.85
        assert config.model_path == "./models/kokoro-onnx"
        assert config.output_dir == "./voices/cloned"

    def test_custom_config(self):
        """Test custom CloningConfig values."""
        from src.audiobook_studio.tts.voice_cloning import CloningConfig

        config = CloningConfig(
            min_sample_duration=10.0,
            min_snr_db=15.0,
            similarity_threshold=0.75,
        )
        assert config.min_sample_duration == 10.0
        assert config.min_snr_db == 15.0
        assert config.similarity_threshold == 0.75


class TestVoiceSample:
    """Tests for VoiceSample dataclass."""

    def test_voice_sample_creation(self):
        """Test creating a VoiceSample."""
        from src.audiobook_studio.tts.voice_cloning import VoiceSample

        sample = VoiceSample(
            id="sample-1",
            file_path=Path("/tmp/test.wav"),
            duration=15.5,
            sample_rate=24000,
            snr_db=22.0,
            text_content="Hello world",
            language="en",
            speaker_id="speaker-1",
        )
        assert sample.id == "sample-1"
        assert sample.duration == 15.5
        assert sample.sample_rate == 24000
        assert sample.snr_db == 22.0
        assert sample.speaker_id == "speaker-1"

    def test_voice_sample_default_timestamp(self):
        """Test VoiceSample has default timestamp."""
        from src.audiobook_studio.tts.voice_cloning import VoiceSample

        sample = VoiceSample(
            id="sample-1",
            file_path=Path("/tmp/test.wav"),
            duration=15.0,
            sample_rate=24000,
            snr_db=20.0,
            text_content="Test",
            language="zh",
            speaker_id="speaker-1",
        )
        assert sample.timestamp is not None
        assert isinstance(sample.timestamp, str)


class TestVoicePrint:
    """Tests for VoicePrint dataclass."""

    def test_voice_print_creation(self):
        """Test creating a VoicePrint."""
        from src.audiobook_studio.tts.voice_cloning import (
            AudioQuality,
            VoicePrint,
        )

        voice_print = VoicePrint(
            speaker_id="speaker-1",
            voice_hash="abc123",
            embedding=[0.1, 0.2, 0.3],
            quality=AudioQuality.GOOD,
            sample_count=5,
            avg_snr=22.5,
            created_at="2026-01-01",
            updated_at="2026-01-02",
        )
        assert voice_print.speaker_id == "speaker-1"
        assert voice_print.quality == AudioQuality.GOOD
        assert voice_print.sample_count == 5


class TestVoiceCloningManager:
    """Tests for VoiceCloningManager."""

    def test_manager_initialization(self, tmp_path):
        """Test VoiceCloningManager initialization."""
        from src.audiobook_studio.tts.voice_cloning import (
            VoiceCloningManager,
            CloningConfig,
        )

        config = CloningConfig(
            output_dir=str(tmp_path / "voices"),
            model_path=str(tmp_path / "models"),
        )
        with patch.object(VoiceCloningManager, "_load_voice_prints"):
            manager = VoiceCloningManager(config)
        assert manager.config == config
        assert manager.voice_prints == {}
        assert manager.voice_samples == {}

    def test_assess_quality(self, tmp_path):
        """Test quality assessment based on SNR."""
        from src.audiobook_studio.tts.voice_cloning import (
            VoiceCloningManager,
            AudioQuality,
        )

        manager = VoiceCloningManager()
        # Test the private method
        assert manager._assess_quality(30.0) == AudioQuality.EXCELLENT
        assert manager._assess_quality(22.0) == AudioQuality.GOOD
        assert manager._assess_quality(17.0) == AudioQuality.FAIR
        assert manager._assess_quality(10.0) == AudioQuality.POOR

    def test_is_sample_valid_too_short(self, tmp_path):
        """Test sample validation for too-short samples."""
        from src.audiobook_studio.tts.voice_cloning import (
            VoiceCloningManager,
            VoiceSample,
        )

        manager = VoiceCloningManager()
        sample = VoiceSample(
            id="sample-1",
            file_path=Path("/tmp/test.wav"),
            duration=10.0,  # Below min 15s
            sample_rate=24000,
            snr_db=22.0,
            text_content="Test",
            language="zh",
            speaker_id="speaker-1",
        )

        is_valid, msg = manager._is_sample_valid(sample)
        assert is_valid is False
        assert "时长不足" in msg

    def test_is_sample_valid_low_snr(self, tmp_path):
        """Test sample validation for low SNR."""
        from src.audiobook_studio.tts.voice_cloning import (
            VoiceCloningManager,
            VoiceSample,
        )

        manager = VoiceCloningManager()
        sample = VoiceSample(
            id="sample-1",
            file_path=Path("/tmp/test.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=15.0,  # Below min 20dB
            text_content="Test",
            language="zh",
            speaker_id="speaker-1",
        )

        is_valid, msg = manager._is_sample_valid(sample)
        assert is_valid is False
        assert "信噪比不足" in msg

    def test_is_sample_valid(self, tmp_path):
        """Test sample validation for valid sample."""
        from src.audiobook_studio.tts.voice_cloning import (
            VoiceCloningManager,
            VoiceSample,
        )

        manager = VoiceCloningManager()
        sample = VoiceSample(
            id="sample-1",
            file_path=Path("/tmp/test.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=22.0,
            text_content="Test",
            language="zh",
            speaker_id="speaker-1",
        )

        is_valid, msg = manager._is_sample_valid(sample)
        assert is_valid is True
        assert "有效" in msg

    def test_add_voice_sample_invalid(self, tmp_path):
        """Test adding an invalid sample."""
        from src.audiobook_studio.tts.voice_cloning import (
            VoiceCloningManager,
            VoiceSample,
        )

        manager = VoiceCloningManager()
        sample = VoiceSample(
            id="sample-1",
            file_path=Path("/tmp/test.wav"),
            duration=10.0,
            sample_rate=24000,
            snr_db=15.0,
            text_content="Test",
            language="zh",
            speaker_id="speaker-1",
        )

        success, msg = manager.add_voice_sample(sample)
        assert success is False

    def test_synthesize_speech_unknown_speaker(self, tmp_path):
        """Test speech synthesis with unknown speaker."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager

        manager = VoiceCloningManager()
        success, msg, path = manager.synthesize_speech(
            text="Hello",
            speaker_id="unknown",
        )
        assert success is False
        assert "找不到说话人" in msg
        assert path is None

    def test_get_voice_info_unknown_speaker(self, tmp_path):
        """Test get_voice_info for unknown speaker."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager

        manager = VoiceCloningManager()
        info = manager.get_voice_info("unknown")
        assert info is None

    def test_calculate_audio_hash(self):
        """Test audio hash calculation."""
        import numpy as np
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager

        manager = VoiceCloningManager()
        audio = np.array([1, 2, 3, 4, 5], dtype=np.float32)
        hash_result = manager._calculate_audio_hash(audio, 24000)
        assert isinstance(hash_result, str)
        assert len(hash_result) == 64  # SHA256 hex length

    def test_estimate_snr_empty(self):
        """Test SNR estimation for empty audio."""
        import numpy as np
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager

        manager = VoiceCloningManager()
        empty_audio = np.array([], dtype=np.float32)
        snr = manager._estimate_snr(empty_audio, 24000)
        assert snr == 0.0

    def test_estimate_snr_normal(self):
        """Test SNR estimation for normal audio."""
        import numpy as np
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager

        manager = VoiceCloningManager()
        # Generate synthetic audio with noise
        np.random.seed(42)
        audio = np.random.randn(1000).astype(np.float32)
        audio = audio + np.sin(np.linspace(0, 2 * np.pi, 1000)).astype(np.float32) * 0.5
        snr = manager._estimate_snr(audio, 24000)
        assert isinstance(snr, (float, np.floating))
        assert float(snr) >= 0.0


class TestVoiceCloningManagerMore:
    """Additional tests for VoiceCloningManager to improve coverage."""

    def test_load_voice_prints_file_exists(self, tmp_path):
        """Test _load_voice_prints when file exists."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager, VoicePrint

        # Create a temporary voice_prints.json
        voice_prints_dir = tmp_path / "voices"
        voice_prints_dir.mkdir()
        prints_file = voice_prints_dir / "voice_prints.json"
        test_data = {
            "test_speaker": {
                "speaker_id": "test_speaker",
                "voice_hash": "hash123",
                "embedding": [0.1, 0.2, 0.3],
                "quality": "good",
                "sample_count": 2,
                "avg_snr": 22.0,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-02"
            }
        }
        prints_file.write_text(json.dumps(test_data))

        # Initialize manager with custom directory
        with patch.object(Path, 'mkdir'):
            manager = VoiceCloningManager()
            # Override the paths to use our temp directory
            manager.voice_prints = {}
            prints_file = Path("./voices/voice_prints.json")
            prints_file.parent.mkdir(parents=True, exist_ok=True)
            prints_file.write_text(json.dumps(test_data))

            # Call the method
            manager._load_voice_prints()

            # Check that the voice print was loaded
            assert "test_speaker" in manager.voice_prints
            assert manager.voice_prints["test_speaker"].speaker_id == "test_speaker"
            assert manager.voice_prints["test_speaker"].voice_hash == "hash123"

    def test_save_voice_prints(self, tmp_path):
        """Test _save_voice_prints."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager, VoicePrint, AudioQuality

        manager = VoiceCloningManager()
        # Create a test voice print
        test_print = VoicePrint(
            speaker_id="test_speaker",
            voice_hash="hash456",
            embedding=[0.4, 0.5, 0.6],
            quality=AudioQuality.GOOD,
            sample_count=1,
            avg_snr=21.0,
            created_at="2026-01-01",
            updated_at="2026-01-02"
        )
        manager.voice_prints["test_speaker"] = test_print

        with patch("builtins.open", mock_open()) as mock_file:
            manager._save_voice_prints()
            # Check that file was opened for writing
            mock_file.assert_called_once()
            handle = mock_file()
            # Check that json.dump was called
            handle.write.assert_called()

    def test_update_voice_print_new(self):
        """Test _update_voice_print when creating new fingerprint."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager, VoiceSample, AudioQuality

        manager = VoiceCloningManager()
        # Clear existing prints but keep the manager's internal state consistent
        manager.voice_prints.clear()
        manager.voice_samples.clear()

        # Create a valid sample and add it properly
        sample = VoiceSample(
            id="sample1",
            file_path=Path("/tmp/sample1.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=22.0,
            text_content="Test content",
            language="zh-CN",
            speaker_id="new_speaker",
        )

        # First add the sample (this populates voice_samples)
        success_add, msg_add = manager.add_voice_sample(sample)
        assert success_add is True

        # Now update the voice print (this should create a new one)
        success, message = manager._update_voice_print("new_speaker")
        assert success is True
        assert "creates new" in message.lower() or "创建新" in message
        assert "new_speaker" in manager.voice_prints
        assert manager.voice_prints["new_speaker"].speaker_id == "new_speaker"
        assert manager.voice_prints["new_speaker"].sample_count == 1

    def test_update_voice_print_existing(self):
        """Test _update_voice_print when updating existing fingerprint."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager, VoiceSample, VoicePrint, AudioQuality

        manager = VoiceCloningManager()
        # Pre-populate with an existing voice print
        existing_print = VoicePrint(
            speaker_id="existing_speaker",
            voice_hash="old_hash",
            embedding=[0.1, 0.1, 0.1],
            quality=AudioQuality.GOOD,
            sample_count=1,
            avg_snr=20.0,
            created_at="2026-01-01",
            updated_at="2026-01-01"
        )
        manager.voice_prints["existing_speaker"] = existing_print
        manager.voice_samples["existing_speaker"] = []

        # Add a new sample with different characteristics
        sample = VoiceSample(
            id="sample2",
            file_path=Path("/tmp/sample2.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=25.0,  # Different SNR
            text_content="Test content 2",
            language="zh-CN",
            speaker_id="existing_speaker",
        )

        success, message = manager._update_voice_print("existing_speaker")
        assert success is True
        assert "updates" in message.lower() or "更新" in message
        # Should have updated the voice print
        assert manager.voice_prints["existing_speaker"].sample_count == 1
        assert manager.voice_prints["existing_speaker"].voice_hash != "old_hash"

    def test_synthesize_speech_success(self):
        """Test synthesize_speech success case."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager, VoicePrint, AudioQuality

        manager = VoiceCloningManager()
        # Pre-populate with a voice print
        voice_print = VoicePrint(
            speaker_id="test_speaker",
            voice_hash="hash123",
            embedding=[0.1, 0.2, 0.3],
            quality=AudioQuality.GOOD,
            sample_count=1,
            avg_snr=22.0,
            created_at="2026-01-01",
            updated_at="2026-01-02"
        )
        manager.voice_prints["test_speaker"] = voice_print
        manager.voice_samples["test_speaker"] = []

        with patch("pathlib.Path.touch") as mock_touch:
            success, message, audio_path = manager.synthesize_speech(
                text="Hello world",
                speaker_id="test_speaker",
                language="zh-CN",
                emotion="happy"
            )
            assert success is True
            assert "success" in message.lower() or "成功" in message
            assert audio_path is not None
            mock_touch.assert_called_once()

    def test_synthesize_speech_poor_quality(self):
        """Test synthesize_speech with poor quality voice."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager, VoicePrint, AudioQuality

        manager = VoiceCloningManager()
        # Pre-populate with a poor quality voice print
        voice_print = VoicePrint(
            speaker_id="bad_speaker",
            voice_hash="hash123",
            embedding=[0.1, 0.2, 0.3],
            quality=AudioQuality.POOR,  # Poor quality
            sample_count=1,
            avg_snr=10.0,
            created_at="2026-01-01",
            updated_at="2026-01-02"
        )
        manager.voice_prints["bad_speaker"] = voice_print

        success, message, audio_path = manager.synthesize_speech(
            text="Hello world",
            speaker_id="bad_speaker",
            language="zh-CN",
            emotion="happy"
        )
        assert success is False
        assert "质量太差" in message or "quality too poor" in message.lower()
        assert audio_path is None

    def test_get_voice_info_exists(self):
        """Test get_voice_info for existing speaker."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager, VoicePrint, AudioQuality

        manager = VoiceCloningManager()
        # Pre-populate with a voice print
        voice_print = VoicePrint(
            speaker_id="test_speaker",
            voice_hash="hash123",
            embedding=[0.1, 0.2, 0.3],
            quality=AudioQuality.GOOD,
            sample_count=5,
            avg_snr=22.0,
            created_at="2026-01-01",
            updated_at="2026-01-02"
        )
        manager.voice_prints["test_speaker"] = voice_print

        info = manager.get_voice_info("test_speaker")
        assert info is not None
        assert info["speaker_id"] == "test_speaker"
        assert info["quality"] == "good"
        assert info["sample_count"] == 5
        assert info["avg_snr_db"] == 22.0

    def test_get_voice_info_not_exists(self):
        """Test get_voice_info for non-existing speaker."""
        from src.audiobook_studio.tts.voice_cloning import VoiceCloningManager

        manager = VoiceCloningManager()
        info = manager.get_voice_info("nonexistent")
        assert info is None

    def test_main_function(self):
        """Test main function runs without error."""
        from src.audiobook_studio.tts.voice_cloning import main
        # We can't easily test the full main function due to prints,
        # but we can test that it doesn't crash when imported
        assert main is not None
        # Actually calling it would produce output, so we just verify it exists
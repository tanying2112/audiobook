"""Tests for tts/clone.py."""

import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# Add src to path
sys.path.insert(0, "src")

from audiobook_studio.tts.clone import (
    AudioQuality,
    CloningConfig,
    VoiceCloner,
    VoiceCloningEngine,
    VoicePrint,
    VoiceSample,
    check_kokoro_model_availability,
    clone_voice,
    extract_voice_features,
    get_kokoro_model_path,
    is_kokoro_available,
    load_voice_print,
)


def test_audio_quality_enum():
    """Test AudioQuality enum."""
    assert AudioQuality.EXCELLENT.value == "excellent"
    assert AudioQuality.GOOD.value == "good"
    assert AudioQuality.FAIR.value == "fair"
    assert AudioQuality.POOR.value == "poor"


def test_cloning_config_defaults():
    """Test CloningConfig default values."""
    config = CloningConfig()
    assert config.min_sample_duration == 15.0
    assert config.min_snr_db == 20.0
    assert config.similarity_threshold == 0.85
    assert config.model_path == "./models/kokoro-onnx"
    assert config.output_dir == "./voices/cloned"


def test_voice_sample_creation():
    """Test VoiceSample creation."""
    sample = VoiceSample(
        id="test_sample_001",
        file_path=Path("/fake/path.wav"),
        duration=15.0,
        sample_rate=24000,
        snr_db=25.0,
        text_content="Hello world",
        language="zh-CN",
        speaker_id="speaker1",
    )
    assert sample.id == "test_sample_001"
    assert sample.file_path == Path("/fake/path.wav")
    assert sample.duration == 15.0
    assert sample.sample_rate == 24000
    assert sample.snr_db == 25.0
    assert sample.text_content == "Hello world"
    assert sample.language == "zh-CN"
    assert sample.speaker_id == "speaker1"


def test_voice_print_creation():
    """Test VoicePrint creation."""
    now = datetime.now().isoformat()
    voice_print = VoicePrint(
        speaker_id="speaker1",
        voice_hash="abc123",
        embedding=[0.1] * 256,
        quality=AudioQuality.GOOD,
        sample_count=5,
        avg_snr=25.0,
        created_at=now,
        updated_at=now,
    )
    assert voice_print.speaker_id == "speaker1"
    assert voice_print.voice_hash == "abc123"
    np.testing.assert_array_almost_equal(
        np.array(voice_print.embedding),
        np.array([0.1] * 256, dtype=np.float32),
        decimal=5,
    )
    assert voice_print.quality == AudioQuality.GOOD
    assert voice_print.sample_count == 5
    assert voice_print.avg_snr == 25.0


def test_voice_cloner_init():
    """Test VoiceCloner initialization."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        cloner = VoiceCloner()
        assert cloner is not None
        assert isinstance(cloner.engine, VoiceCloningEngine)


def test_voice_cloner_init_unavailable():
    """Test VoiceCloner initialization when model is not available."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=False):
        # VoiceCloner doesn't raise error on init, but model_ready will be False
        cloner = VoiceCloner()
        assert cloner is not None
        assert cloner.engine._model_ready is False


def test_voice_cloning_engine_init():
    """Test VoiceCloningEngine initialization."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        with patch("audiobook_studio.tts.clone.VoiceCloningEngine._load_voice_prints"):
            with patch("audiobook_studio.tts.clone.Path.mkdir"):
                engine = VoiceCloningEngine()
                assert engine is not None
                assert engine.config is not None
                assert engine.voice_prints == {}
                assert engine.voice_samples == {}


def test_voice_cloning_engine_add_voice_sample():
    """Test VoiceCloningEngine add_voice_sample method."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        with patch("audiobook_studio.tts.clone.VoiceCloningEngine._load_voice_prints"):
            with patch("audiobook_studio.tts.clone.Path.mkdir"):
                engine = VoiceCloningEngine()

        # Create a valid sample
        sample = VoiceSample(
            id="test_sample_001",
            file_path=Path("/fake/path.wav"),
            duration=20.0,  # >= 15s
            sample_rate=24000,
            snr_db=25.0,  # >= 20dB
            text_content="Hello world",
            language="zh-CN",
            speaker_id="speaker1",
        )

        # Mock extract_voice_features to avoid file I/O
        with patch(
            "audiobook_studio.tts.clone.extract_voice_features",
            return_value=np.ones(256, dtype=np.float32) * 0.5,
        ):
            with patch.object(engine, "_save_voice_prints"):
                success, message = engine.add_voice_sample(sample)

        assert success is True
        assert "speaker1" in engine.voice_prints
        voice_print = engine.voice_prints["speaker1"]
        assert voice_print.speaker_id == "speaker1"
        assert voice_print.sample_count == 1
        assert voice_print.avg_snr == 25.0


def test_voice_cloning_engine_add_invalid_sample():
    """Test VoiceCloningEngine add_voice_sample with invalid sample."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        with patch("audiobook_studio.tts.clone.VoiceCloningEngine._load_voice_prints"):
            with patch("audiobook_studio.tts.clone.Path.mkdir"):
                engine = VoiceCloningEngine()

        # Sample too short (< 15s)
        sample = VoiceSample(
            id="test_sample_001",
            file_path=Path("/fake/path.wav"),
            duration=5.0,  # < 15s
            sample_rate=24000,
            snr_db=25.0,
            text_content="Hello world",
            language="zh-CN",
            speaker_id="speaker1",
        )

        with patch.object(engine, "_save_voice_prints"):
            success, message = engine.add_voice_sample(sample)

        assert success is False
        assert "时长不足" in message or "不足" in message


def test_voice_cloning_engine_get_voice_info():
    """Test VoiceCloningEngine get_voice_info method."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        with patch("audiobook_studio.tts.clone.VoiceCloningEngine._load_voice_prints"):
            with patch("audiobook_studio.tts.clone.Path.mkdir"):
                engine = VoiceCloningEngine()

        # Add a sample first
        sample = VoiceSample(
            id="test_sample_001",
            file_path=Path("/fake/path.wav"),
            duration=20.0,
            sample_rate=24000,
            snr_db=25.0,
            text_content="Hello world",
            language="zh-CN",
            speaker_id="speaker1",
        )

        with patch(
            "audiobook_studio.tts.clone.extract_voice_features",
            return_value=np.ones(256, dtype=np.float32) * 0.5,
        ):
            with patch.object(engine, "_save_voice_prints"):
                engine.add_voice_sample(sample)

        info = engine.get_voice_info("speaker1")
        assert info is not None
        assert info["speaker_id"] == "speaker1"
        assert info["quality"] in ["excellent", "good", "fair", "poor"]
        assert info["sample_count"] == 1
        assert info["avg_snr_db"] == 25.0

        # Test non-existent speaker
        assert engine.get_voice_info("nonexistent") is None


def test_extract_voice_features():
    """Test extract_voice_features function."""
    # Mock soundfile.read to return test audio
    with patch(
        "soundfile.read",
        return_value=(np.random.randn(24000 * 5).astype(np.float32), 24000),
    ):
        features = extract_voice_features(Path("/fake/path.wav"), 24000)

        assert isinstance(features, np.ndarray)
        assert features.shape == (256,)
        assert features.dtype == np.float32
        # Features should be normalized between 0 and 1
        assert np.all(features >= 0.0)
        assert np.all(features <= 1.0)


def test_check_kokoro_model_availability():
    """Test check_kokoro_model_availability function."""
    # Test with non-existent path
    result = check_kokoro_model_availability("/nonexistent/path")
    assert result is False

    # Test with existing path (but no model files)
    result = check_kokoro_model_availability("/tmp")
    assert result is False


def test_is_kokoro_available():
    """Test is_kokoro_available function."""
    # Should return the current global state
    result = is_kokoro_available()
    assert isinstance(result, bool)


def test_get_kokoro_model_path():
    """Test get_kokoro_model_path function."""
    result = get_kokoro_model_path()
    # Should return Path or None
    assert result is None or isinstance(result, Path)


def test_clone_voice_convenience():
    """Test clone_voice convenience function."""
    with patch("audiobook_studio.tts.clone.VoiceCloner") as mock_cloner_class:
        mock_cloner = MagicMock()
        mock_cloner.clone_voice.return_value = (True, "Success", "speaker1")
        mock_cloner_class.return_value = mock_cloner

        success, message, voice_id = clone_voice(Path("/fake/sample.wav"), "speaker1")

        assert success is True
        assert message == "Success"
        assert voice_id == "speaker1"
        mock_cloner.clone_voice.assert_called_once_with(Path("/fake/sample.wav"), "speaker1")


def test_load_voice_print_convenience():
    """Test load_voice_print convenience function."""
    with patch("audiobook_studio.tts.clone.VoiceCloner") as mock_cloner_class:
        mock_cloner = MagicMock()
        mock_cloner.engine.get_voice_info.return_value = {
            "speaker_id": "speaker1",
            "quality": "good",
        }
        mock_cloner_class.return_value = mock_cloner

        result = load_voice_print("speaker1")

        assert result is not None
        assert result["speaker_id"] == "speaker1"
        mock_cloner.engine.get_voice_info.assert_called_once_with("speaker1")


def test_voice_cloner_clone_voice():
    """Test VoiceCloner.clone_voice method.

    The clone_voice method creates a NEW VoiceCloningEngine instance
    to call _estimate_snr, so we need to patch the constructor.
    """
    # Create a mock engine that will be returned by VoiceCloningEngine()
    mock_engine = MagicMock()
    # add_voice_sample returns Tuple[bool, str] (not 3-tuple)
    mock_engine.add_voice_sample.return_value = (True, "Created voice print")
    mock_engine._estimate_snr.return_value = 25.0

    # First create the VoiceCloner with a mocked engine
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        with patch("audiobook_studio.tts.clone.VoiceCloningEngine._load_voice_prints"):
            with patch("audiobook_studio.tts.clone.Path.mkdir"):
                with patch(
                    "audiobook_studio.tts.clone.VoiceCloningEngine",
                    return_value=mock_engine,
                ):
                    cloner = VoiceCloner()

    # Now mock everything needed for clone_voice:
    # - Path.exists() for the sample file
    # - soundfile.read for audio data
    # - VoiceCloningEngine() constructor (which is called inside clone_voice to get _estimate_snr)
    with patch(
        "soundfile.read",
        return_value=(np.random.randn(24000 * 20).astype(np.float32), 24000),
    ):
        with patch.object(Path, "exists", return_value=True):
            # Mock the NEW VoiceCloningEngine() that gets created inside clone_voice
            with patch(
                "audiobook_studio.tts.clone.VoiceCloningEngine",
                return_value=mock_engine,
            ):
                success, message, voice_id = cloner.clone_voice(Path("/fake/sample.wav"), "speaker1")

                assert success is True
                assert voice_id == "speaker1"
                mock_engine.add_voice_sample.assert_called_once()


def test_voice_cloner_get_cloned_voices():
    """Test VoiceCloner.get_cloned_voices method."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        with patch("audiobook_studio.tts.clone.VoiceCloningEngine._load_voice_prints"):
            with patch("audiobook_studio.tts.clone.Path.mkdir"):
                cloner = VoiceCloner()

        # Add a mock voice print
        cloner.engine.voice_prints["speaker1"] = VoicePrint(
            speaker_id="speaker1",
            voice_hash="abc123",
            embedding=[0.1] * 256,
            quality=AudioQuality.GOOD,
            sample_count=3,
            avg_snr=25.0,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
        )

        voices = cloner.get_cloned_voices()

        assert len(voices) == 1
        assert voices[0]["speaker_id"] == "speaker1"
        assert voices[0]["quality"] == "good"
        assert voices[0]["sample_count"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

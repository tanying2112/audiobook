"""Tests for tts/clone.py."""

import sys
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
    assert AudioQuality.LOW.value == "low"
    assert AudioQuality.MEDIUM.value == "medium"
    assert AudioQuality.HIGH.value == "high"


def test_cloning_config_defaults():
    """Test CloningConfig default values."""
    config = CloningConfig()
    assert config.quality == AudioQuality.MEDIUM
    assert config.model_path == "./models/kokoro-onnx"
    assert config.use_cuda is False
    assert config.vocoder == "default"
    assert config.length_scale == 1.0
    assert config.noise_scale == 0.667
    assert config.noise_scale_w == 0.8
    assert config.sampling_rate == 24000


def test_voice_sample_creation():
    """Test VoiceSample creation."""
    sample = VoiceSample(
        audio_path=Path("/fake/path.wav"),
        text="Hello world",
        speaker_id="speaker1",
    )
    assert sample.audio_path == Path("/fake/path.wav")
    assert sample.text == "Hello world"
    assert sample.speaker_id == "speaker1"


def test_voice_print_creation():
    """Test VoicePrint creation."""
    voice_print = VoicePrint(
        speaker_id="speaker1",
        embedding=np.array([0.1, 0.2, 0.3]),
        sample_count=5,
    )
    assert voice_print.speaker_id == "speaker1"
    np.testing.assert_array_equal(voice_print.embedding, np.array([0.1, 0.2, 0.3]))
    assert voice_print.sample_count == 5


def test_voice_cloner_init():
    """Test VoiceCloner initialization."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        cloner = VoiceCloner()
        assert cloner is not None


def test_voice_cloner_init_unavailable():
    """Test VoiceCloner initialization when model is not available."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=False):
        with pytest.raises(RuntimeError, match="Kokoro model is not available"):
            VoiceCloner()


def test_voice_cloner_extract_features():
    """Test VoiceCloner extract_voice_features method."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        cloner = VoiceCloner()
        # Mock the internal extract_voice_features function
        with patch("audiobook_studio.tts.clone.extract_voice_features") as mock_extract:
            mock_extract.return_value = np.array([0.1, 0.2, 0.3])
            result = cloner.extract_voice_features(Path("/fake/path.wav"))
            np.testing.assert_array_equal(result, np.array([0.1, 0.2, 0.3]))
            mock_extract.assert_called_once_with(Path("/fake/path.wav"), 24000)


def test_voice_cloner_compute_similarity():
    """Test VoiceCloner compute_similarity method."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        cloner = VoiceCloner()
        embedding1 = np.array([0.1, 0.2, 0.3])
        embedding2 = np.array([0.4, 0.5, 0.6])
        # Cosine similarity: (0.1*0.4 + 0.2*0.5 + 0.3*0.6) / (sqrt(0.01+0.04+0.09)*sqrt(0.16+0.25+0.36))
        # = (0.04+0.10+0.18) / (sqrt(0.14)*sqrt(0.77)) = 0.32 / (0.374*0.877) ≈ 0.32/0.328 ≈ 0.975
        similarity = cloner.compute_similarity(embedding1, embedding2)
        assert 0.97 < similarity < 0.98


def test_voice_cloner_add_sample():
    """Test VoiceCloner add_sample method."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        cloner = VoiceCloner()
        sample = VoiceSample(
            audio_path=Path("/fake/path.wav"),
            text="Hello",
            speaker_id="speaker1",
        )
        # Mock extract_voice_features to return a fixed embedding
        with patch.object(cloner, 'extract_voice_features', return_value=np.array([0.1, 0.2, 0.3])) as mock_extract:
            cloner.add_sample(sample)
            assert "speaker1" in cloner.voice_prints
            voice_print = cloner.voice_prints["speaker1"]
            assert voice_print.speaker_id == "speaker1"
            assert voice_print.sample_count == 1
            np.testing.assert_array_equal(voice_print.embedding, np.array([0.1, 0.2, 0.3]))


def test_voice_cloner_get_voice_print():
    """Test VoiceCloner get_voice_print method."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        cloner = VoiceCloner()
        # Add a sample first
        sample = VoiceSample(
            audio_path=Path("/fake/path.wav"),
            text="Hello",
            speaker_id="speaker1",
        )
        with patch.object(cloner, 'extract_voice_features', return_value=np.array([0.1, 0.2, 0.3])):
            cloner.add_sample(sample)
        
        voice_print = cloner.get_voice_print("speaker1")
        assert voice_print is not None
        assert voice_print.speaker_id == "speaker1"
        
        # Test non-existent speaker
        assert cloner.get_voice_print("nonexistent") is None


def test_voice_cloner_list_speakers():
    """Test VoiceCloner list_speakers method."""
    with patch("audiobook_stadio.tts.clone.is_kokoro_available", return_value=True):
        cloner = VoiceCloner()
        assert cloner.list_speakers() == []
        
        # Add two speakers
        sample1 = VoiceSample(
            audio_path=Path("/fake/path1.wav"),
            text="Hello",
            speaker_id="speaker1",
        )
        sample2 = VoiceSample(
            audio_path=Path("/fake/path2.wav"),
            text="World",
            speaker_id="speaker2",
        )
        with patch.object(cloner, 'extract_voice_features', return_value=np.array([0.1, 0.2, 0.3])):
            cloner.add_sample(sample1)
            cloner.add_sample(sample2)
        
        speakers = cloner.list_speakers()
        assert set(speakers) == {"speaker1", "speaker2"}


def test_voice_cloner_remove_speaker():
    """Test VoiceCloner remove_speaker method."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        cloner = VoiceCloner()
        # Add a sample
        sample = VoiceSample(
            audio_path=Path("/fake/path.wav"),
            text="Hello",
            speaker_id="speaker1",
        )
        with patch.object(cloner, 'extract_voice_features', return_value=np.array([0.1, 0.2, 0.3])):
            cloner.add_sample(sample)
        
        assert cloner.remove_speaker("speaker1") is True
        assert cloner.get_voice_print("speaker1") is None
        assert cloner.remove_speaker("nonexistent") is False


def test_voice_cloning_engine_init():
    """Test VoiceCloningEngine initialization."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        engine = VoiceCloningEngine()
        assert engine is not None
        assert isinstance(engine.cloner, VoiceCloner)


def test_voice_cloning_engine_load_sample():
    """Test VoiceCloningEngine load_sample method."""
    with patch("audiobook_studio.tts.clone.is_kokoro_available", return_value=True):
        engine = VoiceCloningEngine()
        # Mock the cloner's add_sample method
        with patch.object(engine.cloner, 'add_sample') as mock_add_sample:
            engine.load_sample(
                audio_path=Path("/fake/path.wav"),
                text="Hello",
                speaker_id="speaker1",
            )
            mock_add_sample.assert_called_once()
            args, kwargs = mock_add_sample.call_args
            assert isinstance(args[0], VoiceSample)
            assert args[0].audio_path == Path("/fake/path.wav")
            assert args[0].text == "Hello"
            assert args[0].speaker_id == "speaker1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

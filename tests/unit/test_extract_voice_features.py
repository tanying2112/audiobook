"""Tests for extract_voice_features function - covering missing branches."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pytest

from src.audiobook_studio.tts.clone import extract_voice_features


class TestExtractVoiceFeatures:
    """Tests for extract_voice_features function - targeting missing branches."""

    def test_extract_voice_features_resampling(self):
        """Test resampling branch (sr != sample_rate) - covers lines 98-99."""
        # Create a temporary audio file with different sample rate
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            # Create a WAV file with 48000 Hz sample rate (different from 24000)
            import soundfile as sf
            audio_data = np.sin(np.linspace(0, 100, 48000)).astype(np.float32)
            sf.write(tmp.name, audio_data, 48000)
            
            try:
                features = extract_voice_features(Path(tmp.name), sample_rate=24000)
                assert len(features) == 256
                assert features.dtype == np.float32
            finally:
                Path(tmp.name).unlink(missing_ok=True)

    def test_extract_voice_features_empty_audio(self):
        """Test empty audio normalization branch - covers lines 106-111."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            import soundfile as sf
            # Create empty/very short audio
            audio_data = np.array([], dtype=np.float32)
            sf.write(tmp.name, audio_data, 24000)
            try:
                features = extract_voice_features(Path(tmp.name), sample_rate=24000)
                assert len(features) == 256
                # Should return default features (0.5)
                assert np.allclose(features, 0.5)
            finally:
                Path(tmp.name).unlink(missing_ok=True)

    def test_extract_voice_features_short_audio(self):
        """Test short audio (<=100 samples) skips spectral centroid - covers lines 114-129."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            import soundfile as sf
            # Create very short audio (< 100 samples)
            audio_data = np.sin(np.linspace(0, 10, 50)).astype(np.float32)
            sf.write(tmp.name, audio_data, 24000)
            
            try:
                features = extract_voice_features(Path(tmp.name), sample_rate=24000)
                assert len(features) == 256
            finally:
                Path(tmp.name).unlink(missing_ok=True)

    def test_extract_voice_features_zero_magnitudes(self):
        """Test zero magnitudes branch - covers lines 124-117.
        
        This tests when np.sum(magnitudes) == 0 in the FFT.
        """
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            import soundfile as sf
            # Create silent audio (all zeros) - will produce zero magnitudes
            audio_data = np.zeros(24000, dtype=np.float32)
            sf.write(tmp.name, audio_data, 24000)
            
            try:
                features = extract_voice_features(Path(tmp.name), sample_rate=24000)
                assert len(features) == 256
            finally:
                Path(tmp.name).unlink(missing_ok=True)

    def test_extract_voice_features_exception_handler(self):
        """Test exception handler branch - covers lines 147-150.
        
        Mock soundfile.read to raise an exception.
        """
        with patch('soundfile.read') as mock_read:
            mock_read.side_effect = Exception("Mocked read error")
            
            features = extract_voice_features(Path("dummy.wav"), sample_rate=24000)
            assert len(features) == 256
            assert np.allclose(features, 0.5)

    def test_extract_voice_features_zero_crossing_rate(self):
        """Test zero crossing rate calculation - line 129."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            import soundfile as sf
            # Audio with clear zero crossings
            audio_data = np.sin(np.linspace(0, 100, 24000)).astype(np.float32)
            sf.write(tmp.name, audio_data, 24000)
            
            try:
                features = extract_voice_features(Path(tmp.name), sample_rate=24000)
                assert len(features) == 256
                # Check that ZCR features are present (8 repetitions)
                # ZCR should be around 0.5 for sine wave
            finally:
                Path(tmp.name).unlink(missing_ok=True)

    def test_extract_voice_features_rms(self):
        """Test RMS energy calculation - line 133."""
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
            import soundfile as sf
            audio_data = np.sin(np.linspace(0, 100, 24000)).astype(np.float32)
            sf.write(tmp.name, audio_data, 24000)
            
            try:
                features = extract_voice_features(Path(tmp.name), sample_rate=24000)
                assert len(features) == 256
                # RMS should be around 0.707 for sine wave
            finally:
                Path(tmp.name).unlink(missing_ok=True)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

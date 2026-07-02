"""Integration tests for real audio processing without pydub.

Tests that the core audio analysis utilities (ffmpeg_probe) and quality
metrics work correctly on Python 3.14 without pydub installed.
"""

import asyncio
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ===========================================================================
# ffmpeg_probe utility tests (with mocked subprocess)
# ===========================================================================


class TestFfmpegProbeFunctions:
    """Test ffmpeg_probe.py utility functions using mocked subprocess calls."""

    def test_get_duration_sync_parsing(self):
        """get_duration_sync parses ffprobe JSON output correctly."""
        from src.audiobook_studio.utils.ffmpeg_probe import get_duration

        mock_json = '{"format": {"duration": "12.345"}}'
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_json

        async def run():
            with patch(
                "src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe",
                return_value=mock_result,
            ):
                result = await get_duration(Path("test.wav"))
                return result

        result = asyncio.run(run())
        assert result == 12345  # 12.345 * 1000 = 12345

    def test_get_duration_handles_zero_duration(self):
        """get_duration handles missing or zero duration gracefully."""
        from src.audiobook_studio.utils.ffmpeg_probe import get_duration

        mock_json = '{"format": {}}'
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = mock_json

        async def run():
            with patch(
                "src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe",
                return_value=mock_result,
            ):
                return await get_duration(Path("test.wav"))

        result = asyncio.run(run())
        assert result == 0

    def test_get_duration_raises_on_ffprobe_failure(self):
        """get_duration raises RuntimeError when ffprobe returns non-zero."""
        from src.audiobook_studio.utils.ffmpeg_probe import get_duration

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "No such file"

        async def run():
            with patch(
                "src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe",
                return_value=mock_result,
            ):
                return await get_duration(Path("missing.wav"))

        with pytest.raises(RuntimeError, match="ffprobe failed"):
            asyncio.run(run())

    def test_get_audio_info_parsing(self):
        """get_audio_info parses combined format + stream info."""
        from src.audiobook_studio.utils.ffmpeg_probe import get_audio_info

        mock_data = {
            "format": {"duration": "30.0", "format_name": "wav"},
            "streams": [{"codec_name": "pcm_s16le", "sample_rate": "44100"}],
        }
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = str(mock_data)  # json.dumps would be ideal but eval works for testing

        async def run():
            import json

            mock_result.stdout = json.dumps(mock_data)
            with patch(
                "src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe",
                return_value=mock_result,
            ):
                return await get_audio_info(Path("test.wav"))

        result = asyncio.run(run())
        assert result["format"]["duration"] == "30.0"
        assert len(result["streams"]) == 1
        assert result["streams"][0]["codec_name"] == "pcm_s16le"

    def test_get_rms_peak_parsing(self):
        """get_rms_peak parses astats metadata from ffmpeg stderr."""
        from src.audiobook_studio.utils.ffmpeg_probe import get_rms_peak

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = "lavfi.astats.Overall.RMS_level=-15.23\n" "lavfi.astats.Overall.Peak_level=-3.45\n"

        async def run():
            with patch(
                "src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg",
                return_value=mock_result,
            ):
                return await get_rms_peak(Path("test.wav"))

        rms, peak = asyncio.run(run())
        assert abs(rms - (-15.23)) < 0.01
        assert abs(peak - (-3.45)) < 0.01

    def test_get_rms_peak_fallback_to_volumedetect(self):
        """get_rms_peak falls back to volumedetect when astats returns default."""
        from src.audiobook_studio.utils.ffmpeg_probe import get_rms_peak

        # First call (astats) returns default values
        astats_result = MagicMock()
        astats_result.returncode = 0
        astats_result.stderr = "some unrelated output"

        # Second call (volumedetect) returns actual values
        volumedetect_result = MagicMock()
        volumedetect_result.returncode = 0
        volumedetect_result.stderr = "mean_volume: -20.5 dB\n" "max_volume: -3.2 dB\n"

        call_count = [0]

        async def mock_ffmpeg(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return astats_result
            return volumedetect_result

        async def run():
            with patch(
                "src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg",
                side_effect=mock_ffmpeg,
            ):
                return await get_rms_peak(Path("test.wav"))

        rms, peak = asyncio.run(run())
        assert abs(rms - (-20.5)) < 0.01
        assert abs(peak - (-3.2)) < 0.01

    def test_read_pcm_samples_empty_file(self):
        """read_pcm_samples returns empty array when ffmpeg produces no output."""
        from src.audiobook_studio.utils.ffmpeg_probe import read_pcm_samples

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = b""

        async def run():
            with patch(
                "src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg",
                return_value=mock_result,
            ):
                return await read_pcm_samples(Path("silent.wav"))

        result = asyncio.run(run())
        assert isinstance(result, np.ndarray)
        assert len(result) == 0

    def test_read_pcm_samples_with_data(self):
        """read_pcm_samples correctly parses PCM float32 data."""
        from src.audiobook_studio.utils.ffmpeg_probe import read_pcm_samples

        # Create some known float32 samples
        samples = np.array([0.1, -0.2, 0.3, -0.4, 0.5], dtype=np.float32)
        raw_bytes = samples.tobytes()

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = raw_bytes

        async def run():
            with patch(
                "src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg",
                return_value=mock_result,
            ):
                return await read_pcm_samples(Path("test.wav"))

        result = asyncio.run(run())
        assert len(result) == 5
        np.testing.assert_array_almost_equal(result, samples)


# ===========================================================================
# QualityCheckSuite defensive initialization
# ===========================================================================


class TestQualityCheckSuiteDefensiveInit:
    """Test that QualityCheckSuite handles missing optional backends gracefully."""

    def test_suite_initializes_with_no_optional_deps(self):
        """QualityCheckSuite should initialize without error when all optional deps are missing."""
        from src.audiobook_studio.quality.metrics import QualityCheckSuite

        # Patch all optional imports to raise ImportError
        with patch.dict(
            "sys.modules",
            {
                "onnxruntime": None,
                "funasr": None,
                "faster_whisper": None,
                "speechbrain": None,
                "speechbrain.inference": None,
                "speechbrain.inference.speaker": None,
            },
        ):
            suite = QualityCheckSuite(config={}, hardware_profile="cpu")
            # Should initialize without exception
            assert suite is not None

    def test_check_all_gracefully_returns_when_no_backends(self):
        """check_all should return a valid result even when no metric backends are available."""
        from src.audiobook_studio.quality.metrics import QualityCheckSuite

        with patch.dict(
            "sys.modules",
            {
                "onnxruntime": None,
                "funasr": None,
                "faster_whisper": None,
                "speechbrain": None,
                "speechbrain.inference": None,
                "speechbrain.inference.speaker": None,
            },
        ):
            suite = QualityCheckSuite(config={}, hardware_profile="cpu")
            # Use a non-existent file to trigger the no-backend path
            result = suite.check_all(Path("/nonexistent/audio.wav"))
            assert result is not None
            assert hasattr(result, "passed")


# ===========================================================================
# QualityCheckPipeline._check_optional_dependencies
# ===========================================================================


class TestCheckOptionalDependencies:
    """Test the static method that checks which hard-metric features are available."""

    def test_returns_dict_with_expected_keys(self):
        """Feature map always contains the four expected keys."""
        from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline

        features = QualityCheckPipeline._check_optional_dependencies()
        assert "ffmpeg" in features
        assert "dnsmos" in features
        assert "asr" in features
        assert "speaker_sim" in features
        # ffmpeg is always True (system dependency)
        assert features["ffmpeg"] is True

    def test_values_are_booleans(self):
        """All feature values are booleans."""
        from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline

        features = QualityCheckPipeline._check_optional_dependencies()
        for key, value in features.items():
            assert isinstance(value, bool), f"Feature '{key}' should be bool, got {type(value)}"

    @patch.dict("sys.modules", {"onnxruntime": None})
    def test_dnsmos_false_when_onnxruntime_missing(self):
        """dnsmos should be False when onnxruntime is not importable."""
        from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline

        features = QualityCheckPipeline._check_optional_dependencies()
        assert features["dnsmos"] is False

    @patch.dict("sys.modules", {"onnxruntime": MagicMock(), "onnxruntime.capi": MagicMock()})
    def test_dnsmos_true_when_onnxruntime_present(self):
        """dnsmos should be True when onnxruntime is importable."""
        from src.audiobook_studio.pipeline.quality_check import QualityCheckPipeline

        features = QualityCheckPipeline._check_optional_dependencies()
        assert features["dnsmos"] is True


# ===========================================================================
# No pydub import anywhere in the critical path
# ===========================================================================


class TestNoPydubInCriticalPath:
    """Verify that pydub is not imported in the audio processing critical path."""

    def test_ffmpeg_probe_does_not_import_pydub(self):
        """ffmpeg_probe module should not import pydub."""
        import importlib

        import src.audiobook_studio.utils.ffmpeg_probe as mod

        # Check the module's source for pydub import
        source_file = Path(mod.__file__).read_text()
        # Should not have 'import pydub' or 'from pydub'
        assert "import pydub" not in source_file, "pydub is imported in ffmpeg_probe.py"
        assert "from pydub" not in source_file, "pydub is imported in ffmpeg_probe.py"

    def test_quality_check_does_not_import_pydub(self):
        """quality_check.py should not import pydub."""
        # Use the module file path directly since the pipeline __init__
        # exports a function named `quality_check` that shadows the module.
        source_path = (
            Path(__file__).resolve().parent.parent.parent / "src" / "audiobook_studio" / "pipeline" / "quality_check.py"
        )
        source_file = source_path.read_text()
        # Should not have 'import pydub' or 'from pydub'
        for i, line in enumerate(source_file.split("\n"), 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            assert "import pydub" not in stripped, f"pydub imported at line {i}"
            assert "from pydub" not in stripped, f"pydub imported at line {i}"

    def test_metrics_does_not_import_pydub(self):
        """quality/metrics.py should not import pydub."""
        import src.audiobook_studio.quality.metrics as mod

        source_file = Path(mod.__file__).read_text()
        # Allow mentions in comments/docstrings but not actual imports
        lines = source_file.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            assert "import pydub" not in stripped, f"pydub imported at line {i}"
            assert "from pydub" not in stripped, f"pydub imported at line {i}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

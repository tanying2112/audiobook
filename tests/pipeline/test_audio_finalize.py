"""Unit tests for AudioFinalize module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.pipeline.audio_finalize import AudioFinalizer
from src.audiobook_studio.schemas.audio_finalize import (
    AudioFinalizeParams,
    AudioFinalizeResult,
)


class TestAudioFinalizeParams:
    """Test AudioFinalizeParams schema."""

    def test_default_params(self):
        """Test default parameter values."""
        params = AudioFinalizeParams()
        assert params.apply_loudnorm is True
        assert params.loudnorm_target_i == -20.0
        assert params.apply_fade is True
        assert params.fade_in_ms == 500
        assert params.fade_out_ms == 500
        assert params.apply_sfx is True
        assert params.sfx_gain_db == -20.0
        assert params.embed_metadata is True
        assert params.output_format == "mp3"
        assert params.output_bitrate == "128k"

    def test_custom_params(self):
        """Test custom parameter values."""
        params = AudioFinalizeParams(
            loudnorm_target_i=-23.0,
            loudnorm_target_lra=5.0,
            loudnorm_target_tp=-1.0,
            fade_in_ms=1000,
            fade_out_ms=1000,
            fade_shape="sin",
            sfx_gain_db=-15.0,
            metadata_title="Test Chapter",
            metadata_album="Test Book",
            output_format="m4b",
            output_bitrate="192k",
        )
        assert params.loudnorm_target_i == -23.0
        assert params.loudnorm_target_lra == 5.0
        assert params.loudnorm_target_tp == -1.0
        assert params.fade_in_ms == 1000
        assert params.fade_shape == "sin"
        assert params.sfx_gain_db == -15.0
        assert params.metadata_title == "Test Chapter"
        assert params.output_format == "m4b"

    def test_validation_bounds(self):
        """Test parameter validation bounds."""
        # Valid bounds
        params = AudioFinalizeParams(
            loudnorm_target_i=-10.0,  # max
            loudnorm_target_lra=20.0,  # max
            loudnorm_target_tp=-1.0,  # max
            fade_in_ms=5000,  # max
            fade_out_ms=5000,  # max
        )
        assert params.loudnorm_target_i == -10.0
        assert params.loudnorm_target_lra == 20.0

        # Should fail validation - out of bounds
        with pytest.raises(Exception):  # Pydantic ValidationError
            AudioFinalizeParams(loudnorm_target_i=-5.0)  # > -10

        with pytest.raises(Exception):
            AudioFinalizeParams(loudnorm_target_i=-35.0)  # < -30

        with pytest.raises(Exception):
            AudioFinalizeParams(fade_in_ms=6000)  # > 5000


class TestAudioFinalizer:
    """Test AudioFinalizer class."""

    def test_init_default(self):
        """Test default initialization."""
        finalizer = AudioFinalizer()
        assert finalizer.mock_mode is False
        assert finalizer.sfx_library_path is not None

    def test_init_mock_mode(self):
        """Test mock mode initialization."""
        finalizer = AudioFinalizer(mock_mode=True)
        assert finalizer.mock_mode is True

    def test_init_custom_sfx_path(self):
        """Test custom SFX library path."""
        custom_path = Path("/custom/sfx/path")
        finalizer = AudioFinalizer(sfx_library_path=custom_path, mock_mode=True)
        assert finalizer.sfx_library_path == custom_path

    @pytest.mark.parametrize(
        "sfx_tags,expected_count",
        [
            (["ambient_cheerful"], 1),
            (["ambient_tense", "ambient_soft"], 2),
            ([], 0),
            (None, 0),
        ],
    )
    def test_resolve_sfx_files(self, sfx_tags, expected_count):
        """Test SFX tag resolution."""
        finalizer = AudioFinalizer(mock_mode=True)
        resolved = finalizer._resolve_sfx_files(sfx_tags or [])
        assert len(resolved) == expected_count

    def test_build_loudnorm_filter(self):
        """Test loudnorm filter string generation."""
        finalizer = AudioFinalizer(mock_mode=True)
        params = AudioFinalizeParams(
            loudnorm_target_i=-23.0,
            loudnorm_target_lra=7.0,
            loudnorm_target_tp=-2.0,
        )
        filter_str = finalizer._build_loudnorm_filter(params)
        assert "loudnorm=I=-23.0" in filter_str
        assert "LRA=7.0" in filter_str
        assert "TP=-2.0" in filter_str

    def test_build_fade_filter(self):
        """Test fade filter string generation."""
        finalizer = AudioFinalizer(mock_mode=True)
        params = AudioFinalizeParams(
            fade_in_ms=1000,
            fade_out_ms=1000,
            fade_shape="sin",
        )
        filter_str = finalizer._build_fade_filter(params)
        assert "afade=t=in:st=0:d=1.0:sin" in filter_str
        assert "afade=t=out" in filter_str
        assert "d=1.0" in filter_str

    def test_finalize_mock_success(self):
        """Test successful finalize in mock mode."""
        finalizer = AudioFinalizer(mock_mode=True)
        input_path = Path("/tmp/test_input.mp3")
        output_path = Path("/tmp/test_output.mp3")
        params = AudioFinalizeParams(
            metadata_title="Test",
            metadata_album="Test Album",
        )

        result = finalizer.finalize(
            input_path, output_path, params, ["ambient_cheerful"]
        )

        assert result.input_path == str(input_path)
        assert result.output_path == str(output_path)
        assert result.duration_ms == 10000  # Mock duration
        assert result.loudnorm_applied is True
        assert result.fade_applied is True
        assert result.sfx_applied is True
        assert (
            result.metadata_embedded is True
        )  # Mock mode sets True when metadata_title is provided

    def test_finalize_mock_no_sfx(self):
        """Test finalize without SFX in mock mode."""
        finalizer = AudioFinalizer(mock_mode=True)
        input_path = Path("/tmp/test_input.mp3")
        output_path = Path("/tmp/test_output.mp3")
        params = AudioFinalizeParams(apply_sfx=False)

        result = finalizer.finalize(input_path, output_path, params, None)

        assert result.sfx_applied is False

    def test_finalize_mock_sfx_disabled(self):
        """Test finalize with SFX disabled."""
        finalizer = AudioFinalizer(mock_mode=True)
        input_path = Path("/tmp/test_input.mp3")
        output_path = Path("/tmp/test_output.mp3")
        params = AudioFinalizeParams(apply_sfx=False)

        result = finalizer.finalize(
            input_path, output_path, params, ["ambient_cheerful"]
        )

        assert result.sfx_applied is False

    @patch("subprocess.run")
    def test_finalize_real_success(self, mock_run, tmp_path):
        """Test successful finalize in real mode."""
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="-20.0")

        # Create dummy input file
        input_path = tmp_path / "input.mp3"
        input_path.write_bytes(b"dummy audio")
        output_path = tmp_path / "output.mp3"

        finalizer = AudioFinalizer(mock_mode=False)
        params = AudioFinalizeParams(
            apply_loudnorm=True,
            apply_fade=True,
            apply_sfx=False,
            embed_metadata=False,
        )

        # Mock _measure_loudness and _get_duration
        with patch.object(
            finalizer, "_measure_loudness", return_value=(-20.0, 7.0, -2.0, -40.0)
        ):
            with patch.object(finalizer, "_get_duration", return_value=5000):
                result = finalizer.finalize(input_path, output_path, params, None)

        assert result.input_path == str(input_path)
        assert result.output_path == str(output_path)
        assert result.duration_ms == 5000
        assert result.loudnorm_applied is True
        assert result.fade_applied is True
        assert len(result.errors) == 0

    @patch("subprocess.run")
    def test_finalize_real_ffmpeg_not_found(self, mock_run, tmp_path):
        """Test finalize with ffmpeg not found."""
        mock_run.side_effect = FileNotFoundError("ffmpeg not found")

        input_path = tmp_path / "input.mp3"
        input_path.write_bytes(b"dummy audio")
        output_path = tmp_path / "output.mp3"

        finalizer = AudioFinalizer(mock_mode=False)
        params = AudioFinalizeParams()

        with patch.object(
            finalizer, "_measure_loudness", return_value=(-20.0, 7.0, -2.0, -40.0)
        ):
            with patch.object(finalizer, "_get_duration", return_value=5000):
                result = finalizer.finalize(input_path, output_path, params, None)

        assert len(result.errors) > 0 or len(result.warnings) > 0
        assert output_path.exists()  # Should fallback to copy

    def test_measure_loudness_missing_file(self):
        """Test loudness measurement with missing file."""
        finalizer = AudioFinalizer(mock_mode=True)
        result = finalizer._measure_loudness(Path("/nonexistent/file.mp3"))
        assert result == (0.0, 0.0, 0.0, 0.0)

    def test_get_duration_missing_file(self):
        """Test duration measurement with missing file."""
        finalizer = AudioFinalizer(mock_mode=True)
        result = finalizer._get_duration(Path("/nonexistent/file.mp3"))
        assert result == 0


class TestAudioFinalizeResult:
    """Test AudioFinalizeResult schema."""

    def test_result_creation(self):
        """Test result creation with all fields."""
        result = AudioFinalizeResult(
            input_path="/tmp/input.mp3",
            output_path="/tmp/output.mp3",
            duration_ms=60000,
            measured_i=-20.0,
            measured_lra=7.0,
            measured_tp=-2.0,
            measured_thresh=-40.0,
            loudnorm_applied=True,
            fade_applied=True,
            sfx_applied=False,
            metadata_embedded=True,
            warnings=["warning1"],
            errors=["error1"],
        )
        assert result.duration_ms == 60000
        assert result.measured_i == -20.0
        assert len(result.warnings) == 1
        assert len(result.errors) == 1

    def test_result_defaults(self):
        """Test result with default empty lists."""
        result = AudioFinalizeResult(
            input_path="/tmp/input.mp3",
            output_path="/tmp/output.mp3",
            duration_ms=10000,
            measured_i=0,
            measured_lra=0,
            measured_tp=0,
            measured_thresh=0,
        )
        assert result.warnings == []
        assert result.errors == []

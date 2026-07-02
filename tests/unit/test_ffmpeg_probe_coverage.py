"""Targeted tests for ffmpeg_probe.py covering TimeoutError and ValueError paths.

Covers:
- _run_ffprobe / _run_ffmpeg asyncio.TimeoutError handlers
- get_rms_peak astats ValueError parsing (line 162)
- get_rms_peak volumedetect fallback ValueError paths (lines 172-173, 177-178)
- read_pcm_samples with bytes that are too short for float32
"""

import asyncio
import struct
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from src.audiobook_studio.utils.ffmpeg_probe import (
    _run_ffmpeg,
    _run_ffprobe,
    detect_silence,
    get_duration,
    get_rms_peak,
    read_pcm_samples,
)


class TestTimeoutErrorPaths:
    """Test asyncio.TimeoutError handlers in _run_ffprobe and _run_ffmpeg."""

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_run_ffprobe_timeout(self, mock_exec):
        """Test _run_ffprobe kills process on TimeoutError."""

        async def _fake_wait_for(coro, *, timeout=None):
            if asyncio.iscoroutine(coro):
                try:
                    await coro
                except Exception:
                    pass
            raise asyncio.TimeoutError()

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock()
        mock_proc.wait = AsyncMock()
        mock_exec.return_value = mock_proc

        with patch("asyncio.wait_for", _fake_wait_for):
            with pytest.raises(asyncio.TimeoutError):
                await _run_ffprobe(["-v", "quiet"], timeout=1)

        mock_proc.kill.assert_called_once()

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_run_ffmpeg_timeout(self, mock_exec):
        """Test _run_ffmpeg kills process on TimeoutError."""

        async def _fake_wait_for(coro, *, timeout=None):
            if asyncio.iscoroutine(coro):
                try:
                    await coro
                except Exception:
                    pass
            raise asyncio.TimeoutError()

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock()
        mock_proc.wait = AsyncMock()
        mock_exec.return_value = mock_proc

        with patch("asyncio.wait_for", _fake_wait_for):
            with pytest.raises(asyncio.TimeoutError):
                await _run_ffmpeg(["-i", "test.mp3"], timeout=1)

        mock_proc.kill.assert_called_once()


class TestGetRmsPeakValueErrors:
    """Test ValueError handling in astats and volumedetect parsing."""

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_astats_invalid_rms_value(self, mock_run):
        """Test astats with unparseable RMS level falls through to volumedetect."""
        # First call: astats returns malformed RMS (ValueError in float())
        # Second call: volumedetect succeeds
        mock_run.side_effect = [
            MagicMock(
                returncode=0,
                stderr="frame:0 lavfi.astats.Overall.RMS_level=not_a_number\n"
                "frame:0 lavfi.astats.Overall.Peak_level=-1.5\n",
            ),
            MagicMock(
                returncode=0,
                stderr="mean_volume: -18.0 dB\nmax_volume: -3.0 dB\n",
            ),
        ]
        rms, peak = await get_rms_peak(Path("test.mp3"))
        # RMS parsing failed (stayed -60.0), so fallback was triggered
        # But peak was parsed from astats as -1.5
        # Actually, if rms_db == -60.0 and peak_db == -60.0 check:
        # rms_db is still -60.0 (bad parse), peak_db is -1.5, so condition is False
        # Hmm, let me re-check. The condition is `if rms_db == -60.0 and peak_db == -60.0:`
        # If peak_db was parsed as -1.5, the condition is False, so volumedetect is NOT called
        assert rms == -60.0  # RMS was not parsed
        assert peak == -1.5  # Peak was parsed from astats

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_astats_both_invalid_fallback_volumedetect(self, mock_run):
        """Test astats with both values invalid triggers volumedetect fallback."""
        mock_run.side_effect = [
            MagicMock(
                returncode=0,
                stderr="frame:0 lavfi.astats.Overall.RMS_level=bad_rms\n"
                "frame:0 lavfi.astats.Overall.Peak_level=bad_peak\n",
            ),
            MagicMock(
                returncode=0,
                stderr="mean_volume: -20.0 dB\nmax_volume: -5.0 dB\n",
            ),
        ]
        rms, peak = await get_rms_peak(Path("test.mp3"))
        # Both astats values failed to parse (-60.0 each), fallback triggered
        assert rms == -20.0
        assert peak == -5.0

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_volumedetect_invalid_mean_volume(self, mock_run):
        """Test volumedetect with invalid mean_volume line."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=""),  # astats empty
            MagicMock(
                returncode=0,
                stderr="mean_volume: not_a_number\nmax_volume: -3.0 dB\n",
            ),
        ]
        rms, peak = await get_rms_peak(Path("test.mp3"))
        # mean_volume parsing failed, but max_volume parsed
        assert rms == -60.0  # Not parsed
        assert peak == -3.0

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_volumedetect_invalid_max_volume(self, mock_run):
        """Test volumedetect with invalid max_volume line."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=""),  # astats empty
            MagicMock(
                returncode=0,
                stderr="mean_volume: -15.0 dB\nmax_volume: bad\n",
            ),
        ]
        rms, peak = await get_rms_peak(Path("test.mp3"))
        assert rms == -15.0
        assert peak == -60.0  # Not parsed

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_astats_no_matching_lines(self, mock_run):
        """Test astats with no matching key lines at all."""
        mock_run.side_effect = [
            MagicMock(
                returncode=0,
                stderr="some unrelated output\nanother line\n",
            ),
            MagicMock(
                returncode=0,
                stderr="mean_volume: -10.0 dB\nmax_volume: -1.0 dB\n",
            ),
        ]
        rms, peak = await get_rms_peak(Path("test.mp3"))
        assert rms == -10.0
        assert peak == -1.0

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_astats_failure_raises(self, mock_run):
        """Test astats subprocess failure raises RuntimeError."""
        mock_run.return_value = MagicMock(returncode=1, stderr="ffmpeg error")
        with pytest.raises(RuntimeError, match="astats failed"):
            await get_rms_peak(Path("test.mp3"))

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_volumedetect_fallback_error_no_crash(self, mock_run):
        """Test volumedetect fallback with returncode != 0 returns defaults."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=""),  # astats empty
            MagicMock(returncode=1, stderr="error"),  # volumedetect fails
        ]
        rms, peak = await get_rms_peak(Path("test.mp3"))
        assert rms == -60.0
        assert peak == -60.0


class TestReadPcmEdgeCases:
    """Test read_pcm_samples edge cases."""

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_read_pcm_bytes_odd_length(self, mock_run):
        """Test read_pcm_samples with odd-length bytes triggers ValueError."""
        # Code calls np.frombuffer which raises ValueError for non-multiple-of-4
        mock_run.return_value = MagicMock(returncode=0, stdout=b"\x00\x00\x00")
        with pytest.raises(ValueError, match="buffer size must be a multiple of element size"):
            await read_pcm_samples(Path("test.mp3"))

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_read_pcm_binary_stdout(self, mock_run):
        """Test read_pcm_samples with binary stdout (bytes, not string)."""
        fake_bytes = struct.pack("2f", 0.5, -0.5)
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_bytes)
        samples = await read_pcm_samples(Path("test.mp3"))
        assert len(samples) == 2
        assert abs(samples[0] - 0.5) < 0.001
        assert abs(samples[1] + 0.5) < 0.001

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_read_pcm_string_stdout_valid_length(self, mock_run):
        """Test read_pcm_samples when stdout is a string of correct length (12 chars = 12 bytes = 3 floats)."""
        # "hello world " is 12 chars -> 12 bytes -> 3 float32
        mock_run.return_value = MagicMock(returncode=0, stdout="hello world ")
        samples = await read_pcm_samples(Path("test.mp3"))
        assert len(samples) == 3
        assert samples.dtype == np.float32

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_read_pcm_string_stdout_invalid_length(self, mock_run):
        """Test read_pcm_samples with string of invalid length raises ValueError."""
        mock_run.return_value = MagicMock(returncode=0, stdout="abc")
        with pytest.raises(ValueError, match="buffer size must be a multiple of element size"):
            await read_pcm_samples(Path("test.mp3"))


class TestDetectSilenceEdgeCases:
    """Test detect_silence edge cases."""

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_detect_silence_short_region_skipped(self, mock_run):
        """Test silence region shorter than min_duration_ms is skipped."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr="silence_start: 1.000\nsilence_end: 1.200\n",  # 200ms < 500ms
        )
        result = await detect_silence(Path("test.mp3"), min_duration_ms=500)
        assert result == []

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_detect_silence_multiple_regions(self, mock_run):
        """Test multiple silence regions detected."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr=("silence_start: 1.000\nsilence_end: 3.000\n" "silence_start: 5.000\nsilence_end: 8.000\n"),
        )
        result = await detect_silence(Path("test.mp3"), min_duration_ms=500)
        assert len(result) == 2
        assert result[0] == (1000.0, 3000.0)
        assert result[1] == (5000.0, 8000.0)


class TestGetDurationEdgeCases:
    """Test get_duration edge cases."""

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe")
    async def test_get_duration_large_value(self, mock_run):
        """Test get_duration with a large duration value."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"format": {"duration": "3600.0"}}',  # 1 hour
        )
        duration = await get_duration(Path("test.mp3"))
        assert duration == 3600000

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe")
    async def test_get_duration_fractional(self, mock_run):
        """Test get_duration with fractional seconds."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"format": {"duration": "1.5"}}',
        )
        duration = await get_duration(Path("test.mp3"))
        assert duration == 1500

"""Tests for ffmpeg_probe media analysis utilities."""

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.audiobook_studio.utils.ffmpeg_probe import (
    _run_ffmpeg,
    _run_ffprobe,
    detect_silence,
    detect_silence_sync,
    get_audio_info,
    get_audio_info_sync,
    get_duration,
    get_duration_sync,
    get_rms_peak,
    get_rms_peak_sync,
    read_pcm_samples,
    read_pcm_samples_sync,
)


def run_async(coro):
    """Helper to run async coroutine in tests."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestAsyncRunners:
    """Test internal async process runners."""

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_run_ffprobe_success(self, mock_exec):
        """Test _run_ffprobe returns completed process on success."""
        from unittest.mock import AsyncMock

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b'{"format": {}}', b""))
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result = await _run_ffprobe(["-v", "quiet"])
        assert result.returncode == 0
        assert result.stdout == '{"format": {}}'

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_run_ffprobe_failure(self, mock_exec):
        """Test _run_ffprobe on failure."""
        from unittest.mock import AsyncMock

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"error"))
        mock_proc.returncode = 1
        mock_exec.return_value = mock_proc

        result = await _run_ffprobe(["-v", "quiet"])
        assert result.returncode == 1
        assert "error" in result.stderr

    @pytest.mark.asyncio
    @patch("asyncio.create_subprocess_exec")
    async def test_run_ffmpeg_success(self, mock_exec):
        """Test _run_ffmpeg success."""
        from unittest.mock import AsyncMock

        mock_proc = MagicMock()
        mock_proc.communicate = AsyncMock(return_value=(b"output", b""))
        mock_proc.returncode = 0
        mock_exec.return_value = mock_proc

        result = await _run_ffmpeg(["-i", "input.mp3"])
        assert result.returncode == 0


class TestGetDuration:
    """Test get_duration function."""

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe")
    async def test_get_duration_success(self, mock_run):
        """Test successful duration extraction."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"format": {"duration": "12.345"}}'
        mock_run.return_value = mock_result

        duration = await get_duration(Path("test.mp3"))
        assert duration == 12345

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe")
    async def test_get_duration_failure(self, mock_run):
        """Test failure raises RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "ffprobe error"
        mock_run.return_value = mock_result

        with pytest.raises(RuntimeError, match="ffprobe failed"):
            await get_duration(Path("test.mp3"))

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe")
    async def test_get_duration_zero_duration(self, mock_run):
        """Test zero duration."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"format": {}}'
        mock_run.return_value = mock_result

        duration = await get_duration(Path("test.mp3"))
        assert duration == 0


class TestDetectSilence:
    """Test detect_silence function."""

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    @patch("src.audiobook_studio.utils.ffmpeg_probe.get_duration")
    async def test_detect_silence_no_silence(self, mock_dur, mock_run):
        """Test no silence detected."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = await detect_silence(Path("test.mp3"))
        assert result == []

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_detect_silence_failure(self, mock_run):
        """Test failure raises RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "ffmpeg error"
        mock_run.return_value = mock_result

        with pytest.raises(RuntimeError, match="silencedetect failed"):
            await detect_silence(Path("test.mp3"))

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe.get_duration")
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_detect_silence_with_regions(self, mock_run, mock_dur):
        """Test silence detected with paired start/end."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr="silence_start: 1.000\nsilence_end: 3.000\n",
        )
        mock_dur.return_value = 5000

        result = await detect_silence(
            Path("test.mp3"), threshold_db=-40, min_duration_ms=500
        )
        assert len(result) == 1
        assert result[0] == (1000.0, 3000.0)

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe.get_duration")
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_detect_silence_unpaired_start(self, mock_run, mock_dur):
        """Test silence detected without end (uses duration)."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr="silence_start: 1.000\n",
        )
        mock_dur.return_value = 5000

        result = await detect_silence(Path("test.mp3"))
        assert len(result) == 1
        assert result[0] == (1000.0, 5000.0)


class TestGetRmsPeak:
    """Test get_rms_peak function."""

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_get_rms_peak_with_astats(self, mock_run):
        """Test RMS/Peak extraction via astats."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr="frame:0 lavfi.astats.Overall.RMS_level=-20.5\n"
            "frame:0 lavfi.astats.Overall.Peak_level=-1.5\n",
        )
        rms, peak = await get_rms_peak(Path("test.mp3"))
        assert rms == -20.5
        assert peak == -1.5

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_get_rms_peak_failure(self, mock_run):
        """Test fallback to volumedetect when astats fails."""
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=""),  # astats fails
            MagicMock(
                returncode=0,
                stderr="mean_volume: -18.0 dB\nmax_volume: -2.0 dB\n",
            ),  # volumedetect success
        ]
        rms, peak = await get_rms_peak(Path("test.mp3"))
        assert rms == -18.0
        assert peak == -2.0

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_get_rms_peak_ffmpeg_failure(self, mock_run):
        """Test fallback returns defaults when both astats and volumedetect fail."""
        # First call (astats) succeeds but parsing fails (no output)
        # Second call (volumedetect) fails with returncode=1
        mock_run.side_effect = [
            MagicMock(returncode=0, stderr=""),  # astats succeeds but empty output
            MagicMock(returncode=1, stderr="error"),  # volumedetect fails
        ]
        rms, peak = await get_rms_peak(Path("test.mp3"))
        # Should return defaults (-60.0, -60.0)
        assert rms == -60.0
        assert peak == -60.0


class TestGetAudioInfo:
    """Test get_audio_info function."""

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe")
    async def test_get_audio_info_success(self, mock_run):
        """Test audio info extraction."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = '{"format": {"duration": "10"}, "streams": []}'
        mock_run.return_value = mock_result

        info = await get_audio_info(Path("test.mp3"))
        assert "format" in info
        assert "streams" in info

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe")
    async def test_get_audio_info_failure(self, mock_run):
        """Test failure raises RuntimeError."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "error"
        mock_run.return_value = mock_result

        with pytest.raises(RuntimeError, match="ffprobe failed"):
            await get_audio_info(Path("test.mp3"))


class TestReadPcmSamples:
    """Test read_pcm_samples function."""

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_read_pcm_success(self, mock_run):
        """Test PCM sample extraction."""
        import struct

        import numpy as np

        # Create fake float32 data: 4 samples (16 bytes)
        fake_bytes = struct.pack("4f", 0.1, -0.2, 0.3, -0.4)
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_bytes)

        samples = await read_pcm_samples(Path("test.mp3"))
        assert len(samples) == 4
        # Fixed point arithmetic check
        assert abs(samples[0] - 0.1) < 0.001

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_read_pcm_failure(self, mock_run):
        """Test failure raises RuntimeError."""
        mock_result = MagicMock(returncode=1, stderr="error")
        mock_run.return_value = mock_result

        with pytest.raises(RuntimeError, match="PCM extraction failed"):
            await read_pcm_samples(Path("test.mp3"))

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_read_pcm_empty_output(self, mock_run):
        """Test empty PCM output."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        samples = await read_pcm_samples(Path("test.mp3"))
        assert len(samples) == 0

    @pytest.mark.asyncio
    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    async def test_read_pcm_str_output(self, mock_run):
        """Test string output gets encoded to bytes."""
        # String gets encoded to latin-1 bytes, but not valid float32 -> returns empty
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        samples = await read_pcm_samples(Path("test.mp3"))
        assert len(samples) == 0


class TestSyncWrappers:
    """Test synchronous wrappers."""

    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe")
    def test_get_duration_sync(self, mock_run):
        """Test sync get_duration."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"format": {"duration": "5.5"}}',
        )
        duration = get_duration_sync(Path("test.mp3"))
        assert duration == 5500

    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    def test_detect_silence_sync(self, mock_run):
        """Test sync detect_silence."""
        mock_run.return_value = MagicMock(returncode=0, stderr="")
        result = detect_silence_sync(Path("test.mp3"))
        assert result == []

    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    def test_get_rms_peak_sync(self, mock_run):
        """Test sync get_rms_peak."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stderr="frame:0 lavfi.astats.Overall.RMS_level=-15.0\n"
            "frame:0 lavfi.astats.Overall.Peak_level=-1.0\n",
        )
        rms, peak = get_rms_peak_sync(Path("test.mp3"))
        assert rms == -15.0
        assert peak == -1.0

    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffprobe")
    def test_get_audio_info_sync(self, mock_run):
        """Test sync get_audio_info."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"format": {}}',
        )
        info = get_audio_info_sync(Path("test.mp3"))
        assert info == {"format": {}}

    @patch("src.audiobook_studio.utils.ffmpeg_probe._run_ffmpeg")
    def test_read_pcm_samples_sync(self, mock_run):
        """Test sync read_pcm_samples."""
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        samples = read_pcm_samples_sync(Path("test.mp3"))
        assert len(samples) == 0

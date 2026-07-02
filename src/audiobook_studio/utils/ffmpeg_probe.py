"""
FFmpeg/FFprobe audio analysis utilities.

Provides async functions for audio analysis using ffprobe/ffmpeg subprocess.
Replaces pydub.AudioSegment usage for Python 3.14+ compatibility.
"""

import asyncio
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import List, Tuple

import numpy as np

logger = logging.getLogger(__name__)


async def _run_ffprobe(args: List[str], timeout: int = 30) -> subprocess.CompletedProcess:
    """Run ffprobe asynchronously and return result."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return subprocess.CompletedProcess(
            args=["ffprobe"] + args,
            returncode=proc.returncode,
            stdout=stdout.decode("utf-8", errors="ignore"),
            stderr=stderr.decode("utf-8", errors="ignore"),
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise


async def _run_ffmpeg(args: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Run ffmpeg asynchronously and return result."""
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return subprocess.CompletedProcess(
            args=["ffmpeg"] + args,
            returncode=proc.returncode,
            stdout=stdout.decode("utf-8", errors="ignore"),
            stderr=stderr.decode("utf-8", errors="ignore"),
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise


async def get_duration(path: Path) -> int:
    """Get audio duration in milliseconds using ffprobe.

    Args:
        path: Path to audio file

    Returns:
        Duration in milliseconds
    """
    result = await _run_ffprobe(
        [
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(path),
        ]
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    probe_data = json.loads(result.stdout)
    duration_sec = float(probe_data.get("format", {}).get("duration", 0))
    return int(duration_sec * 1000)


async def detect_silence(
    path: Path,
    threshold_db: float = -40.0,
    min_duration_ms: int = 500,
) -> List[Tuple[float, float]]:
    """Detect silence regions in audio file using ffmpeg silencedetect filter.

    Args:
        path: Path to audio file
        threshold_db: Silence threshold in dB (default: -40)
        min_duration_ms: Minimum silence duration to report in ms (default: 500)

    Returns:
        List of (start_ms, end_ms) tuples for silence regions
    """
    result = await _run_ffmpeg(
        [
            "-v",
            "error",
            "-i",
            str(path),
            "-af",
            f"silencedetect=noise={threshold_db}dB:d={min_duration_ms/1000}",
            "-f",
            "null",
            "-",
        ]
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg silencedetect failed: {result.stderr}")

    stderr = result.stderr
    silence_starts: List[float] = []
    silence_ends: List[float] = []

    for line in stderr.split("\n"):
        m = re.search(r"silence_start: ([\d.]+)", line)
        if m:
            silence_starts.append(float(m.group(1)))
        m = re.search(r"silence_end: ([\d.]+)", line)
        if m:
            silence_ends.append(float(m.group(1)))

    # Pair starts and ends
    silence_regions: List[Tuple[float, float]] = []
    for i, start in enumerate(silence_starts):
        if i < len(silence_ends):
            end = silence_ends[i]
        else:
            # No end found, get total duration
            duration = await get_duration(path)
            end = duration / 1000.0

        duration_ms = (end - start) * 1000
        if duration_ms >= min_duration_ms:
            silence_regions.append((start * 1000, end * 1000))

    return silence_regions


async def get_rms_peak(path: Path) -> Tuple[float, float]:
    """Get RMS and peak levels in dB using ffmpeg astats filter.

    Args:
        path: Path to audio file

    Returns:
        Tuple of (rms_db, peak_db)
    """
    result = await _run_ffmpeg(
        [
            "-v",
            "error",
            "-i",
            str(path),
            "-af",
            "astats=metadata=1:reset=1,ametadata=print:key=lavfi.astats.Overall.RMS_level:key=lavfi.astats.Overall.Peak_level",
            "-f",
            "null",
            "-",
        ]
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg astats failed: {result.stderr}")

    stderr = result.stderr
    rms_db = -60.0
    peak_db = -60.0

    for line in stderr.split("\n"):
        if "lavfi.astats.Overall.RMS_level" in line:
            try:
                rms_db = float(line.split("=")[-1].strip())
            except (ValueError, IndexError):
                pass
        elif "lavfi.astats.Overall.Peak_level" in line:
            try:
                peak_db = float(line.split("=")[-1].strip())
            except (ValueError, IndexError):
                pass

    # If astats didn't work, fallback to volumedetect
    if rms_db == -60.0 and peak_db == -60.0:
        result = await _run_ffmpeg(
            [
                "-v",
                "error",
                "-i",
                str(path),
                "-af",
                "volumedetect",
                "-f",
                "null",
                "-",
            ]
        )

        if result.returncode == 0:
            stderr = result.stderr
            for line in stderr.split("\n"):
                if "mean_volume:" in line:
                    try:
                        rms_db = float(line.split(":")[-1].strip().replace(" dB", ""))
                    except (ValueError, IndexError):
                        pass
                elif "max_volume:" in line:
                    try:
                        peak_db = float(line.split(":")[-1].strip().replace(" dB", ""))
                    except (ValueError, IndexError):
                        pass

    return (rms_db, peak_db)


async def get_audio_info(path: Path) -> dict:
    """Get comprehensive audio info using ffprobe.

    Args:
        path: Path to audio file

    Returns:
        Dictionary with format and stream info
    """
    result = await _run_ffprobe(
        [
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr}")

    return json.loads(result.stdout)


async def read_pcm_samples(path: Path, sample_rate: int = 16000, channels: int = 1) -> np.ndarray:
    """Read raw PCM samples from audio file using ffmpeg.

    Args:
        path: Path to audio file
        sample_rate: Target sample rate
        channels: Target number of channels

    Returns:
        NumPy array of float32 samples
    """
    result = await _run_ffmpeg(
        [
            "-v",
            "quiet",
            "-i",
            str(path),
            "-f",
            "f32le",
            "-acodec",
            "pcm_f32le",
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            "-",
        ]
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg PCM extraction failed: {result.stderr}")

    raw_bytes = result.stdout.encode("latin-1") if isinstance(result.stdout, str) else result.stdout
    if not raw_bytes:
        return np.array([], dtype=np.float32)

    samples = np.frombuffer(raw_bytes, dtype=np.float32)
    return samples


# Synchronous wrappers for backward compatibility
def get_duration_sync(path: Path) -> int:
    """Synchronous wrapper for get_duration."""
    return asyncio.run(get_duration(path))


def detect_silence_sync(
    path: Path,
    threshold_db: float = -40.0,
    min_duration_ms: int = 500,
) -> List[Tuple[float, float]]:
    """Synchronous wrapper for detect_silence."""
    return asyncio.run(detect_silence(path, threshold_db, min_duration_ms))


def get_rms_peak_sync(path: Path) -> Tuple[float, float]:
    """Synchronous wrapper for get_rms_peak."""
    return asyncio.run(get_rms_peak(path))


def get_audio_info_sync(path: Path) -> dict:
    """Synchronous wrapper for get_audio_info."""
    return asyncio.run(get_audio_info(path))


def read_pcm_samples_sync(path: Path, sample_rate: int = 16000, channels: int = 1) -> np.ndarray:
    """Synchronous wrapper for read_pcm_samples."""
    return asyncio.run(read_pcm_samples(path, sample_rate, channels))


if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) > 1:
        test_path = Path(sys.argv[1])
        if test_path.exists():
            logger.info(f"Duration: {get_duration_sync(test_path)}ms")
            logger.info(f"Silence regions: {detect_silence_sync(test_path)}")
            logger.info(f"RMS/Peak: {get_rms_peak_sync(test_path)}")
        else:
            logger.info(f"File not found: {test_path}")
    else:
        logger.info("Usage: python -m audiobook_studio.utils.ffmpeg_probe <audio_file>")

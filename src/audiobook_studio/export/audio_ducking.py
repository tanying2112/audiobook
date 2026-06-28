"""
D3 — Audio-Ducking 混音模块

在 TTS 音频上叠加背景音乐 (BGM)，并实现 Auto-Ducking
（说话时自动降低背景音量，对话抬升 12dB）。
"""

import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from ..utils.ffmpeg_probe import detect_silence_sync, get_duration_sync

logger = logging.getLogger(__name__)


@dataclass
class DuckingSegment:
    """混音段落定义."""

    start_ms: int
    end_ms: int
    type: str = "speech"  # "speech" | "sfx" | "silence"
    duck_gain_db: float = -12.0  # BGM 降低 dB (对话抬升 12dB)
    label: str = ""


@dataclass
class MixConfig:
    """混音配置."""

    bgm_path: Optional[str] = None  # BGM 文件路径
    bgm_volume_db: float = -20.0  # BGM 基础音量 (相对 TTS)
    duck_attack_ms: int = 50  # Ducking 启动时间
    duck_release_ms: int = 200  # Ducking 恢复时间
    duck_threshold_db: float = -24.0  # Ducking 触发阈值
    duck_ratio: float = 4.0  # Ducking 压缩比
    sfx_volume_db: float = -6.0  # SFX 音量
    silence_threshold_db: float = -50.0  # 静音检测阈值


def detect_speech_segments(
    audio_path: Path,
    silence_threshold_db: float = -50.0,
    min_speech_ms: int = 200,
) -> List[DuckingSegment]:
    """检测音频文件中的人声/静音段落.

    使用 ffmpeg 的 silencedetect 滤镜识别静音区域，返回语音段落。
    """
    # Use utility function for silence detection
    silence_regions = detect_silence_sync(
        audio_path,
        threshold_db=silence_threshold_db,
        min_duration_ms=min_speech_ms,
    )

    segments: List[DuckingSegment] = []

    # Get total duration
    total_duration_ms = get_duration_sync(audio_path)

    if not silence_regions:
        # No silence detected — whole file is speech
        segments.append(DuckingSegment(0, total_duration_ms, "speech", label="speech"))
        return segments

    prev_end = 0.0
    for start_ms, end_ms in silence_regions:
        # Speech segment before this silence
        speech_start_ms = int(prev_end)
        speech_end_ms = int(start_ms)
        if speech_end_ms - speech_start_ms >= min_speech_ms:
            segments.append(
                DuckingSegment(speech_start_ms, speech_end_ms, "speech", label="speech")
            )

        # Silence segment
        silence_end_ms = int(end_ms)
        if silence_end_ms - speech_end_ms >= min_speech_ms:
            segments.append(
                DuckingSegment(
                    speech_end_ms,
                    silence_end_ms,
                    "silence",
                    duck_gain_db=0,
                    label="silence",
                )
            )
        prev_end = end_ms

    # Trailing speech
    if prev_end < total_duration_ms:
        segments.append(
            DuckingSegment(int(prev_end), total_duration_ms, "speech", label="speech")
        )

    return segments


def mix_with_ducking(
    speech_path: Path,
    output_path: Path,
    bgm_path: Optional[str] = None,
    ducking_segments: Optional[List[DuckingSegment]] = None,
    config: Optional[MixConfig] = None,
) -> Path:
    """将 TTS 语音与 BGM 混音，应用 Auto-Ducking.

    Args:
        speech_path: TTS 语音文件路径
        output_path: 混音输出路径
        bgm_path: BGM 音频文件路径 (None = 仅做语音后处理)
        ducking_segments: 预定义的混音段落 (None = 自动检测)
        config: 混音配置

    Returns:
        混音输出文件路径
    """
    cfg = config or MixConfig()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Get speech duration
    speech_duration_ms = get_duration_sync(speech_path)
    speech_duration_s = speech_duration_ms / 1000.0

    # Detect segments if not provided
    segments = ducking_segments or detect_speech_segments(
        speech_path, cfg.silence_threshold_db
    )

    if not bgm_path:
        # No BGM — just apply post-processing (normalize + fade)
        logger.info("No BGM provided; applying post-processing only")
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(speech_path),
            "-af",
            "loudnorm=I=-16:LRA=11:TP=-1.5,afade=t=in:ss=0:d=0.3,afade=t=out:st=0:d=0.5",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info(f"Post-processed audio: {output_path}")
        return output_path

    # Apply BGM with ducking using ffmpeg sidechain compression
    bgm_loop = [
        "-stream_loop",
        (
            "-1"
            if speech_duration_s > 30
            else str(int(30 / max(speech_duration_s, 1)) + 1)
        ),
        "-i",
        str(bgm_path),
    ]

    # Build ffmpeg filter for sidechain compression (auto-ducking)
    # sidechaincompress: when speech detected, BGM volume reduces by duck_gain_db
    threshold_db = cfg.duck_threshold_db
    filter_complex = (
        f"[1:a]loudnorm=I=-20:LRA=7:TP=-2,"
        f"volume={cfg.bgm_volume_db}dB[bgm];"
        f"[0:a][bgm]sidechaincompress="
        f"threshold={threshold_db}dB:"
        f"ratio={cfg.duck_ratio}:"
        f"attack={cfg.duck_attack_ms}:"
        f"release={cfg.duck_release_ms}:"
        f"makeup=2dB[mixed];"
        f"[mixed]loudnorm=I=-16:LRA=11:TP=-1.5,"
        f"afade=t=in:ss=0:d=0.5,"
        f"afade=t=out:st={speech_duration_s - 0.5}:d=0.5[out]"
    )

    cmd = (
        [
            "ffmpeg",
            "-y",
            "-i",
            str(speech_path),
        ]
        + bgm_loop
        + [
            "-filter_complex",
            filter_complex,
            "-map",
            "[out]",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            "-shortest",
            str(output_path),
        ]
    )

    logger.info(f"Mixing with auto-ducking: {' '.join(cmd[:8])}...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg mixing timed out")
        # Fallback: simple volume adjustment
        fallback_cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(speech_path),
            "-af",
            "loudnorm=I=-16:LRA=11:TP=-1.5",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            str(output_path),
        ]
        subprocess.run(fallback_cmd, check=True, capture_output=True, text=True)
        logger.warning(f"Used fallback (no ducking): {output_path}")

    logger.info(f"Mixed audio: {output_path}")
    return output_path


def add_sfx(
    speech_path: Path,
    sfx_path: Path,
    output_path: Path,
    insert_at_ms: int = 0,
    sfx_volume_db: float = -6.0,
) -> Path:
    """叠加音效 (SFX) 到音频指定位置."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(speech_path),
        "-i",
        str(sfx_path),
        "-filter_complex",
        f"[1:a]volume={sfx_volume_db}dB[sfx];"
        f"[0:a][sfx]overlay=enable='between(t,{insert_at_ms/1000},{insert_at_ms/1000+3})':format=auto[out]",
        "-map",
        "[out]",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    logger.info(f"SFX added: {output_path}")
    return output_path

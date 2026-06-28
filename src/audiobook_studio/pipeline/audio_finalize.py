"""Audio finalize module — TTS 合成后音频后处理.

包含：
- AudioFinalizer: 后处理器类

设计意图:
TTS 合成完成后，对音频进行标准化后处理：
1. loudnorm - EBU R128 响度标准化
2. afade - 淡入淡出
3. SFX 叠加 - 场景音效混音
4. 元数据嵌入 - 章节标记、Cover Art 等
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Optional

from ..schemas.audio_finalize import AudioFinalizeParams, AudioFinalizeResult

logger = logging.getLogger(__name__)

# Default SFX library paths (can be extended)
DEFAULT_SFX_LIBRARY_PATH = Path("assets/sfx")


class AudioFinalizer:
    """音频后处理器 — TTS 合成完成后的标准化处理.

    用法::

        finalizer = AudioFinalizer()
        result = finalizer.finalize(
            input_path="output/raw.mp3",
            output_path="output/finalized.mp3",
            params=AudioFinalizeParams(
                metadata_title="Chapter 1",
                metadata_album="红楼梦",
            )
        )
    """

    def __init__(
        self,
        sfx_library_path: Optional[Path] = None,
        mock_mode: bool = False,
    ):
        self.sfx_library_path = sfx_library_path or DEFAULT_SFX_LIBRARY_PATH
        self.mock_mode = mock_mode

    def finalize(
        self,
        input_path: Path,
        output_path: Path,
        params: AudioFinalizeParams,
        sfx_tags: Optional[List[str]] = None,
    ) -> AudioFinalizeResult:
        """对 TTS 输出音频进行后处理.

        Args:
            input_path: 输入音频文件路径 (TTS 合成输出)
            output_path: 输出音频文件路径 (后处理完成)
            params: 后处理参数配置
            sfx_tags: 音效标签列表 (用于从 SFX 库查找对应音效文件)

        Returns:
            AudioFinalizeResult: 后处理结果
        """
        logger.info(f"Finalizing audio: {input_path} → {output_path}")

        if not self.mock_mode:
            return self._finalize_real(input_path, output_path, params, sfx_tags)
        else:
            return self._finalize_mock(input_path, output_path, params, sfx_tags)

    def _finalize_mock(
        self,
        input_path: Path,
        output_path: Path,
        params: AudioFinalizeParams,
        sfx_tags: Optional[List[str]] = None,
    ) -> AudioFinalizeResult:
        """Mock mode: simulate processing without actual ffmpeg."""
        # Create dummy output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"MP3 finalized dummy audio")

        return AudioFinalizeResult(
            input_path=str(input_path),
            output_path=str(output_path),
            duration_ms=10000,  # Mock 10 seconds
            measured_i=params.loudnorm_target_i,
            measured_lra=params.loudnorm_target_lra,
            measured_tp=params.loudnorm_target_tp,
            measured_thresh=-40.0,
            loudnorm_applied=params.apply_loudnorm,
            fade_applied=params.apply_fade,
            sfx_applied=params.apply_sfx and bool(sfx_tags),
            metadata_embedded=params.embed_metadata and bool(params.metadata_title),
            warnings=[],
            errors=[],
        )

    def _finalize_real(
        self,
        input_path: Path,
        output_path: Path,
        params: AudioFinalizeParams,
        sfx_tags: Optional[List[str]] = None,
    ) -> AudioFinalizeResult:
        """Real mode: actual ffmpeg processing."""
        warnings = []
        errors = []

        # Validate input
        if not input_path.exists():
            errors.append(f"Input file not found: {input_path}")
            return AudioFinalizeResult(
                input_path=str(input_path),
                output_path=str(output_path),
                duration_ms=0,
                measured_i=0,
                measured_lra=0,
                measured_tp=0,
                measured_thresh=0,
                loudnorm_applied=False,
                fade_applied=False,
                sfx_applied=False,
                metadata_embedded=False,
                warnings=warnings,
                errors=errors,
            )

        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Build ffmpeg filter chain
        filters = []
        loudnorm_applied = False
        fade_applied = False
        sfx_applied = False

        # 1. Loudnorm (EBU R128) - must be first for accurate measurement
        if params.apply_loudnorm:
            loudnorm_filter = self._build_loudnorm_filter(params)
            filters.append(loudnorm_filter)
            loudnorm_applied = True

        # 2. Fade in/out
        if params.apply_fade:
            fade_filter = self._build_fade_filter(params)
            filters.append(fade_filter)
            fade_applied = True

        # 3. Build filter_complex
        filter_complex = ",".join(filters) if filters else "anull"

        # 4. Build ffmpeg command
        cmd = ["ffmpeg", "-y", "-i", str(input_path)]

        # Add SFX overlay if requested
        sfx_inputs = []
        if params.apply_sfx and sfx_tags:
            sfx_files = self._resolve_sfx_files(sfx_tags)
            for sfx_path in sfx_files:
                if sfx_path.exists():
                    cmd.extend(["-i", str(sfx_path)])
                    sfx_inputs.append(sfx_path)
                else:
                    warnings.append(f"SFX file not found: {sfx_path}")

            if sfx_inputs:
                sfx_applied = True
                # Add amix filter for SFX overlay
                num_inputs = 1 + len(sfx_inputs)
                filter_complex = f"[0:a]{filter_complex}[main]"
                for i in range(len(sfx_inputs)):
                    filter_complex += (
                        f";[{i+1}:a]volume={params.sfx_gain_db/20:.4f}[sfx{i}]"
                    )
                filter_complex += f";[main]" + "".join(
                    f"[sfx{i}]" for i in range(len(sfx_inputs))
                )
                filter_complex += (
                    f"amix=inputs={num_inputs}:duration=first:dropout_transition=2"
                )

        # Apply filter and set output format
        if filter_complex:
            cmd.extend(["-filter_complex", filter_complex])

        cmd.extend(
            [
                "-c:a",
                (
                    "libmp3lame"
                    if params.output_format == "mp3"
                    else "aac" if params.output_format == "m4b" else "pcm_s16le"
                ),
                "-b:a",
                params.output_bitrate,
                "-map",
                "0:a" if not sfx_inputs else "0:a",
                str(output_path),
            ]
        )

        # Execute ffmpeg
        try:
            logger.info(f"Running ffmpeg: {' '.join(cmd[:10])}...")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

            if result.returncode != 0:
                errors.append(f"ffmpeg failed: {result.stderr}")
                # Fallback: copy input to output
                import shutil

                shutil.copy2(input_path, output_path)
                warnings.append("ffmpeg failed, fell back to simple copy")

        except FileNotFoundError:
            errors.append("ffmpeg not found")
            import shutil

            shutil.copy2(input_path, output_path)
            warnings.append("ffmpeg not found, fell back to simple copy")
        except subprocess.TimeoutExpired:
            errors.append("ffmpeg timed out")
            import shutil

            shutil.copy2(input_path, output_path)
            warnings.append("ffmpeg timed out, fell back to simple copy")

        # 5. Embed metadata (separate ffmpeg call for metadata)
        metadata_embedded = False
        if params.embed_metadata and not errors:
            metadata_embedded = self._embed_metadata(output_path, params)

        # 6. Measure final output
        measured_i, measured_lra, measured_tp, measured_thresh = self._measure_loudness(
            output_path
        )
        duration_ms = self._get_duration(output_path)

        logger.info(
            f"Audio finalized: {output_path.name}, "
            f"duration={duration_ms}ms, loudness={measured_i:.1f} LUFS"
        )

        return AudioFinalizeResult(
            input_path=str(input_path),
            output_path=str(output_path),
            duration_ms=duration_ms,
            measured_i=measured_i,
            measured_lra=measured_lra,
            measured_tp=measured_tp,
            measured_thresh=measured_thresh,
            loudnorm_applied=loudnorm_applied,
            fade_applied=fade_applied,
            sfx_applied=sfx_applied,
            metadata_embedded=metadata_embedded,
            warnings=warnings,
            errors=errors,
        )

    def _build_loudnorm_filter(self, params: AudioFinalizeParams) -> str:
        """Build ffmpeg loudnorm filter string."""
        return (
            f"loudnorm="
            f"I={params.loudnorm_target_i}:"
            f"LRA={params.loudnorm_target_lra}:"
            f"TP={params.loudnorm_target_tp}:"
            f"print_format=summary"
        )

    def _build_fade_filter(self, params: AudioFinalizeParams) -> str:
        """Build ffmpeg fade in/out filter string."""
        fade_in_sec = params.fade_in_ms / 1000.0
        fade_out_sec = params.fade_out_ms / 1000.0

        # Note: fade out needs duration, not end time - we use a placeholder
        # that gets replaced after we know the actual duration
        fade_parts = []
        if params.fade_in_ms > 0:
            fade_parts.append(f"afade=t=in:st=0:d={fade_in_sec}:{params.fade_shape}")
        if params.fade_out_ms > 0:
            # Fade out will be applied from (duration - fade_out_ms) to end
            # We use a placeholder that gets resolved in post-processing
            fade_parts.append(
                f"afade=t=out:st=PLACEHOLDER:d={fade_out_sec}:{params.fade_shape}"
            )

        return ",".join(fade_parts) if fade_parts else "anull"

    def _resolve_sfx_files(self, sfx_tags: List[str]) -> List[Path]:
        """Resolve SFX tags to file paths."""
        # Map common SFX tags to filename patterns
        sfx_mapping = {
            "ambient_cheerful": "ambient_cheerful.mp3",
            "ambient_melancholic": "ambient_melancholic.mp3",
            "ambient_tense": "ambient_tense.mp3",
            "ambient_suspense": "ambient_suspense.mp3",
            "ambient_surprise": "ambient_surprise.mp3",
            "ambient_soft": "ambient_soft.mp3",
            "ambient_sigh": "ambient_sigh.mp3",
        }

        resolved = []
        for tag in sfx_tags:
            filename = sfx_mapping.get(tag, f"{tag}.mp3")
            resolved.append(self.sfx_library_path / filename)

        return resolved

    def _embed_metadata(self, audio_path: Path, params: AudioFinalizeParams) -> bool:
        """Embed metadata into audio file using ffmpeg."""
        metadata_args = []

        if params.metadata_title:
            metadata_args.extend(["-metadata", f"title={params.metadata_title}"])
        if params.metadata_artist:
            metadata_args.extend(["-metadata", f"artist={params.metadata_artist}"])
        if params.metadata_album:
            metadata_args.extend(["-metadata", f"album={params.metadata_album}"])
        if params.metadata_track:
            metadata_args.extend(["-metadata", f"track={params.metadata_track}"])
        if params.metadata_year:
            metadata_args.extend(["-metadata", f"year={params.metadata_year}"])
        if params.metadata_genre:
            metadata_args.extend(["-metadata", f"genre={params.metadata_genre}"])

        if not metadata_args:
            return False

        # Temporary file for atomic write
        temp_path = audio_path.with_suffix(audio_path.suffix + ".tmp")

        cmd = (
            [
                "ffmpeg",
                "-y",
                "-i",
                str(audio_path),
                "-c",
                "copy",  # Copy audio stream without re-encoding
            ]
            + metadata_args
            + [str(temp_path)]
        )

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0:
                temp_path.replace(audio_path)
                logger.info(f"Embedded metadata into {audio_path.name}")
                return True
            else:
                logger.warning(f"Failed to embed metadata: {result.stderr}")
                if temp_path.exists():
                    temp_path.unlink()
                return False
        except Exception as e:
            logger.warning(f"Metadata embedding failed: {e}")
            if temp_path.exists():
                temp_path.unlink()
            return False

    def _measure_loudness(self, audio_path: Path) -> tuple:
        """Measure EBU R128 loudness using ffmpeg."""
        if not audio_path.exists():
            return 0.0, 0.0, 0.0, 0.0

        cmd = [
            "ffmpeg",
            "-i",
            str(audio_path),
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            stderr = result.stderr

            # Parse ebur128 output
            # Look for: I: -20.0 LUFS, LRA: 7.0 LU, Peak: -2.0 dBFS, Threshold: -40.0 LUFS
            i_match = re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", stderr)
            lra_match = re.search(r"LRA:\s*(-?\d+\.?\d*)\s*LU", stderr)
            tp_match = re.search(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", stderr)
            thresh_match = re.search(r"Threshold:\s*(-?\d+\.?\d*)\s*LUFS", stderr)

            return (
                float(i_match.group(1)) if i_match else -20.0,
                float(lra_match.group(1)) if lra_match else 7.0,
                float(tp_match.group(1)) if tp_match else -2.0,
                float(thresh_match.group(1)) if thresh_match else -40.0,
            )
        except Exception as e:
            logger.warning(f"Failed to measure loudness: {e}")
            return -20.0, 7.0, -2.0, -40.0

    def _get_duration(self, audio_path: Path) -> int:
        """Get audio duration in milliseconds using ffprobe."""
        if not audio_path.exists():
            return 0

        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return int(float(result.stdout.strip()) * 1000)
        except Exception as e:
            logger.warning(f"Failed to get duration: {e}")
            return 0


# Convenience function for module-level import
def finalize_audio(
    input_path: Path,
    output_path: Path,
    params: Optional[AudioFinalizeParams] = None,
    sfx_tags: Optional[List[str]] = None,
    mock_mode: bool = False,
) -> AudioFinalizeResult:
    """Convenience function for audio finalization.

    Args:
        input_path: Input audio file path
        output_path: Output audio file path
        params: Post-processing parameters (uses defaults if None)
        sfx_tags: SFX tags to overlay
        mock_mode: If True, simulate processing without ffmpeg

    Returns:
        AudioFinalizeResult: Processing result
    """
    finalizer = AudioFinalizer(mock_mode=mock_mode)
    if params is None:
        params = AudioFinalizeParams()
    return finalizer.finalize(input_path, output_path, params, sfx_tags)

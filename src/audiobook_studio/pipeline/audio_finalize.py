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

import asyncio
import logging
import re
from pathlib import Path
from typing import List, Optional

from ..analyzer import DEFAULT_EFFECTS_LIBRARY_PATH, SceneTagMapper
from ..export.pool import run_ffmpeg
from ..schemas.audio_finalize import AudioFinalizeParams, AudioFinalizeResult
from ..security import safe_subprocess_args
from ..utils.async_utils import run_async_safe
from ..utils.loudness import aresample_filter, resolve_loudness

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
        effects_library_path: Optional[Path] = None,
        mock_mode: bool = False,
    ):
        self.sfx_library_path = sfx_library_path or DEFAULT_SFX_LIBRARY_PATH
        self.effects_library_path = effects_library_path or DEFAULT_EFFECTS_LIBRARY_PATH
        self.mock_mode = mock_mode
        # Initialize scene tag mapper from analyzer module
        self.scene_tag_mapper = SceneTagMapper(effects_library_path=self.effects_library_path)

    def finalize(
        self,
        input_path: Path,
        output_path: Path,
        params: AudioFinalizeParams,
        sfx_tags: Optional[List[str]] = None,
        scene_tags: Optional[List[str]] = None,
    ) -> AudioFinalizeResult:
        """对 TTS 输出音频进行后处理.

        Args:
            input_path: 输入音频文件路径 (TTS 合成输出)
            output_path: 输出音频文件路径 (后处理完成)
            params: 后处理参数配置
            sfx_tags: 情感音效标签列表 (用于从 SFX 库查找对应音效文件)
            scene_tags: 环境场景标签列表 (用于从 effects 库查找环境音效文件)

        Returns:
            AudioFinalizeResult: 后处理结果
        """
        logger.info(f"Finalizing audio: {input_path} → {output_path}")

        if not self.mock_mode:
            return self._finalize_real(input_path, output_path, params, sfx_tags, scene_tags)
        else:
            return self._finalize_mock(input_path, output_path, params, sfx_tags, scene_tags)

    def _finalize_mock(
        self,
        input_path: Path,
        output_path: Path,
        params: AudioFinalizeParams,
        sfx_tags: Optional[List[str]] = None,
        scene_tags: Optional[List[str]] = None,
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
            preset_applied=params.loudness_preset,
            measured_lra=params.loudnorm_target_lra,
            measured_tp=params.loudnorm_target_tp,
            measured_thresh=-40.0,
            loudnorm_applied=params.apply_loudnorm,
            fade_applied=params.apply_fade,
            sfx_applied=params.apply_sfx and (bool(sfx_tags) or bool(scene_tags)),
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
        scene_tags: Optional[List[str]] = None,
    ) -> AudioFinalizeResult:
        """Real mode: actual ffmpeg processing."""
        warnings: List[str] = []
        errors: List[str] = []

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

        # 响度档解析 (2026-10-09): preset 覆写显式目标; 拷贝参数不惊扰调用方对象
        preset_applied = params.loudness_preset
        if params.loudness_preset:
            pi, plra, ptp = resolve_loudness(params.loudness_preset)
            params = params.model_copy(update={
                "loudnorm_target_i": pi,
                "loudnorm_target_lra": plra,
                "loudnorm_target_tp": ptp,
            })

        # P2 修复 (2026-10-11): loudnorm 内部升采样恒输出 192kHz (linear 模式亦然),
        # 链尾 aresample 收回输入采样率 — 保住 "输出 SR = 输入 SR" 契约。
        # 之前 wav 直出 192k、mp3/m4b 由编码器自动协商到 48k。
        input_sr = self._get_sample_rate(input_path)

        # 两遍线性 loudnorm: 先测输入响度, linear=true 纯增益 (无动态泵动)
        measured_pre = None
        if params.apply_loudnorm and params.loudnorm_two_pass:
            mi, mlra, mtp, mth = self._measure_loudness(input_path)
            if mi < -1.0:  # 有效测量 (0.0 = 失败哨兵; 真实综合响度必 < -1 LUFS)
                measured_pre = {"i": mi, "lra": mlra, "tp": mtp, "thresh": mth}

        # Build ffmpeg filter chain
        filters = []
        loudnorm_applied = False
        fade_applied = False
        sfx_applied = False

        # 1. Loudnorm (EBU R128) - must be first for accurate measurement
        if params.apply_loudnorm:
            loudnorm_filter = self._build_loudnorm_filter(params, measured_pre)
            filters.append(loudnorm_filter)
            loudnorm_applied = True

        # 2. Fade in/out
        if params.apply_fade:
            # 淡出起点需真实时长 (P3a 修复): 旧实现留 "st=PLACEHOLDER" 字面量
            # 且从未解析 → ffmpeg 解析必败 → 主路径整链回退纯拷贝,
            # loudnorm/alimiter 从未真正生效。
            input_duration_ms = self._get_duration(input_path)
            fade_filter = self._build_fade_filter(params, input_duration_ms)
            filters.append(fade_filter)
            fade_applied = True

        # 3. Build filter_complex
        filter_complex = ",".join(filters) if filters else "anull"

        # 4. Build ffmpeg command
        cmd = ["ffmpeg", "-y", "-i", str(input_path)]

        # 叠加轨 (SFX / 场景环境音) — 2026-10-09 对照原声复盘后重写, 修三处:
        # 1) volume 增益: 旧写法 dB/20 被当线性值 (volume=-1.0 实为 -1dB≈全电平),
        #    正确写法 volume=<dB>dB;
        # 2) 混音收口: 旧 `-map 0:a` 令 filter_complex 输出无人消费 → ffmpeg rc=234,
        #    叠加轨从未真正混入 (静默回退纯拷贝); 现在混音输出标注 [aout] 并显式 -map;
        # 3) sfx+scene 组合旧实现对 [main] 二次消费 (图错误); 现在统一一次成图。
        mix_labels: List[str] = []
        next_input = 1
        if params.apply_sfx and sfx_tags:
            for sfx_path in self._resolve_sfx_files(sfx_tags):
                if sfx_path.exists():
                    cmd.extend(["-i", str(sfx_path)])
                    mix_labels.append(
                        f"[{next_input}:a]volume={params.sfx_gain_db}dB[ov{next_input}]"
                    )
                    next_input += 1
                else:
                    warnings.append(f"SFX file not found: {sfx_path}")

        if params.apply_sfx and scene_tags:
            for scene_path in self.scene_tag_mapper.resolve(scene_tags):
                if scene_path.exists():
                    cmd.extend(["-i", str(scene_path)])
                    mix_labels.append(
                        f"[{next_input}:a]volume={params.sfx_gain_db}dB[ov{next_input}]"
                    )
                    next_input += 1
                else:
                    warnings.append(f"Scene effect file not found: {scene_path}")

        mix_used = bool(mix_labels)
        if not mix_used and params.apply_loudnorm:
            # 主语音-only 路径: loudnorm 后紧跟 TP 限幅器 (v6 链), fade 之前。
            # level=disabled 防止自动 makeup gain; TP 目标由 preset 推导 (-3 dBTP → 0.7079)。
            # SFX 路径不走这里 — 其 alimiter 在 amix 收口处已有 (保持既有行为)。
            tp_limit = 10 ** (params.loudnorm_target_tp / 20.0)
            # loudnorm 构建时必为 filters[0] (见上方 "must be first" 注释), 插到其后
            filters.insert(1, f"alimiter=limit={tp_limit:.4f}:attack=5:release=100:level=disabled")
            # aresample 收尾 (P2): loudnorm 恒输出 192k, 收回输入 SR
            filters.append(aresample_filter(input_sr))
            filter_complex = ",".join(filters) if filters else "anull"
        if mix_used:
            sfx_applied = True
            # amix normalize=0 关掉 1/n 衰减; 混合峰值可能越过 loudnorm 的 TP 目标,
            # 串 TP 限幅器兜底 (P0.1 v4 链同款 attack/release)
            tp_limit = 10 ** (params.loudnorm_target_tp / 20.0)
            ov_refs = "".join(f"[ov{i}]" for i in range(1, next_input))
            filter_complex = (
                f"[0:a]{filter_complex}[main];" + ";".join(mix_labels) + ";"
                f"[main]{ov_refs}amix=inputs={1 + len(mix_labels)}:duration=first:normalize=0,"
                f"alimiter=limit={tp_limit:.4f}:attack=5:release=100:level=disabled,"
                f"{aresample_filter(input_sr)}[aout]"
            )
        else:
            # P3a 修复: -filter_complex 的无标注链在 "-map 0:a" 消费输入流后无法
            # 绑定 (ffmpeg: "Cannot find an unused audio input stream") → 主路径
            # rc!=0 整链回退纯拷贝。与 SFX 路径同构: [0:a]<chain>[aout]。
            filter_complex = f"[0:a]{filter_complex}[aout]"

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
                "[aout]",
                str(output_path),
            ]
        )

        # Execute ffmpeg
        try:
            logger.info(f"Running ffmpeg: {' '.join(cmd[:10])}...")
            # Validate command args for security
            cmd = safe_subprocess_args(cmd)
            # Run under global semaphore with timeout
            result = run_async_safe(run_ffmpeg(cmd, timeout=120, capture_output=True))

            if result.returncode != 0:
                stderr_str = (
                    result.stderr.decode("utf-8", errors="replace")
                    if isinstance(result.stderr, bytes)
                    else str(result.stderr)
                )
                errors.append(f"ffmpeg failed: {stderr_str}")
                # Fallback: copy input to output
                import shutil

                shutil.copy2(input_path, output_path)
                warnings.append("ffmpeg failed, fell back to simple copy")

        except FileNotFoundError:
            errors.append("ffmpeg not found")
            import shutil

            shutil.copy2(input_path, output_path)
            warnings.append("ffmpeg not found, fell back to simple copy")
        except asyncio.TimeoutError:
            errors.append("ffmpeg timed out")
            import shutil

            shutil.copy2(input_path, output_path)
            warnings.append("ffmpeg timed out, fell back to simple copy")

        # 5. Embed metadata (separate ffmpeg call for metadata)
        metadata_embedded = False
        if params.embed_metadata and not errors:
            metadata_embedded = self._embed_metadata(output_path, params)

        # 6. Measure final output
        measured_i, measured_lra, measured_tp, measured_thresh = self._measure_loudness(output_path)
        duration_ms = self._get_duration(output_path)

        logger.info(
            f"Audio finalized: {output_path.name}, " f"duration={duration_ms}ms, loudness={measured_i:.1f} LUFS"
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
            preset_applied=preset_applied,
            fade_applied=fade_applied,
            sfx_applied=sfx_applied,
            metadata_embedded=metadata_embedded,
            warnings=warnings,
            errors=errors,
        )

    def _build_loudnorm_filter(
        self, params: AudioFinalizeParams, measured: Optional[dict] = None
    ) -> str:
        """Build ffmpeg loudnorm filter string.

        measured 为两遍法第一遍测量值时走 linear 模式 (纯增益, 无动态响度泵动);
        否则单遍动态模式 (旧行为)。
        """
        # 响度档在此解析, 直接调用方无须先经 _finalize_real 的 model_copy
        if params.loudness_preset:
            pi, plra, ptp = resolve_loudness(params.loudness_preset)
        else:
            pi, plra, ptp = (
                params.loudnorm_target_i,
                params.loudnorm_target_lra,
                params.loudnorm_target_tp,
            )
        base = f"loudnorm=I={pi}:LRA={plra}:TP={ptp}"
        if measured:
            base += (
                f":measured_I={measured['i']}:measured_LRA={measured['lra']}:"
                f"measured_TP={measured['tp']}:measured_thresh={measured['thresh']}:"
                f"linear=true"
            )
        return base + ":print_format=summary"

    def _build_fade_filter(
        self, params: AudioFinalizeParams, duration_ms: int = 0
    ) -> str:
        """Build ffmpeg fade filter string.

        duration_ms 为输入实测时长 (ffprobe); 淡出起点 = 时长 - 淡出时长。
        旧实现留 "st=PLACEHOLDER" 字面量且从未解析 → ffmpeg 解析必败,
        主路径整链回退纯拷贝 (loudnorm/限幅器从未生效), P3a 修复为真实起点。
        """
        fade_in_sec = params.fade_in_ms / 1000.0
        fade_out_sec = params.fade_out_ms / 1000.0

        # P3a 修复: 旧写法 ":{shape}" 裸位置参数落到 afade 的 start_sample
        # → ffmpeg 解析必败 (Invalid argument) → 主路径整链回退纯拷贝。
        # 正确写法 ":curve={shape}"; ffmpeg 无 "sin" 曲线 (最接近 qsin),
        # schema 允许的 "sin" 映射 qsin 保持链可跑。
        shape = "qsin" if params.fade_shape == "sin" else params.fade_shape
        fade_parts = []
        if params.fade_in_ms > 0:
            fade_parts.append(f"afade=t=in:st=0:d={fade_in_sec}:curve={shape}")
        if params.fade_out_ms > 0:
            fade_out_start = max(0.0, (duration_ms - params.fade_out_ms) / 1000.0)
            fade_parts.append(
                f"afade=t=out:st={fade_out_start:.3f}:d={fade_out_sec}:curve={shape}"
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

        # Temporary file for atomic write. 临时文件必须保留原扩展名在后
        # (``xxx.tmp.mp3``) — 旧写法 ``xxx.mp3.tmp`` 令 ffmpeg 无法从扩展名
        # 推断 muxer (mp3/wav/m4b 全中招), metadata 嵌入静默失败 (2026-10-12
        # 系统管线实测发现)。
        temp_path = audio_path.with_name(audio_path.stem + ".tmp" + audio_path.suffix)

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
            # Validate command args for security
            cmd = safe_subprocess_args(cmd)
            # Run under global semaphore with timeout
            result = run_async_safe(run_ffmpeg(cmd, timeout=60, capture_output=True))
            if result.returncode == 0:
                temp_path.replace(audio_path)
                logger.info(f"Embedded metadata into {audio_path.name}")
                return True
            else:
                logger.warning(
                    f"Failed to embed metadata: {result.stderr.decode('utf-8', errors='replace') if isinstance(result.stderr, bytes) else str(result.stderr)}"
                )
                if temp_path.exists():
                    temp_path.unlink()
                return False
        except Exception as e:
            logger.warning(f"Metadata embedding failed: {e}")
            if temp_path.exists():
                temp_path.unlink()
            return False

    def _measure_loudness(self, audio_path: Path) -> tuple[float, float, float, float]:
        """Measure EBU R128 loudness using ffmpeg."""
        if not audio_path.exists():
            return 0.0, 0.0, 0.0, 0.0

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(audio_path),
            "-af",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ]

        try:
            # Validate command args for security
            cmd = safe_subprocess_args(cmd)
            # Run under global semaphore with timeout
            result = run_async_safe(run_ffmpeg(cmd, timeout=60, capture_output=True))
            stderr = (
                result.stderr.decode("utf-8", errors="replace")
                if isinstance(result.stderr, bytes)
                else str(result.stderr)
            )

            # Parse ebur128: 只取 Summary 块 (否则首匹配是逐 100ms 的瞬时 I:)
            # Summary: I: -20.0 LUFS / LRA: 7.0 LU / Peak: -2.0 dBFS / Threshold: -40.0 LUFS
            s = stderr[stderr.find("Summary:"):] if "Summary:" in stderr else stderr
            i_match = re.search(r"I:\s*(-?\d+\.?\d*)\s*LUFS", s)
            lra_match = re.search(r"LRA:\s*(-?\d+\.?\d*)\s*LU", s)
            tp_match = re.search(r"Peak:\s*(-?\d+\.?\d*)\s*dBFS", s)
            thresh_match = re.search(r"Threshold:\s*(-?\d+\.?\d*)\s*LUFS", s)

            if not i_match:
                raise ValueError(f"no ebur128 summary in output: {stderr[-200:]}")
            return (
                float(i_match.group(1)),
                float(lra_match.group(1)) if lra_match else 0.0,
                float(tp_match.group(1)) if tp_match else 0.0,
                float(thresh_match.group(1)) if thresh_match else 0.0,
            )
        except Exception as e:
            logger.warning(f"Failed to measure loudness: {e}")
            # 失败显式归零 (旧代码回退 -20/7/-2/-40 假值, 掩盖测量从未生效的事实)
            return 0.0, 0.0, 0.0, 0.0

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
            # Validate command args for security
            cmd = safe_subprocess_args(cmd)
            # Run under global semaphore with timeout
            result = run_async_safe(run_ffmpeg(cmd, timeout=10, capture_output=True))
            return int(float(result.stdout.strip()) * 1000)
        except Exception as e:
            logger.warning(f"Failed to get duration: {e}")
            return 0

    def _get_sample_rate(self, audio_path: Path) -> int:
        """Get audio sample rate via ffprobe (P2: aresample 收尾的目标采样率)."""
        if not audio_path.exists():
            return 44100

        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=sample_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio_path),
        ]

        try:
            # Validate command args for security
            cmd = safe_subprocess_args(cmd)
            # Run under global semaphore with timeout
            result = run_async_safe(run_ffmpeg(cmd, timeout=10, capture_output=True))
            m = re.search(r"\d+", str(result.stdout))
            if m:
                return int(m.group(0))
            logger.warning(f"No sample_rate in ffprobe output for {audio_path}")
        except Exception as e:
            logger.warning(f"Failed to get sample rate: {e}")
        # 探测失败兜底: 有声书标准 44.1kHz (好于放任 loudnorm 的 192k 直出)
        return 44100


# Convenience function for module-level import
def finalize_audio(
    input_path: Path,
    output_path: Path,
    params: Optional[AudioFinalizeParams] = None,
    sfx_tags: Optional[List[str]] = None,
    scene_tags: Optional[List[str]] = None,
    mock_mode: bool = False,
) -> AudioFinalizeResult:
    """Convenience function for audio finalization.

    Args:
        input_path: Input audio file path
        output_path: Output audio file path
        params: Post-processing parameters (uses defaults if None)
        sfx_tags: SFX tags to overlay
        scene_tags: Scene tags for environmental effects
        mock_mode: If True, simulate processing without ffmpeg

    Returns:
        AudioFinalizeResult: Processing result
    """
    finalizer = AudioFinalizer(mock_mode=mock_mode)
    if params is None:
        params = AudioFinalizeParams()
    return finalizer.finalize(input_path, output_path, params, sfx_tags, scene_tags)

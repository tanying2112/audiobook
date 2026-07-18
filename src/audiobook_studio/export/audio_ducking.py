"""
D3 — Audio-Ducking 混音模块

在 TTS 音频上叠加背景音乐 (BGM)，并实现 Auto-Ducking
（说话时自动降低背景音量，对话抬升 12dB）。
支持基于 LLM 提取的 scene_tags 进行环境音效 (SFX) 混音。
"""

import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any

from ..utils.ffmpeg_probe import detect_silence_sync, get_duration_sync
from ..analyzer import SceneTagMapper, normalize_scene_tag

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
    # SFX 相关配置
    sfx_library_path: Optional[str] = None  # SFX 素材库路径
    sfx_default_volume_db: float = -6.0  # SFX 默认音量
    sfx_fade_ms: int = 100  # SFX 淡入淡出毫秒数


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
            segments.append(DuckingSegment(speech_start_ms, speech_end_ms, "speech", label="speech"))

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
        segments.append(DuckingSegment(int(prev_end), total_duration_ms, "speech", label="speech"))

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
    segments = ducking_segments or detect_speech_segments(speech_path, cfg.silence_threshold_db)

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
        ("-1" if speech_duration_s > 30 else str(int(30 / max(speech_duration_s, 1)) + 1)),
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


# =============================================================================
# SFX Mixing based on Scene Tags — 基于场景标签的环境音效混音
# =============================================================================


@dataclass
class SFXSegment:
    """SFX 混音段落定义."""

    start_ms: int
    end_ms: int
    scene_tag: str
    sfx_file: Path
    volume_db: float = -6.0
    fade_ms: int = 100
    label: str = ""


def build_sfx_segments_from_paragraphs(
    paragraphs: List[Dict[str, Any]],
    speech_duration_ms: int,
    mapper: SceneTagMapper,
    config: Optional[MixConfig] = None,
) -> List[SFXSegment]:
    """从段落数据构建 SFX 混音段落.

    Args:
        paragraphs: 段落列表，每个包含 index, text, sfx_tags, duration_ms 等
        speech_duration_ms: 总语音时长(毫秒)
        mapper: 场景标签映射器
        config: 混音配置

    Returns:
        SFXSegment 列表，每个段落包含开始/结束时间、场景标签、音效文件路径
    """
    cfg = config or MixConfig()
    sfx_segments: List[SFXSegment] = []

    # Get SFX library path
    effects_lib = Path(cfg.sfx_library_path or "assets/effects")

    # Calculate cumulative duration for each paragraph
    cumulative_ms = 0
    for para in paragraphs:
        # Get paragraph duration
        para_duration = para.get("duration_ms", 3000)
        para_start = cumulative_ms
        para_end = min(cumulative_ms + para_duration, speech_duration_ms)

        # Get SFX tags for this paragraph
        sfx_tags = para.get("sfx_tags", [])
        if not sfx_tags:
            cumulative_ms = para_end
            continue

        # Map scene tags to SFX files
        for tag in sfx_tags:
            normalized_tag = normalize_scene_tag(tag)
            sfx_file = mapper.resolve([normalized_tag], require_exists=False)
            if sfx_file:
                sfx_path = sfx_file[0]  # resolve returns list
                sfx_segments.append(
                    SFXSegment(
                        start_ms=para_start,
                        end_ms=para_end,
                        scene_tag=normalized_tag,
                        sfx_file=sfx_path,
                        volume_db=cfg.sfx_default_volume_db,
                        fade_ms=cfg.sfx_fade_ms,
                        label=f"SFX:{normalized_tag}",
                    )
                )

        cumulative_ms = para_end

    return sfx_segments


def mix_sfx_segments(
    speech_path: Path,
    sfx_segments: List[SFXSegment],
    output_path: Path,
) -> Path:
    """将多个 SFX 段落混音到语音轨道上.

    使用 ffmpeg 的 amerge/overlay 滤镜逐层叠加音效。

    Args:
        speech_path: 主语音文件路径
        sfx_segments: SFX 段落列表
        output_path: 输出路径

    Returns:
        混音后的输出文件路径
    """
    if not sfx_segments:
        # No SFX to add, just copy/normalize
        import shutil

        shutil.copy2(speech_path, output_path)
        logger.info(f"No SFX segments; copied speech to {output_path}")
        return output_path

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Build ffmpeg filter complex for multiple SFX overlays
    # We'll chain overlays: [0:a][1:a]overlay[tmp1]; [tmp1][2:a]overlay[tmp2]...
    inputs = ["-i", str(speech_path)]
    filter_parts = []
    last_label = "0:a"

    for i, seg in enumerate(sfx_segments):
        sfx_input_idx = i + 1
        inputs.extend(["-i", str(seg.sfx_file)])

        # Apply volume and fade to SFX
        sfx_label = f"sfx{i}"
        filter_parts.append(
            f"[{sfx_input_idx}:a]volume={seg.volume_db}dB,"
            f"afade=t=in:st=0:d={seg.fade_ms/1000},"
            f"afade=t=out:st={(seg.end_ms - seg.start_ms)/1000 - seg.fade_ms/1000}:d={seg.fade_ms/1000}[{sfx_label}]"
        )

        # Overlay SFX at the right time
        next_label = f"mix{i}"
        enable_expr = f"between(t,{seg.start_ms/1000},{seg.end_ms/1000})"
        filter_parts.append(
            f"[{last_label}][{sfx_label}]overlay=enable='{enable_expr}':format=auto[{next_label}]"
        )
        last_label = next_label

    filter_complex = ";".join(filter_parts) + f";[{last_label}]loudnorm=I=-16:LRA=11:TP=-1.5[out]"

    cmd = (
        ["ffmpeg", "-y"]
        + inputs
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
            str(output_path),
        ]
    )

    logger.info(f"Mixing {len(sfx_segments)} SFX segments...")
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        logger.error("ffmpeg SFX mixing timed out")
        # Fallback: copy original
        import shutil

        shutil.copy2(speech_path, output_path)
        logger.warning(f"Used fallback (no SFX): {output_path}")

    logger.info(f"SFX mixed audio: {output_path}")
    return output_path


def mix_full_pipeline(
    speech_path: Path,
    output_path: Path,
    bgm_path: Optional[str] = None,
    paragraphs: Optional[List[Dict[str, Any]]] = None,
    config: Optional[MixConfig] = None,
) -> Path:
    """完整混音流水线：BGM Ducking + SFX 混音.

    Args:
        speech_path: TTS 合成的完整语音文件
        output_path: 最终输出路径
        bgm_path: 可选 BGM 文件路径
        paragraphs: 可选段落数据（含 sfx_tags, duration_ms 等）
        config: 混音配置

    Returns:
        最终混音输出路径
    """
    cfg = config or MixConfig()

    # Step 1: Apply BGM with ducking (or just normalize if no BGM)
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        temp_path = Path(tmp.name)

    try:
        mix_with_ducking(
            speech_path=speech_path,
            output_path=temp_path,
            bgm_path=bgm_path,
            config=cfg,
        )

        # Step 2: Apply SFX if paragraphs provided
        if paragraphs:
            mapper = SceneTagMapper(effects_library=Path(cfg.sfx_library_path or "assets/effects"))
            sfx_segments = build_sfx_segments_from_paragraphs(
                paragraphs=paragraphs,
                speech_duration_ms=get_duration_sync(temp_path),
                mapper=mapper,
                config=cfg,
            )
            if sfx_segments:
                mix_sfx_segments(
                    speech_path=temp_path,
                    sfx_segments=sfx_segments,
                    output_path=output_path,
                )
                return output_path

        # No SFX or no paragraphs - just use the BGM-mixed result
        import shutil

        shutil.move(temp_path, output_path)
        return output_path

    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


# =============================================================================
# SFX Mixing based on Scene Tags — 基于场景标签的环境音效混音
# =============================================================================


@dataclass
class SFXSegment:
    """SFX 混音段落定义."""

    start_ms: int
    end_ms: int
    scene_tag: str
    sfx_file: Path
    volume_db: float = -6.0
    fade_ms: int = 100
    label: str = ""


def build_sfx_segments_from_paragraphs(
    paragraphs: List[Dict[str, Any]],
    speech_duration_ms: int,
    mapper: SceneTagMapper,
    config: Optional[MixConfig] = None,
) -> List[SFXSegment]:
    """从段落数据构建 SFX 混音段落.

    Args:
        paragraphs: 段落列表，每个包含 index, text, sfx_tags, duration_ms 等
        speech_duration_ms: 总语音时长(毫秒)
        mapper: 场景标签映射器
        config: 混音配置

    Returns:
        SFXSegment 列表，每个段落包含开始/结束时间、场景标签、音效文件路径
    """
    cfg = config or MixConfig()
    sfx_segments: List[SFXSegment] = []

    # Get SFX library path
    effects_lib = Path(cfg.sfx_library_path or "assets/effects")

    # Calculate cumulative time offset for each paragraph
    current_offset_ms = 0

    for para in paragraphs:
        para_duration = para.get("duration_ms", 3000)  # Default 3s per paragraph
        para_sfx_tags = para.get("sfx_tags", [])
        para_needs_sfx = para.get("needs_sfx", False)

        if para_needs_sfx and para_sfx_tags:
            # Resolve scene tags to SFX files
            for tag in para_sfx_tags:
                clean_tag = normalize_scene_tag(tag)
                filename = mapper.mapping.get(clean_tag, f"{clean_tag}.mp3")
                sfx_path = effects_lib / filename

                if sfx_path.exists():
                    sfx_segments.append(
                        SFXSegment(
                            start_ms=current_offset_ms,
                            end_ms=current_offset_ms + para_duration,
                            scene_tag=clean_tag,
                            sfx_file=sfx_path,
                            volume_db=cfg.sfx_default_volume_db,
                            fade_ms=cfg.sfx_fade_ms,
                            label=f"para_{para.get('index', 0)}_{clean_tag}",
                        )
                    )
                else:
                    logger.warning(f"SFX file not found for tag '{tag}': {sfx_path}")

        current_offset_ms += para_duration

    return sfx_segments


def mix_with_sfx(
    speech_path: Path,
    output_path: Path,
    sfx_segments: List[SFXSegment],
    bgm_path: Optional[str] = None,
    ducking_segments: Optional[List[DuckingSegment]] = None,
    config: Optional[MixConfig] = None,
) -> Path:
    """将语音、BGM(可选)、多个 SFX 叠加混音.

    先应用 BGM + Ducking，再叠加 SFX，最后归一化。

    Args:
        speech_path: TTS 语音文件路径
        output_path: 最终输出路径
        sfx_segments: SFX 段落列表
        bgm_path: 可选 BGM 文件路径
        ducking_segments: 可选预定义 Ducking 段落
        config: 混音配置

    Returns:
        混音输出文件路径
    """
    cfg = config or MixConfig()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Step 1: If no SFX and no BGM, just post-process speech
    if not sfx_segments and not bgm_path:
        return mix_with_ducking(speech_path, output_path, None, ducking_segments, cfg)

    # Step 2: Create temp file for BGM+Ducking mix (if BGM provided)
    # Otherwise use original speech as base
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        base_audio = Path(tmp.name)

    try:
        if bgm_path:
            # Mix speech with BGM + ducking first
            mix_with_ducking(speech_path, base_audio, bgm_path, ducking_segments, cfg)
            base = base_audio
        else:
            # No BGM, use speech directly
            base = speech_path

        # Step 3: Overlay all SFX segments
        if sfx_segments:
            # Build ffmpeg filter complex for multiple SFX overlays
            filter_parts = []
            input_parts = ["ffmpeg", "-y", "-i", str(base)]

            # Add all SFX as inputs
            for i, sfx_seg in enumerate(sfx_segments):
                input_parts.extend(["-i", str(sfx_seg.sfx_file)])

            # Build filter: first normalize base, then overlay each SFX
            # [0:a] is base (speech or speech+bgm)
            # [1:a], [2:a], ... are SFX files
            filter_chain = "[0:a]loudnorm=I=-16:LRA=11:TP=-1.5[base];"

            for i, sfx_seg in enumerate(sfx_segments):
                start_s = sfx_seg.start_ms / 1000.0
                end_s = sfx_seg.end_ms / 1000.0
                fade_in = f"afade=t=in:st=0:d={sfx_seg.fade_ms/1000.0}"
                fade_out = f"afade=t=out:st={(sfx_seg.end_ms - sfx_seg.start_ms - sfx_seg.fade_ms)/1000.0}:d={sfx_seg.fade_ms/1000.0}"
                vol = f"volume={sfx_seg.volume_db}dB"
                sfx_filter = f"[{i+1}:a]{vol},{fade_in},{fade_out}[sfx{i}];"
                filter_chain += sfx_filter

            # Overlay all SFX onto base
            overlay_inputs = "[base]"
            for i in range(len(sfx_segments)):
                overlay_inputs += f"[sfx{i}]"
            overlay_inputs += f"overlay=enable='between(t,{sfx_segments[0].start_ms/1000},{sfx_segments[-1].end_ms/1000})':format=auto[out]"

            # Fix: proper overlay chain
            current = "[base]"
            for i in range(len(sfx_segments)):
                start_s = sfx_segments[i].start_ms / 1000.0
                next_current = f"[mix{i}]"
                filter_chain += f"{current}[sfx{i}]overlay=enable='between(t,{start_s},{sfx_segments[i].end_ms/1000.0})':format=auto{next_current};"
                current = next_current

            filter_chain += f"{current}afade=t=in:ss=0:d=0.5,afade=t=out:st={get_duration_sync(base)/1000.0-0.5}:d=0.5[out]"

            cmd = input_parts + ["-filter_complex", filter_chain, "-map", "[out]", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(output_path)]
        else:
            # No SFX, just copy base with normalization
            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                str(base),
                "-af",
                "loudnorm=I=-16:LRA=11:TP=-1.5,afade=t=in:ss=0:d=0.5,afade=t=out:st=0:d=0.5",
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

        logger.info(f"Mixing with SFX: {len(sfx_segments)} segments, BGM: {bool(bgm_path)}")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg mixing with SFX timed out")
            raise

        logger.info(f"Mixed audio with SFX: {output_path}")
        return output_path

    finally:
        # Cleanup temp file
        if base_audio.exists() and base_audio != speech_path:
            base_audio.unlink(missing_ok=True)


def mix_chapter_with_scene_tags(
    speech_path: Path,
    output_path: Path,
    paragraphs: List[Dict[str, Any]],
    bgm_path: Optional[str] = None,
    config: Optional[MixConfig] = None,
    effects_library_path: Optional[str] = None,
) -> Path:
    """高层封装：基于段落的 scene_tags 进行完整章节混音 (BGM + Ducking + SFX).

    Args:
        speech_path: 拼接后的章节语音文件
        output_path: 输出文件路径
        paragraphs: 段落列表，含 index, text, sfx_tags, needs_sfx, duration_ms
        bgm_path: 可选 BGM 路径
        config: 可选混音配置
        effects_library_path: 可选音效库路径

    Returns:
        混音后的输出文件路径
    """
    cfg = config or MixConfig()
    if effects_library_path:
        cfg.sfx_library_path = effects_library_path

    # Create scene tag mapper
    mapper = SceneTagMapper(effects_library_path=Path(cfg.sfx_library_path or "assets/effects"))

    # Detect ducking segments from speech
    ducking_segments = detect_speech_segments(speech_path, cfg.silence_threshold_db)

    # Get speech duration
    speech_duration_ms = get_duration_sync(speech_path)

    # Build SFX segments from paragraphs
    sfx_segments = build_sfx_segments_from_paragraphs(
        paragraphs=paragraphs,
        speech_duration_ms=speech_duration_ms,
        mapper=mapper,
        config=cfg,
    )

    # Mix everything
    return mix_with_sfx(
        speech_path=speech_path,
        output_path=output_path,
        sfx_segments=sfx_segments,
        bgm_path=bgm_path,
        ducking_segments=ducking_segments,
        config=cfg,
    )

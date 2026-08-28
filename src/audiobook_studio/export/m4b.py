"""
D1 — M4B 封装模块

使用 ffmpeg 将章节音频合成为 M4B (AAC + 章节标记) 格式，
兼容 Apple Books / Audiobookshelf 等主流有声书平台。
"""

import logging
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ChapterMarker:
    """M4B 章节标记."""

    title: str
    start_ms: int
    duration_ms: int

    @property
    def start_seconds(self) -> float:
        return self.start_ms / 1000.0

    @property
    def end_seconds(self) -> float:
        return (self.start_ms + self.duration_ms) / 1000.0


@dataclass
class M4bMetadata:
    """M4B 元数据."""

    title: str = ""
    artist: str = ""
    album: str = ""
    genre: str = "Audiobook"
    year: str = ""
    cover_image: Optional[str] = None  # Path to cover image
    chapters: List[ChapterMarker] = field(default_factory=list)


def _build_ffmpeg_chapter_metadata(
    chapters: List[ChapterMarker],
    total_duration_ms: int,
) -> str:
    """构建 ffmpeg chapter metadata 文件内容 (FFMETADATA format)."""
    lines = [";FFMETADATA1"]
    for i, ch in enumerate(chapters):
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"id={i}")
        lines.append(f"START={ch.start_ms}")
        end_ms = min(ch.start_ms + ch.duration_ms, total_duration_ms)
        lines.append(f"END={end_ms}")
        # Escape = and ; and \n in title
        safe_title = ch.title.replace("=", "\\=").replace(";", "\\;").replace("\n", " ").strip()
        lines.append(f"title={safe_title or f'Chapter {i+1}'}")
    return "\n".join(lines)


def _normalize_audio(input_path: Path, output_path: Path, cfg: Optional["MasteringConfig"] = None) -> None:
    """Apply the S2-5 mastering post-processing chain to one segment.

    Single ffmpeg pass combining noise reduction (``afftdn`` — the ffmpeg-native
    equivalent of ``noisereduce``), silence removal and EBU R128 ``loudnorm``
    (I=-16 / TP=-1.5 / LRA=11). Outputs a mono 44.1 kHz WAV suitable for M4B
    concatenation. Runs exactly one ``subprocess.run`` call.
    """
    from .mastering import MasteringConfig, build_master_filtergraph

    cfg = cfg or MasteringConfig()
    fg = build_master_filtergraph(cfg)
    if not fg:
        # All steps disabled: just copy the bytes through.
        output_path.write_bytes(Path(input_path).read_bytes())
        return
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-af",
        fg,
        "-c:a",
        "pcm_s16le",
        "-ar",
        "44100",
        "-ac",
        "1",
        str(output_path),
    ]
    logger.info(f"Mastering audio: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _ffprobe_duration_ms(path: Path) -> int:
    """Probe audio duration in milliseconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(path),
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return int(float(result.stdout.strip()) * 1000)


def build_m4b(
    audio_segments: List[Path],
    chapter_markers: List[ChapterMarker],
    output_path: Path,
    metadata: Optional[M4bMetadata] = None,
    normalize: bool = True,
) -> Path:
    """将多个音频段落合成为 M4B 文件。

    Args:
        audio_segments: 按顺序排列的章节 MP3/WAV 文件列表
        chapter_markers: 章节标记列表 (需与 audio_segments 一一对应)
        output_path: 输出 .m4b 文件路径
        metadata: M4B 元数据
        normalize: 是否应用 S2-5 母带后处理链路
                   (降噪 afftdn + 静音修剪 silenceremove + 响度归一化 loudnorm I=-16)。
                   默认开启。每段独立母带化后，章节标记时长会按修剪后音频重测，
                   以保持章节同步。

    Returns:
        输出文件路径
    """
    if len(audio_segments) != len(chapter_markers):
        raise ValueError(
            f"audio_segments ({len(audio_segments)}) and chapter_markers "
            f"({len(chapter_markers)}) must have same length"
        )

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = metadata or M4bMetadata()

    # Step 1: Concatenate all segments into a single temp file
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        concat_list = tmpdir_path / "concat.txt"

        total_duration_ms = 0
        normalized_segments: List[Path] = []

        with open(concat_list, "w") as f:
            for i, seg_path in enumerate(audio_segments):
                seg_path = Path(seg_path)
                if not seg_path.exists():
                    logger.warning(f"Audio segment not found: {seg_path}, creating silence")
                    silence_path = tmpdir_path / f"silence_{i}.wav"
                    subprocess.run(
                        [
                            "ffmpeg",
                            "-y",
                            "-f",
                            "lavfi",
                            "-i",
                            "anullsrc=r=44100:cl=mono",
                            "-t",
                            "1",
                            str(silence_path),
                        ],
                        check=True,
                        capture_output=True,
                    )
                    normalized_path = silence_path
                else:
                    if normalize:
                        # S2-5 母带后处理 (分段)：降噪 (afftdn) + 静音修剪 (silenceremove)。
                        # 注意：响度归一化 (loudnorm) 在整书拼接后统一做，保证导出整书
                        # 通过 loudnorm 校验 (input_i ≈ -16)，而非逐段归一化导致整书偏离。
                        from .mastering import MasteringConfig

                        mastered_path = tmpdir_path / f"mastered_{i}.wav"
                        _normalize_audio(
                            seg_path,
                            mastered_path,
                            cfg=MasteringConfig(enable_loudnorm=False),
                        )
                        normalized_path = mastered_path
                        if i < len(chapter_markers):
                            try:
                                dur_ms = _ffprobe_duration_ms(mastered_path)
                                chapter_markers[i].duration_ms = dur_ms
                            except Exception as e:  # pragma: no cover - defensive
                                logger.warning(
                                    f"Failed to probe mastered segment {mastered_path}: {e}"
                                )
                    else:
                        normalized_path = seg_path

                f.write(f"file '{normalized_path.absolute()}'\n")

                # Update duration for chapter markers
                if i < len(chapter_markers):
                    total_duration_ms += chapter_markers[i].duration_ms
                normalized_segments.append(normalized_path)

        # Step 2: Concatenate all normalized segments
        concat_output = tmpdir_path / "concat.wav"
        concat_cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list),
            "-c:a",
            "pcm_s16le",
            "-ar",
            "44100",
            "-ac",
            "1",
            str(concat_output),
        ]
        logger.info(f"Concatenating segments: {' '.join(concat_cmd)}")
        subprocess.run(concat_cmd, check=True, capture_output=True, text=True)

        # S2-5 整书响度归一化：对拼接后的完整音频统一做 loudnorm (I=-16/TP=-1.5/LRA=11)，
        # 保证导出 M4B 通过 loudnorm 校验 (input_i ≈ -16)。此步骤不改变时长，
        # 章节标记仍与拼接音频同步。
        m4b_source = concat_output
        if normalize:
            from .mastering import MasteringConfig

            normalized_output = tmpdir_path / "concat_normalized.wav"
            _normalize_audio(
                concat_output,
                normalized_output,
                cfg=MasteringConfig(enable_noisereduce=False, enable_silenceremove=False),
            )
            m4b_source = normalized_output

        # Get accurate duration from the (normalized) concatenated file
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(m4b_source),
        ]
        result = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
        total_duration_ms = int(float(result.stdout.strip()) * 1000)

        # Step 3: Write chapter metadata
        chapter_meta_path = tmpdir_path / "chapters.txt"
        chapter_meta = _build_ffmpeg_chapter_metadata(chapter_markers, total_duration_ms)
        chapter_meta_path.write_text(chapter_meta, encoding="utf-8")
        logger.info(f"Chapter metadata:\n{chapter_meta}")

        # Step 4: Apply chapter markers + metadata to produce M4B
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(m4b_source),
            "-i",
            str(chapter_meta_path),
            "-map_metadata",
            "1",
            "-map",
            "0:a",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "1",
        ]

        # Add global metadata
        if meta.title:
            cmd += ["-metadata", f"title={meta.title}"]
        if meta.artist:
            cmd += ["-metadata", f"artist={meta.artist}"]
        if meta.album:
            cmd += ["-metadata", f"album={meta.album}"]
        if meta.genre:
            cmd += ["-metadata", f"genre={meta.genre}"]
        if meta.year:
            cmd += ["-metadata", f"date={meta.year}"]

        # Cover image
        if meta.cover_image and Path(meta.cover_image).exists():
            cmd += ["-i", meta.cover_image, "-map", "2", "-c:v", "copy"]

        cmd.append(str(output_path))

        logger.info(f"Building M4B: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    output_size = output_path.stat().st_size
    logger.info(f"M4B created: {output_path} ({output_size / 1024 / 1024:.1f} MB)")

    return output_path


def build_m4b_single_source(
    full_audio_path: Path,
    chapter_markers: List[ChapterMarker],
    output_path: Path,
    metadata: Optional[M4bMetadata] = None,
    master: bool = False,
) -> Path:
    """从已合成的完整音频 + 章节标记构建 M4B.

    当整书音频已预合成时使用此函数，跳过 concat 步骤。

    Args:
        master: 是否应用 S2-5 母带后处理 (响度归一化 + 降噪)。为保持调用方传入的
               章节标记位置不漂移，此处默认不启用 silenceremove。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = metadata or M4bMetadata()

    source_for_m4b = Path(full_audio_path)
    if master:
        # 母带后处理：降噪 + 响度归一化 (不做静音修剪，避免章节标记漂移)
        from .mastering import MasteringConfig

        mastered_path = output_path.parent / f"{output_path.stem}_mastered.wav"
        _normalize_audio(
            full_audio_path,
            mastered_path,
            cfg=MasteringConfig(enable_silenceremove=False),
        )
        source_for_m4b = mastered_path

    # Get audio duration
    probe_cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(full_audio_path),
    ]
    result = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
    total_duration_ms = int(float(result.stdout.strip()) * 1000)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        chapter_meta_path = tmpdir_path / "chapters.txt"
        chapter_meta = _build_ffmpeg_chapter_metadata(chapter_markers, total_duration_ms)
        chapter_meta_path.write_text(chapter_meta, encoding="utf-8")

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(source_for_m4b),
            "-i",
            str(chapter_meta_path),
            "-map_metadata",
            "1",
            "-map",
            "0:a",
            "-codec:a",
            "copy",
        ]

        if meta.title:
            cmd += ["-metadata", f"title={meta.title}"]
        if meta.artist:
            cmd += ["-metadata", f"artist={meta.artist}"]
        if meta.album:
            cmd += ["-metadata", f"album={meta.album}"]
        if meta.genre:
            cmd += ["-metadata", f"genre={meta.genre}"]
        if meta.year:
            cmd += ["-metadata", f"date={meta.year}"]
        if meta.cover_image and Path(meta.cover_image).exists():
            cmd += ["-i", meta.cover_image, "-map", "2", "-c:v", "copy"]

        cmd.append(str(output_path))

        logger.info(f"Building M4B from single source: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, capture_output=True, text=True)

    logger.info(f"M4B created (single source): {output_path}")
    return output_path

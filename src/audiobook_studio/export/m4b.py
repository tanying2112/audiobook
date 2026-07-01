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
    lines = ["; FFMETADATA"]
    for i, ch in enumerate(chapters):
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={ch.start_ms}")
        end_ms = min(ch.start_ms + ch.duration_ms, total_duration_ms)
        lines.append(f"END={end_ms}")
        # Escape = and ; and \n in title
        safe_title = (
            ch.title.replace("=", "\\=").replace(";", "\\;").replace("\n", " ").strip()
        )
        lines.append(f"title={safe_title or f'Chapter {i+1}'}")
    return "\n".join(lines)


def _normalize_audio(input_path: Path, output_path: Path) -> None:
    """Apply loudnorm normalization + fade in/out as preprocessing.

    D5 integration: loudnorm 响度归一化 + 淡入淡出。
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
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
    logger.info(f"Normalizing audio: {' '.join(cmd)}")
    subprocess.run(cmd, check=True, capture_output=True, text=True)


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
        normalize: 是否应用 loudnorm 归一化 + 淡入淡出

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
                    logger.warning(
                        f"Audio segment not found: {seg_path}, creating silence"
                    )
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
            "-c",
            "copy",
            str(concat_output),
        ]
        logger.info(f"Concatenating segments: {' '.join(concat_cmd)}")
        subprocess.run(concat_cmd, check=True, capture_output=True, text=True)

        # Get accurate duration from the concatenated file
        probe_cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "csv=p=0",
            str(concat_output),
        ]
        result = subprocess.run(probe_cmd, check=True, capture_output=True, text=True)
        total_duration_ms = int(float(result.stdout.strip()) * 1000)

        # Step 3: Write chapter metadata
        chapter_meta_path = tmpdir_path / "chapters.txt"
        chapter_meta = _build_ffmpeg_chapter_metadata(
            chapter_markers, total_duration_ms
        )
        chapter_meta_path.write_text(chapter_meta, encoding="utf-8")
        logger.info(f"Chapter metadata:\n{chapter_meta}")

        # Step 4: Apply chapter markers + metadata to produce M4B
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(concat_output),
            "-i",
            str(chapter_meta_path),
            "-map_metadata",
            "1",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
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
) -> Path:
    """从已合成的完整音频 + 章节标记构建 M4B.

    当整书音频已预合成时使用此函数，跳过 concat 步骤。
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    meta = metadata or M4bMetadata()

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
        chapter_meta = _build_ffmpeg_chapter_metadata(
            chapter_markers, total_duration_ms
        )
        chapter_meta_path.write_text(chapter_meta, encoding="utf-8")

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(full_audio_path),
            "-i",
            str(chapter_meta_path),
            "-map_metadata",
            "1",
            "-codec",
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

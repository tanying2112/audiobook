"""
D6 — MP3 ID3v2.4 标签写入模块

为 MP3 音频文件写入标准 ID3v2.4 标签，包含：
- 标题、艺术家、专辑、年份、流派
- 章节标记 (TOC/CHAP)
- 封面图片 (APIC)
- 同步歌词 (SYLT) / 非同步歌词 (USLT)
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import mutagen
    from mutagen.id3 import APIC  # Attached picture
    from mutagen.id3 import CHAP  # Chapter
    from mutagen.id3 import COMM  # Comments
    from mutagen.id3 import CTOC  # Table of contents
    from mutagen.id3 import SYLT  # Synchronized lyric
    from mutagen.id3 import TALB  # Album
    from mutagen.id3 import TCON  # Genre
    from mutagen.id3 import TDRC  # Year/Date
    from mutagen.id3 import TIT2  # Title
    from mutagen.id3 import TPE1  # Artist
    from mutagen.id3 import TPOS  # Disc number
    from mutagen.id3 import TRCK  # Track number
    from mutagen.id3 import TXXX  # User defined text
    from mutagen.id3 import USLT  # Unsynchronized lyric
    from mutagen.id3 import (
        ID3,
    )
    from mutagen.mp3 import MP3

    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    mutagen = None
    ID3 = None
    MP3 = None

logger = logging.getLogger(__name__)


@dataclass
class ChapterInfo:
    """MP3 章节信息 (用于 CHAP/TOC 标签)."""

    title: str
    start_ms: int
    end_ms: int

    @property
    def start_seconds(self) -> float:
        return self.start_ms / 1000.0

    @property
    def end_seconds(self) -> float:
        return self.end_ms / 1000.0


@dataclass
class Mp3Metadata:
    """MP3 元数据."""

    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    genre: str = "Audiobook"
    track: int = 0
    disc: int = 1
    cover_image: Optional[str] = None  # Path to cover image
    chapters: List[ChapterInfo] = field(default_factory=list)
    lyrics: Optional[str] = None  # Full text for USLT
    synced_lyrics: Optional[List[tuple[float, str]]] = None  # (timestamp_seconds, text) for SYLT


def _ensure_id3(audio: Any) -> None:
    """Ensure audio file has ID3 tags."""
    if audio.tags is None:
        audio.add_tags()


def write_id3_tags(
    mp3_path: Path,
    metadata: Mp3Metadata,
) -> Path:
    """
    为 MP3 文件写入 ID3v2.4 标签.

    Args:
        mp3_path: MP3 文件路径
        metadata: 元数据对象

    Returns:
        写入标签后的文件路径
    """
    if not MUTAGEN_AVAILABLE:
        logger.warning("mutagen not installed, skipping ID3 tag writing")
        return mp3_path

    mp3_path = Path(mp3_path)
    if not mp3_path.exists():
        raise FileNotFoundError(f"MP3 file not found: {mp3_path}")

    # Load MP3
    audio = MP3(str(mp3_path))
    _ensure_id3(audio)

    # Clear existing tags of same types to avoid duplicates
    tags_to_clear = [
        "TIT2",
        "TPE1",
        "TALB",
        "TDRC",
        "TCON",
        "TRCK",
        "TPOS",
        "APIC",
        "CHAP",
        "CTOC",
        "USLT",
        "SYLT",
        "COMM",
    ]
    for tag_id in tags_to_clear:
        if tag_id in audio.tags:
            del audio.tags[tag_id]

    # Write basic tags
    if metadata.title:
        audio.tags.add(TIT2(encoding=3, text=metadata.title))
    if metadata.artist:
        audio.tags.add(TPE1(encoding=3, text=metadata.artist))
    if metadata.album:
        audio.tags.add(TALB(encoding=3, text=metadata.album))
    if metadata.year:
        audio.tags.add(TDRC(encoding=3, text=metadata.year))
    if metadata.genre:
        audio.tags.add(TCON(encoding=3, text=metadata.genre))
    if metadata.track > 0:
        audio.tags.add(TRCK(encoding=3, text=str(metadata.track)))
    if metadata.disc > 0:
        audio.tags.add(TPOS(encoding=3, text=str(metadata.disc)))

    # Write cover image (APIC)
    if metadata.cover_image and Path(metadata.cover_image).exists():
        with open(metadata.cover_image, "rb") as f:
            cover_data = f.read()
        ext = Path(metadata.cover_image).suffix.lower()
        mime_type = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
        audio.tags.add(
            APIC(
                encoding=3,
                mime=mime_type,
                type=3,  # Front cover
                desc="Cover",
                data=cover_data,
            )
        )
        logger.info(f"Added cover image: {metadata.cover_image}")

    # Write chapters (CHAP) and table of contents (CTOC)
    if metadata.chapters:
        chap_frames = []
        for i, ch in enumerate(metadata.chapters):
            # Create chapter frame
            element_id = f"ch{i+1:03d}"
            chap = CHAP(
                encoding=3,
                element_id=element_id,
                start_time=int(ch.start_seconds * 1000),  # milliseconds
                end_time=int(ch.end_seconds * 1000),
                # Sub-frames for chapter title
                sub_frames=[
                    TIT2(encoding=3, text=ch.title),
                ],
            )
            audio.tags.add(chap)
            chap_frames.append(element_id)

        # Create table of contents
        if chap_frames:
            ctoc = CTOC(
                encoding=3,
                element_id="toc",
                flags=0x02,  # Top-level TOC
                child_element_ids=chap_frames,
                sub_frames=[
                    TIT2(encoding=3, text="Table of Contents"),
                ],
            )
            audio.tags.add(ctoc)

        logger.info(f"Added {len(metadata.chapters)} chapters with TOC")

    # Write unsynchronized lyrics (USLT)
    if metadata.lyrics:
        audio.tags.add(
            USLT(
                encoding=3,
                lang="chi" if any(ord(c) > 127 for c in metadata.lyrics[:100]) else "eng",
                desc="",
                text=metadata.lyrics,
            )
        )
        logger.info("Added unsynchronized lyrics (USLT)")

    # Write synchronized lyrics (SYLT)
    if metadata.synced_lyrics:
        # Format: list of (timestamp_ms, text)
        sylt_data = []
        for timestamp, text in metadata.synced_lyrics:
            sylt_data.append((int(timestamp * 1000), text))

        audio.tags.add(
            SYLT(
                encoding=3,
                lang="chi" if any(ord(c) > 127 for c in metadata.synced_lyrics[0][1][:10]) else "eng",
                format=2,  # Milliseconds
                type=1,  # Lyrics
                desc="",
                text=sylt_data,
            )
        )
        logger.info(f"Added synchronized lyrics (SYLT) with {len(metadata.synced_lyrics)} entries")

    # Save
    audio.tags.save(mp3_path, v2_version=4)
    logger.info(f"ID3v2.4 tags written to: {mp3_path}")

    return mp3_path


def write_chapters_only(
    mp3_path: Path,
    chapters: List[ChapterInfo],
) -> Path:
    """仅写入章节标记 (用于已有标签的文件)."""
    if not MUTAGEN_AVAILABLE:
        logger.warning("mutagen not installed, skipping chapter writing")
        return mp3_path

    mp3_path = Path(mp3_path)
    audio = MP3(str(mp3_path))
    _ensure_id3(audio)

    # Remove existing CHAP/CTOC
    for tag_id in list(audio.tags.keys()):
        if tag_id.startswith("CHAP") or tag_id.startswith("CTOC"):
            del audio.tags[tag_id]

    # Add chapters
    chap_frames = []
    for i, ch in enumerate(chapters):
        element_id = f"ch{i+1:03d}"
        chap = CHAP(
            encoding=3,
            element_id=element_id,
            start_time=int(ch.start_seconds * 1000),
            end_time=int(ch.end_seconds * 1000),
            sub_frames=[TIT2(encoding=3, text=ch.title)],
        )
        audio.tags.add(chap)
        chap_frames.append(element_id)

    # Add TOC
    if chap_frames:
        ctoc = CTOC(
            encoding=3,
            element_id="toc",
            flags=0x02,
            child_element_ids=chap_frames,
            sub_frames=[TIT2(encoding=3, text="Table of Contents")],
        )
        audio.tags.add(ctoc)

    audio.tags.save(mp3_path, v2_version=4)
    logger.info(f"Chapters written to: {mp3_path}")

    return mp3_path


def read_id3_tags(mp3_path: Path) -> Dict[str, Any]:
    """读取 MP3 文件的 ID3 标签."""
    if not MUTAGEN_AVAILABLE:
        return {"error": "mutagen not available"}

    mp3_path = Path(mp3_path)
    if not mp3_path.exists():
        return {"error": "File not found"}

    audio = MP3(str(mp3_path))
    if audio.tags is None:
        return {}

    result = {}
    for tag_id, tag in audio.tags.items():
        if hasattr(tag, "text"):
            result[tag_id] = tag.text
        elif hasattr(tag, "data"):
            result[tag_id] = f"<binary data: {len(tag.data)} bytes>"
        else:
            result[tag_id] = str(tag)

    return result


def add_mp3_to_zip(
    mp3_files: List[Path],
    zip_path: Path,
    metadata: Optional[Mp3Metadata] = None,
) -> Path:
    """将多个 MP3 文件打包为 ZIP (用于分发)."""
    import zipfile

    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for _i, mp3_file in enumerate(mp3_files):
            mp3_file = Path(mp3_file)
            if mp3_file.exists():
                arcname = mp3_file.name
                zf.write(mp3_file, arcname=arcname)

    logger.info(f"ZIP created: {zip_path} with {len(mp3_files)} files")
    return zip_path


# Convenience function for batch export
def export_mp3_chapters(
    audio_files: List[Path],
    chapter_infos: List[ChapterInfo],
    output_dir: Path,
    metadata: Mp3Metadata,
) -> List[Path]:
    """批量导出带章节标记的 MP3 文件."""
    import shutil

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exported_files = []

    for i, (audio_file, chapter) in enumerate(zip(audio_files, chapter_infos, strict=False)):
        output_file = output_dir / f"chapter_{i+1:03d}_{chapter.title}.mp3"

        # Copy original file
        shutil.copy2(audio_file, output_file)

        # Create metadata for this chapter
        chapter_metadata = Mp3Metadata(
            title=chapter.title,
            artist=metadata.artist,
            album=metadata.album,
            year=metadata.year,
            genre=metadata.genre,
            track=i + 1,
            disc=metadata.disc,
            cover_image=metadata.cover_image,
        )

        # Write ID3 tags
        write_id3_tags(output_file, chapter_metadata)
        exported_files.append(output_file)

    return exported_files

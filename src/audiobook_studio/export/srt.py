"""
D2 — SRT 字幕导出模块

从段落注释和音频时间戳生成 SRT 字幕文件，
支持说话人标记和时间戳同步。
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SubtitleEntry:
    """单条字幕条目."""

    index: int
    start_ms: int
    end_ms: int
    text: str
    speaker: Optional[str] = None

    def to_srt_block(self) -> str:
        """生成 SRT 格式的字幕块."""
        lines = [str(self.index)]
        lines.append(f"{_ms_to_srt(self.start_ms)} --> {_ms_to_srt(self.end_ms)}")
        text = self.text
        if self.speaker:
            text = f"[{self.speaker}] {text}"
        lines.append(text)
        return "\n".join(lines)


@dataclass
class SubtitleConfig:
    """字幕生成配置."""

    max_chars_per_line: int = 40
    max_duration_per_entry_ms: int = 5000
    min_duration_per_entry_ms: int = 1000
    include_speaker: bool = True
    language: str = "chi"


def _ms_to_srt(ms: int) -> str:
    """Convert milliseconds to SRT time format HH:MM:SS,mmm."""
    total_seconds = ms / 1000
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def _split_long_text(text: str, max_chars: int) -> List[str]:
    """将长文本按句拆分，控制单行长度."""
    if len(text) <= max_chars:
        return [text.strip()]

    # Try to split on sentence boundaries
    sentences = re.split(r"([。！？.!?])", text)
    chunks: List[str] = []
    current = ""

    for i in range(0, len(sentences), 2):
        part = sentences[i]
        punct = sentences[i + 1] if i + 1 < len(sentences) else ""
        segment = (part + punct).strip()
        if not segment:
            continue

        if len(current) + len(segment) <= max_chars:
            current += segment
        else:
            if current:
                chunks.append(current.strip())
            current = segment

    if current:
        chunks.append(current.strip())

    # If still too long, hard-split at max_chars
    final_chunks: List[str] = []
    for chunk in chunks:
        while len(chunk) > max_chars:
            final_chunks.append(chunk[:max_chars])
            chunk = chunk[max_chars:]
        if chunk:
            final_chunks.append(chunk)

    return final_chunks if final_chunks else [text.strip()]


def generate_srt(
    entries: List[SubtitleEntry],
    output_path: Path,
    config: Optional[SubtitleConfig] = None,
) -> Path:
    """生成 SRT 字幕文件.

    Args:
        entries: 字幕条目列表
        output_path: 输出 .srt 文件路径
        config: 字幕配置

    Returns:
        输出文件路径
    """
    cfg = config or SubtitleConfig()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines: List[str] = []
    srt_index = 1

    for entry in entries:
        duration = entry.end_ms - entry.start_ms
        if duration < cfg.min_duration_per_entry_ms:
            # Too short — extend to minimum
            entry.end_ms = entry.start_ms + cfg.min_duration_per_entry_ms

        if duration > cfg.max_duration_per_entry_ms:
            # Too long — split into multiple entries
            text_chunks = _split_long_text(entry.text, cfg.max_chars_per_line)
            chunk_duration = max(duration // len(text_chunks), cfg.min_duration_per_entry_ms)
            chunk_start = entry.start_ms

            for chunk in text_chunks:
                chunk_end = min(chunk_start + chunk_duration, entry.end_ms)
                sub_entry = SubtitleEntry(
                    index=srt_index,
                    start_ms=chunk_start,
                    end_ms=chunk_end,
                    text=chunk,
                    speaker=entry.speaker,
                )
                lines.append(sub_entry.to_srt_block())
                srt_index += 1
                chunk_start = chunk_end
        else:
            entry.index = srt_index
            lines.append(entry.to_srt_block())
            srt_index += 1

    # Also generate a WebVTT version alongside SRT for web playback
    output_path.write_text("\n\n".join(lines) + "\n", encoding="utf-8")

    # Generate VTT version
    vtt_path = output_path.with_suffix(".vtt")
    vtt_lines = ["WEBVTT", ""]
    for entry in entries:
        duration = entry.end_ms - entry.start_ms
        if duration > cfg.max_duration_per_entry_ms:
            text_chunks = _split_long_text(entry.text, cfg.max_chars_per_line)
            chunk_duration = max(duration // len(text_chunks), cfg.min_duration_per_entry_ms)
            chunk_start = entry.start_ms
            for chunk in text_chunks:
                chunk_end = min(chunk_start + chunk_duration, entry.end_ms)
                vtt_lines.append(f"{_ms_to_srt(chunk_start)} --> {_ms_to_srt(chunk_end)}")
                text = f"[{entry.speaker}] {chunk}" if entry.speaker else chunk
                vtt_lines.append(text)
                vtt_lines.append("")
                chunk_start = chunk_end
        else:
            vtt_lines.append(f"{_ms_to_srt(entry.start_ms)} --> {_ms_to_srt(entry.end_ms)}")
            text = f"[{entry.speaker}] {entry.text}" if entry.speaker else entry.text
            vtt_lines.append(text)
            vtt_lines.append("")

    vtt_path.write_text("\n".join(vtt_lines), encoding="utf-8")

    entry_count = srt_index - 1
    logger.info(
        f"SRT created: {output_path} ({entry_count} entries, "
        f"{output_path.stat().st_size / 1024:.1f} KB)"
    )
    logger.info(f"VTT also created: {vtt_path}")

    return output_path


def build_subtitle_entries_from_paragraphs(
    paragraphs: List[dict],
    audio_segments: List[dict],
) -> List[SubtitleEntry]:
    """从段落和音频片段构建字幕条目.

    Args:
        paragraphs: 段落列表，每项含 text, character_name
        audio_segments: 音频片段列表，每项含 paragraph_id, duration_ms 等

    Returns:
        字幕条目列表
    """
    # Build paragraph_id → duration mapping
    para_duration: dict[int, int] = {}
    current_offset = 0
    para_order: List[int] = []

    for seg in audio_segments:
        pid = seg.get("paragraph_id")
        if pid is None:
            continue
        duration = seg.get("duration_ms", 3000)
        para_duration[pid] = duration
        if pid not in para_order:
            para_order.append(pid)

    entries: List[SubtitleEntry] = []
    offset_ms = 0

    for para in paragraphs:
        pid = para["id"]
        text = para.get("original_text") or para.get("text", "")
        speaker = para.get("character_name")
        duration = para_duration.get(pid, 3000)

        entry = SubtitleEntry(
            index=len(entries) + 1,
            start_ms=offset_ms,
            end_ms=offset_ms + duration,
            text=text,
            speaker=speaker,
        )
        entries.append(entry)
        offset_ms += duration

    return entries

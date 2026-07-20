"""
D4 — 批量导出编排器

整合 M4B、SRT、Audio-Ducking 模块，提供全流程导出 API。
"""

import json
import logging
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..utils.ffmpeg_probe import get_duration_sync
from .audio_ducking import MixConfig, mix_full_pipeline, mix_with_ducking
from .m4b import ChapterMarker, M4bMetadata, build_m4b
from .srt import SubtitleConfig, SubtitleEntry, generate_srt

logger = logging.getLogger(__name__)


class ExportFormat(str, Enum):
    """导出格式选项."""

    M4B = "m4b"
    SRT = "srt"
    VTT = "vtt"
    M4B_SRT = "m4b_srt"
    ALL = "all"


class ExportProgress(str, Enum):
    """导出进度状态."""

    PENDING = "pending"
    CONCATENATING = "concatenating"
    CHAPTERING = "chaptering"
    SUBTITLES = "subtitles"
    DUCKING = "ducking"
    COMPRESSING = "compressing"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass
class ExportJob:
    """单个导出任务."""

    project_id: int
    chapter_ids: Optional[List[int]] = None  # None = all chapters
    formats: Set[ExportFormat] = field(default_factory=lambda: {ExportFormat.M4B_SRT})
    bgm_path: Optional[str] = None
    include_cover: bool = True
    cover_image: Optional[str] = None
    normalize: bool = True
    subtitle_config: Optional[SubtitleConfig] = None
    mix_config: Optional[MixConfig] = None
    output_dir: Optional[str] = None

    # Runtime
    progress: ExportProgress = ExportProgress.PENDING
    output_paths: Dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None


def _collect_chapter_data(
    project_id: int,
    chapter_id: int,
    session,
) -> Optional[dict]:
    """从数据库收集单个章节的导出数据.

    返回:
        {
            "chapter": Chapter ORM obj,
            "audio_segments": [...],
            "paragraphs": [...]
        }
    """
    from ..models.audio_segment import AudioSegment
    from ..models.chapter import Chapter
    from ..models.paragraph import Paragraph

    chapter = session.query(Chapter).filter_by(id=chapter_id, project_id=project_id).first()
    if not chapter:
        logger.warning(f"Chapter {chapter_id} not found in project {project_id}")
        return None

    paragraphs = session.query(Paragraph).filter_by(chapter_id=chapter_id).order_by(Paragraph.index).all()
    audio_segments = session.query(AudioSegment).filter_by(chapter_id=chapter_id, is_current=True).all()

    if not audio_segments:
        logger.warning(f"No audio segments for chapter {chapter_id}")
        return None

    return {
        "chapter": chapter,
        "paragraphs": paragraphs,
        "audio_segments": audio_segments,
    }


def _build_chapter_markers(chapter_data: List[dict]) -> List[ChapterMarker]:
    """从章节数据构建 M4B 章节标记."""
    markers: List[ChapterMarker] = []
    cumulative_ms = 0

    for data in chapter_data:
        chapter = data["chapter"]
        segments = data["audio_segments"]

        # Calculate total duration for this chapter
        chapter_duration_ms = 0
        for seg in segments:
            path = Path(seg.file_path)
            if path.exists():
                try:
                    chapter_duration_ms += get_duration_sync(path)
                except Exception as e:
                    logger.warning(f"Failed to probe duration for {path}: {e}, using fallback")
                    chapter_duration_ms += seg.duration_ms or 3000
            else:
                # Try alternate extension
                alt_path = path.with_suffix(".wav" if path.suffix == ".mp3" else ".mp3")
                if alt_path.exists():
                    try:
                        chapter_duration_ms += get_duration_sync(alt_path)
                    except Exception:
                        chapter_duration_ms += seg.duration_ms or 3000
                else:
                    chapter_duration_ms += seg.duration_ms or 3000

        markers.append(
            ChapterMarker(
                title=chapter.title or f"Chapter {chapter.index}",
                start_ms=cumulative_ms,
                duration_ms=chapter_duration_ms,
            )
        )
        cumulative_ms += chapter_duration_ms

    return markers


def _build_segment_markers(chapter_data: List[dict]) -> List[ChapterMarker]:
    """Build one marker per audio segment (for non-stitched audio)."""
    markers: List[ChapterMarker] = []
    cumulative_ms = 0

    for data in chapter_data:
        segments = sorted(data["audio_segments"], key=lambda s: s.id)
        for seg in segments:
            # Calculate duration for this segment
            path = Path(seg.file_path)
            duration = 3000
            if path.exists():
                try:
                    duration = get_duration_sync(path)
                except Exception:
                    duration = seg.duration_ms or 3000
            else:
                alt_path = path.with_suffix(".wav" if path.suffix == ".mp3" else ".mp3")
                if alt_path.exists():
                    try:
                        duration = get_duration_sync(alt_path)
                    except Exception:
                        duration = seg.duration_ms or 3000
                else:
                    duration = seg.duration_ms or 3000

            markers.append(
                ChapterMarker(
                    title=f"Segment {seg.id}",
                    start_ms=cumulative_ms,
                    duration_ms=duration,
                )
            )
            cumulative_ms += duration

    return markers


def _collect_audio_files(chapter_data: List[dict]) -> List[Path]:
    """收集章节所有音频文件路径."""
    files: List[Path] = []
    for data in chapter_data:
        segments = sorted(data["audio_segments"], key=lambda s: s.id)
        for seg in segments:
            path = Path(seg.file_path)
            if path.exists():
                files.append(path)
            else:
                # Try alternate extensions (.wav for .mp3, .mp3 for .wav)
                alt_path = path.with_suffix(".wav" if path.suffix == ".mp3" else ".mp3")
                if alt_path.exists():
                    files.append(alt_path)
    return files


def _build_subtitle_entries(
    chapter_data: List[dict],
) -> List[SubtitleEntry]:
    """从章节数据构建字幕条目."""
    entries: List[SubtitleEntry] = []
    offset_ms = 0

    for data in chapter_data:
        paragraphs = sorted(data["paragraphs"], key=lambda p: p.index)
        segments_map = {seg.paragraph_id: seg for seg in data["audio_segments"]}

        for para in paragraphs:
            seg = segments_map.get(para.id)
            duration = 3000  # fallback

            if seg:
                path = Path(seg.file_path)
                if path.exists():
                    try:
                        duration = get_duration_sync(path)
                    except Exception as e:
                        logger.warning(f"Failed to probe duration for {path}: {e}, using fallback")
                        duration = seg.duration_ms or 3000
                else:
                    duration = seg.duration_ms or 3000

            entries.append(
                SubtitleEntry(
                    index=len(entries) + 1,
                    start_ms=offset_ms,
                    end_ms=offset_ms + duration,
                    text=para.text or "",
                    speaker=para.speaker_canonical_name,
                )
            )
            offset_ms += duration

    return entries


def _build_project_metadata(chapter_data: List[dict], project) -> M4bMetadata:
    """构建 M4B 元数据."""
    first_chapter = chapter_data[0]["chapter"] if chapter_data else None
    return M4bMetadata(
        title=project.title or "Untitled Audiobook",
        artist=project.author or "Unknown",
        album=project.title or "Untitled Audiobook",
    )


def export_project(
    project_id: int,
    session,
    job: ExportJob,
) -> ExportJob:
    """执行完整的项目导出流程.

    Args:
        project_id: 项目 ID
        session: DB session
        job: 导出任务配置

    Returns:
        更新后的导出任务 (含 output_paths)
    """
    from ..models.book import Project

    try:
        project = session.query(Project).filter_by(id=project_id).first()
    except Exception as e:
        job.progress = ExportProgress.FAILED
        job.error = str(e)
        return job

    if not project:
        job.progress = ExportProgress.FAILED
        job.error = f"Project {project_id} not found"
        return job

    # Collect chapter data
    chapters_to_export = job.chapter_ids or [ch.id for ch in sorted(project.chapters, key=lambda c: c.index)]

    chapter_data_list: List[dict] = []
    for ch_id in chapters_to_export:
        data = _collect_chapter_data(project_id, ch_id, session)
        if data:
            chapter_data_list.append(data)

    if not chapter_data_list:
        job.progress = ExportProgress.FAILED
        job.error = "No chapters with audio segments found"
        return job

    # Prepare output directory
    output_dir = Path(job.output_dir or f"./output/project_{project.id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # --- M4B export ---
        if ExportFormat.M4B in job.formats or ExportFormat.M4B_SRT in job.formats or ExportFormat.ALL in job.formats:
            job.progress = ExportProgress.CONCATENATING
            logger.info("Building M4B (chaptered)...")

            audio_files = _collect_audio_files(chapter_data_list)
            segment_markers = _build_segment_markers(chapter_data_list)
            metadata = _build_project_metadata(chapter_data_list, project)

            # Cover image
            if job.include_cover and job.cover_image:
                metadata.cover_image = job.cover_image

            m4b_path = output_dir / f"project_{project.id}.m4b"

            # Prepare paragraph data for SFX mixing (from all chapters)
            all_paragraphs = []
            for data in chapter_data_list:
                for para in data["paragraphs"]:
                    # Get audio segment duration for this paragraph
                    seg = next((s for s in data["audio_segments"] if s.paragraph_id == para.id), None)
                    para_data = {
                        "id": para.id,
                        "index": para.index,
                        "text": para.text,
                        "sfx_tags": para.sfx_tags or [],
                        "duration_ms": seg.duration_ms if seg else 3000,
                    }
                    all_paragraphs.append(para_data)

            # BGM mixing + SFX mixing
            if job.bgm_path:
                job.progress = ExportProgress.DUCKING
                temp_audio = output_dir / "temp_speech_combined.wav"
                # Concatenate all audio first
                concat_list = output_dir / "concat_files.txt"
                with open(concat_list, "w") as f:
                    for af in audio_files:
                        f.write(f"file '{af.absolute()}'\n")
                subprocess.run(
                    [
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
                        str(temp_audio),
                    ],
                    check=True,
                    capture_output=True,
                )

                # Mix with BGM and SFX using full pipeline
                mixed_path = output_dir / "temp_mixed.m4a"
                mix_full_pipeline(
                    speech_path=temp_audio,
                    output_path=mixed_path,
                    bgm_path=job.bgm_path,
                    paragraphs=all_paragraphs,
                    config=job.mix_config,
                )

                # Build M4B from mixed audio
                build_m4b(
                    audio_segments=[mixed_path],
                    chapter_markers=segment_markers,
                    output_path=m4b_path,
                    metadata=metadata,
                    normalize=False,  # Disable for mock audio
                )

                # Cleanup temp files
                for tmp in [temp_audio, mixed_path, concat_list]:
                    if tmp.exists():
                        tmp.unlink()
            else:
                build_m4b(
                    audio_segments=audio_files,
                    chapter_markers=segment_markers,
                    output_path=m4b_path,
                    metadata=metadata,
                    normalize=False,  # Disable for mock audio
                )

            job.output_paths["m4b"] = str(m4b_path)

        # --- SRT export ---
        if ExportFormat.SRT in job.formats or ExportFormat.M4B_SRT in job.formats or ExportFormat.ALL in job.formats:
            job.progress = ExportProgress.SUBTITLES
            logger.info("Generating SRT subtitles...")

            subtitle_entries = _build_subtitle_entries(chapter_data_list)
            srt_path = output_dir / f"project_{project.id}.srt"

            generate_srt(
                entries=subtitle_entries,
                output_path=srt_path,
                config=job.subtitle_config,
            )

            job.output_paths["srt"] = str(srt_path)
            vtt_path = srt_path.with_suffix(".vtt")
            if vtt_path.exists():
                job.output_paths["vtt"] = str(vtt_path)

        # --- Zip bundle (if ALL or multiple formats) ---
        if ExportFormat.ALL in job.formats or len(job.formats) > 1:
            job.progress = ExportProgress.COMPRESSING
            zip_path = output_dir / f"project_{project.id}.zip"
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for path_str in job.output_paths.values():
                    p = Path(path_str)
                    if p.exists():
                        zf.write(p, arcname=p.name)
            job.output_paths["zip"] = str(zip_path)

        job.progress = ExportProgress.COMPLETE
        logger.info(f"Export complete: {job.output_paths}")

    except Exception as e:
        job.progress = ExportProgress.FAILED
        job.error = str(e)
        logger.exception(f"Export failed: {e}")

    return job


def export_chapter(
    project_id: int,
    chapter_id: int,
    session,
    output_dir: Optional[str] = None,
) -> Optional[str]:
    """导出单章节为 M4B (不含合并).

    返回导出文件路径或 None (失败时).
    """
    data = _collect_chapter_data(project_id, chapter_id, session)
    if not data:
        return None

    chapter = data["chapter"]
    audio_files = sorted(data["audio_segments"], key=lambda s: s.id)
    audio_paths = [Path(s.file_path) for s in audio_files if Path(s.file_path).exists()]

    if not audio_paths:
        logger.warning(f"No audio files for chapter {chapter_id}")
        return None

    out_dir = Path(output_dir or f"./output/export/ch{chapter.index:02d}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Concatenate into single M4B chapter file
    chapter_output = out_dir / f"ch{chapter.index:02d}_{chapter.title or chapter.index}.m4b"

    # Calculate total duration using ffprobe
    total_duration_ms = 0
    for seg in data["audio_segments"]:
        path = Path(seg.file_path)
        if path.exists():
            try:
                total_duration_ms += get_duration_sync(path)
            except Exception as e:
                logger.warning(f"Failed to probe duration for {path}: {e}, using fallback")
                total_duration_ms += seg.duration_ms or 3000
        else:
            total_duration_ms += seg.duration_ms or 3000

    chapter_marker = ChapterMarker(
        title=chapter.title or f"Chapter {chapter.index}",
        start_ms=0,
        duration_ms=total_duration_ms,
    )

    build_m4b(
        audio_segments=audio_paths,
        chapter_markers=[chapter_marker],
        output_path=chapter_output,
        metadata=M4bMetadata(
            title=chapter.title or f"Chapter {chapter.index}",
        ),
    )

    return str(chapter_output)

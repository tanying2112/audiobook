"""
Export module for audiobook_studio.

Provides M4B encapsulation with chapter markers, SRT/VTT subtitle generation,
MP3 ID3v2.4 tagging, audio ducking (BGM mixing), and batch export orchestration.
"""

from .audio_ducking import DuckingSegment, MixConfig, detect_speech_segments, mix_with_ducking
from .batch_exporter import ExportFormat, ExportJob, ExportProgress, export_chapter, export_project
from .m4b import ChapterMarker, M4bMetadata, build_m4b, build_m4b_single_source
from .mastering import MasteringConfig, build_master_filtergraph, master_audio, measure_loudness, verify_mastering
from .mp3 import (
    ChapterInfo,
    Mp3Metadata,
    add_mp3_to_zip,
    export_mp3_chapters,
    read_id3_tags,
    write_chapters_only,
    write_id3_tags,
)
from .srt import SubtitleConfig, SubtitleEntry, build_subtitle_entries_from_paragraphs, generate_srt

__all__ = [
    # M4B
    "ChapterMarker",
    "M4bMetadata",
    "build_m4b",
    "build_m4b_single_source",
    # MP3
    "ChapterInfo",
    "Mp3Metadata",
    "write_id3_tags",
    "write_chapters_only",
    "read_id3_tags",
    "add_mp3_to_zip",
    "export_mp3_chapters",
    # SRT
    "SubtitleConfig",
    "SubtitleEntry",
    "generate_srt",
    "build_subtitle_entries_from_paragraphs",
    # Audio Ducking
    "DuckingSegment",
    "MixConfig",
    "detect_speech_segments",
    "mix_with_ducking",
    # Mastering (S2-5)
    "MasteringConfig",
    "build_master_filtergraph",
    "master_audio",
    "measure_loudness",
    "verify_mastering",
    # Batch Export
    "ExportFormat",
    "ExportJob",
    "ExportProgress",
    "export_project",
    "export_chapter",
]

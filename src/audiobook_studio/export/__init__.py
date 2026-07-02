"""
Export module for audiobook_studio.

Provides M4B encapsulation with chapter markers, SRT/VTT subtitle generation,
audio ducking (BGM mixing), and batch export orchestration.
"""

from .audio_ducking import DuckingSegment, MixConfig, detect_speech_segments, mix_with_ducking
from .batch_exporter import ExportFormat, ExportJob, ExportProgress, export_chapter, export_project
from .m4b import ChapterMarker, M4bMetadata, build_m4b, build_m4b_single_source
from .srt import SubtitleConfig, SubtitleEntry, build_subtitle_entries_from_paragraphs, generate_srt

__all__ = [
    # M4B
    "ChapterMarker",
    "M4bMetadata",
    "build_m4b",
    "build_m4b_single_source",
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
    # Batch Export
    "ExportFormat",
    "ExportJob",
    "ExportProgress",
    "export_project",
    "export_chapter",
]

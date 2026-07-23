"""
Stage Name Normalization Utilities

Provides consistent stage naming across different subsystems:
- Pipeline stages (extract, analyze, annotate, edit, audio_postprocess, synthesize, quality)
- LLM Router stages (may use different naming)
- Checkpoint stages (may use abbreviated names)
- Frontend stages (UI-friendly display names)

All stage names are normalized to canonical form for consistent processing.
"""

from enum import Enum
from typing import Any, Dict, List, Optional


class CanonicalStage(Enum):
    """Canonical stage names (7-stage pipeline)."""

    EXTRACT = "extract"
    ANALYZE = "analyze_structure"
    ANNOTATE = "annotate_paragraph"
    EDIT = "edit_for_tts"
    AUDIO_POSTPROCESS = "audio_postprocess"
    SYNTHESIZE = "synthesize"
    QUALITY = "quality_check"

    @property
    def display_name(self) -> str:
        """Human-friendly display name."""
        names = {
            "extract": "文本提取",
            "analyze_structure": "结构分析",
            "annotate_paragraph": "段落标注",
            "edit_for_tts": "TTS 编辑",
            "audio_postprocess": "音频后处理",
            "synthesize": "音频合成",
            "quality_check": "质量检查",
        }
        return names.get(self.value, self.value)

    @property
    def short_name(self) -> str:
        """Short identifier for UI."""
        names = {
            "extract": "提取",
            "analyze_structure": "分析",
            "annotate_paragraph": "标注",
            "edit_for_tts": "编辑",
            "audio_postprocess": "后处理",
            "synthesize": "合成",
            "quality_check": "质检",
        }
        return names.get(self.value, self.value)


# Stage name aliases from different subsystems
STAGE_ALIASES: Dict[str, CanonicalStage] = {
    # Pipeline stage → Canonical
    "extract": CanonicalStage.EXTRACT,
    "analyze": CanonicalStage.ANALYZE,
    "analyze_structure": CanonicalStage.ANALYZE,
    "annotate": CanonicalStage.ANNOTATE,
    "annotate_paragraph": CanonicalStage.ANNOTATE,
    "edit": CanonicalStage.EDIT,
    "edit_for_tts": CanonicalStage.EDIT,
    "audio_postprocess": CanonicalStage.AUDIO_POSTPROCESS,
    "postprocess": CanonicalStage.AUDIO_POSTPROCESS,
    "synthesize": CanonicalStage.SYNTHESIZE,
    "synthesize_paragraphs": CanonicalStage.SYNTHESIZE,
    "quality": CanonicalStage.QUALITY,
    "quality_check": CanonicalStage.QUALITY,
    "qc": CanonicalStage.QUALITY,
    "judge": CanonicalStage.QUALITY,
    # Frontend stage names → Canonical
    "①": CanonicalStage.EXTRACT,
    "②": CanonicalStage.ANALYZE,
    "③": CanonicalStage.ANNOTATE,
    "④": CanonicalStage.EDIT,
    "⑤": CanonicalStage.AUDIO_POSTPROCESS,
    "⑥": CanonicalStage.SYNTHESIZE,
    "⑦": CanonicalStage.QUALITY,
    # Chapter ORM status fields → Canonical
    "extract_status": CanonicalStage.EXTRACT,
    "analyze_status": CanonicalStage.ANALYZE,
    "annotate_status": CanonicalStage.ANNOTATE,
    "edit_status": CanonicalStage.EDIT,
    "synthesize_status": CanonicalStage.SYNTHESIZE,
    "quality_status": CanonicalStage.QUALITY,
    "route_status": CanonicalStage.AUDIO_POSTPROCESS,  # _mapped
    # Checkpoint names → Canonical
    "checkpoint_extract": CanonicalStage.EXTRACT,
    "checkpoint_analyze": CanonicalStage.ANALYZE,
    "checkpoint_annotate": CanonicalStage.ANNOTATE,
    "checkpoint_edit": CanonicalStage.EDIT,
    "checkpoint_audio": CanonicalStage.AUDIO_POSTPROCESS,
    "checkpoint_synthesize": CanonicalStage.SYNTHESIZE,
    "checkpoint_quality": CanonicalStage.QUALITY,
}

# Stage order for iteration
STAGE_ORDER: List[CanonicalStage] = [
    CanonicalStage.EXTRACT,
    CanonicalStage.ANALYZE,
    CanonicalStage.ANNOTATE,
    CanonicalStage.EDIT,
    CanonicalStage.AUDIO_POSTPROCESS,
    CanonicalStage.SYNTHESIZE,
    CanonicalStage.QUALITY,
]


def normalize_stage_name(stage: str, from_system: str = "pipeline") -> str:
    """
    Normalize stage name from any subsystem to canonical form.

    Args:
        stage: Stage name from any subsystem
        from_system: Source system context ('pipeline', 'llm', 'checkpoint', 'frontend', 'orm')

    Returns:
        Canonical stage name (e.g., 'extract', 'analyze_structure', etc.)

    Examples:
        >>> normalize_stage_name(" annotate ")
        'annotate_paragraph'
        >>> normalize_stage_name("qc", from_system="llm")
        'quality_check'
        >>> normalize_stage_name("③", from_system="frontend")
        'annotate_paragraph'
    """
    # Strip whitespace
    stage = stage.strip().lower()

    # Direct lookup in aliases
    if stage in STAGE_ALIASES:
        return STAGE_ALIASES[stage].value

    # Try without underscores
    stage_no_underscore = stage.replace("_", "")
    for alias, canonical in STAGE_ALIASES.items():
        if alias.replace("_", "") == stage_no_underscore:
            return canonical.value

    # If no match, return as-is (may be custom stage)
    return stage


def get_stage_order() -> List[str]:
    """
    Get canonical stage order for iteration.

    Returns:
        List of canonical stage names in order
    """
    return [s.value for s in STAGE_ORDER]


def get_stage_display_name(stage: str) -> str:
    """
    Get human-friendly display name for a stage.

    Args:
        stage: Canonical stage name or alias

    Returns:
        Display name in Chinese
    """
    canonical = normalize_stage_name(stage)
    for s in STAGE_ORDER:
        if s.value == canonical:
            return s.display_name
    return stage


def get_stage_short_name(stage: str) -> str:
    """
    Get short name for UI display.

    Args:
        stage: Canonical stage name or alias

    Returns:
        Short name (1-4 Chinese characters)
    """
    canonical = normalize_stage_name(stage)
    for s in STAGE_ORDER:
        if s.value == canonical:
            return s.short_name
    return stage


# ─────────────────────────────────────────────────────────────────────────────
# Utility for mapping Chapter ORM fields to stages
# ─────────────────────────────────────────────────────────────────────────────

CHAPTER_STATUS_FIELDS = {
    "extract_status": CanonicalStage.EXTRACT,
    "analyze_status": CanonicalStage.ANALYZE,
    "annotate_status": CanonicalStage.ANNOTATE,
    "edit_status": CanonicalStage.EDIT,
    "route_status": CanonicalStage.AUDIO_POSTPROCESS,  # Mapped field
    "synthesize_status": CanonicalStage.SYNTHESIZE,
    "quality_status": CanonicalStage.QUALITY,
}


def infer_audio_postprocess_status(chapter_data: dict[str, Any]) -> str:
    """
    Infer audio_postprocess status from route_status and edit_status.

    The Chapter ORM doesn't have a dedicated audio_postprocess_status field.
    We infer it from the combination of route_status and edit_status.

    Args:
        chapter_data: Chapter ORM data dict

    Returns:
        Status: 'pending', 'running', 'completed', or 'failed'
    """
    route_status = chapter_data.get("route_status", "pending")
    edit_status = chapter_data.get("edit_status", "pending")

    # If both edit and route are complete, audio_postprocess is complete
    if edit_status == "completed" and route_status == "completed":
        return "completed"

    # If either is running, audio_postprocess is running
    if edit_status == "running" or route_status == "running":
        return "running"

    # Default to route_status (proxy)
    return route_status or "pending"

"""Auto-generated Pydantic Output schema for Paragraph."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field


class ParagraphOutput(BaseModel):
    """Output schema for Paragraph operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: Optional[int]
    chapter_id: Optional[int]
    book_id: Optional[int]
    speaker: Optional[str]
    index: int
    chapter_index: Optional[int]
    text: str
    speaker_canonical_name: Optional[str]
    is_dialogue: bool
    emotion: Optional[str]
    emotion_intensity: Optional[float]
    speech_rate: Optional[float]
    pitch_shift_semitones: Optional[int]
    needs_sfx: bool
    sfx_tags: Optional[list]
    pause_before_ms: int
    pause_after_ms: int
    confidence: Optional[float]
    notes: Optional[str]
    edited_text: Optional[str]
    edit_changes_made: Optional[list]
    edit_forbidden_removed: Optional[list]
    edit_confidence: Optional[float]
    edit_rationale: Optional[str]
    edit_difficulty: Optional[str]
    edit_forbid_edit: bool
    routing_engine: Optional[str]
    routing_voice_id: Optional[str]
    routing_prosody_overrides: Optional[dict]
    routing_fallback: Optional[str]
    routing_reasoning: Optional[str]
    routing_estimated_cost: float
    routing_estimated_duration: int
    quality_speaker_clarity: Optional[float]
    quality_emotion_match: Optional[float]
    quality_prosody_naturalness: Optional[float]
    quality_text_audio_alignment: Optional[float]
    quality_overall_score: Optional[float]
    quality_issues: Optional[list]
    quality_fix_suggestions: Optional[list]
    quality_needs_regeneration: bool
    audio_segment_id: Optional[int]
    status: str
    project: Project

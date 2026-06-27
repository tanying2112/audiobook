"""Auto-generated Pydantic Input schema for Paragraph."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field, field_validator


class ParagraphInput(BaseModel):
    """Input schema for Paragraph operations."""

    id: int = Field(description="Unique identifier")
    project_id: Optional[int] = Field()
    chapter_id: Optional[int] = Field()
    book_id: Optional[int] = Field()
    speaker: Optional[str] = Field()
    index: int = Field()
    chapter_index: Optional[int] = Field()
    text: str = Field(description="Text content")
    speaker_canonical_name: Optional[str] = Field()
    is_dialogue: bool = Field()
    emotion: Optional[str] = Field()
    emotion_intensity: Optional[float] = Field()
    speech_rate: Optional[float] = Field()
    pitch_shift_semitones: Optional[int] = Field()
    needs_sfx: bool = Field()
    sfx_tags: Optional[list] = Field()
    pause_before_ms: int = Field()
    pause_after_ms: int = Field()
    confidence: Optional[float] = Field()
    notes: Optional[str] = Field()
    edited_text: Optional[str] = Field(description="Text content")
    edit_changes_made: Optional[list] = Field()
    edit_forbidden_removed: Optional[list] = Field()
    edit_confidence: Optional[float] = Field()
    edit_rationale: Optional[str] = Field()
    edit_difficulty: Optional[str] = Field()
    edit_forbid_edit: bool = Field()
    routing_engine: Optional[str] = Field()
    routing_voice_id: Optional[str] = Field()
    routing_prosody_overrides: Optional[dict] = Field()
    routing_fallback: Optional[str] = Field()
    routing_reasoning: Optional[str] = Field()
    routing_estimated_cost: float = Field()
    routing_estimated_duration: int = Field()
    quality_speaker_clarity: Optional[float] = Field()
    quality_emotion_match: Optional[float] = Field()
    quality_prosody_naturalness: Optional[float] = Field()
    quality_text_audio_alignment: Optional[float] = Field(description="Text content")
    quality_overall_score: Optional[float] = Field()
    quality_issues: Optional[list] = Field()
    quality_fix_suggestions: Optional[list] = Field()
    quality_needs_regeneration: bool = Field()
    audio_segment_id: Optional[int] = Field()
    status: str = Field()
    project: Project = Field()

"""Auto-generated Pydantic Input schema for Quality."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class QualityInput(BaseModel):
    """Input schema for Quality operations."""

    id: int = Field(description="Unique identifier")
    project_id: Optional[int] = Field()
    chapter_id: Optional[int] = Field()
    paragraph_id: Optional[int] = Field()
    tts_edit_id: int = Field()
    speaker_clarity: Optional[float] = Field()
    emotion_match: Optional[float] = Field()
    prosody_naturalness: Optional[float] = Field()
    text_audio_alignment: Optional[float] = Field(description="Text content")
    overall_score: Optional[float] = Field()
    score: Optional[float] = Field()
    comments: Optional[str] = Field()
    issues: Optional[list] = Field()
    fix_suggestions: Optional[list] = Field()
    needs_regeneration: bool = Field()
    judge_model: Optional[str] = Field()
    judge_prompt_version: Optional[str] = Field()
    audio_file_path: Optional[str] = Field()
    audio_duration_ms: Optional[int] = Field()

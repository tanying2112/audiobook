"""Auto-generated Pydantic Output schema for Quality."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class QualityOutput(BaseModel):
    """Output schema for Quality operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: Optional[int]
    chapter_id: Optional[int]
    paragraph_id: Optional[int]
    tts_edit_id: int
    speaker_clarity: Optional[float]
    emotion_match: Optional[float]
    prosody_naturalness: Optional[float]
    text_audio_alignment: Optional[float]
    overall_score: Optional[float]
    score: Optional[float]
    comments: Optional[str]
    issues: Optional[list]
    fix_suggestions: Optional[list]
    needs_regeneration: bool
    judge_model: Optional[str]
    judge_prompt_version: Optional[str]
    audio_file_path: Optional[str]
    audio_duration_ms: Optional[int]

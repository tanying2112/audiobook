"""Auto-generated Pydantic Output schema for AudioSegment."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field


class AudioSegmentOutput(BaseModel):
    """Output schema for AudioSegment operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: int
    chapter_id: int
    paragraph_id: int
    file_path: str
    format: str
    duration_ms: Optional[int]
    file_size_bytes: Optional[int]
    sample_rate: int
    channels: int
    engine: Optional[str]
    voice_id: Optional[str]
    prosody_overrides: Optional[dict]
    version: int
    is_current: bool
    parent_segment_id: Optional[int]
    quality_id: Optional[int]
    status: str
    project: Project

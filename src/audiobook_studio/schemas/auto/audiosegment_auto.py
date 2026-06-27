"""Auto-generated Pydantic Input schema for AudioSegment."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field, field_validator


class AudioSegmentInput(BaseModel):
    """Input schema for AudioSegment operations."""

    id: int = Field(description="Unique identifier")
    project_id: int = Field()
    chapter_id: int = Field()
    paragraph_id: int = Field()
    file_path: str = Field()
    format: str = Field()
    duration_ms: Optional[int] = Field()
    file_size_bytes: Optional[int] = Field()
    sample_rate: int = Field()
    channels: int = Field()
    engine: Optional[str] = Field()
    voice_id: Optional[str] = Field()
    prosody_overrides: Optional[dict] = Field()
    version: int = Field()
    is_current: bool = Field()
    parent_segment_id: Optional[int] = Field()
    quality_id: Optional[int] = Field()
    status: str = Field()
    project: Project = Field()

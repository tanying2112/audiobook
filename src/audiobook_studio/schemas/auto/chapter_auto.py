"""Auto-generated Pydantic Input schema for Chapter."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field, field_validator


class ChapterInput(BaseModel):
    """Input schema for Chapter operations."""

    id: int = Field(description="Unique identifier")
    project_id: int = Field()
    index: int = Field()
    title: Optional[str] = Field()
    raw_text: Optional[str] = Field(description="Text content")
    extracted_text: Optional[str] = Field(description="Text content")
    analyzed_json: Optional[dict] = Field()
    annotated_json: Optional[dict] = Field()
    edited_json: Optional[dict] = Field()
    status: str = Field()
    extract_status: str = Field()
    analyze_status: str = Field()
    annotate_status: str = Field()
    edit_status: str = Field()
    route_status: str = Field()
    synthesize_status: str = Field()
    quality_status: str = Field()
    cost_usd: float = Field()
    token_count: int = Field()
    tts_chars: int = Field()
    started_at: Optional[str] = Field()
    completed_at: Optional[str] = Field()
    project: Project = Field()

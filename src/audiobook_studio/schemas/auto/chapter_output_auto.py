"""Auto-generated Pydantic Output schema for Chapter."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field


class ChapterOutput(BaseModel):
    """Output schema for Chapter operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: int
    index: int
    title: Optional[str]
    raw_text: Optional[str]
    extracted_text: Optional[str]
    analyzed_json: Optional[dict]
    annotated_json: Optional[dict]
    edited_json: Optional[dict]
    status: str
    extract_status: str
    analyze_status: str
    annotate_status: str
    edit_status: str
    route_status: str
    synthesize_status: str
    quality_status: str
    cost_usd: float
    token_count: int
    tts_chars: int
    started_at: Optional[str]
    completed_at: Optional[str]
    project: Project

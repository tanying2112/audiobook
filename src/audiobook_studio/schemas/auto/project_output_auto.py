"""Auto-generated Pydantic Output schema for Project."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ProjectOutput(BaseModel):
    """Output schema for Project operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    title: str
    author: Optional[str]
    genre: Optional[str]
    difficulty: Optional[str]
    language: str
    era: Optional[str]
    total_chapters_estimated: Optional[int]
    global_style_notes: Optional[str]
    story_line_summary: Optional[str]
    status: str
    current_stage: Optional[str]
    progress: float
    total_cost_usd: float
    cost_limit_per_book: float
    cost_limit_per_chapter: float
    completed_at: Optional[str]

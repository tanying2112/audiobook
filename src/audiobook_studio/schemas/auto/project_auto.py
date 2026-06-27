"""Auto-generated Pydantic Input schema for Project."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ProjectInput(BaseModel):
    """Input schema for Project operations."""

    id: int = Field(description="Unique identifier")
    title: str = Field()
    author: Optional[str] = Field()
    genre: Optional[str] = Field()
    difficulty: Optional[str] = Field()
    language: str = Field()
    era: Optional[str] = Field()
    total_chapters_estimated: Optional[int] = Field()
    global_style_notes: Optional[str] = Field()
    story_line_summary: Optional[str] = Field()
    status: str = Field()
    current_stage: Optional[str] = Field()
    progress: float = Field()
    total_cost_usd: float = Field()
    cost_limit_per_book: float = Field()
    cost_limit_per_chapter: float = Field()
    completed_at: Optional[str] = Field()

"""Auto-generated Pydantic Output schema for Character."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field


class CharacterOutput(BaseModel):
    """Output schema for Character operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: int
    canonical_name: str
    gender: Optional[str]
    age_range: Optional[str]
    suggested_voice_id: Optional[str]
    sample_quote: Optional[str]
    project: Project

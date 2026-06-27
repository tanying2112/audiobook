"""Auto-generated Pydantic Input schema for Character."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field, field_validator


class CharacterInput(BaseModel):
    """Input schema for Character operations."""

    id: int = Field(description="Unique identifier")
    project_id: int = Field()
    canonical_name: str = Field()
    gender: Optional[str] = Field()
    age_range: Optional[str] = Field()
    suggested_voice_id: Optional[str] = Field()
    sample_quote: Optional[str] = Field()
    project: Project = Field()

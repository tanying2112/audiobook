"""Auto-generated Pydantic Input schema for EmotionSnapshot."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field, field_validator


class EmotionSnapshotInput(BaseModel):
    """Input schema for EmotionSnapshot operations."""

    id: int = Field(description="Unique identifier")
    project_id: int = Field()
    chapter: int = Field()
    dominant_emotion: str = Field()
    intensity: float = Field()
    notes: Optional[str] = Field()
    project: Project = Field()

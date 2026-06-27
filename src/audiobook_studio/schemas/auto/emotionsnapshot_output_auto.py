"""Auto-generated Pydantic Output schema for EmotionSnapshot."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field


class EmotionSnapshotOutput(BaseModel):
    """Output schema for EmotionSnapshot operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: int
    chapter: int
    dominant_emotion: str
    intensity: float
    notes: Optional[str]
    project: Project

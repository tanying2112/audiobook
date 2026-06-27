"""Auto-generated Pydantic Output schema for LegacyQuality."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field


class LegacyQualityOutput(BaseModel):
    """Output schema for LegacyQuality operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    tts_edit_id: Optional[int]
    score: float
    comments: Optional[str]
    tts_edit: Optional[LegacyTTSEdit]

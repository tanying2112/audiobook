"""Auto-generated Pydantic Input schema for LegacyQuality."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field, field_validator


class LegacyQualityInput(BaseModel):
    """Input schema for LegacyQuality operations."""

    id: int = Field(description="Unique identifier")
    tts_edit_id: Optional[int] = Field()
    score: float = Field()
    comments: Optional[str] = Field()
    tts_edit: Optional[LegacyTTSEdit] = Field()

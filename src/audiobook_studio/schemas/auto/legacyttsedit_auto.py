"""Auto-generated Pydantic Input schema for LegacyTTSEdit."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field, field_validator


class LegacyTTSEditInput(BaseModel):
    """Input schema for LegacyTTSEdit operations."""

    id: int = Field(description="Unique identifier")
    paragraph_id: int = Field()
    edited_text: str = Field(description="Text content")
    voice: Optional[str] = Field()
    paragraph: LegacyParagraph = Field()
    quality: Optional[LegacyQuality] = Field()

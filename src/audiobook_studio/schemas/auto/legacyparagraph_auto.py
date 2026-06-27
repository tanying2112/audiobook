"""Auto-generated Pydantic Input schema for LegacyParagraph."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field, field_validator


class LegacyParagraphInput(BaseModel):
    """Input schema for LegacyParagraph operations."""

    id: int = Field(description="Unique identifier")
    book_id: int = Field()
    index: int = Field()
    text: str = Field(description="Text content")
    speaker: Optional[str] = Field()
    book: LegacyBook = Field()

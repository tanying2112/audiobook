"""Auto-generated Pydantic Output schema for LegacyParagraph."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field


class LegacyParagraphOutput(BaseModel):
    """Output schema for LegacyParagraph operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    book_id: int
    index: int
    text: str
    speaker: Optional[str]
    book: LegacyBook

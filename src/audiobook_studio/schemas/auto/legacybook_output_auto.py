"""Auto-generated Pydantic Output schema for LegacyBook."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field


class LegacyBookOutput(BaseModel):
    """Output schema for LegacyBook operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    title: str
    author: str
    language: str
    isbn: Optional[str]

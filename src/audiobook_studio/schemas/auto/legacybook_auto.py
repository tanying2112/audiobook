"""Auto-generated Pydantic Input schema for LegacyBook."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field, field_validator


class LegacyBookInput(BaseModel):
    """Input schema for LegacyBook operations."""

    id: int = Field(description="Unique identifier")
    title: str = Field()
    author: str = Field()
    language: str = Field()
    isbn: Optional[str] = Field()

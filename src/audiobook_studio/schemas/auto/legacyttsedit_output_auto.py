"""Auto-generated Pydantic Output schema for LegacyTTSEdit."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field


class LegacyTTSEditOutput(BaseModel):
    """Output schema for LegacyTTSEdit operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    paragraph_id: int
    edited_text: str
    voice: Optional[str]
    paragraph: LegacyParagraph
    quality: Optional[LegacyQuality]

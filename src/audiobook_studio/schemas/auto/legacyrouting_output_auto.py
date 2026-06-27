"""Auto-generated Pydantic Output schema for LegacyRouting."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field


class LegacyRoutingOutput(BaseModel):
    """Output schema for LegacyRouting operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    paragraph_id: int
    voice: str
    confidence: Optional[float]
    paragraph: LegacyParagraph

"""Auto-generated Pydantic Input schema for LegacyRouting."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.legacy import LegacyBook, LegacyParagraph, LegacyTTSEdit, LegacyQuality, Field, field_validator


class LegacyRoutingInput(BaseModel):
    """Input schema for LegacyRouting operations."""

    id: int = Field(description="Unique identifier")
    paragraph_id: int = Field()
    voice: str = Field()
    confidence: Optional[float] = Field()
    paragraph: LegacyParagraph = Field()

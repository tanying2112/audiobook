"""Auto-generated Pydantic Input schema for Routing."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RoutingInput(BaseModel):
    """Input schema for Routing operations."""

    id: int = Field(description="Unique identifier")
    project_id: Optional[int] = Field()
    chapter_id: Optional[int] = Field()
    paragraph_id: int = Field()
    engine_choice: Optional[str] = Field()
    voice_id: Optional[str] = Field()
    prosody_overrides: Optional[dict] = Field()
    fallback_engine: Optional[str] = Field()
    reasoning: Optional[str] = Field()
    estimated_cost_usd: float = Field()
    estimated_duration_ms: int = Field()
    actual_engine: Optional[str] = Field()
    actual_cost_usd: Optional[float] = Field()
    actual_duration_ms: Optional[int] = Field()
    status: str = Field()
    voice: Optional[str] = Field()
    confidence: Optional[float] = Field()
    completed_at: Optional[datetime] = Field()

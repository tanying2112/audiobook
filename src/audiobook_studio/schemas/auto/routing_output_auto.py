"""Auto-generated Pydantic Output schema for Routing."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RoutingOutput(BaseModel):
    """Output schema for Routing operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: Optional[int]
    chapter_id: Optional[int]
    paragraph_id: int
    engine_choice: Optional[str]
    voice_id: Optional[str]
    prosody_overrides: Optional[dict]
    fallback_engine: Optional[str]
    reasoning: Optional[str]
    estimated_cost_usd: float
    estimated_duration_ms: int
    actual_engine: Optional[str]
    actual_cost_usd: Optional[float]
    actual_duration_ms: Optional[int]
    status: str
    voice: Optional[str]
    confidence: Optional[float]
    completed_at: Optional[datetime]

"""Auto-generated Pydantic Input schema for TTSEdit."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class TTSEditInput(BaseModel):
    """Input schema for TTSEdit operations."""

    id: int = Field(description="Unique identifier")
    project_id: Optional[int] = Field()
    chapter_id: Optional[int] = Field()
    paragraph_id: int = Field()
    version: int = Field()
    edited_text: str = Field(description="Text content")
    changes_made: Optional[list] = Field()
    forbidden_content_removed: Optional[list] = Field()
    confidence: Optional[float] = Field()
    rationale: Optional[str] = Field()
    difficulty: Optional[str] = Field()
    forbid_edit: bool = Field()
    voice: Optional[str] = Field()
    source: Optional[str] = Field()
    llm_model: Optional[str] = Field()
    prompt_version: Optional[str] = Field()

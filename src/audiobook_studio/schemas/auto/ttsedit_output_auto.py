"""Auto-generated Pydantic Output schema for TTSEdit."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TTSEditOutput(BaseModel):
    """Output schema for TTSEdit operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: Optional[int]
    chapter_id: Optional[int]
    paragraph_id: int
    version: int
    edited_text: str
    changes_made: Optional[list]
    forbidden_content_removed: Optional[list]
    confidence: Optional[float]
    rationale: Optional[str]
    difficulty: Optional[str]
    forbid_edit: bool
    voice: Optional[str]
    source: Optional[str]
    llm_model: Optional[str]
    prompt_version: Optional[str]

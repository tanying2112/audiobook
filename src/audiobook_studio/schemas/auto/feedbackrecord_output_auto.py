"""Auto-generated Pydantic Output schema for FeedbackRecord."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field


class FeedbackRecordOutput(BaseModel):
    """Output schema for FeedbackRecord operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: int
    chapter_id: Optional[int]
    paragraph_id: Optional[int]
    feedback_id: str
    source: str
    stage: str
    input_snapshot: dict
    llm_output: dict
    corrected_output: dict
    rationale: str
    diff_summary: Optional[str]
    pattern_tags: Optional[list]
    processed: bool
    promoted: bool
    project: Project

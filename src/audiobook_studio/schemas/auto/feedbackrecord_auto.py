"""Auto-generated Pydantic Input schema for FeedbackRecord."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field, field_validator


class FeedbackRecordInput(BaseModel):
    """Input schema for FeedbackRecord operations."""

    id: int = Field(description="Unique identifier")
    project_id: int = Field()
    chapter_id: Optional[int] = Field()
    paragraph_id: Optional[int] = Field()
    feedback_id: str = Field()
    source: str = Field()
    stage: str = Field()
    input_snapshot: dict = Field()
    llm_output: dict = Field()
    corrected_output: dict = Field()
    rationale: str = Field()
    diff_summary: Optional[str] = Field()
    pattern_tags: Optional[list] = Field()
    processed: bool = Field()
    promoted: bool = Field()
    project: Project = Field()

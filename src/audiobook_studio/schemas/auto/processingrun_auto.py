"""Auto-generated Pydantic Input schema for ProcessingRun."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field, field_validator

if TYPE_CHECKING:
    from ...models.processing_run import ProcessingRun


class ProcessingRunInput(BaseModel):
    """Input schema for ProcessingRun operations."""

    id: int = Field(description="Unique identifier")
    project_id: int = Field()
    parent_run_id: Optional[int] = Field()
    config_json: str = Field()
    prompt_versions: dict = Field()
    golden_score: Optional[float] = Field()
    status: str = Field()
    error_message: Optional[str] = Field()
    version_tag: Optional[str] = Field()
    commit_message: Optional[str] = Field()
    started_at: datetime = Field()
    completed_at: Optional[datetime] = Field()
    project: Project = Field()
    parent_run: Optional[ProcessingRun] = Field()

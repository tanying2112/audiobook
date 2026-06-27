"""Auto-generated Pydantic Output schema for ProcessingRun."""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel
from ...models.book import Project, Field

if TYPE_CHECKING:
    from ...models.processing_run import ProcessingRun


class ProcessingRunOutput(BaseModel):
    """Output schema for ProcessingRun operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    project_id: int
    parent_run_id: Optional[int]
    config_json: str
    prompt_versions: dict
    golden_score: Optional[float]
    status: str
    error_message: Optional[str]
    version_tag: Optional[str]
    commit_message: Optional[str]
    started_at: datetime
    completed_at: Optional[datetime]
    project: Project
    parent_run: Optional[ProcessingRun]

"""Auto-generated Pydantic Output schema for TaskRecord."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TaskRecordOutput(BaseModel):
    """Output schema for TaskRecord operations."""

    class Config:
        from_attributes = True  # For ORM compatibility


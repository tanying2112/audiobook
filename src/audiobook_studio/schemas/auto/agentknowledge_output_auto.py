"""Auto-generated Pydantic Output schema for AgentKnowledge."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AgentKnowledgeOutput(BaseModel):
    """Output schema for AgentKnowledge operations."""

    class Config:
        from_attributes = True  # For ORM compatibility


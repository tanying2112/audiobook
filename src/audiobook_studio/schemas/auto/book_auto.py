"""Auto-generated Pydantic Input schema for Book."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class BookInput(BaseModel):
    """Input schema for Book operations."""

    id: int = Field(description="Unique identifier")
    title: str = Field()
    author: Optional[str] = Field()
    language: str = Field()
    isbn: Optional[str] = Field()

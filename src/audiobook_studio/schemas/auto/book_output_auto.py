"""Auto-generated Pydantic Output schema for Book."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class BookOutput(BaseModel):
    """Output schema for Book operations."""

    class Config:
        from_attributes = True  # For ORM compatibility

    id: int
    title: str
    author: Optional[str]
    language: str
    isbn: Optional[str]

"""Legacy Pydantic schemas for backward compatibility with existing CRUD API tests.

These schemas match the original simple Book/Paragraph/TTSEdit/Routing/Quality schemas
used by the existing API tests.
"""

from typing import Optional

from pydantic import BaseModel, Field


class Book(BaseModel):
    """Legacy Book schema."""

    id: Optional[int] = Field(default=None, description="Database primary key")
    title: str = Field(..., description="Book title")
    author: str = Field(..., description="Author name")
    language: str = Field(..., description="Language code, e.g., 'en'")
    isbn: Optional[str] = Field(default=None, description="ISBN number if available")

    model_config = {"from_attributes": True}


class Paragraph(BaseModel):
    """Legacy Paragraph schema."""

    id: Optional[int] = Field(default=None, description="Database primary key")
    book_id: int = Field(..., description="Foreign key to Book")
    index: int = Field(..., description="Paragraph order index")
    text: str = Field(..., description="Paragraph text content")
    speaker: Optional[str] = Field(default=None, description="Speaker name if applicable")

    model_config = {"from_attributes": True}


class TTSEdit(BaseModel):
    """Legacy TTSEdit schema."""

    id: Optional[int] = Field(default=None, description="Database primary key")
    paragraph_id: int = Field(..., description="Foreign key to Paragraph")
    edited_text: str = Field(..., description="Edited text for TTS")
    voice: Optional[str] = Field(default=None, description="Voice identifier for synthesis")

    model_config = {"from_attributes": True}


class Routing(BaseModel):
    """Legacy Routing schema."""

    id: Optional[int] = Field(default=None, description="Database primary key")
    paragraph_id: int = Field(..., description="Foreign key to Paragraph")
    voice: str = Field(..., description="Selected voice identifier")
    confidence: Optional[float] = Field(default=None, description="Confidence score (0-1)")

    model_config = {"from_attributes": True}


class Quality(BaseModel):
    """Legacy Quality schema."""

    id: Optional[int] = Field(default=None, description="Database primary key")
    tts_edit_id: int = Field(..., description="Foreign key to TTSEdit")
    score: float = Field(..., description="Overall quality score (0-1)")
    comments: Optional[str] = Field(default=None, description="Feedback comments")

    model_config = {"from_attributes": True}

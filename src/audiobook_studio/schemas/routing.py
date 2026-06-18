"""Routing schema – decision data for selecting TTS voice or processing path.

The schema captures the LLM‑generated routing information that determines which
voice or processing pipeline should be used for a given paragraph.
"""

from pydantic import BaseModel, Field


class Routing(BaseModel):
    """Routing information for a paragraph.

    Attributes
    ----------
    id: int | None
        Primary key – set by the database.
    paragraph_id: int
        Foreign key to the ``Paragraph``.
    voice: str
        Chosen voice identifier.
    confidence: float | None
        Optional confidence score (0‑1).
    """

    id: int | None = Field(default=None, description="Database primary key")
    paragraph_id: int = Field(..., description="Foreign key to Paragraph")
    voice: str = Field(..., description="Selected voice identifier")
    confidence: float | None = Field(default=None, description="Confidence score (0‑1)")

    model_config = {"from_attributes": True}

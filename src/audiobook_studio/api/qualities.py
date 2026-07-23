"""FastAPI router for ``Quality`` CRUD operations (async SQLAlchemy 2.0)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.legacy import LegacyQuality as Quality
from ..schemas.legacy import Quality as QualitySchema
from .dependencies import get_async_db

router = APIRouter(prefix="/qualities", tags=["qualities"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class QualityCreate(BaseModel):
    """Schema for creating a new Quality."""

    tts_edit_id: int
    score: float
    comments: str | None = None


class QualityUpdate(BaseModel):
    """Schema for updating a Quality."""

    score: float | None = None
    comments: str | None = None


class QualityOut(QualitySchema):
    """Quality response schema with ORM config."""

    model_config = ConfigDict(from_attributes=True)


# ── Quality CRUD ─────────────────────────────────────────────────────────────


@router.post("/", response_model=QualityOut, status_code=status.HTTP_201_CREATED)
async def create_quality(payload: QualityCreate, db: AsyncSession = Depends(get_async_db)):
    """Create a new quality record."""
    db_item = Quality(**payload.model_dump())
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item


@router.get("/", response_model=List[QualityOut])
async def list_qualities(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_async_db)):
    """List all quality records."""
    result = await db.execute(select(Quality).offset(skip).limit(limit))
    items = result.scalars().all()
    return items


@router.get("/{quality_id}", response_model=QualityOut)
async def get_quality(quality_id: int, db: AsyncSession = Depends(get_async_db)):
    """Get a quality record by ID."""
    result = await db.execute(select(Quality).where(Quality.id == quality_id))
    i = result.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Quality not found")
    return i


@router.put("/{quality_id}", response_model=QualityOut)
async def update_quality(quality_id: int, payload: QualityUpdate, db: AsyncSession = Depends(get_async_db)):
    """Update a quality record."""
    result = await db.execute(select(Quality).where(Quality.id == quality_id))
    i = result.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Quality not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in {"id", "tts_edit_id"}:
            continue
        setattr(i, field, value)
    await db.commit()
    await db.refresh(i)
    return i


@router.delete("/{quality_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_quality(quality_id: int, db: AsyncSession = Depends(get_async_db)):
    """Delete a quality record."""
    result = await db.execute(select(Quality).where(Quality.id == quality_id))
    i = result.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Quality not found")
    await db.delete(i)
    await db.commit()
    return None

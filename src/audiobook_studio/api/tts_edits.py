"""FastAPI router for ``TTSEdit`` CRUD operations (async SQLAlchemy 2.0)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.legacy import LegacyTTSEdit as TTSEdit
from ..schemas.legacy import TTSEdit as TTSEditSchema
from .dependencies import get_async_db

router = APIRouter(prefix="/tts_edits", tags=["tts_edits"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class TTSEditCreate(BaseModel):
    """Schema for creating a new TTSEdit."""

    paragraph_id: int
    edited_text: str
    voice: Optional[str] = None


class TTSEditUpdate(BaseModel):
    """Schema for updating a TTSEdit."""

    edited_text: Optional[str] = None
    voice: Optional[str] = None


class TTSEditOut(TTSEditSchema):
    """TTSEdit response schema with ORM config."""

    model_config = ConfigDict(from_attributes=True)


# ── TTSEdit CRUD ─────────────────────────────────────────────────────────────


@router.post("/", response_model=TTSEditOut, status_code=status.HTTP_201_CREATED)
async def create_tts_edit(payload: TTSEditCreate, db: AsyncSession = Depends(get_async_db)):
    """Create a new TTS edit."""
    db_edit = TTSEdit(**payload.model_dump())
    db.add(db_edit)
    await db.commit()
    await db.refresh(db_edit)
    return db_edit


@router.get("/", response_model=List[TTSEditOut])
async def list_tts_edits(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_async_db)):
    """List all TTS edits."""
    result = await db.execute(select(TTSEdit).offset(skip).limit(limit))
    items = result.scalars().all()
    return items


@router.get("/{edit_id}", response_model=TTSEditOut)
async def get_tts_edit(edit_id: int, db: AsyncSession = Depends(get_async_db)):
    """Get a TTS edit by ID."""
    result = await db.execute(select(TTSEdit).where(TTSEdit.id == edit_id))
    e = result.scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="TTSEdit not found")
    return e


@router.put("/{edit_id}", response_model=TTSEditOut)
async def update_tts_edit(edit_id: int, payload: TTSEditUpdate, db: AsyncSession = Depends(get_async_db)):
    """Update a TTS edit."""
    result = await db.execute(select(TTSEdit).where(TTSEdit.id == edit_id))
    e = result.scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="TTSEdit not found")
    for field, value in payload.model_dump().items():
        if field in {"id", "paragraph_id"}:
            continue
        setattr(e, field, value)
    await db.commit()
    await db.refresh(e)
    return e


@router.delete("/{edit_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tts_edit(edit_id: int, db: AsyncSession = Depends(get_async_db)):
    """Delete a TTS edit."""
    result = await db.execute(select(TTSEdit).where(TTSEdit.id == edit_id))
    e = result.scalar_one_or_none()
    if not e:
        raise HTTPException(status_code=404, detail="TTSEdit not found")
    await db.delete(e)
    await db.commit()
    return None

"""FastAPI router for ``Book`` CRUD operations (async SQLAlchemy 2.0)."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.legacy import LegacyBook
from ..schemas.legacy import Book as BookSchema
from .dependencies import get_async_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/books", tags=["books"])


# ── Pydantic schemas for API responses ────────────────────────────────────────


class BookCreate(BaseModel):
    """Schema for creating a new book."""

    title: str
    author: str
    language: str
    isbn: Optional[str] = None


class BookUpdate(BaseModel):
    """Schema for updating a book."""

    title: Optional[str] = None
    author: Optional[str] = None
    language: Optional[str] = None
    isbn: Optional[str] = None


class BookOut(BookSchema):
    """Book response schema with ORM config."""

    model_config = ConfigDict(from_attributes=True)


# ── Book CRUD ──────────────────────────────────────────────────────────────────


@router.post("/", response_model=BookOut, status_code=status.HTTP_201_CREATED)
async def create_book(
    payload: BookCreate, db: AsyncSession = Depends(get_async_db)
):
    """Create a new book."""
    book = LegacyBook(**payload.model_dump())
    db.add(book)
    await db.commit()
    await db.refresh(book)
    return book


@router.get("/", response_model=List[BookOut])
async def list_books(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_async_db)):
    """List all books."""
    result = await db.execute(
        select(LegacyBook)
        .options(selectinload(LegacyBook.paragraphs))
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{book_id}", response_model=BookOut)
async def get_book(book_id: int, db: AsyncSession = Depends(get_async_db)):
    """Get a single book by ID."""
    result = await db.execute(select(LegacyBook).where(LegacyBook.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book


@router.put("/{book_id}", response_model=BookOut)
async def update_book(
    book_id: int, payload: BookUpdate, db: AsyncSession = Depends(get_async_db)
):
    """Update a book."""
    result = await db.execute(select(LegacyBook).where(LegacyBook.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(book, field, value)
    await db.commit()
    await db.refresh(book)
    return book


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_book(book_id: int, db: AsyncSession = Depends(get_async_db)):
    """Delete a book and all related data."""
    result = await db.execute(select(LegacyBook).where(LegacyBook.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    await db.delete(book)
    await db.commit()
    return None
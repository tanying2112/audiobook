"""FastAPI router for ``Book`` CRUD operations (legacy API for backward compatibility)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..models.legacy import LegacyBook as Book
from ..schemas.legacy import Book as BookSchema
from .dependencies import get_db

router = APIRouter(prefix="/books", tags=["books"])


@router.post("/", response_model=BookSchema, status_code=status.HTTP_201_CREATED)
def create_book(book: BookSchema, db: Session = Depends(get_db)):
    db_book = Book(**book.model_dump())
    db.add(db_book)
    db.commit()
    db.refresh(db_book)
    return db_book.to_schema()


@router.get("/", response_model=List[BookSchema])
def list_books(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    books = db.query(Book).offset(skip).limit(limit).all()
    return [b.to_schema() for b in books]


@router.get("/{book_id}", response_model=BookSchema)
def get_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book.to_schema()


@router.put("/{book_id}", response_model=BookSchema)
def update_book(book_id: int, payload: BookSchema, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    for field, value in payload.model_dump().items():
        if field == "id":
            continue
        setattr(book, field, value)
    db.commit()
    db.refresh(book)
    return book.to_schema()


@router.delete("/{book_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_book(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    db.delete(book)
    db.commit()
    return None

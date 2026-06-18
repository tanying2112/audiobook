"""FastAPI router for ``Paragraph`` CRUD operations (legacy API)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..models.legacy import LegacyParagraph as Paragraph
from ..schemas.legacy import Paragraph as ParagraphSchema
from .dependencies import get_db

router = APIRouter(prefix="/paragraphs", tags=["paragraphs"])


@router.post("/", response_model=ParagraphSchema, status_code=status.HTTP_201_CREATED)
def create_paragraph(paragraph: ParagraphSchema, db: Session = Depends(get_db)):
    db_par = Paragraph(**paragraph.model_dump())
    db.add(db_par)
    db.commit()
    db.refresh(db_par)
    return db_par.to_schema()


@router.get("/", response_model=List[ParagraphSchema])
def list_paragraphs(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(Paragraph).offset(skip).limit(limit).all()
    return [p.to_schema() for p in items]


@router.get("/{paragraph_id}", response_model=ParagraphSchema)
def get_paragraph(paragraph_id: int, db: Session = Depends(get_db)):
    p = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paragraph not found")
    return p.to_schema()


@router.put("/{paragraph_id}", response_model=ParagraphSchema)
def update_paragraph(
    paragraph_id: int, payload: ParagraphSchema, db: Session = Depends(get_db)
):
    p = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paragraph not found")
    for field, value in payload.model_dump().items():
        setattr(p, field, value)
    db.commit()
    db.refresh(p)
    return p.to_schema()


@router.delete("/{paragraph_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_paragraph(paragraph_id: int, db: Session = Depends(get_db)):
    p = db.query(Paragraph).filter(Paragraph.id == paragraph_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Paragraph not found")
    db.delete(p)
    db.commit()
    return None

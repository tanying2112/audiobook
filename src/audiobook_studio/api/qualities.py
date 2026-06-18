"""FastAPI router for ``Quality`` CRUD operations (legacy API)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..models.legacy import LegacyQuality as Quality
from ..schemas.legacy import Quality as QualitySchema
from .dependencies import get_db

router = APIRouter(prefix="/qualities", tags=["qualities"])


@router.post("/", response_model=QualitySchema, status_code=status.HTTP_201_CREATED)
def create_quality(item: QualitySchema, db: Session = Depends(get_db)):
    db_item = Quality(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item.to_schema()


@router.get("/", response_model=List[QualitySchema])
def list_qualities(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(Quality).offset(skip).limit(limit).all()
    return [i.to_schema() for i in items]


@router.get("/{quality_id}", response_model=QualitySchema)
def get_quality(quality_id: int, db: Session = Depends(get_db)):
    i = db.query(Quality).filter(Quality.id == quality_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Quality not found")
    return i.to_schema()


@router.put("/{quality_id}", response_model=QualitySchema)
def update_quality(
    quality_id: int, payload: QualitySchema, db: Session = Depends(get_db)
):
    i = db.query(Quality).filter(Quality.id == quality_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Quality not found")
    for field, value in payload.model_dump().items():
        setattr(i, field, value)
    db.commit()
    db.refresh(i)
    return i.to_schema()


@router.delete("/{quality_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quality(quality_id: int, db: Session = Depends(get_db)):
    i = db.query(Quality).filter(Quality.id == quality_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Quality not found")
    db.delete(i)
    db.commit()
    return None

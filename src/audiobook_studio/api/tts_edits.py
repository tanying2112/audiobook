"""FastAPI router for ``TTSEdit`` CRUD operations (legacy API)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..models.legacy import LegacyTTSEdit as TTSEdit
from ..schemas.legacy import TTSEdit as TTSEditSchema
from .dependencies import get_db

router = APIRouter(prefix="/tts_edits", tags=["tts_edits"])


@router.post("/", response_model=TTSEditSchema, status_code=status.HTTP_201_CREATED)
def create_tts_edit(edit: TTSEditSchema, db: Session = Depends(get_db)):
    db_edit = TTSEdit(**edit.model_dump())
    db.add(db_edit)
    db.commit()
    db.refresh(db_edit)
    return db_edit.to_schema()


@router.get("/", response_model=List[TTSEditSchema])
def list_tts_edits(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(TTSEdit).offset(skip).limit(limit).all()
    return [e.to_schema() for e in items]


@router.get("/{edit_id}", response_model=TTSEditSchema)
def get_tts_edit(edit_id: int, db: Session = Depends(get_db)):
    e = db.query(TTSEdit).filter(TTSEdit.id == edit_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="TTSEdit not found")
    return e.to_schema()


@router.put("/{edit_id}", response_model=TTSEditSchema)
def update_tts_edit(edit_id: int, payload: TTSEditSchema, db: Session = Depends(get_db)):
    e = db.query(TTSEdit).filter(TTSEdit.id == edit_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="TTSEdit not found")
    for field, value in payload.model_dump().items():
        if field in {"id", "paragraph_id"}:
            continue
        setattr(e, field, value)
    db.commit()
    db.refresh(e)
    return e.to_schema()


@router.delete("/{edit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tts_edit(edit_id: int, db: Session = Depends(get_db)):
    e = db.query(TTSEdit).filter(TTSEdit.id == edit_id).first()
    if not e:
        raise HTTPException(status_code=404, detail="TTSEdit not found")
    db.delete(e)
    db.commit()
    return None

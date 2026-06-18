"""FastAPI router for ``Routing`` CRUD operations (legacy API)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..models.legacy import LegacyRouting as Routing
from ..schemas.legacy import Routing as RoutingSchema
from .dependencies import get_db

router = APIRouter(prefix="/routings", tags=["routings"])


@router.post("/", response_model=RoutingSchema, status_code=status.HTTP_201_CREATED)
def create_routing(item: RoutingSchema, db: Session = Depends(get_db)):
    db_item = Routing(**item.model_dump())
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item.to_schema()


@router.get("/", response_model=List[RoutingSchema])
def list_routings(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(Routing).offset(skip).limit(limit).all()
    return [i.to_schema() for i in items]


@router.get("/{routing_id}", response_model=RoutingSchema)
def get_routing(routing_id: int, db: Session = Depends(get_db)):
    i = db.query(Routing).filter(Routing.id == routing_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Routing not found")
    return i.to_schema()


@router.put("/{routing_id}", response_model=RoutingSchema)
def update_routing(
    routing_id: int, payload: RoutingSchema, db: Session = Depends(get_db)
):
    i = db.query(Routing).filter(Routing.id == routing_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Routing not found")
    for field, value in payload.model_dump().items():
        if field in {"id", "paragraph_id"}:
            continue
        setattr(i, field, value)
    db.commit()
    db.refresh(i)
    return i.to_schema()


@router.delete("/{routing_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_routing(routing_id: int, db: Session = Depends(get_db)):
    i = db.query(Routing).filter(Routing.id == routing_id).first()
    if not i:
        raise HTTPException(status_code=404, detail="Routing not found")
    db.delete(i)
    db.commit()
    return None

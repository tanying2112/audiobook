"""FastAPI router for ``Routing`` CRUD operations (async SQLAlchemy 2.0)."""

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.legacy import LegacyRouting as Routing
from ..schemas.legacy import Routing as RoutingSchema
from .dependencies import get_async_db

router = APIRouter(prefix="/routings", tags=["routings"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────


class RoutingCreate(BaseModel):
    """Schema for creating a new Routing."""

    paragraph_id: int
    voice: str
    confidence: float = 0.9


class RoutingUpdate(BaseModel):
    """Schema for updating a Routing."""

    voice: str | None = None
    confidence: float | None = None


class RoutingOut(RoutingSchema):
    """Routing response schema with ORM config."""

    model_config = ConfigDict(from_attributes=True)


# ── Routing CRUD ─────────────────────────────────────────────────────────────


@router.post("/", response_model=RoutingOut, status_code=status.HTTP_201_CREATED)
async def create_routing(payload: RoutingCreate, db: AsyncSession = Depends(get_async_db)):
    """Create a new routing."""
    db_item = Routing(**payload.model_dump())
    db.add(db_item)
    await db.commit()
    await db.refresh(db_item)
    return db_item


@router.get("/", response_model=List[RoutingOut])
async def list_routings(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_async_db)):
    """List all routings."""
    result = await db.execute(select(Routing).offset(skip).limit(limit))
    items = result.scalars().all()
    return items


@router.get("/{routing_id}", response_model=RoutingOut)
async def get_routing(routing_id: int, db: AsyncSession = Depends(get_async_db)):
    """Get a routing by ID."""
    result = await db.execute(select(Routing).where(Routing.id == routing_id))
    i = result.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Routing not found")
    return i


@router.put("/{routing_id}", response_model=RoutingOut)
async def update_routing(routing_id: int, payload: RoutingUpdate, db: AsyncSession = Depends(get_async_db)):
    """Update a routing."""
    result = await db.execute(select(Routing).where(Routing.id == routing_id))
    i = result.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Routing not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field in {"id", "paragraph_id"}:
            continue
        setattr(i, field, value)
    await db.commit()
    await db.refresh(i)
    return i


@router.delete("/{routing_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_routing(routing_id: int, db: AsyncSession = Depends(get_async_db)):
    """Delete a routing."""
    result = await db.execute(select(Routing).where(Routing.id == routing_id))
    i = result.scalar_one_or_none()
    if not i:
        raise HTTPException(status_code=404, detail="Routing not found")
    await db.delete(i)
    await db.commit()
    return None

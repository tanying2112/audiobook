"""FastAPI router for ``Character`` CRUD (角色声音绑定管理).

Provides character management endpoints:
- ``/api/projects/{project_id}/characters`` — 角色列表和创建
- ``/api/projects/{project_id}/characters/{character_id}`` — 角色详情、更新、删除
- ``/api/voice-mapping`` — 获取声音映射配置
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, status

from ..exceptions import DomainError
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Character, Project
from .dependencies import get_async_db

# Use UnifiedConfig for centralized configuration loading
from ..config.unified import get_unified_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/characters", tags=["characters"])

# Load voice mapping configuration
VOICE_MAPPING_CACHE: Optional[Dict[str, Any]] = None


def load_voice_mapping() -> Dict[str, Any]:
    """Load voice mapping configuration from YAML file via UnifiedConfig."""
    global VOICE_MAPPING_CACHE
    if VOICE_MAPPING_CACHE is None:
        try:
            unified = get_unified_config()
            VOICE_MAPPING_CACHE = unified.load_yaml_config("voice_mapping") or {}
        except Exception as e:
            logger.warning(f"Failed to load voice mapping config: {e}")
            VOICE_MAPPING_CACHE = {}
    return VOICE_MAPPING_CACHE


# ── Pydantic schemas for API responses ────────────────────────────────────────


class CharacterBase(BaseModel):
    canonical_name: str
    aliases: Optional[List[str]] = []
    gender: Optional[str] = None
    age_range: Optional[str] = None
    suggested_voice_id: Optional[str] = None
    sample_quote: Optional[str] = None


class CharacterCreate(CharacterBase):
    pass


class CharacterUpdate(BaseModel):
    canonical_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    gender: Optional[str] = None
    age_range: Optional[str] = None
    suggested_voice_id: Optional[str] = None
    sample_quote: Optional[str] = None


class CharacterResponse(CharacterBase):
    id: int
    project_id: int

    model_config = ConfigDict(from_attributes=True)


class VoiceMappingResponse(BaseModel):
    voice_mapping: Dict[str, Any]
    voice_mapping_en: Dict[str, Any]


# ── API Endpoints ────────────────────────────────────────────────────────────


@router.get("", response_model=List[CharacterResponse])
async def fetch_characters(
    project_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """获取项目下的所有角色."""
    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise DomainError(
            message="Project not found",
            error_code="NOT_FOUND",
            stage="characters",
            context={"project_id": project_id},
        )

    result = await db.execute(select(Character).where(Character.project_id == project_id))
    characters = result.scalars().all()
    return characters


@router.post("", response_model=CharacterResponse, status_code=status.HTTP_201_CREATED)
async def create_character(
    project_id: int,
    character: CharacterCreate,
    db: AsyncSession = Depends(get_async_db),
):
    """创建新角色."""
    # Verify project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise DomainError(
            message="Project not found",
            error_code="NOT_FOUND",
            stage="characters",
            context={"project_id": project_id},
        )

    # Check for duplicate name within the same project
    result = await db.execute(
        select(Character).where(
            Character.project_id == project_id,
            Character.canonical_name == character.canonical_name,
        )
    )
    if result.scalar_one_or_none():
        raise DomainError(
            message="Character with this name already exists in the project",
            error_code="DUPLICATE_NAME",
            stage="characters",
            context={"project_id": project_id, "canonical_name": character.canonical_name},
        )

    db_character = Character(**character.model_dump(), project_id=project_id)
    db.add(db_character)
    await db.commit()
    await db.refresh(db_character)
    return db_character


@router.get("/voice-mapping", response_model=VoiceMappingResponse)
async def get_voice_mapping(project_id: int):
    """获取声音映射配置 (全局配置，不依赖项目)."""
    voice_mapping = load_voice_mapping()
    return VoiceMappingResponse(
        voice_mapping=voice_mapping.get("voice_mapping", {}),
        voice_mapping_en=voice_mapping.get("voice_mapping_en", {}),
    )


# Note: The /voice-mapping endpoint is under /projects/{project_id}/characters/voice-mapping
# due to the router prefix. For a global endpoint, consider a separate router.
# This is kept for backward compatibility.


@router.get("/{character_id}", response_model=CharacterResponse)
async def fetch_character(
    project_id: int,
    character_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """获取单个角色详情."""
    result = await db.execute(
        select(Character).where(Character.id == character_id, Character.project_id == project_id)
    )
    character = result.scalar_one_or_none()
    if not character:
        raise DomainError(
            message="Character not found",
            error_code="NOT_FOUND",
            stage="characters",
            context={"project_id": project_id, "character_id": character_id},
        )
    return character


@router.patch("/{character_id}", response_model=CharacterResponse)
async def update_character(
    project_id: int,
    character_id: int,
    character: CharacterUpdate,
    db: AsyncSession = Depends(get_async_db),
):
    """更新角色信息."""
    result = await db.execute(
        select(Character).where(Character.id == character_id, Character.project_id == project_id)
    )
    db_character = result.scalar_one_or_none()
    if not db_character:
        raise DomainError(
            message="Character not found",
            error_code="NOT_FOUND",
            stage="characters",
            context={"project_id": project_id, "character_id": character_id},
        )

    update_data = character.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_character, field, value)

    await db.commit()
    await db.refresh(db_character)
    return db_character


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character(
    project_id: int,
    character_id: int,
    db: AsyncSession = Depends(get_async_db),
):
    """删除角色."""
    result = await db.execute(
        select(Character).where(Character.id == character_id, Character.project_id == project_id)
    )
    character = result.scalar_one_or_none()
    if not character:
        raise DomainError(
            message="Character not found",
            error_code="NOT_FOUND",
            stage="characters",
            context={"project_id": project_id, "character_id": character_id},
        )

    await db.delete(character)
    await db.commit()


# ── Voice Mapping Endpoint (no project_id in path) ───────────────────────────




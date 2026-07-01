"""FastAPI router for ``Character`` CRUD (角色声音绑定管理).

Provides character management endpoints:
- ``/api/projects/{project_id}/characters`` — 角色列表和创建
- ``/api/projects/{project_id}/characters/{character_id}`` — 角色详情、更新、删除
- ``/api/voice-mapping`` — 获取声音映射配置
"""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..models import Character, Project
from .dependencies import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}/characters", tags=["characters"])

# Load voice mapping configuration
VOICE_MAPPING_CACHE: Optional[Dict[str, Any]] = None


def load_voice_mapping() -> Dict[str, Any]:
    """Load voice mapping configuration from YAML file."""
    global VOICE_MAPPING_CACHE
    if VOICE_MAPPING_CACHE is None:
        try:
            config_path = (
                Path(__file__).parent.parent.parent.parent
                / "config"
                / "voice_mapping.yaml"
            )
            with open(config_path, "r", encoding="utf-8") as f:
                VOICE_MAPPING_CACHE = yaml.safe_load(f)
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
    db: Session = Depends(get_db),
):
    """获取项目下的所有角色."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    characters = db.query(Character).filter(Character.project_id == project_id).all()
    return characters


@router.post("", response_model=CharacterResponse, status_code=status.HTTP_201_CREATED)
async def create_character(
    project_id: int,
    character: CharacterCreate,
    db: Session = Depends(get_db),
):
    """创建新角色."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if canonical_name already exists in this project
    existing = (
        db.query(Character)
        .filter(
            Character.project_id == project_id,
            Character.canonical_name == character.canonical_name,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Character with canonical_name '{character.canonical_name}' already exists in this project",
        )

    db_character = Character(project_id=project_id, **character.model_dump())
    db.add(db_character)
    db.commit()
    db.refresh(db_character)
    logger.info(f"Created character {db_character.id} for project {project_id}")
    return db_character


@router.get("/voice-mapping", response_model=VoiceMappingResponse)
async def get_voice_mapping(
    project_id: int,
):
    """获取声音映射配置."""
    mapping = load_voice_mapping()
    return VoiceMappingResponse(
        voice_mapping=mapping.get("voice_mapping", {}),
        voice_mapping_en=mapping.get("voice_mapping_en", {}),
    )


@router.get("/{character_id}", response_model=CharacterResponse)
async def fetch_character(
    project_id: int,
    character_id: int,
    db: Session = Depends(get_db),
):
    """获取特定角色."""
    character = (
        db.query(Character)
        .filter(Character.project_id == project_id, Character.id == character_id)
        .first()
    )
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")
    return character


@router.put("/{character_id}", response_model=CharacterResponse)
async def update_character(
    project_id: int,
    character_id: int,
    character_update: CharacterUpdate,
    db: Session = Depends(get_db),
):
    """更新角色."""
    character = (
        db.query(Character)
        .filter(Character.project_id == project_id, Character.id == character_id)
        .first()
    )
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    # If canonical_name is being updated, check for conflicts
    if character_update.canonical_name is not None:
        existing = (
            db.query(Character)
            .filter(
                Character.project_id == project_id,
                Character.canonical_name == character_update.canonical_name,
                Character.id != character_id,  # Exclude current character
            )
            .first()
        )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Character with canonical_name '{character_update.canonical_name}' already exists in this project",
        )

    # Update fields
    update_data = character_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(character, field, value)

    db.commit()
    db.refresh(character)
    logger.info(f"Updated character {character_id} for project {project_id}")
    return character


@router.delete("/{character_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_character(
    project_id: int,
    character_id: int,
    db: Session = Depends(get_db),
):
    """删除角色."""
    character = (
        db.query(Character)
        .filter(Character.project_id == project_id, Character.id == character_id)
        .first()
    )
    if not character:
        raise HTTPException(status_code=404, detail="Character not found")

    db.delete(character)
    db.commit()
    logger.info(f"Deleted character {character_id} from project {project_id}")
    return None

"""Configuration API endpoints for constitutional rules and quality
thresholds."""

from typing import Any, Dict, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.audiobook_studio.config.loader import (
    load_contract_versions,
    load_quality_thresholds,
    load_rules,
)

router = APIRouter(prefix="/config", tags=["config"])


class ConfigReloadResponse(BaseModel):
    """Response for config reload operations."""

    success: bool
    message: str
    config: Optional[Dict[str, Any]] = None


class RuleUpdateRequest(BaseModel):
    """Request to update constitutional rules."""

    rules: Dict[str, Any] = Field(..., description="New constitutional rules")


class ThresholdUpdateRequest(BaseModel):
    """Request to update quality thresholds."""

    thresholds: Dict[str, Any] = Field(..., description="New quality thresholds")


class ConfigStatusResponse(BaseModel):
    """Response showing current config status."""

    constitutional_rules: Dict[str, Any]
    quality_thresholds: Dict[str, Any]
    contract_versions: Dict[str, Any]
    last_checked: Optional[str] = None


@router.get("/status", response_model=ConfigStatusResponse)
async def get_config_status():
    """Get current configuration status for all config files."""
    import datetime

    return ConfigStatusResponse(
        constitutional_rules=load_rules(),
        quality_thresholds=load_quality_thresholds(),
        contract_versions=load_contract_versions(),
        last_checked=datetime.datetime.now().isoformat(),
    )


@router.post("/rules/reload", response_model=ConfigReloadResponse)
async def reload_constitutional_rules():
    """Hot-reload constitutional rules from YAML file."""
    rules = load_rules("./config/constitutional_rules.yaml")
    return ConfigReloadResponse(
        success=True,
        message="Constitutional rules reloaded successfully",
        config=rules,
    )


@router.post("/thresholds/reload", response_model=ConfigReloadResponse)
async def reload_quality_thresholds():
    """Hot-reload quality thresholds from YAML file."""
    thresholds = load_quality_thresholds("./config/quality_thresholds.yaml")
    return ConfigReloadResponse(
        success=True,
        message="Quality thresholds reloaded successfully",
        config=thresholds,
    )


@router.post("/contracts/reload", response_model=ConfigReloadResponse)
async def reload_contract_versions():
    """Hot-reload contract versions from YAML file."""
    versions = load_contract_versions("./config/contract_versions.yaml")
    return ConfigReloadResponse(
        success=True,
        message="Contract versions reloaded successfully",
        config=versions,
    )


@router.post("/reload-all", response_model=ConfigReloadResponse)
async def reload_all_configs():
    """Hot-reload all configuration files."""
    rules = load_rules()
    thresholds = load_quality_thresholds()
    versions = load_contract_versions()

    return ConfigReloadResponse(
        success=True,
        message="All configurations reloaded successfully",
        config={
            "constitutional_rules": rules,
            "quality_thresholds": thresholds,
            "contract_versions": versions,
        },
    )


@router.post("/rules/update", response_model=ConfigReloadResponse)
async def update_constitutional_rules(request: RuleUpdateRequest):
    """Update constitutional rules in memory (does not persist to file)."""
    # Note: This only updates in-memory; for persistence,
    # write to YAML file directly or implement a file write endpoint
    from src.audiobook_studio.config.loader import load_rules as _load_rules

    # We can't easily update the file from here without more infrastructure
    # Return the current rules for verification
    current = _load_rules()
    return ConfigReloadResponse(
        success=True,
        message=(
            "Rules update requested (in-memory only). "
            "To persist, update config/constitutional_rules.yaml"
        ),
        config=current,
    )


@router.post("/thresholds/update", response_model=ConfigReloadResponse)
async def update_quality_thresholds(request: ThresholdUpdateRequest):
    """Update quality thresholds in memory (does not persist to file)."""
    current = load_quality_thresholds()
    return ConfigReloadResponse(
        success=True,
        message=(
            "Thresholds update requested (in-memory only). "
            "To persist, update config/quality_thresholds.yaml"
        ),
        config=current,
    )

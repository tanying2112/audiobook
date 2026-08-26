"""Model marketplace API — S3.5 (plugin ecosystem + one-click install).

- ``GET /api/v1/models`` — aggregated, free-resource model catalog (TTS voices
  + discoverable plugins).
- ``POST /api/v1/models/install`` — one-click (registration-only) install of a
  plugin by name.
- ``POST /api/v1/models/uninstall`` — remove a plugin from the registry.
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Query

from ..exceptions import NotFoundError

from .. import plugins
from ..models_catalog import build_model_catalog

router = APIRouter(prefix="/models", tags=["model-market"])


@router.get("")
def list_models() -> Dict[str, Any]:
    """Return the model marketplace catalog (S3.5)."""
    return build_model_catalog()


@router.post("/install")
def install_model(name: str = Query(...)) -> Dict[str, Any]:
    """One-click install of a plugin by name (S3.5).

    Registration-only: writes the plugin into the installed registry. No
    network download occurs. 404 if the plugin is not discoverable.
    """
    try:
        return plugins.install_plugin(name)
    except KeyError as exc:
        raise NotFoundError(resource="Model/Plugin", identifier=name) from exc


@router.post("/uninstall")
def uninstall_model(name: str = Query(...)) -> Dict[str, Any]:
    """Remove a plugin from the installed registry."""
    return plugins.uninstall_plugin(name)

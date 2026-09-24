"""Admin endpoints (PERF-001: warmup, maintenance).

Provides a POST /admin/warmup endpoint to pre-load TTS models before
serving traffic, and other administrative operations.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from starlette.background import BackgroundTasks

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


class HardwareProfileSwitchRequest(BaseModel):
    """Body for switching the active hardware profile at runtime."""

    profile: str


@router.post("/admin/warmup")
async def warmup_engines(background_tasks: BackgroundTasks):
    """Pre-initialize all registered TTS engines in the background.

    Returns immediately with {"status": "warming_up"} and schedules
    engine initialization in a background task so the response is
    not blocked by model loading (2-5s for ONNX models).
    """

    async def _warmup() -> None:
        from ..di import get_app_container
        from ..tts.engine import EngineRegistry

        container = get_app_container()
        registry = container.get(EngineRegistry)
        if registry is None:
            logger.warning("No EngineRegistry in DI container, skipping warmup")
            return
        results = await registry.warmup()
        ok = sum(1 for v in results.values() if v)
        failed = len(results) - ok
        logger.info(f"Warmup complete: {ok} loaded, {failed} failed — {results}")

    background_tasks.add_task(_warmup)
    return {"status": "warming_up"}


@router.post("/admin/hardware-profile/reload")
async def reload_hardware_profile_endpoint():
    """Hot-reload hardware profile configuration from disk.

    Re-reads ``hardware_profile.yaml`` and refreshes the global singleton in
    place, so running pipelines immediately pick up new settings without a
    process restart.
    """
    from ..config.hardware_profile import reload_hardware_profile

    profile = reload_hardware_profile()
    return {"status": "reloaded", "active_profile": profile.active_profile}


@router.post("/admin/hardware-profile/switch")
async def switch_hardware_profile_endpoint(payload: HardwareProfileSwitchRequest):
    """Hot-switch the active hardware profile (e.g. potato / cloud_hybrid / pro_studio).

    Useful for runtime hardware-tier changes (e.g. attaching a GPU) without a
    restart. The running pipeline picks up the new profile on its next read.
    """
    from ..config.hardware_profile import get_hardware_profile

    profile = get_hardware_profile()
    try:
        profile.set_active_profile(payload.profile)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "switched", "active_profile": profile.active_profile}

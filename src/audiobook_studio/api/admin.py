"""Admin endpoints (PERF-001: warmup, maintenance).

Provides a POST /admin/warmup endpoint to pre-load TTS models before
serving traffic, and other administrative operations.
"""

import logging

from fastapi import APIRouter
from starlette.background import BackgroundTasks

logger = logging.getLogger(__name__)

router = APIRouter(tags=["admin"])


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
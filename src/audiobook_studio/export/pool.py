"""Ffmpeg subprocess concurrency control (PERF-004).

Provides a global asyncio.Semaphore to bound concurrent ffmpeg processes,
preventing CPU/memory spikes and OOM kills during parallel exports.
"""

import asyncio
import logging
import os
import subprocess
from typing import Sequence

logger = logging.getLogger(__name__)

_semaphore: asyncio.Semaphore | None = None


def get_ffmpeg_semaphore() -> asyncio.Semaphore:
    """Return the global ffmpeg concurrency semaphore.

    Concurrency is derived from FFMPEG_CONCURRENCY env/setting, defaulting
    to max(1, cpu_count - 1) so one core stays free for the app.
    """
    global _semaphore
    if _semaphore is None:
        from ..config import get_settings

        s = get_settings()
        concurrency = s.FFMPEG_CONCURRENCY or max(1, (os.cpu_count() or 2) - 1)
        _semaphore = asyncio.Semaphore(concurrency)
        logger.info(f"ffmpeg semaphore initialised: max_concurrency={concurrency}")
    return _semaphore


async def run_ffmpeg(args: Sequence[str], **kwargs) -> subprocess.CompletedProcess:
    """Run ffmpeg under the global concurrency semaphore.

    Wraps subprocess.run in asyncio.to_thread so the event loop stays responsive,
    and acquires the semaphore before spawning the process to bound parallelism.
    """
    sem = get_ffmpeg_semaphore()
    async with sem:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: subprocess.run(args, **kwargs))
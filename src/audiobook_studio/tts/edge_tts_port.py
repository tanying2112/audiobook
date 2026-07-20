"""Edge-TTS Port Implementation.

Wraps EdgeTTSEngine to implement the RemoteTTSPort contract for cloud TTS synthesis.
"""

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from .edge_tts_engine import EdgeTTSEngine, create_edge_tts_engine
from .port import RemoteTTSPort, TTSStatus, TTSTaskPayload, TTSTaskResult, TTSTaskStatus

logger = logging.getLogger(__name__)


class EdgeTTSPort(RemoteTTSPort):
    """Cloud-based Edge-TTS implementation of RemoteTTSPort.

    Uses direct synthesis (not async queue) since Edge-TTS is fast enough
    for real-time synthesis without needing a separate scheduling layer.
    """

    def __init__(
        self,
        output_dir: str = "./output",
        engine: Optional[EdgeTTSEngine] = None,
        max_concurrent: int = 4,
        mock_mode: bool = False,
        **kwargs,
    ):
        """
        Args:
            output_dir: Directory to save audio files
            engine: Pre-initialized EdgeTTSEngine (will create if None)
            max_concurrent: Max concurrent synthesis tasks
            mock_mode: If True, use mock engine for testing
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._engine = engine
        self._mock_mode = mock_mode
        self._engine_kwargs = kwargs
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def _get_engine(self) -> EdgeTTSEngine:
        """Lazy-initialize engine."""
        if self._engine is None:
            self._engine = await create_edge_tts_engine(mock_mode=self._mock_mode, **self._engine_kwargs)
        return self._engine

    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        """Submit a TTS synthesis task."""
        async with self._lock:
            if task_id in self._tasks:
                logger.warning(f"Task {task_id} already exists, rejecting")
                return False

            self._tasks[task_id] = {
                "task_id": task_id,
                "payload": payload,
                "status": TTSStatus.PENDING,
                "created_at": datetime.now(UTC).isoformat(),
                "started_at": None,
                "completed_at": None,
                "progress": 0.0,
                "error_message": None,
            }
            # Start synthesis in background
            asyncio.create_task(self._synthesize_task(task_id, payload))
            return True

    async def _synthesize_task(self, task_id: str, payload: TTSTaskPayload) -> None:
        """Internal task to perform synthesis."""
        async with self._semaphore:
            async with self._lock:
                self._tasks[task_id]["status"] = TTSStatus.RUNNING
                self._tasks[task_id]["started_at"] = datetime.now(UTC).isoformat()
                self._tasks[task_id]["progress"] = 0.1

            try:
                engine = await self._get_engine()

                # Build output path
                voice_id = payload.voice_anchor.voice_id
                output_path = self.output_dir / f"{task_id}_{voice_id}.mp3"

                # Map prosody
                prosody = None
                if payload.prosody:
                    prosody = {
                        "rate": payload.prosody.rate,
                        "pitch": payload.prosody.pitch,
                        "volume": payload.prosody.volume,
                        "emotion": payload.prosody.emotion,
                    }

                # Update progress
                async with self._lock:
                    self._tasks[task_id]["progress"] = 0.5

                # Synthesize
                result = await engine.synthesize(
                    text=payload.text,
                    voice_id=voice_id,
                    output_path=output_path,
                    prosody=prosody,
                )

                # Update task with result
                async with self._lock:
                    self._tasks[task_id].update(
                        {
                            "status": TTSStatus.DONE,
                            "completed_at": datetime.now(UTC).isoformat(),
                            "progress": 1.0,
                            "audio_path": result.audio_path,
                            "duration_ms": result.duration_ms,
                            "engine": result.engine,
                            "text_hash": result.text_hash,
                        }
                    )

            except Exception as e:
                logger.error(f"EdgeTTS synthesis failed for task {task_id}: {e}")
                async with self._lock:
                    self._tasks[task_id].update(
                        {
                            "status": TTSStatus.FAILED,
                            "completed_at": datetime.now(UTC).isoformat(),
                            "error_message": str(e),
                        }
                    )

    async def get_status(self, task_id: str) -> Optional[TTSTaskStatus]:
        """Get current status of a task."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            return TTSTaskStatus(
                task_id=task_id,
                status=task["status"],
                progress=task.get("progress"),
                error_message=task.get("error_message"),
            )

    async def get_result(self, task_id: str) -> Optional[TTSTaskResult]:
        """Get final result of completed task."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            if task["status"] not in (TTSStatus.DONE, TTSStatus.FAILED):
                return None  # Not ready yet

            return TTSTaskResult(
                task_id=task_id,
                status=task["status"],
                audio_path=task.get("audio_path"),
                duration_ms=task.get("duration_ms"),
                error_message=task.get("error_message"),
                started_at=task.get("started_at"),
                completed_at=task.get("completed_at"),
            )

    async def cancel(self, task_id: str) -> bool:
        """Cancel a pending/running task."""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False

            if task["status"] in (TTSStatus.DONE, TTSStatus.FAILED):
                return False

            task["status"] = TTSStatus.FAILED
            task["error_message"] = "Cancelled by user"
            task["completed_at"] = datetime.now(UTC).isoformat()
            return True

    async def health_check(self) -> dict[str, Any]:
        """Health check for the port."""
        engine = await self._get_engine()
        return {
            "status": "healthy" if engine.is_available() else "unhealthy",
            "engine": "edge",
            "queue_size": len(self._tasks),
            "max_concurrent": self._semaphore._value,
        }

    async def close(self) -> None:
        """Close the port and cleanup."""
        if self._engine:
            await self._engine.cleanup()
        logger.info("EdgeTTSPort closed")


def create_edge_tts_port(
    output_dir: str = "./output",
    max_concurrent: int = 4,
    mock_mode: bool = False,
    **kwargs,
) -> EdgeTTSPort:
    """Factory to create EdgeTTSPort (synchronous factory - lazy init)."""
    return EdgeTTSPort(output_dir=output_dir, max_concurrent=max_concurrent, mock_mode=mock_mode, **kwargs)

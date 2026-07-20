"""Kokoro Port Implementation.

Wraps KokoroBackend to implement the RemoteTTSPort contract for local TTS synthesis.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from .kokoro_backend import KokoroBackend, create_kokoro_backend
from .port import RemoteTTSPort, TTSStatus, TTSTaskPayload, TTSTaskResult, TTSTaskStatus

logger = logging.getLogger(__name__)


class KokoroPort(RemoteTTSPort):
    """Local Kokoro ONNX implementation of RemoteTTSPort.

    Uses direct synthesis (not async queue) since Kokoro is fast enough
    for real-time synthesis without needing a separate scheduling layer.
    """

    def __init__(
        self,
        output_dir: str = "./output",
        backend: Optional[KokoroBackend] = None,
        max_concurrent: int = 2,
        **kwargs,
    ):
        """
        Args:
            output_dir: Directory to save audio files
            backend: Pre-initialized KokoroBackend (will create if None)
            max_concurrent: Max concurrent synthesis tasks
            **kwargs: Additional args passed to backend factory
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._backend = backend
        self._backend_kwargs = kwargs
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._tasks: dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def _get_backend(self) -> KokoroBackend:
        """Lazy-initialize backend."""
        if self._backend is None:
            self._backend = await create_kokoro_backend(**self._backend_kwargs)
        return self._backend

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
                backend = await self._get_backend()

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

                # Synthesize using Kokoro backend
                result = await backend.synthesize(
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
                            "voice_id": result.voice_id,
                            "text_hash": result.text_hash,
                        }
                    )

            except Exception as e:
                logger.error(f"Kokoro synthesis failed for task {task_id}: {e}")
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
        backend = await self._get_backend()
        return {
            "status": "healthy" if backend.is_available() else "unhealthy",
            "engine": "kokoro",
            "queue_size": len(self._tasks),
            "max_concurrent": self._semaphore._value,
        }

    async def close(self) -> None:
        """Close the port and cleanup."""
        if self._backend:
            await self._backend.cleanup()
        logger.info("KokoroPort closed")


def create_kokoro_port(
    output_dir: str = "./output",
    max_concurrent: int = 2,
    **kwargs,
) -> KokoroPort:
    """Factory to create KokoroPort (synchronous factory - lazy init)."""
    return KokoroPort(output_dir=output_dir, max_concurrent=max_concurrent, **kwargs)

"""Fake In-Memory Implementation of RemoteTTSPort.

Provides a fully functional in-memory implementation for testing and local development.
Simulates realistic async state transitions with configurable delays and failure modes.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from src.audiobook_studio.tts.port import (
    TTSTaskPayload,
    TTSTaskResult,
    TTSTaskStatus,
    TTSStatus,
    RemoteTTSPort,
)


@dataclass
class _TaskState:
    """Internal mutable task state."""

    task_id: str
    payload: TTSTaskPayload
    status: TTSStatus = TTSStatus.PENDING
    progress: float = 0.0
    error_message: Optional[str] = None
    audio_path: Optional[str] = None
    duration_ms: Optional[int] = None
    dnsmos_score: Optional[float] = None
    asr_wer: Optional[float] = None
    speaker_similarity: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    _cancel_requested: bool = False


class FakeRemoteTTSPort(RemoteTTSPort):
    """In-memory Fake implementation of RemoteTTSPort.

    Features:
    - Realistic async state transitions (PENDING -> RUNNING -> DONE/FAILED)
    - Configurable synthesis delay simulation
    - Configurable failure injection
    - Quality metrics simulation (DNSMOS, WER, Speaker Similarity)
    - Cancellation support
    - Health check with queue stats
    - Thread-safe for concurrent access

    Usage:
        port = FakeRemoteTTSPort(synthesis_delay=0.1, failure_rate=0.0)
        await port.submit("task-1", payload)
        status = await port.get_status("task-1")
        result = await port.get_result("task-1")
    """

    def __init__(
        self,
        synthesis_delay: float = 0.1,
        failure_rate: float = 0.0,
        failure_mode: Optional[Callable[[TTSTaskPayload], bool]] = None,
        quality_scores: Optional[dict[str, float]] = None,
        simulate_progress: bool = True,
    ):
        """
        Args:
            synthesis_delay: Base delay in seconds for synthesis simulation.
            failure_rate: Probability of random failure (0.0-1.0).
            failure_mode: Custom function(payload) -> bool to determine failure.
            quality_scores: Dict with keys 'dnsmos', 'wer', 'speaker_sim' for fixed scores.
            simulate_progress: Whether to simulate intermediate RUNNING progress.
        """
        if not 0.0 <= failure_rate <= 1.0:
            raise ValueError("failure_rate must be between 0.0 and 1.0")
        if synthesis_delay < 0:
            raise ValueError("synthesis_delay must be non-negative")

        self._synthesis_delay = synthesis_delay
        self._failure_rate = failure_rate
        self._failure_mode = failure_mode
        self._quality_scores = quality_scores or {
            "dnsmos": 4.2,
            "wer": 0.03,
            "speaker_sim": 0.95,
        }
        self._simulate_progress = simulate_progress

        self._tasks: dict[str, _TaskState] = {}
        self._lock = asyncio.Lock()
        self._background_tasks: set[asyncio.Task] = set()

    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        """Submit a TTS synthesis task (idempotent)."""
        async with self._lock:
            if task_id in self._tasks:
                return False  # Idempotent rejection

            # Validate payload
            if not payload.text or not payload.text.strip():
                raise ValueError("text must be non-empty")
            if not isinstance(payload.voice_anchor, type(payload.voice_anchor)):
                raise TypeError("voice_anchor must be TTSVoiceAnchor instance")

            # Create task state
            state = _TaskState(
                task_id=task_id,
                payload=payload,
                status=TTSStatus.PENDING,
            )
            self._tasks[task_id] = state

            # Start background processing
            task = asyncio.create_task(self._process_task(task_id))
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

            return True

    async def _process_task(self, task_id: str) -> None:
        """Background task processing with state transitions."""
        state = self._tasks.get(task_id)
        if not state:
            return

        try:
            # Transition to RUNNING
            async with self._lock:
                if state._cancel_requested:
                    state.status = TTSStatus.FAILED
                    state.error_message = "Cancelled before start"
                    state.completed_at = datetime.now(UTC).isoformat()
                    return
                state.status = TTSStatus.RUNNING
                state.started_at = datetime.now(UTC).isoformat()
                state.progress = 0.0

            # Simulate progress updates
            if self._simulate_progress and self._synthesis_delay > 0:
                steps = max(1, int(self._synthesis_delay / 0.05))
                for i in range(1, steps + 1):
                    await asyncio.sleep(self._synthesis_delay / steps)
                    async with self._lock:
                        if state._cancel_requested:
                            state.status = TTSStatus.FAILED
                            state.error_message = "Cancelled during synthesis"
                            state.completed_at = datetime.now(UTC).isoformat()
                            return
                        state.progress = i / steps
            else:
                await asyncio.sleep(self._synthesis_delay)

            # Check for cancellation before completion
            async with self._lock:
                if state._cancel_requested:
                    state.status = TTSStatus.FAILED
                    state.error_message = "Cancelled before completion"
                    state.completed_at = datetime.now(UTC).isoformat()
                    return

            # Determine success/failure
            should_fail = False
            if self._failure_mode:
                should_fail = self._failure_mode(state.payload)
            elif self._failure_rate > 0:
                import random

                should_fail = random.random() < self._failure_rate

            if should_fail:
                state.status = TTSStatus.FAILED
                state.error_message = "Synthesis failed (simulated)"
                state.completed_at = datetime.now(UTC).isoformat()
                return

            # Success - generate fake result
            state.status = TTSStatus.DONE
            # Create a local fake WAV file for testing
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / "fake_tts_output"
            temp_dir.mkdir(parents=True, exist_ok=True)
            local_path = temp_dir / f"{task_id}.wav"
            # Create a minimal valid WAV file (silence)
            import wave
            import struct
            with wave.open(str(local_path), 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2)
                wav_file.setframerate(16000)
                # Write 100ms of silence (1600 samples at 16kHz)
                silence = struct.pack('<h', 0) * 1600
                wav_file.writeframes(silence)
            state.audio_path = str(local_path)
            state.duration_ms = len(state.payload.text) * 50  # ~50ms per char
            state.progress = 1.0
            state.dnsmos_score = self._quality_scores.get("dnsmos")
            state.asr_wer = self._quality_scores.get("wer")
            state.speaker_similarity = self._quality_scores.get("speaker_sim")
            state.completed_at = datetime.now(UTC).isoformat()

        except Exception as e:
            async with self._lock:
                state.status = TTSStatus.FAILED
                state.error_message = f"Unexpected error: {e!s}"
                state.completed_at = datetime.now(UTC).isoformat()

    async def get_status(self, task_id: str) -> TTSTaskStatus:
        """Poll for task status (non-blocking)."""
        async with self._lock:
            state = self._tasks.get(task_id)
            if not state:
                return TTSTaskStatus(
                    task_id=task_id,
                    status=TTSStatus.PENDING,
                    error_message=f"Task {task_id} not found",
                )

            return TTSTaskStatus(
                task_id=state.task_id,
                status=state.status,
                progress=state.progress,
                error_message=state.error_message,
                dnsmos_score=state.dnsmos_score,
            )

    async def get_result(self, task_id: str) -> TTSTaskResult:
        """Retrieve full task result (only for terminal states)."""
        async with self._lock:
            state = self._tasks.get(task_id)
            if not state:
                raise KeyError(f"Task {task_id} not found")

            if state.status not in (TTSStatus.DONE, TTSStatus.FAILED):
                raise KeyError(f"Task {task_id} not yet terminal (status: {state.status.value})")

            return TTSTaskResult(
                task_id=state.task_id,
                status=state.status,
                audio_path=state.audio_path,
                duration_ms=state.duration_ms,
                error_message=state.error_message,
                dnsmos_score=state.dnsmos_score,
                asr_wer=state.asr_wer,
                speaker_similarity=state.speaker_similarity,
                started_at=state.started_at,
                completed_at=state.completed_at,
            )

    async def cancel(self, task_id: str) -> bool:
        """Request cancellation of a pending/running task."""
        async with self._lock:
            state = self._tasks.get(task_id)
            if not state:
                return False

            if state.status in (TTSStatus.DONE, TTSStatus.FAILED):
                return False

            state._cancel_requested = True
            return True

    async def health_check(self) -> dict[str, Any]:
        """Check scheduling layer health."""
        async with self._lock:
            pending = sum(1 for s in self._tasks.values() if s.status == TTSStatus.PENDING)
            running = sum(1 for s in self._tasks.values() if s.status == TTSStatus.RUNNING)
            done = sum(1 for s in self._tasks.values() if s.status == TTSStatus.DONE)
            failed = sum(1 for s in self._tasks.values() if s.status == TTSStatus.FAILED)

            return {
                "healthy": True,
                "latency_ms": self._synthesis_delay * 1000,
                "pending_count": pending,
                "running_count": running,
                "done_count": done,
                "failed_count": failed,
                "total_count": len(self._tasks),
            }

    async def close(self) -> None:
        """Release resources (cancel background tasks)."""
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
        self._background_tasks.clear()

    # Convenience methods for testing

    def get_task_state(self, task_id: str) -> Optional[_TaskState]:
        """Get internal task state for inspection (testing only)."""
        return self._tasks.get(task_id)

    def reset(self) -> None:
        """Reset all tasks (testing only)."""
        self._tasks.clear()
        for task in self._background_tasks:
            task.cancel()
        self._background_tasks.clear()


class MockRemoteTTSPort(RemoteTTSPort):
    """Mock implementation for unit testing with pytest-mock.

    Allows pre-programmed responses for submit/get_status/get_result.
    Does NOT simulate async state transitions - use FakeRemoteTTSPort for that.
    """

    def __init__(self):
        self._submit_return: bool = True
        self._submit_side_effect: Optional[Exception] = None
        self._status_return: Optional[TTSTaskStatus] = None
        self._result_return: Optional[TTSTaskResult] = None
        self._result_side_effect: Optional[Exception] = None
        self._cancel_return: bool = True
        self._health_return: dict[str, Any] = {"healthy": True, "latency_ms": 0.0}
        self._call_log: list[tuple[str, tuple, dict]] = []

    # Configuration methods for test setup

    def set_submit_return(self, value: bool) -> None:
        self._submit_return = value

    def set_submit_side_effect(self, exc: Exception) -> None:
        self._submit_side_effect = exc

    def set_status_return(self, status: TTSTaskStatus) -> None:
        self._status_return = status

    def set_result_return(self, result: TTSTaskResult) -> None:
        self._result_return = result

    def set_result_side_effect(self, exc: Exception) -> None:
        self._result_side_effect = exc

    def set_cancel_return(self, value: bool) -> None:
        self._cancel_return = value

    def set_health_return(self, health: dict[str, Any]) -> None:
        self._health_return = health

    # Port methods

    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        self._call_log.append(("submit", (task_id, payload), {}))
        if self._submit_side_effect:
            raise self._submit_side_effect
        return self._submit_return

    async def get_status(self, task_id: str) -> TTSTaskStatus:
        self._call_log.append(("get_status", (task_id,), {}))
        if self._status_return:
            return self._status_return
        return TTSTaskStatus(task_id=task_id, status=TTSStatus.PENDING)

    async def get_result(self, task_id: str) -> TTSTaskResult:
        self._call_log.append(("get_result", (task_id,), {}))
        if self._result_side_effect:
            raise self._result_side_effect
        if self._result_return:
            return self._result_return
        raise KeyError(f"Task {task_id} not found")

    async def cancel(self, task_id: str) -> bool:
        self._call_log.append(("cancel", (task_id,), {}))
        return self._cancel_return

    async def health_check(self) -> dict[str, Any]:
        self._call_log.append(("health_check", (), {}))
        return self._health_return

    async def close(self) -> None:
        self._call_log.append(("close", (), {}))

    # Inspection for tests

    def get_call_log(self) -> list[tuple[str, tuple, dict]]:
        return self._call_log.copy()

    def reset_call_log(self) -> None:
        self._call_log.clear()
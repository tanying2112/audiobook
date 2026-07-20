"""Remote TTS Port Contract.

Defines the abstract interface between the internal orchestration layer (Celery)
and the external Hermes scheduling layer (Redis + R2). This contract ensures
complete decoupling: the internal pipeline never knows about Redis/R2 internals.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class TTSStatus(str, enum.Enum):
    """Task status in the Hermes scheduling layer.

    Strictly controlled state machine: PENDING -> RUNNING -> DONE/FAILED
    No backward transitions allowed except FAILED -> PENDING (manual retry).
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class TTSVoiceAnchor:
    """Voice anchor specification for TTS synthesis.

    Immutable reference to a pre-trained voice profile.
    """

    voice_id: str
    speaker_name: Optional[str] = None
    language: str = "zh-CN"
    reference_audio_path: Optional[str] = None

    def __post_init__(self):
        if not self.voice_id or not self.voice_id.strip():
            raise ValueError("voice_id must be non-empty")


@dataclass(frozen=True)
class TTSProsody:
    """Prosody controls for TTS synthesis.

    All values are hints; actual behavior depends on the backend engine.
    """

    rate: float = 1.0  # Speech rate multiplier (0.5-2.0)
    pitch: float = 0.0  # Pitch shift in semitones (-12 to +12)
    volume: float = 0.0  # Volume gain in dB (-20 to +20)
    emotion: Optional[str] = None  # Emotional tag (happy, sad, neutral, etc.)


@dataclass(frozen=True)
class TTSTaskPayload:
    """Payload submitted to the Hermes layer for TTS synthesis.

    Schema is strictly versioned. Any breaking change requires a new Port version.
    """

    text: str
    voice_anchor: TTSVoiceAnchor
    prosody: Optional[TTSProsody] = None
    # Future: quality_requirements, streaming_callback, etc.
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.text or not self.text.strip():
            raise ValueError("text must be non-empty")
        if not isinstance(self.voice_anchor, TTSVoiceAnchor):
            raise TypeError("voice_anchor must be TTSVoiceAnchor instance")


@dataclass(frozen=True)
class TTSTaskResult:
    """Result returned by the Hermes layer when task completes.

    The `dnsmos_score` and other quality metrics are OPTIONAL and populated
    asynchronously by the downstream Quality Stage. Port consumers must NOT
    block waiting for these fields.
    """

    task_id: str
    status: TTSStatus
    audio_path: Optional[str] = None  # R2 object key or local path
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    # Optional quality metrics - filled by Quality Stage, NOT by Port
    dnsmos_score: Optional[float] = None
    asr_wer: Optional[float] = None
    speaker_similarity: Optional[float] = None
    # Internal tracking
    started_at: Optional[str] = None  # ISO timestamp
    completed_at: Optional[str] = None  # ISO timestamp


@dataclass(frozen=True)
class TTSTaskStatus:
    """Status snapshot returned by get_status().

    Contains minimal info for polling; full result only available when DONE/FAILED.
    """

    task_id: str
    status: TTSStatus
    progress: Optional[float] = None  # 0.0-1.0, estimated
    error_message: Optional[str] = None
    # Quality metrics if already available (optional)
    dnsmos_score: Optional[float] = None


class RemoteTTSPort(ABC):
    """Abstract Port contract for remote TTS scheduling.

    This interface isolates the internal orchestration layer from the external
    Hermes scheduling implementation (Redis state machine + R2 object storage).

    Implementations:
    - Real: HermesPort (talks to Redis + R2 via async HTTP/gRPC)
    - Fake: FakeRemoteTTSPort (in-memory for testing)
    - Mock: MockRemoteTTSPort (for unit testing with pytest-mock)

    Thread-safety: All methods must be safe for concurrent calls.
    """

    @abstractmethod
    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        """Submit a TTS synthesis task to the scheduling layer.

        Args:
            task_id: Unique task identifier (caller-generated, UUID recommended).
            payload: Complete synthesis specification.

        Returns:
            True if task was accepted for scheduling.
            False if task_id already exists (idempotent rejection) or
            scheduling layer is unavailable.

        Raises:
            ValueError: If payload validation fails.
            RuntimeError: If scheduling layer is unreachable.
        """
        ...

    @abstractmethod
    async def get_status(self, task_id: str) -> TTSTaskStatus:
        """Poll for task status.

        Non-blocking status check. Returns immediately with current state.

        Args:
            task_id: Task identifier returned from submit().

        Returns:
            TTSTaskStatus with current state. If task_id unknown,
            returns status=PENDING with error_message set.

        Note:
            For DONE/FAILED tasks, use get_result() to retrieve full result.
        """
        ...

    @abstractmethod
    async def get_result(self, task_id: str) -> TTSTaskResult:
        """Retrieve full task result (only valid when status is DONE or FAILED).

        Args:
            task_id: Task identifier.

        Returns:
            TTSTaskResult with audio_path and metadata.
            Raises KeyError if task not found or not yet terminal.

        Raises:
            KeyError: If task_id not found or status not in {DONE, FAILED}.
        """
        ...

    @abstractmethod
    async def cancel(self, task_id: str) -> bool:
        """Request cancellation of a pending/running task.

        Best-effort; success depends on scheduling layer implementation.

        Args:
            task_id: Task identifier.

        Returns:
            True if cancellation was requested (may still complete).
            False if task not found or already terminal.
        """
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check scheduling layer health.

        Returns:
            Dict with keys: 'healthy' (bool), 'latency_ms' (float),
            'pending_count' (int), 'running_count' (int).
        """
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources (connections, pools, etc.)."""
        ...


# Convenience factory type
PortFactory = Callable[..., RemoteTTSPort]

"""Remote TTS Port Contract for Hermes Scheduling Layer.

Defines the async interface between the orchestration layer and the
external Hermes scheduling system (Redis state machine + R2 storage).
This is a thin wrapper over the unified TTSEngine protocol.
"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class TTSStatus(str, enum.Enum):
    """Task status in the Hermes scheduling layer.

    State machine: PENDING -> RUNNING -> DONE/FAILED
    No backward transitions except FAILED -> PENDING (manual retry).
    """

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


@dataclass(frozen=True)
class TTSVoiceAnchor:
    """Voice anchor specification for TTS synthesis."""

    voice_id: str
    speaker_name: Optional[str] = None
    language: str = "zh-CN"
    reference_audio_path: Optional[str] = None

    def __post_init__(self):
        if not self.voice_id or not self.voice_id.strip():
            raise ValueError("voice_id must be non-empty")


@dataclass(frozen=True)
class TTSProsody:
    """Prosody controls for TTS synthesis."""

    rate: float = 1.0      # Speech rate multiplier (0.5-2.0)
    pitch: float = 0.0     # Pitch shift in semitones (-12 to +12)
    volume: float = 0.0    # Volume gain in dB (-20 to +20)
    emotion: Optional[str] = None  # Emotional tag


@dataclass(frozen=True)
class TTSTaskPayload:
    """Payload submitted to Hermes layer for TTS synthesis."""

    text: str
    voice_anchor: TTSVoiceAnchor
    prosody: Optional[TTSProsody] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.text or not self.text.strip():
            raise ValueError("text must be non-empty")
        if not isinstance(self.voice_anchor, TTSVoiceAnchor):
            raise TypeError("voice_anchor must be TTSVoiceAnchor instance")


@dataclass(frozen=True)
class TTSTaskResult:
    """Result returned by Hermes layer when task completes."""

    task_id: str
    status: TTSStatus
    audio_path: Optional[str] = None          # R2 object key or local path
    duration_ms: Optional[int] = None
    error_message: Optional[str] = None
    dnsmos_score: Optional[float] = None
    asr_wer: Optional[float] = None
    speaker_similarity: Optional[float] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


@dataclass(frozen=True)
class TTSTaskStatus:
    """Status snapshot returned by get_status()."""

    task_id: str
    status: TTSStatus
    progress: Optional[float] = None
    error_message: Optional[str] = None
    dnsmos_score: Optional[float] = None


class RemoteTTSPort(ABC):
    """Abstract Port contract for remote TTS scheduling (Hermes layer).

    This interface isolates the orchestration layer from the external
    Hermes scheduling implementation (Redis + R2).

    NOTE: Most local engines should implement the unified TTSEngine protocol
    instead. Use RemoteTTSPort only for the Hermes scheduling layer.
    """

    @abstractmethod
    async def submit(self, task_id: str, payload: TTSTaskPayload) -> bool:
        """Submit a TTS synthesis task to the scheduling layer.

        Args:
            task_id: Unique task identifier (UUID recommended)
            payload: Complete synthesis specification

        Returns:
            True if task was accepted for scheduling
            False if task_id already exists or scheduler unavailable
        """
        ...

    @abstractmethod
    async def get_status(self, task_id: str) -> TTSTaskStatus:
        """Poll for task status (non-blocking)."""
        ...

    @abstractmethod
    async def get_result(self, task_id: str) -> TTSTaskResult:
        """Retrieve full result (only valid when status is DONE or FAILED)."""
        ...

    @abstractmethod
    async def cancel(self, task_id: str) -> bool:
        """Request cancellation of a pending/running task."""
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check scheduling layer health."""
        ...

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""
        ...